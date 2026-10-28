#!/usr/bin/env python3
"""Reproduce the 2026-10-28 P7 control review from committed raw data.

Reads one formal-v3 run (analysis-v3.json plus per-batch raw/req files) and the
frozen 10s raw files from earlier deployments. Writes a JSON review; it does not
regrade anything and never writes under results/.

Usage:
    python3 analysis/e5_p7_control_review.py [--run results/E5-formal/<run-id>]
        [--out <path>]
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUN = "results/E5-formal/20261027T093314Z-b5b480f"
DELTAS = ("0.1", "1", "10")
BINS_PER_DECADE = 20
BIN0_NS = 100

# 10s raw files retained from every deployment that has one. These are not pooled
# with formal v3; they only test whether the first-operation cost recurs.
FROZEN_10S = (
    ("pilot EBS", "results/E5/20261026T152946Z-b1efcb2/rep-1/ec2/ebs/B-10.raw.csv.gz"),
    ("pilot Lustre", "results/E5/20261026T152946Z-b1efcb2/rep-1/ec2/fsx_lustre/B-10.raw.csv.gz"),
    ("diagnostic r2 EBS", "results/E5-diagnostic/20261027T042037Z-7d9be14/rep-1/diagnostic/round-2/ebs-10.raw.csv"),
    ("diagnostic r3 EBS", "results/E5-diagnostic/20261027T042037Z-7d9be14/rep-1/diagnostic/round-3/ebs-10.raw.csv"),
    ("isolation non-lustre EBS", "results/E5-isolation-validation/20261027T073803Z-647a811/rep-1/diagnostic/non-lustre/ebs-10.raw.csv"),
    ("isolation paired EBS", "results/E5-isolation-validation/20261027T073803Z-647a811/rep-1/diagnostic/lustre-10/ebs-10.raw.csv"),
    ("isolation Lustre", "results/E5-isolation-validation/20261027T073803Z-647a811/rep-1/diagnostic/lustre-10/fsx_lustre-10.raw.csv"),
)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def open_text(path: Path):
    return gzip.open(path, "rt") if path.suffix == ".gz" else path.open("rt")


def quantile(values: list[int], p: float) -> float:
    v = sorted(values)
    i = (len(v) - 1) * p
    lo = math.floor(i)
    hi = min(lo + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (i - lo)


def warm_requests(raw: Path) -> int:
    """The sibling .req file carries the header; raw files do not."""
    req = Path(str(raw).replace(".raw.csv.gz", ".req.csv.gz").replace(".raw.csv", ".req.csv"))
    with open_text(req) as f:
        header = f.readline()
    for item in header.lstrip("# ").split():
        if item.startswith("warm_requests="):
            return int(item.split("=", 1)[1])
    raise ValueError(f"no warm_requests in {req}")


def first_vs_rest(raw: Path) -> dict:
    """Measured-window p50 for the first positive stat and the rest, per tier."""
    warm = warm_requests(raw)
    first, rest = [], []
    with open_text(raw) as f:
        for k, op, seq, ns in csv.reader(f):
            if op != "stat" or int(k) < warm:
                continue
            (first if seq == "0" else rest).append(int(ns))
    return {
        "measured_requests": len(first),
        "first_n": len(first),
        "rest_n": len(rest),
        "first_p10_ns": round(quantile(first, 0.10)),
        "first_p50_ns": round(quantile(first, 0.50)),
        "first_p90_ns": round(quantile(first, 0.90)),
        "rest_p50_ns": round(quantile(rest, 0.50)),
        "ratio_p50": round(quantile(first, 0.50) / quantile(rest, 0.50), 2),
    }


def first_operation_cell(raw: Path, threshold_ns: int) -> dict:
    """First-op decomposition plus the slow-cluster composition it drives."""
    warm = warm_requests(raw)
    by_request: dict[int, list[tuple[int, int]]] = {}
    enoent_first, enoent_rest = [], []
    with open_text(raw) as f:
        for k, op, seq, ns in csv.reader(f):
            if int(k) < warm:
                continue
            if op == "stat":
                by_request.setdefault(int(k), []).append((int(seq), int(ns)))
            elif op == "enoent":
                (enoent_first if seq == "0" else enoent_rest).append(int(ns))
    stats = [(seq, ns) for rows in by_request.values() for seq, ns in rows]
    slow = [(seq, ns) for seq, ns in stats if ns > threshold_ns]
    out = first_vs_rest(raw)
    out.update({
        "threshold_ns": threshold_ns,
        "slow_ops": len(slow),
        "slow_first_ops": sum(1 for seq, _ in slow if seq == 0),
        "slow_first_share": round(sum(1 for seq, _ in slow if seq == 0) / len(slow), 4) if slow else None,
        "slow_centroid_without_first_ns": centroid_without_first(stats),
        "enoent_first_p50_ns": round(quantile(enoent_first, 0.50)),
        "enoent_rest_p50_ns": round(quantile(enoent_rest, 0.50)),
        "enoent_ratio_p50": round(quantile(enoent_first, 0.50) / quantile(enoent_rest, 0.50), 2),
    })
    return out


def bin_center_ns(b: int) -> float:
    return BIN0_NS * 10 ** ((b + 0.5) / BINS_PER_DECADE)


def bin_of(ns: int) -> int:
    return math.floor(math.log10(ns / BIN0_NS) * BINS_PER_DECADE)


def kmeans2_weighted(hist: dict[int, int]) -> tuple[float, float] | None:
    """Same weighted log10 k-means as the grader, so the comparison is direct."""
    pts = sorted(((b + 0.5) / BINS_PER_DECADE + math.log10(BIN0_NS), c) for b, c in hist.items() if c > 0)
    if len(pts) < 2:
        return None
    c1, c2 = pts[0][0], pts[-1][0]
    for _ in range(200):
        a = [(x, w) for x, w in pts if abs(x - c1) <= abs(x - c2)]
        b = [(x, w) for x, w in pts if abs(x - c1) > abs(x - c2)]
        if not a or not b:
            break
        n1 = sum(x * w for x, w in a) / sum(w for _, w in a)
        n2 = sum(x * w for x, w in b) / sum(w for _, w in b)
        if abs(n1 - c1) < 1e-12 and abs(n2 - c2) < 1e-12:
            break
        c1, c2 = n1, n2
    return 10 ** c1, 10 ** c2


def centroid_without_first(values: list[tuple[int, int]]) -> float | None:
    hist: dict[int, int] = {}
    for seq, ns in values:
        if seq == 0 or ns <= 0:
            continue
        hist[bin_of(ns)] = hist.get(bin_of(ns), 0) + 1
    km = kmeans2_weighted(hist)
    return round(km[1]) if km else None



def rate_above(req_path: Path, threshold_ns: int) -> dict:
    """Measured-window share of positive stats whose bin centre exceeds threshold."""
    above = total = 0
    with open_text(req_path) as f:
        for line in f:
            if line.startswith("#") or line.startswith("k,"):
                continue
            parts = line.rstrip("\n").split(",")
            if parts[1] != "m" or not parts[5]:
                continue
            for item in parts[5].split("|"):
                b, c = (int(x) for x in item.split(":"))
                total += c
                if bin_center_ns(b) > threshold_ns:
                    above += c
    return {"above": above, "ops": total, "rate": round(above / total, 6) if total else None}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default=DEFAULT_RUN)
    ap.add_argument("--out")
    args = ap.parse_args()

    run = ROOT / args.run
    analysis_path = run / "analysis-v3.json"
    rep = next(iter(json.loads(analysis_path.read_text())["replications"].values()))
    base = run / "rep-1/formal/batches"
    sources: dict[str, str] = {str(analysis_path.relative_to(ROOT)): sha256(analysis_path)}

    gate, rates, spread = {}, {}, {}
    for d in DELTAS:
        target = rep["b"]["fsx_lustre"][d]
        control = rep["matched_controls"][d]
        boundary = target["stat_split"]["threshold_ns"]
        noise = control["stat_split"]["slow_centroid_ns"]
        share = control["slow_share_stat"]
        gate[d] = {
            "control_slow_share": share,
            "control_slow_centroid_ns": noise,
            "lustre_threshold_ns": boundary,
            "share_gate_triggered": share > 0.01,
            "centroid_gate_triggered": boundary is not None and noise is not None and noise >= boundary and share > 0,
            "registered_consequence": "NOT EVALUABLE",
            "implemented_consequence": "ERROR",
        }
        rows = {}
        for label, rel in (
            ("EBS matched", f"lustre-{d}/ebs-{d}.req.csv"),
            ("EBS batch", f"non-lustre/ebs-{d}.req.csv"),
            ("Lustre", f"lustre-{d}/fsx_lustre-{d}.req.csv"),
        ):
            path = base / rel
            rows[label] = rate_above(path, boundary)
            sources[str(path.relative_to(ROOT))] = sha256(path)
        rates[d] = rows
        spread[d] = {
            "matched_slow_centroid_ns": control["stat_split"]["slow_centroid_ns"],
            "batch_slow_centroid_ns": rep["b"]["ebs"][d]["stat_split"]["slow_centroid_ns"],
            "lustre_threshold_ns": boundary,
            "relative_spread": round(
                abs(control["stat_split"]["slow_centroid_ns"] - rep["b"]["ebs"][d]["stat_split"]["slow_centroid_ns"])
                / min(control["stat_split"]["slow_centroid_ns"], rep["b"]["ebs"][d]["stat_split"]["slow_centroid_ns"]), 4),
        }

    tiers = {
        "EBS matched": ("lustre-10/ebs-10.raw.csv", rep["matched_controls"]["10"]["stat_split"]["threshold_ns"]),
        "EBS batch": ("non-lustre/ebs-10.raw.csv", rep["b"]["ebs"]["10"]["stat_split"]["threshold_ns"]),
        "Lustre": ("lustre-10/fsx_lustre-10.raw.csv", rep["b"]["fsx_lustre"]["10"]["stat_split"]["threshold_ns"]),
        "EFS plain": ("non-lustre/efs_host_plain-10.raw.csv", rep["b"]["efs_host_plain"]["10"]["stat_split"]["threshold_ns"]),
        "EFS TLS": ("non-lustre/efs_host_tls-10.raw.csv", rep["b"]["efs_host_tls"]["10"]["stat_split"]["threshold_ns"]),
        "OpenZFS": ("non-lustre/fsx_openzfs-10.raw.csv", rep["b"]["fsx_openzfs"]["10"]["stat_split"]["threshold_ns"]),
        "ONTAP": ("non-lustre/fsx_ontap-10.raw.csv", rep["b"]["fsx_ontap"]["10"]["stat_split"]["threshold_ns"]),
    }
    decomposition = {}
    for label, (rel, threshold) in tiers.items():
        path = base / rel
        decomposition[label] = first_operation_cell(path, threshold)
        sources[str(path.relative_to(ROOT))] = sha256(path)

    invariance = {}
    for label, pattern in (
        ("EBS matched", "lustre-{d}/ebs-{d}.raw.csv"),
        ("Lustre", "lustre-{d}/fsx_lustre-{d}.raw.csv"),
    ):
        invariance[label] = {}
        for d in DELTAS:
            path = base / pattern.format(d=d)
            invariance[label][d] = first_vs_rest(path)
            sources[str(path.relative_to(ROOT))] = sha256(path)

    replication = {}
    for label, rel in FROZEN_10S:
        path = ROOT / rel
        replication[label] = first_vs_rest(path)
        sources[rel] = sha256(path)

    out = {
        "review": "P7 matched-control construct, first-operation decomposition",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "run": args.run,
        "grade_unchanged": "P7 ERROR; no aggregate verdict; no regrade",
        "gate": gate,
        "control_rate_above_lustre_threshold": rates,
        "same_run_ebs_control_spread": spread,
        "first_operation_10s": decomposition,
        "first_operation_by_interval": invariance,
        "frozen_10s_replication": replication,
        "limitations": [
            "Descriptive review only. It does not alter the registered classifier, the P7 gate or any grade.",
            "The first operation is a real cost a request pays; this review separates it from steady-state ops, it does not delete it.",
            "Frozen-run cells used different methods and are not pooled with formal v3; they only test whether the first-op cost recurs.",
            "n=1 formal deployment. No causal claim about scheduler or CPU-cache behaviour is made from timing alone.",
            "Histogram rates are bin-limited (20 bins/decade); the raw 10s counts are exact.",
        ],
    }
    out["sources_sha256"] = dict(sorted(sources.items()))
    text = json.dumps(out, indent=2) + "\n"
    if args.out:
        Path(args.out).write_text(text)
        print(f"wrote {args.out}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
