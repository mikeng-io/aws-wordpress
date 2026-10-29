#!/usr/bin/env python3
"""P4 diagnostic: compare A3 with A8's first pass and its later passes.

A8 runs ten passes (`E5_A8_PASSES=10`) while A3 runs once after the idle wait, so
pooling all ten A8 passes is not like-for-like. This prints, per tier and run, the
A3 median, the first A8 pass median, the median of passes 2-10, and the ratio the
grader uses (all A8 passes over A3). Reads committed raw CSVs; no AWS.

Usage:
    python3 analysis/e5_p4_passes.py [results/E5-formal/<run> ...]
"""

from __future__ import annotations

import csv
import statistics
import sys
from pathlib import Path

TIERS = ("efs_host_plain", "efs_host_tls", "fsx_openzfs", "fsx_ontap")
DEFAULT_RUNS = (
    "results/E5-formal/20261028T103017Z-342d6b4",
    "results/E5-formal/20261028T125412Z-f6659e0",
    "results/E5-formal/20261028T160106Z-dd5fce0",
)
PASS_OPS = 1000


def stat_ns(path: Path) -> list[int]:
    with path.open(newline="") as fh:
        return [int(row[3]) for row in csv.reader(fh) if row[1] == "stat"]


def main(argv: list[str]) -> int:
    runs = argv[1:] or list(DEFAULT_RUNS)
    print("run,tier,a3_ns,a8_pass1_ns,a8_passes2_10_ns,a8_all_over_a3")
    for run in runs:
        for tier in TIERS:
            base = Path(run) / "rep-1" / "formal" / "ec2" / tier
            a3 = stat_ns(base / "A3.csv")
            a8 = stat_ns(base / "A8.csv")
            chunks = [a8[i : i + PASS_OPS] for i in range(0, len(a8), PASS_OPS)]
            if not a3 or len(chunks) < 2:
                raise SystemExit(f"missing or short A3/A8 data: {base}")
            a3_med = statistics.median(a3)
            first = statistics.median(chunks[0])
            rest = statistics.median([v for chunk in chunks[1:] for v in chunk])
            print(
                f"{Path(run).name},{tier},{a3_med:.0f},{first:.0f},{rest:.0f},"
                f"{statistics.median(a8) / a3_med:.3f}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
