#!/usr/bin/env python3
"""Bimodality / cluster analysis for E3 latency distributions.

EFS latency distributions are not unimodal: an NFS client answers some metadata
calls from its local attribute cache (no network round trip) and sends the rest to
the server. Reporting a single median across both populations describes neither.

Method: 1-D k-means (k=2, Lloyd's algorithm) on log10(latency). Log space is the
right domain - the modes are separated by orders of magnitude, so Euclidean
distance on raw nanoseconds would let the slow mode dominate initialisation.
Initialised deterministically at the 10th and 90th percentiles rather than
randomly, so the result is reproducible.

Separation is then tested rather than assumed: a split is only reported as bimodal
if the two clusters are well separated (silhouette-style margin) AND each holds a
non-trivial share of the sample. Otherwise the distribution is reported unimodal
and the pooled statistics stand.
"""
from __future__ import annotations

import csv
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path

MIN_CLUSTER_SHARE = 0.02   # a mode holding <2% is noise, not a population
MIN_LOG10_SEPARATION = 0.5 # centroids must differ by >=~3.2x to call it bimodal


def load_op(run_dir: Path, mount: str, op: str) -> list[int]:
    vals: list[int] = []
    for rep in sorted(run_dir.glob("rep-*")):
        f = rep / f"{mount}.csv"
        if not f.exists():
            continue
        with f.open() as fh:
            for row in csv.reader(fh):
                if len(row) == 2 and row[0] == op:
                    try:
                        vals.append(int(row[1]))
                    except ValueError:
                        pass
    return vals


def kmeans2_log(vals: list[int], iters: int = 100) -> tuple[list[int], list[int], float, float]:
    xs = [math.log10(v) for v in vals if v > 0]
    s = sorted(xs)
    c1 = s[int(len(s) * 0.10)]
    c2 = s[int(len(s) * 0.90)]
    for _ in range(iters):
        a, b = [], []
        for x in xs:
            (a if abs(x - c1) <= abs(x - c2) else b).append(x)
        if not a or not b:
            break
        n1, n2 = statistics.fmean(a), statistics.fmean(b)
        if abs(n1 - c1) < 1e-12 and abs(n2 - c2) < 1e-12:
            c1, c2 = n1, n2
            break
        c1, c2 = n1, n2
    lo = [v for v in vals if v > 0 and abs(math.log10(v) - c1) <= abs(math.log10(v) - c2)]
    hi = [v for v in vals if v > 0 and abs(math.log10(v) - c1) > abs(math.log10(v) - c2)]
    return lo, hi, c1, c2


def med(v: list[int]) -> int:
    s = sorted(v)
    return s[len(s) // 2]


def median_ci95(v: list[int]) -> list[int]:
    s = sorted(v); n = len(s)
    if n < 10:
        return [s[0], s[-1]]
    z = 1.96
    lo = max(0, int(math.floor(n / 2 - z * math.sqrt(n) / 2)))
    hi = min(n - 1, int(math.ceil(n / 2 + z * math.sqrt(n) / 2)))
    return [s[lo], s[hi]]


def analyse(vals: list[int]) -> dict:
    if len(vals) < 30:
        return {"n": len(vals), "verdict": "too few samples"}
    lo, hi, c1, c2 = kmeans2_log(vals, )
    sep = c2 - c1
    share_lo = len(lo) / len(vals)
    share_hi = len(hi) / len(vals)
    bimodal = (sep >= MIN_LOG10_SEPARATION
               and min(share_lo, share_hi) >= MIN_CLUSTER_SHARE)
    out = {
        "n": len(vals),
        "pooled_median_ns": med(vals),
        "log10_centroid_separation": round(sep, 3),
        "separation_factor": round(10 ** sep, 1),
        "verdict": "bimodal" if bimodal else "unimodal",
    }
    if bimodal:
        out["clusters"] = {
            "fast": {
                "n": len(lo), "share": round(share_lo, 4),
                "median_ns": med(lo), "median_ci95_ns": median_ci95(lo),
            },
            "slow": {
                "n": len(hi), "share": round(share_hi, 4),
                "median_ns": med(hi), "median_ci95_ns": median_ci95(hi),
            },
        }
    return out


def main(run_dir: Path) -> int:
    ops = ["stat", "stat_enoent", "open_read", "create", "unlink"]
    report = {"run": run_dir.name, "method": {
        "algorithm": "1-D k-means (k=2, Lloyd) on log10(latency_ns)",
        "initialisation": "deterministic: 10th and 90th percentile of log10 values",
        "bimodal_criteria": {
            "min_log10_centroid_separation": MIN_LOG10_SEPARATION,
            "min_cluster_share": MIN_CLUSTER_SHARE,
        },
    }, "results": {}}

    for mount in ("local", "efs"):
        for op in ops:
            vals = load_op(run_dir, mount, op)
            if vals:
                report["results"].setdefault(op, {})[mount] = analyse(vals)

    (run_dir / "clusters.json").write_text(json.dumps(report, indent=2) + "\n")

    def fmt(ns: float) -> str:
        return f"{ns/1000:,.1f} µs" if ns < 1_000_000 else f"{ns/1_000_000:,.2f} ms"

    lines = ["# E3 cluster analysis — is the distribution one population or two?", "",
             f"Run `{run_dir.name}`. Method: 1-D k-means (k=2) on log10(latency),",
             "deterministically initialised at the 10th/90th percentiles. A split counts as",
             f"bimodal only if the centroids differ by ≥{MIN_LOG10_SEPARATION} in log10",
             f"(≥{10**MIN_LOG10_SEPARATION:.1f}×) and each cluster holds ≥{MIN_CLUSTER_SHARE:.0%} of the sample.",
             "", "| op | mount | n | verdict | separation | fast cluster | slow cluster |",
             "|---|---|--:|---|--:|---|---|"]
    for op in ops:
        for mount in ("local", "efs"):
            r = report["results"].get(op, {}).get(mount)
            if not r:
                continue
            if r.get("verdict") == "bimodal":
                c = r["clusters"]
                fast = f"{c['fast']['share']:.1%} @ {fmt(c['fast']['median_ns'])}"
                slow = f"{c['slow']['share']:.1%} @ {fmt(c['slow']['median_ns'])}"
            else:
                fast = slow = "—"
            lines.append(
                f"| {op} | {mount} | {r['n']:,} | {r['verdict']} | "
                f"{r.get('separation_factor','—')}× | {fast} | {slow} |")
    lines.append("")
    (run_dir / "clusters.md").write_text("\n".join(lines) + "\n")
    print(f"e3_clusters: wrote {run_dir / 'clusters.md'}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: e3_clusters.py <results/E3/RUN_ID>", file=sys.stderr)
        raise SystemExit(64)
    raise SystemExit(main(Path(sys.argv[1])))
