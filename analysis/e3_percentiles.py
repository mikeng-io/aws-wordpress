#!/usr/bin/env python3
"""Turn E3 bench.c CSV output into a latency percentile report.

Reads two raw CSVs (local ephemeral, EFS) from the same task run and produces a
side-by-side comparison. Reads results; never rewrites them.
"""
from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from pathlib import Path


def load(path: Path) -> dict[str, list[int]]:
    d: dict[str, list[int]] = defaultdict(list)
    with path.open() as f:
        for row in csv.reader(f):
            if len(row) != 2:
                continue
            try:
                d[row[0]].append(int(row[1]))
            except ValueError:
                continue
    return d


def percentiles(vals: list[int]) -> dict:
    v = sorted(vals)
    n = len(v)
    if n == 0:
        return {}
    def pct(p: float) -> int:
        return v[min(n - 1, int(n * p))]
    return {
        "n": n,
        "p50_ns": pct(0.50),
        "p95_ns": pct(0.95),
        "p99_ns": pct(0.99),
        "max_ns": v[-1],
    }


def main(local_csv: Path, efs_csv: Path, out_dir: Path) -> int:
    local = load(local_csv)
    efs = load(efs_csv)
    ops = sorted(set(local) | set(efs))

    report = {op: {"local": percentiles(local.get(op, [])), "efs": percentiles(efs.get(op, []))}
               for op in ops}
    (out_dir / "percentiles.json").write_text(json.dumps(report, indent=2) + "\n")

    lines = [
        "# E3 latency percentiles: local ephemeral vs EFS",
        "",
        "Same task, same benchmark, same tree shape - only the mount differs.",
        "",
        "| op | mount | n | p50 | p95 | p99 | max | p99 ratio (EFS/local) |",
        "|---|---|--:|--:|--:|--:|--:|--:|",
    ]
    for op in ops:
        l, e = report[op]["local"], report[op]["efs"]
        ratio = f"{e['p99_ns'] / l['p99_ns']:.1f}x" if l.get("p99_ns") else "n/a"
        for label, r in (("local", l), ("efs", e)):
            if not r:
                continue
            lines.append(
                f"| {op} | {label} | {r['n']} | {r['p50_ns']:,} | {r['p95_ns']:,} | "
                f"{r['p99_ns']:,} | {r['max_ns']:,} | "
                f"{ratio if label == 'efs' else ''} |"
            )
    lines.append("")
    (out_dir / "percentiles.md").write_text("\n".join(lines) + "\n")

    print(f"e3_percentiles: wrote {out_dir / 'percentiles.md'}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("usage: e3_percentiles.py <local.csv> <efs.csv> <out_dir>", file=sys.stderr)
        raise SystemExit(64)
    raise SystemExit(main(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])))
