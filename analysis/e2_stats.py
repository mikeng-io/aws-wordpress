#!/usr/bin/env python3
"""E2 storage matrix: per-tier latency statistics, and a verdict on prediction 5.

Reads results/E2/<run-id>/rep-*/<arm>/<tier>.csv and writes summary.json plus a
markdown table. Same statistical choices as E3 (see docs/benchmark-protocol.md):
percentiles from the pooled sample, geometric mean alongside the median because a
geomean below the median is the signature of two populations, and a distribution-free
median CI from the order statistic rather than a normal approximation - latency is
log-normal at best and the normal approximation understates the interval.

Prediction 5 is pre-registered in experiments/E2-storage-matrix/README.md and is
DIFFERENTIAL: instance store and Fargate ephemeral must TIE on stat p50 - both are
answered by the kernel's dentry cache without reaching a device - and SEPARATE on
the device-touching ops. This script decides that mechanically rather than by
eyeballing the table, because a prediction that gets graded by its own author after
seeing the numbers is not a prediction.

Usage:  python3 analysis/e2_stats.py results/E2/<run-id>
"""
from __future__ import annotations

import csv
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path

# A "tie" means the medians' 95% confidence intervals overlap, OR the ratio between
# them is under this factor. Two tiers within 1.5x on an op measured in microseconds
# are not meaningfully different for this study's purposes; the effects it cares
# about are 100x. Declared before looking at the numbers.
TIE_MAX_RATIO = 1.5
# A "separation" needs to clear this. Between 1.5x and 3x is neither, and the
# prediction is recorded as INCONCLUSIVE for that op rather than forced.
SEPARATION_MIN_RATIO = 3.0

DEVICE_TOUCHING_OPS = ["create", "unlink", "open_read"]
CACHE_ANSWERED_OPS = ["stat"]


def load_csv(path: Path) -> dict[str, list[int]]:
    """Read bench output: bare "op,ns" lines, no header.

    A header row is tolerated but not required - the benchmark writes none, and an
    earlier collection path added one, so both shapes exist in the wild.
    """
    ops: dict[str, list[int]] = defaultdict(list)
    with path.open() as fh:
        for row in csv.reader(fh):
            if len(row) != 2:
                continue
            op, ns = row[0].strip(), row[1].strip()
            if not ns.isdigit():   # skips a header line if one is present
                continue
            ops[op].append(int(ns))
    return ops


