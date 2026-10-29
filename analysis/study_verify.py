#!/usr/bin/env python3
"""Offline closeout replay, using Git-tracked inputs in disposable copies.

Never executes a collector, queries AWS, or writes into a frozen input run.
Historical E5 graders are selected by their recorded SHA-256, not today's rules.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

REPO = Path(__file__).resolve().parents[1]
E5_RUNS = (
    "20261028T103017Z-342d6b4", "20261028T125412Z-f6659e0",
    "20261028T160106Z-dd5fce0",
)


def git(*args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(REPO), *args])


def tracked(prefix: str) -> list[str]:
    return git("ls-files", "-z", "--", prefix).decode().strip("\0").split("\0")


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def differences(old, new, path="") -> list[str]:
    """Require every frozen field; additional current diagnostics are permitted."""
    if isinstance(old, dict):
        if not isinstance(new, dict):
            return [path + ": type mismatch"]
        return [d for k, v in old.items() for d in (
            differences(v, new[k], path + "/" + k) if k in new
            else [path + "/" + k + ": missing field"]
        )]
    if isinstance(old, list):
        if not isinstance(new, list) or len(old) != len(new):
            return [path + ": list length/type mismatch"]
        return [d for i, (a, b) in enumerate(zip(old, new))
                for d in differences(a, b, path + f"/{i}")]
    if isinstance(old, float) and isinstance(new, float) and math.isnan(old) and math.isnan(new):
        return []
    return [] if old == new else [f"{path}: {old!r} != {new!r}"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True,
                        help="new receipt directory; existing paths are refused")
    parser.add_argument("--reuse-e0", type=Path,
                        help="prior verifier JSON; reuse only its two PASS E0 checks after input/parser hash validation")
    args = parser.parse_args()
    out = args.output.resolve()
    # A receipt may be a new results/closeout run, never an experiment's input.
    results = (REPO / "results").resolve()
    if out == results or (results in out.parents and
                          out.relative_to(results).parts[0] != "closeout"):
        parser.error("receipt output must not be inside a frozen experiment/pricing run")
    if out.exists():
        parser.error("receipt directory exists; choose a new path")
    out.mkdir(parents=True)
    files = [p for p in tracked("results") if p]
    before = {p: digest(REPO / p) for p in files}
    (out / "inputs.sha256.json").write_text(json.dumps(before, indent=2) + "\n")
    checks = []
    reused_e0 = {}
    reuse_provenance = None
    if args.reuse_e0:
        prior_path = args.reuse_e0.resolve()
        prior = json.loads(prior_path.read_text())
        prior_inputs = json.loads((prior_path.parent / "inputs.sha256.json").read_text())
        modules = ("analysis/e0_census.py", "analysis/e0_aggregate.py")
        if (not prior.get("frozen_inputs_unchanged") or prior_inputs != before or
                any(prior["analysis_sha256"].get(m) != digest(REPO / m) for m in modules)):
            parser.error("E0 reuse refused: frozen inputs or census/aggregate source changed")
        wanted = {"e0-20260827T185901Z-bff2d22", "e0-20260902T105746Z-f62a686"}
        reused_e0 = {c["check"]: c for c in prior["checks"]
                     if c["check"] in wanted and c["status"] == "PASS"}
        if set(reused_e0) != wanted:
            parser.error("E0 reuse refused: both required PASS checks are missing")
        reuse_provenance = dict(prior_report_sha256=digest(prior_path),
                                prior_inputs_sha256=digest(prior_path.parent / "inputs.sha256.json"),
                                scope="only two E0 checks; all frozen inputs and both analysis module hashes unchanged")
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    for key in list(env):
        if key.startswith("AWS_"):
            env.pop(key)
    env["AWS_EC2_METADATA_DISABLED"] = "true"

    with tempfile.TemporaryDirectory(prefix="aws-wordpress-replay-") as temp:
        scratch = Path(temp)
        copied = {}

        def copy_run(relative: str) -> Path:
            if relative not in copied:
                dest = scratch / relative
                for name in tracked(relative):
                    if not name:
                        continue
                    target = scratch / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(REPO / name, target)
                copied[relative] = dest
            return copied[relative]

        def execute(label: str, script: Path, arguments: list[Path]) -> subprocess.CompletedProcess:
            result = subprocess.run([sys.executable, str(script), *map(str, arguments)],
                                    cwd=REPO, env=env, capture_output=True, text=True)
            (out / f"{label}.stdout.txt").write_text(result.stdout.replace(str(scratch), "<scratch>").replace(str(REPO), "<repo>"))
            (out / f"{label}.stderr.txt").write_text(result.stderr.replace(str(scratch), "<scratch>").replace(str(REPO), "<repo>"))
            if result.returncode:
                raise RuntimeError(f"{label}: exit {result.returncode}; see stderr receipt")
            return result

        def replay(relative: str, script: str, outputs: list[str], label: str):
            try:
                dest = copy_run(relative)
                execute(label, REPO / "analysis" / script, [dest])
                delta = [d for name in outputs for d in differences(
                    json.loads((REPO / relative / name).read_text()),
                    json.loads((dest / name).read_text()), name)]
                checks.append(dict(check=label, input=relative,
                                   status="PASS" if not delta else "DRIFT",
                                   comparison="all recorded JSON fields; extra current diagnostics allowed",
                                   differences=delta))
            except (OSError, ValueError, RuntimeError) as exc:
                checks.append(dict(check=label, input=relative, status="ERROR", error=str(exc)))

        for run in ("20260827T185901Z-bff2d22", "20260902T105746Z-f62a686"):
            relative = "results/E0/" + run
            label = "e0-" + run
            if label in reused_e0:
                checks.append({**reused_e0[label], "reused_from_report_sha256": reuse_provenance["prior_report_sha256"]})
                continue
            dest = copy_run(relative)
            try:
                execute(label + "-census", REPO / "analysis/e0_census.py", [dest])
                execute(label + "-aggregate", REPO / "analysis/e0_aggregate.py", [dest])
                outputs = [p.relative_to(REPO / relative).as_posix()
                           for p in (REPO / relative).rglob("*.census.json")]
                outputs += ["summary.json", "aggregate.json"]
                delta = [d for name in outputs for d in differences(
                    json.loads((REPO / relative / name).read_text()),
                    json.loads((dest / name).read_text()), name)]
                checks.append(dict(check=label, input=relative, status="PASS" if not delta else "DRIFT",
                                   census_files=len(outputs)-2, differences=delta))
            except (OSError, ValueError, RuntimeError) as exc:
                checks.append(dict(check=label, status="ERROR", error=str(exc)))

        topology = (REPO / "results/E1/20260902T060000Z-24d9bb9/host-mount.txt").read_text()
        mounts = [x for x in topology.splitlines() if " type nfs4 " in x]
        proxies = [x for x in topology.splitlines() if "/sbin/efs-proxy " in x]
        checks.append(dict(check="e1-topology", status="PASS" if len(mounts)==len(proxies)==2 else "DRIFT",
                           nfs_mounts=len(mounts), tls_proxies=len(proxies)))
        for run in ("20260910T163206Z-66dcff8", "20260910T182051Z-53b5423",
                    "20261015T000959Z-85382cc", "20261029T070456Z-a2041d6"):
            replay("results/E2/" + run, "e2_stats.py", ["summary.json"], "e2-" + run)
        for script, output in (("e3_stats.py", "stats.json"), ("e3_clusters.py", "clusters.json")):
            replay("results/E3/20260910T113000Z-6016f58", script, [output], script[:-3])
        replay("results/E4/20261029T091909Z-842d596", "e4_stats.py", ["summary.json"], "e4-formal")
        # Cost paths are source paths, so compare the estimate, not a temporary pathname.
        for run in ("20261029T090427Z-3b8faf3", "20261029T091909Z-842d596"):
            relative = "results/E4/" + run
            dest = copy_run(relative)
            pricing = json.loads((REPO / relative / "rep-1/meta.json").read_text())["pricing_snapshot"]
            copy_run("results/pricing/" + pricing)
            label = "e4-cost-" + run
            try:
                execute(label, REPO / "analysis/e4_campaign.py", [dest])
                old = json.loads((REPO / relative / "campaign-summary.json").read_text())["cost_estimate"]
                new = json.loads((dest / "campaign-summary.json").read_text())["cost_estimate"]
                delta = differences(old, new)
                checks.append(dict(check=label, status="PASS" if not delta else "DRIFT", differences=delta))
            except (OSError, ValueError, RuntimeError) as exc:
                checks.append(dict(check=label, status="ERROR", error=str(exc)))

        def pinned(report: dict) -> tuple[Path, str]:
            hashes = report["grader_sha256"]
            current = all(digest(REPO / "analysis" / name) == sha for name, sha in hashes.items())
            if current:
                return REPO / "analysis/e5_formal_stats.py", git("rev-parse", "HEAD").decode().strip()
            revisions = git("log", "--format=%H", "--", *["analysis/"+n for n in hashes]).decode().splitlines()
            for rev in revisions:
                blobs = {name: subprocess.run(["git", "-C", str(REPO), "show", f"{rev}:analysis/{name}"],
                                             capture_output=True).stdout for name in hashes}
                if all(hashlib.sha256(blobs[n]).hexdigest() == h for n, h in hashes.items()):
                    folder = scratch / "graders" / rev
                    folder.mkdir(parents=True, exist_ok=True)
                    for name, data in blobs.items():
                        (folder / name).write_bytes(data)
                    # e5_stats imports E2 summary statistics; E2 in turn may use
                    # E3's cluster helper. Keep the transitive helpers at the same revision.
                    for name in ("e2_stats.py", "e3_clusters.py"):
                        (folder / name).write_bytes(git("show", f"{rev}:analysis/{name}"))
                    return folder / "e5_formal_stats.py", rev
            raise ValueError("recorded grader hashes unavailable in Git history")

        for runs, report_name, label in [
            *[([run], "analysis-v3.json", "e5-"+run)
              for run in ("20261027T093314Z-b5b480f", *E5_RUNS)],
            (list(E5_RUNS), "analysis-pooled-3.json", "e5-pooled-three"),
        ]:
            relative = "results/E5-formal/" + runs[-1]
            try:
                old = json.loads((REPO / relative / report_name).read_text())
                script, rev = pinned(old)
                # E5 is read-only, but copies ensure all analysis only sees tracked artifacts.
                result = execute(label, script, [copy_run("results/E5-formal/"+r) for r in runs])
                new = json.loads(result.stdout)
                delta = differences(old, new)
                checks.append(dict(check=label, status="PASS" if not delta else "DRIFT",
                                   grader_revision=rev,
                                   grader_helper_sha256={name:digest(script.parent/name) for name in ("e2_stats.py", "e3_clusters.py")},
                                   predictions={k:v['status'] for k,v in new['predictions'].items()},
                                   differences=delta))
            except (OSError, ValueError, RuntimeError) as exc:
                checks.append(dict(check=label, status="ERROR", error=str(exc)))
        result = execute("e5-p4-passes", REPO / "analysis/e5_p4_passes.py",
                         [copy_run("results/E5-formal/"+r) for r in E5_RUNS])
        checks.append(dict(check="e5-p4-passes", status="PASS", diagnostic_rows=len(result.stdout.splitlines())-1,
                           note="diagnostic only; no v3 threshold changes or regrading"))
        # The published chart declares its source run. Rebuild in scratch, never overwrite docs.
        chart = REPO / "docs/charts/e2-storage-matrix.html"
        ids = [r for r in ("20260910T163206Z-66dcff8", "20260910T182051Z-53b5423",
                           "20261015T000959Z-85382cc", "20261029T070456Z-a2041d6") if r in chart.read_text()]
        if len(ids) == 1:
            label = "e2-published-chart"
            result = subprocess.run([sys.executable, str(REPO/"analysis/e2_chart.py"),
                                     str(copy_run("results/E2/"+ids[0])), "--out", str(scratch/"chart.html")],
                                    cwd=REPO, env=env, capture_output=True, text=True)
            equal = result.returncode==0 and (scratch/"chart.html").read_bytes()==chart.read_bytes()
            checks.append(dict(check=label, status="PASS" if equal else "DRIFT", input_run=ids[0],
                               comparison="byte-for-byte HTML", exit_code=result.returncode))
        else:
            checks.append(dict(check="e2-published-chart", status="ERROR", error="ambiguous/missing source run"))

    unchanged = all((REPO / p).exists() and digest(REPO / p)==sha for p,sha in before.items())
    report = dict(utc=datetime.now(timezone.utc).isoformat(), source_head=git("rev-parse", "HEAD").decode().strip(),
                  mode="offline replay of Git-tracked evidence in disposable copies; no AWS or collector calls",
                  analysis_sha256={str(p.relative_to(REPO)):digest(p) for p in sorted((REPO/"analysis").glob("*.py"))},
                  frozen_input_files=len(before), frozen_inputs_unchanged=unchanged, checks=checks,
                  e0_reuse_provenance=reuse_provenance,
                  status="PASS" if unchanged and all(c['status']=="PASS" for c in checks) else "REVIEW REQUIRED",
                  excluded="failed/partial campaigns and smoke/pilot/diagnostic methods are indexed, not pooled or regraded")
    (out / "verification.json").write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps({"status":report['status'],"frozen_inputs_unchanged":unchanged,
                      "checks":[{k:v for k,v in c.items() if k in ('check','status','error')} for c in checks]},indent=2))
    return 0 if report['status']=="PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
