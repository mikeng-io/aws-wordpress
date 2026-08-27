#!/usr/bin/env python3
"""Turn E0 strace output into census.json.

Reads a results/E0/<run-id>/ directory in place and writes census.json next to each
trace, plus a summary.json and summary.md for the run.

Reads results; never rewrites them. The traces themselves are left untouched.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

# `strace -f` prefixes each line with a PID. Unfinished/resumed pairs and signal
# lines are skipped rather than stitched: a request that races a signal is rare and
# stitching would invent data.
LINE = re.compile(r"^(?:\d+\s+)?(?P<call>\w+)\((?P<args>.*)\)\s+=\s+(?P<ret>.+)$")
QUOTED = re.compile(r'"((?:[^"\\]|\\.)*)"')

STAT_CALLS = {"stat", "lstat", "fstat", "newfstatat", "statx", "access", "faccessat",
              "faccessat2", "fstatat64", "stat64", "lstat64"}
OPEN_CALLS = {"open", "openat", "openat2"}
DIR_CALLS = {"getdents", "getdents64"}
LINK_CALLS = {"readlink", "readlinkat"}


def classify(call: str) -> str:
    if call in STAT_CALLS:
        return "stat"
    if call in OPEN_CALLS:
        return "open"
    if call in DIR_CALLS:
        return "readdir"
    if call in LINK_CALLS:
        return "readlink"
    return "other"


def parse(path: Path) -> dict:
    by_call: Counter[str] = Counter()
    by_family: Counter[str] = Counter()
    errno_counts: Counter[str] = Counter()
    paths: Counter[str] = Counter()
    failed = 0
    total = 0
    unparsed = 0

    for raw in path.read_text(errors="replace").splitlines():
        if "<unfinished" in raw or "resumed>" in raw or raw.startswith(("+++", "---")):
            continue
        m = LINE.match(raw.strip())
        if not m:
            unparsed += 1
            continue

        call, args, ret = m["call"], m["args"], m["ret"]
        total += 1
        by_call[call] += 1
        by_family[classify(call)] += 1

        q = QUOTED.search(args)
        if q:
            paths[q.group(1)] += 1

        if ret.startswith("-1"):
            failed += 1
            parts = ret.split()
            if len(parts) > 1:
                errno_counts[parts[1]] += 1

    # A path is a "component" when some other observed path sits beneath it: the
    # realpath cache missed and the kernel was asked about a directory on the way to
    # a file. These are pure overhead - the multiplier that makes a stat storm worse
    # than its file count suggests.
    unique = set(paths)
    prefixes = {p for p in unique if any(o.startswith(p + "/") for o in unique)}
    component_ops = sum(paths[p] for p in prefixes)

    return {
        "trace_file": path.name,
        "total_file_syscalls": total,
        "unparsed_lines": unparsed,
        "by_family": dict(by_family.most_common()),
        "by_syscall": dict(by_call.most_common()),
        "unique_paths": len(unique),
        "path_component_ops": component_ops,
        "distinct_file_ops": total - component_ops,
        "failed_ops": failed,
        "failed_ratio": round(failed / total, 4) if total else 0.0,
        "errno": dict(errno_counts.most_common()),
        "top_paths": [{"path": p, "ops": n} for p, n in paths.most_common(15)],
    }


def main(run_dir: Path) -> int:
    traces = sorted(run_dir.glob("**/*.strace"))
    if not traces:
        print(f"e0_census: no traces under {run_dir}", file=sys.stderr)
        return 66

    summary: dict[str, dict] = {}
    for trace in traces:
        census = parse(trace)
        (trace.with_suffix(".census.json")).write_text(json.dumps(census, indent=2) + "\n")

        profile = trace.parent.name
        rep = trace.parent.parent.name if trace.parent.parent.name.startswith("rep-") else "rep-1"
        endpoint, cohort, _ = trace.name.split(".", 2)
        summary.setdefault(f"{rep}/{profile}", {})[f"{endpoint}.{cohort}"] = {
            "total": census["total_file_syscalls"],
            "stat": census["by_family"].get("stat", 0),
            "open": census["by_family"].get("open", 0),
            "unique_paths": census["unique_paths"],
            "component_ops": census["path_component_ops"],
            "failed_ratio": census["failed_ratio"],
        }

    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")

    lines = [
        "# E0 census summary",
        "",
        f"Run: `{run_dir.name}`",
        "",
        "Counts are filesystem syscalls per single request. E0 measures counts, not",
        "latency — these are the multiplier that per-op latency gets multiplied by.",
        "",
        "| profile | endpoint.cohort | total | stat | open | unique paths | component ops | failed |",
        "|---|---|--:|--:|--:|--:|--:|--:|",
    ]
    for profile in sorted(summary):
        for key in sorted(summary[profile]):
            r = summary[profile][key]
            lines.append(
                f"| {profile} | {key} | {r['total']} | {r['stat']} | {r['open']} | "
                f"{r['unique_paths']} | {r['component_ops']} | {r['failed_ratio']:.1%} |"
            )
    lines.append("")
    (run_dir / "summary.md").write_text("\n".join(lines) + "\n")

    print(f"e0_census: wrote census for {len(traces)} traces")
    print(f"e0_census: {run_dir / 'summary.md'}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: e0_census.py <results/E0/RUN_ID>", file=sys.stderr)
        raise SystemExit(64)
    raise SystemExit(main(Path(sys.argv[1])))
