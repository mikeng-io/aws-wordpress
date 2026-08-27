#!/usr/bin/env python3
"""Aggregate E0 census output across repetitions.

Reports median and IQR rather than mean and standard deviation: syscall counts are
bounded below and occasionally spike, so the median is the honest centre and the IQR
says how much a single run should be trusted.

Reads results; never rewrites them.
"""
from __future__ import annotations

import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

METRICS = ("total_file_syscalls", "unique_paths", "path_component_ops", "failed_ops")


def main(run_dir: Path) -> int:
    cells: dict[tuple[str, str, str], list[dict]] = defaultdict(list)

    for census in sorted(run_dir.glob("**/*.census.json")):
        d = json.loads(census.read_text())
        profile = census.parent.name
        endpoint, cohort, _ = census.name.split(".", 2)
        cells[(profile, endpoint, cohort)].append(d)

    if not cells:
        print(f"e0_aggregate: no census files under {run_dir}", file=sys.stderr)
        return 66

    out: dict[str, dict] = {}
    for (profile, endpoint, cohort), runs in sorted(cells.items()):
        stats: dict[str, object] = {"n": len(runs)}
        for metric in METRICS:
            vals = sorted(r[metric] for r in runs)
            stats[metric] = {
                "median": statistics.median(vals),
                "min": vals[0],
                "max": vals[-1],
                "iqr": (statistics.quantiles(vals, n=4)[2] - statistics.quantiles(vals, n=4)[0])
                       if len(vals) >= 4 else None,
            }
        stat_vals = sorted(r["by_family"].get("stat", 0) for r in runs)
        stats["stat_median"] = statistics.median(stat_vals)
        open_vals = sorted(r["by_family"].get("open", 0) for r in runs)
        stats["open_median"] = statistics.median(open_vals)
        out[f"{profile}/{endpoint}/{cohort}"] = stats

    (run_dir / "aggregate.json").write_text(json.dumps(out, indent=2) + "\n")

    lines = [
        "# E0 aggregate",
        "",
        f"Run: `{run_dir.name}`",
        "",
        "Median across repetitions, with min-max range. Counts are filesystem syscalls",
        "per single request. E0 measures counts, not latency.",
        "",
        "| profile | endpoint | cohort | n | total (median) | range | stat | open | ENOENT-ish fails |",
        "|---|---|---|--:|--:|---|--:|--:|--:|",
    ]
    for key, s in out.items():
        profile, endpoint, cohort = key.split("/")
        tot = s["total_file_syscalls"]
        lines.append(
            f"| {profile} | {endpoint} | {cohort} | {s['n']} | {tot['median']:.0f} | "
            f"{tot['min']}–{tot['max']} | {s['stat_median']:.0f} | {s['open_median']:.0f} | "
            f"{s['failed_ops']['median']:.0f} |"
        )
    lines.append("")
    (run_dir / "aggregate.md").write_text("\n".join(lines) + "\n")

    print(f"e0_aggregate: {len(out)} cells -> {run_dir / 'aggregate.md'}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: e0_aggregate.py <results/E0/RUN_ID>", file=sys.stderr)
        raise SystemExit(64)
    raise SystemExit(main(Path(sys.argv[1])))
