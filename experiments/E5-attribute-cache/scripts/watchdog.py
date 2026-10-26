#!/usr/bin/env python3
"""Host-owned E5 runner supervisor. AWS mutations exist only in launch/recover.

No SDK, Docker or Node dependency for cleanup: only host Python and AWS CLI v2.
State is private local operational data; credentials stay in the process environment.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import uuid

STACK = "E5-AttributeCache-dev"
REGION = "ap-southeast-1"
TAG = "E5WatchdogRun"
REPO = Path(__file__).resolve().parents[3]
ROOT = REPO / ".e5-watchdog"


class Failure(RuntimeError):
    pass


class CommandFailure(Failure):
    def __init__(self, text):
        super().__init__(text)
        self.not_found = "ValidationError" in text and "does not exist" in text


def command(argv, timeout=45):
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Failure(f"{Path(argv[0]).name} command unavailable/timed out") from exc
    if p.returncode:
        raise CommandFailure(p.stderr.strip() or f"{Path(argv[0]).name} exited {p.returncode}")
    return p.stdout


def atomic(path, data):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def tags(obj):
    return {t["Key"]: t["Value"] for t in obj.get("Tags", [])}


class Guard:
    def __init__(self, directory, state, clock=time.time, sleep=time.sleep, timer=time.monotonic):
        self.directory, self.state = Path(directory), state
        self.clock, self.sleep, self.timer = clock, sleep, timer
        self.api_deadline = None
        if not re.fullmatch(r"[0-9a-f]{32}", state["token"]):
            raise Failure("invalid run token")
        if state["region"] != REGION or not re.fullmatch(r"\d{12}", state["account"]):
            raise Failure("invalid study region/account")

    def save(self, phase=None, **fields):
        if phase:
            self.state["phase"] = phase
        self.state.update(fields, heartbeat=self.clock())
        atomic(self.directory / "state.json", self.state)

    def aws(self, *args):
        remaining = 45 if self.api_deadline is None else self.api_deadline - self.timer()
        if remaining <= 0:
            raise Failure("watchdog operation deadline reached")
        text = command([self.state["aws_bin"], *args, "--region", REGION,
                        "--no-cli-pager", "--cli-connect-timeout", "10",
                        "--cli-read-timeout", "20", "--output", "json"], timeout=min(45, remaining))
        return {} if args[0] == "s3" else (json.loads(text) if text.strip() else {})

    def identity(self):
        if self.aws("sts", "get-caller-identity")["Account"] != self.state["account"]:
            raise Failure("AWS account changed; refusing cleanup")

    def describe(self, name):
        try:
            stacks = self.aws("cloudformation", "describe-stacks", "--stack-name", name)["Stacks"]
            if len(stacks) != 1:
                raise Failure("invalid describe-stacks response; absence unproven")
            return stacks[0]
        except CommandFailure as exc:
            if exc.not_found:
                return None
            raise

    def own(self, stack):
        t = tags(stack)
        arn = stack["StackId"]
        prefix = f"arn:aws:cloudformation:{REGION}:{self.state['account']}:stack/{STACK}/"
        return (arn.startswith(prefix) and t.get(TAG) == self.state["token"]
                and t.get("Study") == "aws-wordpress" and t.get("Experiment") == "E5")

    def capture(self, stack):
        if not self.own(stack):
            raise Failure("stack ownership mismatch; refusing mutation")
        arn = stack["StackId"]
        entry = self.state["stacks"].setdefault(arn, {"sources": [], "diagnostics": []})
        # Event history retains IDs after rollback; resources retain RETAINed buckets.
        queries = (("list-stack-resources", "StackResourceSummaries"), ("describe-stack-events", "StackEvents"))
        for operation, key in queries:
            rows = self.aws("cloudformation", operation, "--stack-name", arn)[key]
            for r in rows:
                rid, typ = r.get("PhysicalResourceId", ""), r.get("ResourceType")
                if typ in ("AWS::FSx::FileSystem", "AWS::FSx::Volume") and re.fullmatch(r"(?:fs|fsvol)-[0-9a-f]+", rid):
                    if rid not in entry["sources"]:
                        entry["sources"].append(rid)
                if typ == "AWS::S3::Bucket" and r.get("LogicalResourceId", "").startswith("DiagnosticsBucket"):
                    if rid and rid not in entry["diagnostics"]:
                        entry["diagnostics"].append(rid)
            # Persist partial provenance before the next API call can fail.
            self.save()

    def discover(self):
        # A stack can finish rollback/deletion between monitor ticks. Discover its
        # unique ARN from history, then verify its tags before recording any IDs.
        for summary in self.aws("cloudformation", "list-stacks")["StackSummaries"]:
            if summary["StackName"] != STACK:
                continue
            stack = self.describe(summary["StackId"])
            if stack and self.own(stack):
                self.capture(stack)

    def backups(self):
        ids = {i for e in self.state["stacks"].values() for i in e["sources"]}
        result = []
        for b in self.aws("fsx", "describe-backups")["Backups"]:
            if b["Lifecycle"] == "DELETED":
                continue
            t = tags(b)
            source = {b.get("FileSystem", {}).get("FileSystemId"), b.get("Volume", {}).get("VolumeId")}
            tagged = (t.get(TAG) == self.state["token"] and t.get("Study") == "aws-wordpress"
                      and t.get("Experiment") == "E5")
            if source & ids or tagged:
                result.append(b)
        return result

    def diagnostics(self):
        for arn, entry in self.state["stacks"].items():
            for bucket in entry["diagnostics"]:
                if bucket in self.state.get("diagnostics_removed", []):
                    continue
                try:
                    bt = self.aws("s3api", "get-bucket-tagging", "--bucket", bucket, "--expected-bucket-owner", self.state["account"])["TagSet"]
                except CommandFailure as exc:
                    if "NoSuchBucket" in str(exc):
                        self.state.setdefault("diagnostics_removed", []).append(bucket)
                        self.save()
                        continue
                    raise
                if {t["Key"]: t["Value"] for t in bt}.get(TAG) != self.state["token"]:
                    raise Failure("diagnostics bucket ownership mismatch; retained")
                dest = self.directory / "diagnostics" / arn.rsplit("/", 1)[-1] / bucket
                dest.mkdir(parents=True, exist_ok=True)
                self.aws("s3", "sync", f"s3://{bucket}/", str(dest), "--only-show-errors")
                self.aws("s3", "rb", f"s3://{bucket}", "--force")
                self.state.setdefault("diagnostics_removed", []).append(bucket)
                self.save()

    def stop_runner(self):
        # Exact container ID plus label; never act on a reused human-readable name.
        if not self.state.get("container_id"):
            return True
        try:
            obj = json.loads(command(["docker", "inspect", self.state["container_id"]], timeout=15))[0]
            if obj["Config"].get("Labels", {}).get(TAG) != self.state["token"]:
                raise Failure("runner ownership mismatch")
            if obj["State"]["Status"] in ("running", "restarting", "paused"):
                command(["docker", "kill", self.state["container_id"]], timeout=15)
                return False  # inspect again before declaring it stopped
            return obj["State"]["Status"] in ("created", "exited", "dead")
        except Failure as exc:
            # Docker loss is the failure being covered. The shared state fence
            # also prevents another replication when the old daemon comes back.
            if isinstance(exc, CommandFailure) and ("No such object" in str(exc) or "No such container" in str(exc)):
                return True
            self.save(docker_stop_error=str(exc))
            return False

    def cleanup(self):
        self.save("cleaning")  # persist fence BEFORE touching Docker or AWS
        self.stop_runner()
        deadline = self.timer() + 5400
        self.api_deadline = deadline
        empty_since = None
        while self.timer() < deadline:
            try:
                runner_stopped = self.stop_runner()
                self.identity()
                self.discover()
                active = []
                for arn in list(self.state["stacks"]):
                    stack = self.describe(arn)
                    if stack is None or stack["StackStatus"] == "DELETE_COMPLETE":
                        continue
                    self.capture(stack)
                    active.append(arn)
                    if stack["StackStatus"] != "DELETE_IN_PROGRESS":
                        self.aws("cloudformation", "delete-stack", "--stack-name", arn)
                remaining = self.backups()
                self.save(remaining_backups=[b["BackupId"] for b in remaining], remaining_stacks=active,
                          runner_stopped=runner_stopped)
                for backup in remaining:
                    if backup["Lifecycle"] in ("AVAILABLE", "FAILED"):
                        self.aws("fsx", "delete-backup", "--backup-id", backup["BackupId"])
                if not active and not remaining:
                    if empty_since is not None and self.timer() - empty_since >= 60 and runner_stopped:
                        self.diagnostics()
                        self.save("complete", cleanup_verified=True, runner_stopped=True)
                        return
                    empty_since = self.timer() if empty_since is None else empty_since
                else:
                    empty_since = None
            except (Failure, ValueError, KeyError) as exc:
                empty_since = None
                self.save(last_error=str(exc))
            self.sleep(10)
        self.save("failed", cleanup_verified=False, last_error="cleanup deadline exceeded; inspect retained state")
        raise Failure("cleanup not verified; retained state requires recovery")

    def supervise(self):
        self.save("running", supervisor_pid=os.getpid())
        try:
            command(["docker", "start", self.state["container_id"]], timeout=30)
            lost_since = None
            deadline = self.timer() + max(0, self.state["max_seconds"] - max(0, self.clock() - self.state["started"]))
            self.api_deadline = deadline
            while self.timer() < deadline:
                self.save()
                # AWS observation failure is itself a reason to stop, not proof of
                # absence. cleanup retries with the persisted ownership fence.
                stack = self.describe(STACK)
                if stack:
                    self.capture(stack)
                try:
                    obj = json.loads(command(["docker", "inspect", self.state["container_id"]], timeout=15))[0]
                    if obj["Config"].get("Labels", {}).get(TAG) != self.state["token"]:
                        raise Failure("runner label changed")
                    state = obj["State"]
                    if state["Status"] not in ("created", "running", "restarting", "paused"):
                        self.save(runner_exit=state.get("ExitCode"), stop_reason="runner exited")
                        break
                    lost_since = None
                except Failure:
                    lost_since = self.timer() if lost_since is None else lost_since
                    if self.timer() - lost_since >= 60:
                        self.save(stop_reason="Docker unavailable for 60 seconds")
                        break
                self.sleep(10)
            else:
                self.save(stop_reason="host run deadline exceeded")
        except (Failure, ValueError, KeyError) as exc:
            self.save(stop_reason=str(exc))
        finally:
            self.cleanup()


def lock_root():
    ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    handle = open(ROOT / "lock", "a+")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        handle.close()
        raise Failure("another host watchdog/recovery holds the study lock") from exc
    return handle


def launch(reps):
    if not 1 <= reps <= 3:
        raise Failure("replications must be between 1 and 3")
    if os.environ.get("AWS_DEFAULT_REGION", REGION) != REGION or os.environ.get("AWS_REGION", REGION) != REGION:
        raise Failure("E5 is pinned to ap-southeast-1")
    with lock_root() as lease:
        if (ROOT / "latest.json").is_file():
            previous = Path(json.loads((ROOT / "latest.json").read_text())["directory"])
            old = json.loads((previous / "state.json").read_text())
            if old.get("phase") != "complete" or not old.get("cleanup_verified"):
                raise Failure("previous run is unresolved; run e5-watchdog-recover first")
        aws_bin = shutil.which("aws")
        if not aws_bin or not command([aws_bin, "--version"]).startswith("aws-cli/2"):
            raise Failure("host requires AWS CLI v2")
        command(["docker", "info", "--format", "{{.ServerVersion}}"], timeout=15)
        # Never persist environment variables or command output containing credentials.
        account = json.loads(command([aws_bin, "sts", "get-caller-identity", "--region", REGION,
                                      "--output", "json", "--no-cli-pager"]))["Account"]
        token = uuid.uuid4().hex
        directory = ROOT / token
        directory.mkdir(mode=0o700)
        state = {"token": token, "account": account, "region": REGION, "aws_bin": aws_bin,
                 "started": time.time(), "max_seconds": 21600, "phase": "armed", "stacks": {}}
        guard = Guard(directory, state)
        if guard.describe(STACK) is not None:
            raise Failure("E5 stack already exists; inspect it before launching")
        guard.save()
        cmd = ["docker", "create", "--name", f"e5-run-{token[:12]}", "--label", f"{TAG}={token}",
               "-v", "/var/run/docker.sock:/var/run/docker.sock", "-v", f"{REPO}:/repo",
               "-v", "aws-wordpress-node-modules:/repo/infra/node_modules",
               "-v", f"{directory}:/e5-watchdog:ro", "-e", f"E5_WATCHDOG_TOKEN={token}",
               "-e", f"E5_WATCHDOG_ACCOUNT={account}", "-e", "E5_WATCHDOG_STATE=/e5-watchdog/state.json"]
        for key in ("STOP_AFTER_REP", "RESUME_RUN_ID", "RESUME_ALLOW_CHANGED"):
            cmd += ["-e", f"{key}={os.environ.get(key, '')}"]
        cmd += ["aws-wordpress-runner", "bash", "-c",
                "cd infra && npm ci --no-audit --no-fund --loglevel=error && cd .. && make doctor && make e5 REPS=" + str(reps)]
        state["container_id"] = command(cmd).strip()
        if not re.fullmatch(r"[0-9a-f]{64}", state["container_id"]):
            raise Failure("Docker returned an invalid container ID")
        guard.save()
        atomic(ROOT / "latest.json", {"directory": str(directory)})
        with open(directory / "supervisor.log", "a") as log:
            subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "serve", "--directory", str(directory),
                              "--lock-fd", str(lease.fileno())], stdin=subprocess.DEVNULL,
                             stdout=log, stderr=log, start_new_session=True, pass_fds=(lease.fileno(),))
        print(f"Host watchdog: {directory}\nStatus: make e5-watchdog-status\nRunner: docker logs -f {state['container_id']}")


def check_lease():
    path = os.environ.get("E5_WATCHDOG_STATE")
    if not path:
        raise Failure("E5 requires make e5-container with the host watchdog")
    state = json.loads(Path(path).read_text())
    token = os.environ.get("E5_WATCHDOG_TOKEN", "")
    age = time.time() - state["heartbeat"]
    if (not re.fullmatch(r"[0-9a-f]{32}", token) or state["token"] != token
        or state["account"] != os.environ.get("E5_WATCHDOG_ACCOUNT")
        or state["region"] != REGION or state["phase"] != "running" or not 0 <= age <= 60):
        raise Failure("host watchdog lease is stale, fenced or mismatched")


def preflight():
    check_lease()
    path = Path(os.environ["E5_WATCHDOG_STATE"])
    state = json.loads(path.read_text())
    state["aws_bin"] = os.environ.get("E5_WATCHDOG_AWS_BIN") or shutil.which("aws") or "aws"
    guard = Guard(path.parent, state)
    guard.identity()
    if guard.describe(STACK) is not None:
        raise Failure("E5 stack already exists; never deploy over an unknown state")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("action", choices=("launch", "serve", "status", "recover", "check-lease", "preflight"))
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--directory", type=Path)
    ap.add_argument("--lock-fd", type=int)
    args = ap.parse_args()
    if args.action == "preflight":
        preflight()
        return
    if args.action == "check-lease":
        check_lease()
        return
    if args.action == "launch":
        launch(args.reps)
        return
    directory = args.directory or Path(json.loads((ROOT / "latest.json").read_text())["directory"])
    state = json.loads((directory / "state.json").read_text())
    if args.action == "status":
        print(json.dumps(state, indent=2))
        return
    if args.action == "serve":
        if args.lock_fd is None:
            raise Failure("serve is internal; use launch")
        os.fstat(args.lock_fd)
        Guard(directory, state).supervise()
    else:
        with lock_root():
            state["aws_bin"] = shutil.which("aws") or "aws"
            if not command([state["aws_bin"], "--version"]).startswith("aws-cli/2"):
                raise Failure("recovery requires AWS CLI v2")
            Guard(directory, state).cleanup()


if __name__ == "__main__":
    try:
        main()
    except (Failure, OSError, ValueError, KeyError) as exc:
        print(f"E5 watchdog failed: {exc}", file=sys.stderr)
        sys.exit(2)
