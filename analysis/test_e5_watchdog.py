"""Failure injection for the host watchdog. All AWS and Docker calls are fakes."""
import contextlib
import io
import copy
import importlib.util
import json
import os
import select
import subprocess
import sys
import time
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("e5_watchdog", Path(__file__).resolve().parents[1] /
    "experiments/E5-attribute-cache/scripts/watchdog.py")
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)
REAL_COMMAND = w.command
TOKEN = "a" * 32
ACCOUNT = "123456789012"
ARN = f"arn:aws:cloudformation:ap-southeast-1:{ACCOUNT}:stack/{w.STACK}/owned-id"


def stack(token=TOKEN, arn=ARN):
    return {"StackName": w.STACK, "StackId": arn, "StackStatus": "CREATE_COMPLETE", "Tags": [
        {"Key": "Study", "Value": "aws-wordpress"}, {"Key": "Experiment", "Value": "E5"},
        {"Key": w.TAG, "Value": token}]}


class Clock:
    def __init__(self): self.now = 1000
    def time(self): return self.now
    def sleep(self, seconds): self.now += seconds


class Fake:
    def __init__(self, clock):
        self.clock = clock
        self.stack = stack()
        self.calls = []
        self.docker_calls = []
        self.running = True
        self.docker_until = 0
        self.runner_status = "running"
        self.account = ACCOUNT
        self.api_error = None
        self.diag = False
        self.diag_tag = TOKEN
        self.sync_fail = False
        self.late = False
        self.late_added = False
        self.backups = [
            {"BackupId": "backup-own", "Lifecycle": "AVAILABLE", "FileSystem": {"FileSystemId": "fs-abc"}},
            {"BackupId": "backup-foreign", "Lifecycle": "AVAILABLE", "Tags": stack("b"*32)["Tags"]}]

    def docker(self, argv, timeout=45):
        self.docker_calls.append(argv[:])
        if argv[1] == "inspect" and self.clock.now < self.docker_until:
            raise w.Failure("Docker daemon unavailable")
        action = argv[1]
        if action == "inspect":
            return json.dumps([{"Config": {"Labels": {w.TAG: TOKEN}}, "State": {
                "Status": self.runner_status if self.running else "exited", "ExitCode": 0}}])
        if action == "kill":
            self.running = False
        return ""

    def aws(self, *args):
        self.calls.append(args)
        op = args[:2]
        if self.api_error == op:
            raise w.CommandFailure("AccessDenied: simulated outage")
        if op == ("sts", "get-caller-identity"):
            return {"Account": self.account}
        if op == ("cloudformation", "list-stacks"):
            return {"StackSummaries": [] if self.stack is None else [self.stack]}
        if op == ("cloudformation", "describe-stacks"):
            if self.stack is None:
                raise w.CommandFailure("ValidationError: Stack does not exist")
            return {"Stacks": [self.stack]}
        if op == ("cloudformation", "list-stack-resources"):
            resources = [{"ResourceType": "AWS::FSx::FileSystem", "PhysicalResourceId": "fs-abc"}]
            if self.diag:
                resources.append({"ResourceType": "AWS::S3::Bucket", "LogicalResourceId": "DiagnosticsBucketABC",
                                  "PhysicalResourceId": "e5-test-diagnostics"})
            return {"StackResourceSummaries": resources}
        if op == ("cloudformation", "describe-stack-events"):
            return {"StackEvents": [{"ResourceType": "AWS::FSx::Volume", "PhysicalResourceId": "fsvol-def"}]}
        if op == ("cloudformation", "delete-stack"):
            self.stack["StackStatus"] = "DELETE_COMPLETE"
            return {}
        if op == ("fsx", "describe-backups"):
            if self.late and not self.late_added and self.clock.now >= 1040:
                self.late_added = True
                self.backups.append({"BackupId": "backup-late", "Lifecycle": "AVAILABLE",
                                     "Volume": {"VolumeId": "fsvol-def"}})
            return {"Backups": copy.deepcopy(self.backups)}
        if op == ("fsx", "delete-backup"):
            bid = args[args.index("--backup-id") + 1]
            self.backups = [b for b in self.backups if b["BackupId"] != bid]
            return {}
        if op == ("s3api", "get-bucket-tagging"):
            return {"TagSet": [{"Key": w.TAG, "Value": self.diag_tag}]}
        if op == ("s3", "sync"):
            if self.sync_fail: raise w.Failure("diagnostics copy failed")
            return {}
        if op == ("s3", "rb"):
            return {}
        raise AssertionError(args)


class WatchdogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.clock = Clock()
        self.backend = Fake(self.clock)
        self.state = {"token": TOKEN, "account": ACCOUNT, "region": w.REGION, "aws_bin": "aws",
                      "stacks": {}, "container_id": "c"*64, "started": 1000,
                      "max_seconds": 30, "phase": "armed"}
        self.guard = w.Guard(self.directory, self.state, clock=self.clock.time, sleep=self.clock.sleep, timer=self.clock.time)
        self.guard.aws = self.backend.aws
        self.patcher = patch.object(w, "command", self.backend.docker)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def deletes(self):
        return [c for c in self.backend.calls if c[:2] == ("cloudformation", "delete-stack")]

    def test_deadline_kills_exact_runner_then_deletes_exact_stack_arn(self):
        self.guard.supervise()
        self.assertEqual(self.state["phase"], "complete")
        self.assertTrue(self.state["cleanup_verified"])
        self.assertTrue(any(c[1:3] == ["kill", "c"*64] for c in self.backend.docker_calls))
        self.assertEqual(self.deletes()[0][-1], ARN)
        deleted_backups = [c[-1] for c in self.backend.calls if c[:2] == ("fsx", "delete-backup")]
        self.assertEqual(deleted_backups, ["backup-own"])
        self.assertEqual(self.backend.backups[0]["BackupId"], "backup-foreign")

    def test_zero_runner_exit_does_not_skip_leftover_cleanup(self):
        self.backend.running = False
        self.guard.supervise()
        self.assertTrue(self.deletes())
        self.assertEqual(self.state["runner_exit"], 0)
        self.assertTrue(self.state["cleanup_verified"])

    def test_docker_loss_does_not_block_aws_cleanup(self):
        self.state["max_seconds"] = 21600
        self.backend.docker_until = 1080
        self.guard.supervise()
        self.assertIn("Docker unavailable", self.state["stop_reason"])
        self.assertTrue(self.deletes())
        self.assertEqual(self.state["phase"], "complete")

    def test_permanent_docker_loss_clears_aws_but_never_claims_runner_quiescence(self):
        self.state["max_seconds"] = 21600
        self.backend.docker_until = 999999
        with self.assertRaises(w.Failure): self.guard.supervise()
        self.assertTrue(self.deletes())
        self.assertEqual(self.state["phase"], "failed")
        self.assertFalse(self.state["cleanup_verified"])
        self.assertFalse(self.state["runner_stopped"])

    def test_aws_denied_is_not_treated_as_stack_absence(self):
        self.backend.api_error = ("cloudformation", "describe-stacks")
        with self.assertRaises(w.CommandFailure): self.guard.describe(w.STACK)
        with self.assertRaises(w.Failure): self.guard.supervise()
        self.assertFalse(self.state["cleanup_verified"])
        self.assertFalse(self.deletes())

    def test_wrong_account_never_mutates_aws(self):
        self.backend.account = "999999999999"
        with self.assertRaises(w.Failure): self.guard.cleanup()
        self.assertFalse(self.deletes())
        self.assertFalse(any(c[:2] == ("fsx", "delete-backup") for c in self.backend.calls))

    def test_foreign_nonce_stack_and_backup_are_ignored(self):
        self.backend.stack = stack("b"*32)
        self.backend.backups = [self.backend.backups[-1]]
        self.guard.cleanup()
        self.assertFalse(self.deletes())
        self.assertFalse(any(c[:2] == ("fsx", "delete-backup") for c in self.backend.calls))

    def test_same_tags_in_wrong_account_arn_do_not_establish_ownership(self):
        candidate = stack(arn=ARN.replace(ACCOUNT, "999999999999"))
        self.assertFalse(self.guard.own(candidate))

    def test_roll_back_event_ids_are_captured_for_backup_sweep(self):
        self.guard.capture(self.backend.stack)
        self.assertIn("fsvol-def", self.state["stacks"][ARN]["sources"])

    def test_late_final_backup_resets_two_empty_observations(self):
        self.backend.late = True
        self.guard.cleanup()
        self.assertTrue(any(c[-1] == "backup-late" for c in self.backend.calls if c[:2] == ("fsx", "delete-backup")))
        self.assertGreaterEqual(self.clock.now, 1110)

    def test_diagnostics_copy_precedes_delete(self):
        self.backend.diag = True
        self.guard.cleanup()
        ops = [c[:2] for c in self.backend.calls]
        self.assertLess(ops.index(("s3", "sync")), ops.index(("s3", "rb")))
        self.assertIn("e5-test-diagnostics", self.state["diagnostics_removed"])

    def test_copy_failure_preserves_diagnostics(self):
        self.backend.diag = self.backend.sync_fail = True
        with self.assertRaises(w.Failure): self.guard.cleanup()
        self.assertFalse(any(c[:2] == ("s3", "rb") for c in self.backend.calls))

    def test_foreign_bucket_tag_preserves_bucket(self):
        self.backend.diag = True
        self.backend.diag_tag = "b"*32
        with self.assertRaises(w.Failure): self.guard.cleanup()
        self.assertFalse(any(c[:2] in (("s3", "sync"), ("s3", "rb")) for c in self.backend.calls))

    def test_recovery_reuses_persisted_source_ids_after_stack_disappeared(self):
        self.guard.capture(self.backend.stack)
        self.backend.stack = None
        saved = json.loads((self.directory / "state.json").read_text())
        recovery = w.Guard(self.directory, saved, self.clock.time, self.clock.sleep, self.clock.time)
        recovery.aws = self.backend.aws
        recovery.cleanup()
        self.assertFalse(any(b["BackupId"] == "backup-own" for b in self.backend.backups))

    def test_token_tags_find_backup_even_when_no_stack_was_observed(self):
        self.backend.stack = None
        self.backend.backups = [{"BackupId": "backup-tagged", "Lifecycle": "AVAILABLE", "Tags": stack()["Tags"]}]
        self.guard.cleanup()
        self.assertEqual(self.backend.backups, [])

    def test_fence_is_saved_before_first_stop_or_aws_mutation(self):
        original = self.backend.docker
        def inspect_fence(argv, timeout=45):
            self.assertEqual(json.loads((self.directory / "state.json").read_text())["phase"], "cleaning")
            return original(argv, timeout)
        with patch.object(w, "command", inspect_fence): self.guard.cleanup()

    def test_fresh_lease_passes_and_cleanup_phase_blocks_next_deploy(self):
        self.guard.save("running")
        env = {"E5_WATCHDOG_STATE": str(self.directory / "state.json"),
               "E5_WATCHDOG_TOKEN": TOKEN, "E5_WATCHDOG_ACCOUNT": ACCOUNT, "E5_WATCHDOG_AWS_BIN": "aws"}
        with patch.dict(os.environ, env), patch.object(w.time, "time", self.clock.time):
            w.check_lease()
            self.guard.save("cleaning")
            with self.assertRaises(w.Failure): w.check_lease()

    def test_stale_future_wrong_account_or_wrong_token_lease_fails(self):
        self.guard.save("running")
        env = {"E5_WATCHDOG_STATE": str(self.directory / "state.json"),
               "E5_WATCHDOG_TOKEN": TOKEN, "E5_WATCHDOG_ACCOUNT": ACCOUNT, "E5_WATCHDOG_AWS_BIN": "aws"}
        with patch.dict(os.environ, env), patch.object(w.time, "time", self.clock.time):
            for changes in ({"heartbeat": 939}, {"heartbeat": 1001}, {"token": "b"*32}, {"account": "999999999999"}):
                candidate = dict(self.state, **changes)
                w.atomic(self.directory / "state.json", candidate)
                with self.assertRaises(w.Failure): w.check_lease()

    def test_partial_provenance_survives_event_api_failure(self):
        self.backend.api_error = ("cloudformation", "describe-stack-events")
        with self.assertRaises(w.CommandFailure): self.guard.capture(self.backend.stack)
        saved = json.loads((self.directory / "state.json").read_text())
        self.assertIn("fs-abc", saved["stacks"][ARN]["sources"])

    def test_empty_describe_response_is_not_absence(self):
        with patch.object(self.guard, "aws", return_value={"Stacks": []}):
            with self.assertRaises(w.Failure): self.guard.describe(w.STACK)

    def test_launcher_creates_stopped_container_and_detaches_host_supervisor(self):
        calls = []
        def fake_command(argv, timeout=45):
            calls.append(argv)
            if argv[1] == "--version": return "aws-cli/2.99.0"
            if argv[1:3] == ["sts", "get-caller-identity"]: return json.dumps({"Account": ACCOUNT})
            if argv[1:3] == ["cloudformation", "describe-stacks"]:
                raise w.CommandFailure("ValidationError: Stack does not exist")
            if argv[1] == "create": return "c"*64
            return "fake"
        def spawn(argv, **kwargs):
            self.assertIn("serve", argv)
            self.assertTrue(kwargs["start_new_session"])
            self.assertEqual(len(kwargs["pass_fds"]), 1)
            os.fstat(kwargs["pass_fds"][0])
            directory = Path(argv[argv.index("--directory")+1])
            state = json.loads((directory/"state.json").read_text())
            self.assertEqual(state["phase"], "armed")
            self.assertEqual(state["container_id"], "c"*64)
        env = {"AWS_DEFAULT_REGION": w.REGION, "AWS_REGION": w.REGION}
        with patch.object(w, "ROOT", self.directory), patch.object(w, "find_aws_v2", return_value="aws"), \
             patch.object(w, "command", fake_command), patch.object(w.subprocess, "Popen", side_effect=spawn), \
             patch.dict(os.environ, env):
            with contextlib.redirect_stdout(io.StringIO()): w.launch(1)
        self.assertTrue(any(c[1] == "create" for c in calls))
        self.assertFalse(any(c[1] == "start" for c in calls))

    def test_unresolved_previous_run_blocks_new_launch(self):
        self.guard.save("failed")
        w.atomic(self.directory/"latest.json", {"directory": str(self.directory)})
        with patch.object(w, "ROOT", self.directory), patch.object(w, "command") as cmd, \
             patch.dict(os.environ, {"AWS_DEFAULT_REGION": w.REGION, "AWS_REGION": w.REGION}):
            with self.assertRaises(w.Failure): w.launch(1)
            cmd.assert_not_called()

    def test_real_detached_process_keeps_lock_and_cleans_after_parent_is_killed(self):
        analysis = str(Path(__file__).resolve().parent)
        directory = str(self.directory)
        worker = f"""
import sys,time,json
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,{analysis!r})
from test_e5_watchdog import w,Clock,Fake
w.ROOT=Path({directory!r})
for _ in range(250):
 if (w.ROOT/'go').exists(): break
 time.sleep(.02)
else: raise RuntimeError('parent kill handshake timed out')
try:
 extra=w.lock_root()
except w.Failure: pass
else: raise RuntimeError('inherited host lock was lost with parent')
clock=Clock(); backend=Fake(clock); backend.running=False
state={self.state!r}
guard=w.Guard(w.ROOT,state,clock.time,clock.sleep,clock.time); guard.aws=backend.aws
with patch.object(w,'command',backend.docker): guard.supervise()
assert state['cleanup_verified']
(w.ROOT/'done').write_text('verified')
"""
        parent = f"""
import sys,subprocess,time
from pathlib import Path
sys.path.insert(0,{analysis!r})
from test_e5_watchdog import w
w.ROOT=Path({directory!r}); lease=w.lock_root()
with open(w.ROOT/'worker.log','w') as log:
 child=subprocess.Popen([sys.executable,'-c',{worker!r}],stdin=subprocess.DEVNULL,
       stdout=log,stderr=log,start_new_session=True,pass_fds=(lease.fileno(),))
print(child.pid,flush=True)
time.sleep(30)
"""
        env = {"PATH": os.environ["PATH"], "PYTHONDONTWRITEBYTECODE": "1"}
        proc = subprocess.Popen([sys.executable, "-c", parent], stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, env=env)
        child_pid = None
        try:
            self.assertTrue(select.select([proc.stdout], [], [], 5)[0], "parent handshake timed out")
            child_pid = int(proc.stdout.readline())
            proc.kill(); proc.wait(timeout=5)
            (self.directory/"go").write_text("parent killed")
            deadline = time.monotonic()+5
            while not (self.directory/"done").exists() and time.monotonic()<deadline: time.sleep(.02)
            self.assertTrue((self.directory/"done").exists(), (self.directory/"worker.log").read_text())
            saved = json.loads((self.directory/"state.json").read_text())
            self.assertEqual(saved["phase"], "complete")
        finally:
            if proc.poll() is None: proc.kill(); proc.wait(timeout=5)
            if child_pid and not (self.directory/"done").exists():
                try: os.kill(child_pid, 15)
                except ProcessLookupError: pass
            proc.stdout.close(); proc.stderr.close()

    def test_creating_backup_is_not_ignored_or_force_deleted(self):
        self.backend.backups[0]["Lifecycle"] = "CREATING"
        with self.assertRaises(w.Failure): self.guard.cleanup()
        self.assertIn("backup-own", self.state["remaining_backups"])
        self.assertFalse(any(c[:2] == ("fsx", "delete-backup") for c in self.backend.calls))

    def test_wall_clock_jump_does_not_extend_cleanup_deadline(self):
        self.guard.clock = lambda: -100000
        self.backend.api_error = ("cloudformation", "list-stacks")
        with self.assertRaises(w.Failure): self.guard.cleanup()
        self.assertEqual(self.clock.now, 6400)
        self.assertFalse(self.state["cleanup_verified"])

    def test_runner_preflight_requires_absence_not_permission_failure(self):
        self.guard.save("running")
        env = {"E5_WATCHDOG_STATE": str(self.directory / "state.json"),
               "E5_WATCHDOG_TOKEN": TOKEN, "E5_WATCHDOG_ACCOUNT": ACCOUNT, "E5_WATCHDOG_AWS_BIN": "aws"}
        with patch.dict(os.environ, env), patch.object(w.time, "time", self.clock.time), \
             patch.object(w.Guard, "aws", side_effect=self.backend.aws):
            with self.assertRaises(w.Failure): w.preflight()  # existing owned stack is still a refusal
            self.backend.stack = None
            w.preflight()
            self.backend.api_error = ("cloudformation", "describe-stacks")
            with self.assertRaises(w.CommandFailure): w.preflight()

    def test_expired_operation_budget_prevents_another_api_command(self):
        self.guard.api_deadline = self.clock.now - 1
        with patch.object(w, "command") as cmd:
            with self.assertRaises(w.Failure): w.Guard.aws(self.guard, "fsx", "describe-backups")
            cmd.assert_not_called()

    def test_aws_selection_skips_wrong_architecture_and_v1_candidates(self):
        def cli(argv, timeout=45):
            if argv[0] == "/old/aws": raise w.Failure("could not execute (OS errno 86)")
            return "aws-cli/1.0" if argv[0] == "/v1/aws" else "aws-cli/2.35.19"
        with patch.object(w.os, "get_exec_path", return_value=["/old", "/v1", "/good"]), \
             patch.object(w.Path, "is_file", return_value=True), patch.object(w.os, "access", return_value=True), \
             patch.object(w, "command", side_effect=cli):
            self.assertEqual(w.find_aws_v2(), "/good/aws")

    def test_aws_selection_refuses_when_no_working_v2_exists(self):
        with patch.object(w.os, "get_exec_path", return_value=["/old"]), \
             patch.object(w.Path, "is_file", return_value=True), patch.object(w.os, "access", return_value=True), \
             patch.object(w, "command", side_effect=w.Failure("wrong architecture")):
            with self.assertRaises(w.Failure): w.find_aws_v2()

    def test_command_distinguishes_execution_failure_from_timeout(self):
        with patch.object(w.subprocess, "run", side_effect=OSError(86,"Bad CPU type")):
            with self.assertRaisesRegex(w.Failure, "OS errno 86"): REAL_COMMAND(["aws","--version"])
        with patch.object(w.subprocess, "run", side_effect=subprocess.TimeoutExpired(["aws"],1)):
            with self.assertRaisesRegex(w.Failure, "timed out"): REAL_COMMAND(["aws","--version"])

    def test_lock_rejects_second_host_supervisor(self):
        with patch.object(w, "ROOT", self.directory):
            first = w.lock_root()
            try:
                with self.assertRaises(w.Failure): w.lock_root()
            finally: first.close()


if __name__ == "__main__":
    unittest.main()