def pct(values: list[int], p: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    idx = min(int(round(p / 100 * (len(ordered) - 1))), len(ordered) - 1)
    return ordered[idx]


def median_ci95(values: list[int]) -> tuple[int, int]:
    """Distribution-free CI for the median, from the binomial order statistic."""
    n = len(values)
    if n < 8:
        return (0, 0)
    ordered = sorted(values)
    # Normal approximation to the binomial rank bounds - standard for large n.
    half = 1.96 * math.sqrt(n) / 2
    lo = max(int(math.floor(n / 2 - half)), 0)
    hi = min(int(math.ceil(n / 2 + half)), n - 1)
    return (ordered[lo], ordered[hi])


def geo_mean(values: list[int]) -> float:
    positive = [v for v in values if v > 0]
    if not positive:
        return 0.0
    return math.exp(sum(math.log(v) for v in positive) / len(positive))


def summarize(values: list[int]) -> dict:
    lo, hi = median_ci95(values)
    p50, p99 = pct(values, 50), pct(values, 99)
    return {
        "n": len(values),
        "p50_ns": p50,
        "p90_ns": pct(values, 90),
        "p99_ns": p99,
        "median_ci95_ns": [lo, hi],
        "geomean_ns": round(geo_mean(values), 1),
        # A geomean well below the median means two populations, not one - the
        # signal that found EFS's bimodal stat in E3.
        "geomean_over_median": round(geo_mean(values) / p50, 3) if p50 else None,
        "tail_p99_over_p50": round(p99 / p50, 2) if p50 else None,
    }


def collect(run_dir: Path) -> dict[str, dict[str, list[int]]]:
    """{tier: {op: [ns, ...]}} pooled across replications, tier keyed as arm/tier."""
    pooled: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    reps = sorted(run_dir.glob("rep-*"))
    if not reps:
        raise SystemExit(f"no rep-* directories under {run_dir}")
    for rep in reps:
        for arm_dir in sorted(rep.iterdir()):
            if not arm_dir.is_dir():
                continue
            for csv_path in sorted(arm_dir.glob("*.csv")):
                key = f"{arm_dir.name}/{csv_path.stem}"
                for op, values in load_csv(csv_path).items():
                    pooled[key][op].extend(values)
    return pooled


def per_rep_medians(run_dir: Path) -> dict[str, dict[str, list[int]]]:
    """Median per replication, so between-rep agreement can be reported."""
    out: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    for rep in sorted(run_dir.glob("rep-*")):
        for arm_dir in sorted(rep.iterdir()):
            if not arm_dir.is_dir():
                continue
            for csv_path in sorted(arm_dir.glob("*.csv")):
                key = f"{arm_dir.name}/{csv_path.stem}"
                for op, values in load_csv(csv_path).items():
                    if values:
                        out[key][op].append(int(statistics.median(values)))
    return out


def verdict(a: dict, b: dict) -> tuple[str, float]:
    """TIE / SEPARATED / INCONCLUSIVE between two summarized ops, plus the ratio."""
    lo_a, hi_a = a["median_ci95_ns"]
    lo_b, hi_b = b["median_ci95_ns"]
    hi, lo = max(a["p50_ns"], b["p50_ns"]), min(a["p50_ns"], b["p50_ns"])
    ratio = hi / lo if lo else float("inf")
    overlap = not (hi_a < lo_b or hi_b < lo_a)
    if overlap or ratio <= TIE_MAX_RATIO:
        return "TIE", ratio
    if ratio >= SEPARATION_MIN_RATIO:
        return "SEPARATED", ratio
    return "INCONCLUSIVE", ratio


def grade_prediction_5(stats: dict) -> dict:
    """Prediction 5: instance store and Fargate ephemeral tie on stat, separate on
    the device-touching ops. Graded mechanically against thresholds fixed above."""
    ist = stats.get("ec2/instance_store")
    eph = stats.get("fargate/ephemeral")
    if not ist or not eph:
        return {"status": "NOT EVALUABLE", "reason": "missing instance_store or ephemeral"}

    checks = []
    for op in CACHE_ANSWERED_OPS:
        if op in ist and op in eph:
            v, r = verdict(ist[op], eph[op])
            checks.append({"op": op, "expected": "TIE", "observed": v, "ratio": round(r, 2)})
    for op in DEVICE_TOUCHING_OPS:
        if op in ist and op in eph:
            v, r = verdict(ist[op], eph[op])
            checks.append({"op": op, "expected": "SEPARATED", "observed": v, "ratio": round(r, 2)})

    met = [c for c in checks if c["observed"] == c["expected"]]
    failed = [c for c in checks if c["observed"] != c["expected"]]
    # The refutation condition named in the README is a UNIFORM result - the same
    # verdict everywhere - because that is what "the split is by operation, not by
    # tier" denies.
    observed = {c["observed"] for c in checks}
    uniform = len(observed) == 1

    if not failed:
        status = "SUPPORTED"
    elif uniform:
        status = "REFUTED"
    else:
        status = "PARTIALLY SUPPORTED"
    return {
        "status": status,
        "checks": checks,
        "met": len(met),
        "total": len(checks),
        "uniform_across_ops": uniform,
        "thresholds": {"tie_max_ratio": TIE_MAX_RATIO, "separation_min_ratio": SEPARATION_MIN_RATIO},
    }


def render(stats: dict, agreement: dict, pred5: dict) -> str:
    ops = ["stat", "stat_enoent", "open_read", "create", "unlink"]
    lines = ["| Tier | " + " | ".join(f"{o} p50" for o in ops) + " |",
             "|---" * (len(ops) + 1) + "|"]
    for tier in sorted(stats):
        cells = []
        for op in ops:
            s = stats[tier].get(op)
            cells.append(fmt_ns(s["p50_ns"]) if s else "—")
        lines.append(f"| `{tier}` | " + " | ".join(cells) + " |")

    lines += ["", "### Prediction 5 (pre-registered, graded mechanically)", "",
              f"**{pred5['status']}** — {pred5.get('met', 0)}/{pred5.get('total', 0)} checks met.", ""]
    if "checks" in pred5:
        lines += ["| Op | Expected | Observed | Ratio |", "|---|---|---|--:|"]
        for c in pred5["checks"]:
            mark = "" if c["observed"] == c["expected"] else " ⚠"
            lines.append(f"| `{c['op']}` | {c['expected']} | {c['observed']}{mark} | {c['ratio']}× |")

    lines += ["", "### Between-replication agreement (median of each rep)", "",
              "| Tier | op | per-rep medians | spread |", "|---|---|---|--:|"]
    for tier in sorted(agreement):
        for op in ("stat", "create"):
            meds = agreement[tier].get(op)
            if not meds or len(meds) < 2:
                continue
            spread = max(meds) / min(meds) if min(meds) else float("inf")
            lines.append(f"| `{tier}` | `{op}` | {', '.join(fmt_ns(m) for m in meds)} | {spread:.2f}× |")
    return "\n".join(lines)


def fmt_ns(ns: int) -> str:
    if ns >= 1_000_000:
        return f"{ns / 1_000_000:.2f} ms"
    if ns >= 1_000:
        return f"{ns / 1_000:.1f} µs"
    return f"{ns} ns"


def main(run_dir: Path) -> int:
    pooled = collect(run_dir)
    stats = {tier: {op: summarize(v) for op, v in ops.items()} for tier, ops in pooled.items()}
    agreement = per_rep_medians(run_dir)
    pred5 = grade_prediction_5(stats)

    out = {
        "experiment": "E2",
        "run_id": run_dir.name,
        "replications": len(list(run_dir.glob("rep-*"))),
        "tiers": stats,
        "between_rep_medians": {t: dict(o) for t, o in agreement.items()},
        "prediction_5": pred5,
    }
    (run_dir / "summary.json").write_text(json.dumps(out, indent=2) + "\n")
    table = render(stats, agreement, pred5)
    (run_dir / "summary.md").write_text(table + "\n")
    print(table)
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(main(Path(sys.argv[1])))
