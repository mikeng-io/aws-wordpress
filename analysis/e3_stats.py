#!/usr/bin/env python3
"""Distribution statistics for E3 latency data.

Percentiles alone are two numbers off a distribution; this reports the shape,
the spread, and how much to trust the centre.

Latency is log-normally distributed, so the geometric mean is reported alongside
the median - an arithmetic mean of latencies is dominated by the tail and says
little about a typical operation. The median CI is a distribution-free order
statistic interval (Thompson), not a normal approximation, because the data are
not normal. Between-rep agreement is reported explicitly: if three independent
task runs disagree, no single-run percentile deserves quoting.
"""
from __future__ import annotations

import csv
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path

PCTS = [1, 5, 10, 25, 50, 75, 90, 95, 99]


def load(path: Path) -> dict[str, list[int]]:
    d: dict[str, list[int]] = defaultdict(list)
    with path.open() as f:
        for row in csv.reader(f):
            if len(row) == 2:
                try:
                    d[row[0]].append(int(row[1]))
                except ValueError:
                    pass
    return d


def pct(v: list[int], p: float) -> int:
    return v[min(len(v) - 1, int(len(v) * p / 100))]


def median_ci95(v: list[int]) -> tuple[int, int]:
    """Distribution-free 95% CI for the median (normal approx to the binomial
    order statistic). Valid without assuming a distribution shape."""
    n = len(v)
    if n < 10:
        return (v[0], v[-1])
    z = 1.96
    lo = max(0, int(math.floor(n / 2 - z * math.sqrt(n) / 2)))
    hi = min(n - 1, int(math.ceil(n / 2 + z * math.sqrt(n) / 2)))
    return (v[lo], v[hi])


def geo_mean(v: list[int]) -> float:
    return math.exp(statistics.fmean(math.log(x) for x in v if x > 0))


def summarize(vals: list[int]) -> dict:
    v = sorted(vals)
    lo, hi = median_ci95(v)
    return {
        "n": len(v),
        "percentiles_ns": {f"p{p}": pct(v, p) for p in PCTS},
        "max_ns": v[-1],
        "median_ns": pct(v, 50),
        "median_ci95_ns": [lo, hi],
        "geometric_mean_ns": round(geo_mean(v), 1),
        # p99/p50 - how heavy the tail is. Near 1 = tight/local-disk-shaped.
        "tail_ratio_p99_p50": round(pct(v, 99) / pct(v, 50), 2),
        # IQR/median - spread independent of the tail.
        "iqr_over_median": round((pct(v, 75) - pct(v, 25)) / pct(v, 50), 3),
    }


def main(run_dir: Path) -> int:
    reps = sorted(p for p in run_dir.iterdir() if p.is_dir() and p.name.startswith("rep-"))
    if not reps:
        print(f"e3_stats: no rep-* dirs under {run_dir}", file=sys.stderr)
        return 66

    per_rep: dict[str, dict[str, dict[str, list[int]]]] = {}
    pooled: dict[str, dict[str, list[int]]] = {"local": defaultdict(list), "efs": defaultdict(list)}

    for rep in reps:
        per_rep[rep.name] = {}
        for mount in ("local", "efs"):
            f = rep / f"{mount}.csv"
            if not f.exists():
                continue
            data = load(f)
            per_rep[rep.name][mount] = data
            for op, vals in data.items():
                pooled[mount][op].extend(vals)

    ops = sorted(pooled["local"])
    report = {"run": run_dir.name, "reps": len(reps), "ops": {}, "between_rep": {}}

    for op in ops:
        loc, efs = summarize(pooled["local"][op]), summarize(pooled["efs"][op])
        report["ops"][op] = {
            "local": loc,
            "efs": efs,
            "median_ratio_efs_over_local": round(efs["median_ns"] / loc["median_ns"], 1),
            "p99_ratio_efs_over_local": round(
                efs["percentiles_ns"]["p99"] / loc["percentiles_ns"]["p99"], 1),
        }
        # Between-rep agreement on the median: if reps disagree, say so loudly.
        for mount in ("local", "efs"):
            meds = [pct(sorted(per_rep[r][mount][op]), 50) for r in per_rep if op in per_rep[r][mount]]
            if len(meds) > 1:
                spread = (max(meds) - min(meds)) / statistics.fmean(meds)
                report["between_rep"].setdefault(op, {})[mount] = {
                    "rep_medians_ns": meds,
                    "spread_pct_of_mean": round(spread * 100, 1),
                }

    (run_dir / "stats.json").write_text(json.dumps(report, indent=2) + "\n")

    def us(ns: float) -> str:
        return f"{ns/1000:,.1f} µs" if ns < 1_000_000 else f"{ns/1_000_000:,.2f} ms"

    lines = [
        f"# E3 distribution statistics", "",
        f"Run `{run_dir.name}` · {len(reps)} reps pooled · distribution-free median CIs.",
        "",
        "Latency is log-normal, so the geometric mean is reported rather than an",
        "arithmetic mean, which the tail would dominate. `tail` is p99/p50: near 1.0 is",
        "a tight, local-disk-shaped distribution; large means a heavy tail.",
        "",
        "| op | mount | n | median (95% CI) | geo-mean | p95 | p99 | tail p99/p50 |",
        "|---|---|--:|--:|--:|--:|--:|--:|",
    ]
    for op in ops:
        for mount in ("local", "efs"):
            s = report["ops"][op][mount]
            ci = s["median_ci95_ns"]
            lines.append(
                f"| {op} | {mount} | {s['n']:,} | {us(s['median_ns'])} "
                f"({us(ci[0])}–{us(ci[1])}) | {us(s['geometric_mean_ns'])} | "
                f"{us(s['percentiles_ns']['p95'])} | {us(s['percentiles_ns']['p99'])} | "
                f"{s['tail_ratio_p99_p50']}× |")
    lines += ["", "## EFS penalty by operation", "",
              "| op | median ratio | p99 ratio |", "|---|--:|--:|"]
    for op in ops:
        r = report["ops"][op]
        lines.append(f"| {op} | {r['median_ratio_efs_over_local']}× | {r['p99_ratio_efs_over_local']}× |")

    lines += ["", "## Between-rep agreement", "",
              "Three independent Fargate task runs. Spread is (max−min)/mean of the",
              "per-rep medians - the check on whether any single run is quotable.", "",
              "| op | mount | rep medians | spread |", "|---|---|---|--:|"]
    for op in ops:
        for mount in ("local", "efs"):
            b = report["between_rep"].get(op, {}).get(mount)
            if b:
                meds = " / ".join(us(m) for m in b["rep_medians_ns"])
                lines.append(f"| {op} | {mount} | {meds} | {b['spread_pct_of_mean']}% |")
    lines.append("")
    (run_dir / "stats.md").write_text("\n".join(lines) + "\n")
    print(f"e3_stats: wrote {run_dir / 'stats.md'}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: e3_stats.py <results/E3/RUN_ID>", file=sys.stderr)
        raise SystemExit(64)
    raise SystemExit(main(Path(sys.argv[1])))
