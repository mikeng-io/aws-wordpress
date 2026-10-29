#!/usr/bin/env python3
"""E2 storage matrix: per-tier latency statistics, and verdicts on predictions 1, 3 and 5.

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

Predictions 1 and 3 are graded by rules fixed in the same README on 2026-10-15,
before any FSx or throughput data existed ("Prediction 1: the throughput
measurement", and the sharpened kill conditions). The constants below are those
rules transcribed, not tuned.

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

# Comparisons the study actually makes claims about, declared here rather than
# assembled ad hoc after seeing the data. Each is (label, tier_a, tier_b): the
# question is always "does this axis move anything", so the expected answer for all
# of them is TIE and a SEPARATED verdict would be the interesting one.
# The FSx pairs were added 2026-10-15, before any FSx data existed. Unlike the EFS
# pairs they carry no expected verdict: whether a server-backed tier other than EFS
# moves stat is the open question, and the comparison is reported either way.
# efs_host_plain is the ruler because it is the same client path as FSx: host
# mount, no TLS, bind-mounted into the container.
DECLARED_COMPARISONS = [
    ("device: attached NVMe vs network block", "ec2/instance_store", "ec2/ebs"),
    ("TLS cost, container-direct (EC2)", "ec2/efs", "ec2/efs_plain"),
    ("TLS cost, host mount (EC2)", "ec2/efs_host_tls", "ec2/efs_host_plain"),
    ("TLS cost, container-direct (Fargate)", "fargate/efs", "fargate/efs_plain"),
    ("mount topology, TLS held", "ec2/efs", "ec2/efs_host_tls"),
    ("mount topology, plain held", "ec2/efs_plain", "ec2/efs_host_plain"),
    ("compute type, direct+TLS held", "ec2/efs", "fargate/efs"),
    ("server: FSx OpenZFS vs EFS", "ec2/fsx_openzfs", "ec2/efs_host_plain"),
    ("server: FSx ONTAP vs EFS", "ec2/fsx_ontap", "ec2/efs_host_plain"),
    ("server: FSx Lustre vs EFS", "ec2/fsx_lustre", "ec2/efs_host_plain"),
    ("NFS server, OpenZFS vs ONTAP", "ec2/fsx_openzfs", "ec2/fsx_ontap"),
]

# --- prediction 2 (FUSE arms) --------------------------------------------------------
# Fixed in experiments/E2-storage-matrix/fuse-arms.md before the first mount:
# JuiceFS must be >=10x faster than EFS on stat AND still >=3x slower than local.
P2_MIN_EFS_FACTOR = 10.0
P2_MIN_LOCAL_SEPARATION = 3.0
P2_EFS_TIER = "ec2/efs_host_plain"
P2_LOCAL_TIER = "ec2/instance_store"
P2_JUICE_TIER = "ec2/juicefs"

# --- prediction 3 -------------------------------------------------------------------
BLOCK_TIERS = ["ec2/instance_store", "ec2/ebs", "fargate/ephemeral"]
P3_MIN_FACTOR = 10.0   # "within one order of magnitude" refutes

# --- prediction 1 -------------------------------------------------------------------
# The seven tiers ranked, the metric, and the thresholds - all from the README.
P1_TIERS = [
    "ec2/instance_store", "ec2/ebs", "fargate/ephemeral", "ec2/efs_host_plain",
    "ec2/fsx_openzfs", "ec2/fsx_lustre", "ec2/fsx_ontap",
]
P1_STREAMS = 4                 # graded metric: 4-stream read MB/s
P1_AGREE_MIN_RHO = 0.7
P1_DIFFER_MAX_RHO = 0.3
P1_MAX_RESIDENT_PCT = 1.0      # a read phase starting above this measured RAM
P1_MIN_EVALUABLE_REPS = 3
P1_LUSTRE_MIN_RANK_GAP = 2
COMPARISON_OPS = ["stat", "open_read", "create", "unlink"]


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


def latency_csvs(arm_dir: Path) -> list[Path]:
    """Latency CSVs only. The arm directory also holds conformance, throughput and
    mount-facts CSVs; their rows happen not to parse as "op,ns" today, but relying on
    that is how a new file type quietly becomes a tier."""
    return [p for p in sorted(arm_dir.glob("*.csv"))
            if "." not in p.stem and p.stem != "mount-facts"]


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
            for csv_path in latency_csvs(arm_dir):
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
            for csv_path in latency_csvs(arm_dir):
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


def grade_prediction_2(stats: dict) -> dict:
    """P2: JuiceFS beats EFS by a wide margin and still loses to local storage."""
    jfs = stats.get(P2_JUICE_TIER)
    efs = stats.get(P2_EFS_TIER)
    local = stats.get(P2_LOCAL_TIER)
    if not jfs or not efs or not local or not all("stat" in t for t in (jfs, efs, local)):
        return {"status": "NOT EVALUABLE", "reason": "missing juicefs, EFS or local stat"}
    j = jfs["stat"]["p50_ns"]
    e = efs["stat"]["p50_ns"]
    l = local["stat"]["p50_ns"]
    if not j or not e or not l:
        return {"status": "NOT EVALUABLE", "reason": "zero median"}
    efs_ratio = j / e
    local_ratio = j / l
    if efs_ratio >= 1.0:
        status = "REFUTED"
        reason = "JuiceFS is not faster than EFS"
    elif efs_ratio <= 1.0 / P2_MIN_EFS_FACTOR and local_ratio >= P2_MIN_LOCAL_SEPARATION:
        status = "SUPPORTED"
        reason = ">=10x faster than EFS and still >=3x slower than local"
    else:
        status = "INCONCLUSIVE"
        reason = "direction held but the wide-margin / local-separation test did not"
    return {
        "status": status,
        "reason": reason,
        "juicefs_stat_p50_ns": j,
        "efs_stat_p50_ns": e,
        "local_stat_p50_ns": l,
        "juicefs_over_efs": efs_ratio,
        "juicefs_over_local": local_ratio,
        "min_efs_factor": P2_MIN_EFS_FACTOR,
        "min_local_separation": P2_MIN_LOCAL_SEPARATION,
    }


def grade_prediction_4(run_dir: Path) -> dict:
    """P4: Mountpoint for S3 fails the single-node POSIX conformance suite.

    Any FAIL is enough - the prediction is about semantics, not the number of
    failures. ERROR means the suite could not run and must not be read as a pass.
    The same checks repeat in every replication; report the distinct checks, not
    three copies of each.
    """
    by_rep: dict[str, list[tuple[str, str, str]]] = {}
    for rep in sorted(run_dir.glob("rep-*")):
        path = rep / "ec2" / "mountpoint_s3.conformance.csv"
        if not path.exists():
            continue
        rows: list[tuple[str, str, str]] = []
        with path.open() as fh:
            for row in csv.reader(fh):
                if len(row) >= 2 and not row[0].strip().startswith("TOTAL_"):
                    rows.append((row[0].strip(), row[1].strip(),
                                 row[2].strip() if len(row) > 2 else ""))
        by_rep[rep.name] = rows
    if not by_rep:
        return {"status": "NOT EVALUABLE", "reason": "no Mountpoint conformance CSV"}

    fails: dict[str, str] = {}
    errors: dict[str, str] = {}
    checks: set[str] = set()
    per_rep: dict[str, dict[str, int]] = {}
    for rep, rows in by_rep.items():
        checks.update(c for c, _, _ in rows)
        rep_fails = [c for c, st, _ in rows if st == "FAIL"]
        rep_errors = [c for c, st, _ in rows if st == "ERROR"]
        for c, st, d in rows:
            if st == "FAIL":
                fails.setdefault(c, d)
            elif st == "ERROR":
                errors.setdefault(c, d)
        per_rep[rep] = {"fails": len(rep_fails), "errors": len(rep_errors)}

    if fails:
        status = "SUPPORTED"
        reason = f"{len(fails)} distinct conformance check(s) failed"
    elif errors:
        status = "ERROR"
        reason = f"{len(errors)} check(s) could not run; no PASS/FAIL verdict"
    else:
        status = "REFUTED"
        reason = "all conformance checks passed"
    return {
        "status": status,
        "reason": reason,
        "checks": len(checks),
        "replications": len(by_rep),
        "per_rep": per_rep,
        "fails": [{"check": c, "detail": d} for c, d in fails.items()],
        "errors": [{"check": c, "detail": d} for c, d in errors.items()],
    }

def grade_prediction_3(stats: dict) -> dict:
    """No server-backed tier within one order of magnitude of the block group on stat."""
    block = [stats[t]["stat"]["p50_ns"] for t in BLOCK_TIERS if "stat" in stats.get(t, {})]
    if len(block) != len(BLOCK_TIERS):
        return {"status": "NOT EVALUABLE", "reason": "a block-backed tier is missing"}
    block_p50 = statistics.median(block)
    bar = block_p50 * P3_MIN_FACTOR
    server = {t: s_["stat"]["p50_ns"] for t, s_ in stats.items()
              if ("efs" in t or "fsx" in t) and "stat" in s_}
    if not server:
        return {"status": "NOT EVALUABLE", "reason": "no server-backed tiers"}
    within = sorted(t for t, p in server.items() if p < bar)
    return {
        "status": "REFUTED" if within else "SUPPORTED",
        "block_group_stat_p50_ns": block_p50,
        "bar_ns": bar,
        "server_tiers": {t: {"stat_p50_ns": p, "factor": round(p / block_p50, 1)}
                         for t, p in sorted(server.items())},
        "within_one_order": within,
        # Before 2026-10-15 E2 had no FSx tiers; a verdict on EFS alone is a verdict
        # on a narrower claim than the prediction makes, and says so.
        "fsx_tiers_present": sorted(t for t in server if "fsx" in t),
    }


def average_ranks(values: dict[str, float], descending: bool) -> dict[str, float]:
    """Rank 1 = best. Ties share the mean of the ranks they span."""
    order = sorted(values, key=lambda k: -values[k] if descending else values[k])
    ranks: dict[str, float] = {}
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in order[i:j + 1]:
            ranks[k] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def spearman(a: dict[str, float], b: dict[str, float]) -> float:
    """Pearson correlation of two rank vectors over the same keys."""
    keys = sorted(a)
    xa, xb = [a[k] for k in keys], [b[k] for k in keys]
    ma, mb = statistics.fmean(xa), statistics.fmean(xb)
    cov = sum((x - ma) * (y - mb) for x, y in zip(xa, xb))
    var = math.sqrt(sum((x - ma) ** 2 for x in xa) * sum((y - mb) ** 2 for y in xb))
    return cov / var if var else 0.0


def load_tput(path: Path) -> dict:
    """{'read_<n>': {...}, 'write_<n>': {...}} or {'error': ...} for one tier."""
    if not path.is_file():
        return {"error": "missing"}
    out: dict = {}
    for row in csv.reader(path.open()):
        if len(row) != 5:
            continue
        phase, streams, nbytes, ns, resident = row
        if phase == "error":
            return {"error": "probe failed"}
        nbytes_i, ns_i = int(nbytes), int(ns)
        out[f"{phase}_{streams}"] = {
            "bytes": nbytes_i, "ns": ns_i,
            "mb_per_s": round(nbytes_i / ns_i * 1e3, 1) if ns_i else None,
            "resident_pct": float(resident),
        }
    return out


def grade_prediction_1(run_dir: Path) -> dict:
    """Spearman rho between stat-p50 rank and 4-stream read MB/s rank, per replication."""
    reps_out = []
    for rep in sorted(run_dir.glob("rep-*")):
        row: dict = {"rep": rep.name, "tiers": {}}
        problems = []
        stat_p50: dict[str, float] = {}
        tput: dict[str, float] = {}
        for tier in P1_TIERS:
            arm, name = tier.split("/")
            lat = rep / arm / f"{name}.csv"
            t = load_tput(rep / arm / f"{name}.tput.csv")
            read = t.get(f"read_{P1_STREAMS}")
            entry: dict = {"throughput": t}
            if not lat.is_file() or not load_csv(lat).get("stat"):
                problems.append(f"{tier}: no stat data")
            else:
                stat_p50[tier] = statistics.median(load_csv(lat)["stat"])
                entry["stat_p50_ns"] = stat_p50[tier]
            if "error" in t or read is None:
                problems.append(f"{tier}: throughput ERROR ({t.get('error', 'no 4-stream read')})")
            elif read["resident_pct"] > P1_MAX_RESIDENT_PCT:
                problems.append(f"{tier}: throughput ERROR (read started {read['resident_pct']}% resident)")
            else:
                tput[tier] = read["mb_per_s"]
            row["tiers"][tier] = entry
        if problems:
            row.update({"evaluable": False, "problems": problems})
        else:
            sr = average_ranks(stat_p50, descending=False)
            tr = average_ranks(tput, descending=True)
            rho = spearman(sr, tr)
            reading = ("AGREE" if rho >= P1_AGREE_MIN_RHO
                       else "DIFFER" if rho <= P1_DIFFER_MAX_RHO else "INCONCLUSIVE")
            gap = sr["ec2/fsx_lustre"] - tr["ec2/fsx_lustre"]
            row.update({"evaluable": True, "rho": round(rho, 3), "reading": reading,
                        "stat_rank": sr, "throughput_rank": tr, "lustre_rank_gap": gap})
        reps_out.append(row)

    ok = [r for r in reps_out if r["evaluable"]]
    if len(ok) < P1_MIN_EVALUABLE_REPS:
        status = "NOT EVALUABLE"
        lustre = "NOT EVALUABLE"
    else:
        readings = {r["reading"] for r in ok}
        status = ("SUPPORTED" if readings == {"DIFFER"}
                  else "REFUTED" if readings == {"AGREE"} else "INCONCLUSIVE")
        gaps = [r["lustre_rank_gap"] for r in ok]
        lustre = ("SUPPORTED" if all(g >= P1_LUSTRE_MIN_RANK_GAP for g in gaps)
                  else "REFUTED" if all(g <= 0 for g in gaps) else "INCONCLUSIVE")
    return {
        "status": status,
        "lustre_clause": lustre,
        "evaluable_reps": len(ok),
        "replications": reps_out,
        "rules": {"tiers": P1_TIERS, "streams": P1_STREAMS,
                  "agree_min_rho": P1_AGREE_MIN_RHO, "differ_max_rho": P1_DIFFER_MAX_RHO,
                  "max_resident_pct": P1_MAX_RESIDENT_PCT,
                  "min_evaluable_reps": P1_MIN_EVALUABLE_REPS,
                  "lustre_min_rank_gap": P1_LUSTRE_MIN_RANK_GAP},
    }


def explore_prediction_1_bound(run_dir: Path) -> dict:
    """EXPLORATORY, never a verdict. Rule drafted 2026-10-15 while replications 2-3
    of 20261015T000959Z-85382cc were running, before their data was seen.

    A phase that started r% resident delivered (1 - r) of its bytes from storage in
    the measured time, so its storage throughput lies between measured x (1 - r) and
    measured. Spearman rho is computed at both ends, with the graded rule's
    thresholds. "robust" means the reading is identical at both bounds in every
    replication. Only the residency guard is relaxed here; every other ERROR
    (missing data, a failed probe) still makes a replication unusable.
    """
    reps_out = []
    for rep in sorted(run_dir.glob("rep-*")):
        stat_p50: dict[str, float] = {}
        upper: dict[str, float] = {}
        lower: dict[str, float] = {}
        resident: dict[str, float] = {}
        problems = []
        for tier in P1_TIERS:
            arm, name = tier.split("/")
            lat = rep / arm / f"{name}.csv"
            t = load_tput(rep / arm / f"{name}.tput.csv")
            read = t.get(f"read_{P1_STREAMS}")
            stats_ = load_csv(lat).get("stat") if lat.is_file() else None
            if not stats_:
                problems.append(f"{tier}: no stat data")
                continue
            if "error" in t or read is None:
                problems.append(f"{tier}: {t.get('error', 'no 4-stream read')}")
                continue
            stat_p50[tier] = statistics.median(stats_)
            r = max(read["resident_pct"], 0.0)
            resident[tier] = r
            upper[tier] = read["mb_per_s"]
            lower[tier] = read["mb_per_s"] * (1 - r / 100)
        if problems:
            reps_out.append({"rep": rep.name, "usable": False, "problems": problems})
            continue
        sr = average_ranks(stat_p50, descending=False)
        out = {"rep": rep.name, "usable": True,
               "resident_pct": {k: v for k, v in resident.items() if v > 0}}
        for label, tp in (("upper", upper), ("lower", lower)):
            tr = average_ranks(tp, descending=True)
            rho = spearman(sr, tr)
            out[label] = {
                "rho": round(rho, 3),
                "reading": ("AGREE" if rho >= P1_AGREE_MIN_RHO
                            else "DIFFER" if rho <= P1_DIFFER_MAX_RHO else "INCONCLUSIVE"),
                "lustre_throughput_rank": tr["ec2/fsx_lustre"],
                "lustre_rank_gap": sr["ec2/fsx_lustre"] - tr["ec2/fsx_lustre"],
            }
        out["robust"] = out["upper"]["reading"] == out["lower"]["reading"]
        reps_out.append(out)
    usable = [r for r in reps_out if r["usable"]]
    return {
        "status": "EXPLORATORY - NOT A VERDICT",
        "robust_in_every_replication": bool(usable) and all(r["robust"] for r in usable),
        "readings": sorted({r["upper"]["reading"] for r in usable} | {r["lower"]["reading"] for r in usable}),
        "replications": reps_out,
    }


def noise_floor(agreement: dict) -> dict:
    """Between-replication spread per tier/op - the floor any claim must clear.

    A 1.08x difference between two tiers means nothing if the same tier varies 1.8x
    between deployments of itself. Published as a first-class number for exactly that
    reason, rather than left for the reader to derive.
    """
    out: dict[str, dict] = {}
    for tier, ops in agreement.items():
        for op, meds in ops.items():
            if len(meds) < 2 or not min(meds):
                continue
            out.setdefault(tier, {})[op] = {
                "per_rep_medians_ns": meds,
                "spread": round(max(meds) / min(meds), 3),
            }
    return out


def comparisons(stats: dict, floors: dict) -> list[dict]:
    """Every declared comparison, judged against the between-rep noise floor."""
    out = []
    for label, a, b in DECLARED_COMPARISONS:
        if a not in stats or b not in stats:
            continue
        for op in COMPARISON_OPS:
            if op not in stats[a] or op not in stats[b]:
                continue
            v, r = verdict(stats[a][op], stats[b][op])
            # The worst between-rep spread of either arm on this op. A difference
            # smaller than this is indistinguishable from re-running the same thing.
            fl = max(
                floors.get(a, {}).get(op, {}).get("spread", 1.0),
                floors.get(b, {}).get(op, {}).get("spread", 1.0),
            )
            out.append({
                "comparison": label, "op": op, "a": a, "b": b,
                "ratio": round(r, 3), "verdict": v,
                "noise_floor_spread": fl,
                "inside_noise_floor": r <= fl,
            })
    return out


def clusters(run_dir: Path, pooled: dict) -> dict:
    """Bimodality test per tier/op, reusing E3's gates unchanged.

    Imported rather than reimplemented: E3 found EFS stat to be two populations, and
    a second implementation of the same test is how two experiments quietly stop
    being comparable.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from e3_clusters import kmeans2_log, MIN_CLUSTER_SHARE, MIN_LOG10_SEPARATION

    out: dict[str, dict] = {}
    for tier, ops in pooled.items():
        for op in ("stat", "open_read"):
            vals = ops.get(op)
            if not vals or len(vals) < 100:
                continue
            lo, hi, c_lo, c_hi = kmeans2_log(vals)
            if not lo or not hi:
                continue
            share = len(lo) / len(vals)
            bimodal = (
                share >= MIN_CLUSTER_SHARE
                and (1 - share) >= MIN_CLUSTER_SHARE
                and (c_hi - c_lo) >= MIN_LOG10_SEPARATION
            )
            out.setdefault(tier, {})[op] = {
                "fast_share": round(share, 4),
                "fast_median_ns": int(statistics.median(lo)),
                "slow_median_ns": int(statistics.median(hi)),
                "centroid_separation": round(10 ** (c_hi - c_lo), 1),
                "bimodal": bimodal,
                "gates": {"min_cluster_share": MIN_CLUSTER_SHARE,
                          "min_log10_separation": MIN_LOG10_SEPARATION},
            }
    return out


def render_p1_p3(pred1: dict, pred3: dict) -> list[str]:
    lines = ["", "### Prediction 1 (pre-registered 2026-10-15, graded mechanically)", "",
             f"**{pred1['status']}** — {pred1['evaluable_reps']} evaluable replication(s); "
             f"Lustre clause **{pred1['lustre_clause']}**.", ""]
    for r in pred1["replications"]:
        if r["evaluable"]:
            lines.append(f"- `{r['rep']}`: ρ = {r['rho']} → {r['reading']}; "
                         f"Lustre stat rank − throughput rank = {r['lustre_rank_gap']}")
        else:
            lines.append(f"- `{r['rep']}`: not evaluable — " + "; ".join(r["problems"]))
    lines += ["", "#### Prediction 1, exploratory residency bound (not a verdict)", ""]
    for r in pred1.get("_explore", {}).get("replications", []):
        if r["usable"]:
            lines.append(f"- `{r['rep']}`: ρ {r['upper']['rho']} ({r['upper']['reading']}) at measured, "
                         f"{r['lower']['rho']} ({r['lower']['reading']}) at the residency floor; "
                         f"Lustre throughput rank {r['upper']['lustre_throughput_rank']} / "
                         f"{r['lower']['lustre_throughput_rank']}; robust: {r['robust']}")
        else:
            lines.append(f"- `{r['rep']}`: unusable — " + "; ".join(r["problems"]))
    lines += ["", "### Prediction 3 (graded mechanically)", "", f"**{pred3['status']}**"]
    if "bar_ns" in pred3:
        lines += [f"", f"Block-group stat p50 {fmt_ns(int(pred3['block_group_stat_p50_ns']))}; "
                  f"bar is 10× = {fmt_ns(int(pred3['bar_ns']))}. "
                  f"FSx tiers present: {', '.join(pred3['fsx_tiers_present']) or 'none'}.", "",
                  "| Server tier | stat p50 | × block group |", "|---|--:|--:|"]
        for t_, d in pred3["server_tiers"].items():
            lines.append(f"| `{t_}` | {fmt_ns(d['stat_p50_ns'])} | {d['factor']}× |")
    elif "reason" in pred3:
        lines.append(f"— {pred3['reason']}")
    return lines


def render(stats: dict, agreement: dict, pred5: dict, comps: list, clus: dict) -> str:
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

    if comps:
        lines += ["", "### Declared comparisons, judged against the noise floor", "",
                  "| Comparison | op | ratio | verdict | rep-to-rep spread | inside noise? |",
                  "|---|---|--:|---|--:|---|"]
        for c in comps:
            lines.append(
                f"| {c['comparison']} | `{c['op']}` | {c['ratio']:.2f}× | {c['verdict']} | "
                f"{c['noise_floor_spread']:.2f}× | {'yes' if c['inside_noise_floor'] else '**NO**'} |")

    bim = [(t_, o, d) for t_, ops in clus.items() for o, d in ops.items() if d["bimodal"]]
    if bim:
        lines += ["", "### Bimodality (1-D k-means on log10, E3's gates)", "",
                  "| Tier | op | fast share | fast median | slow median | separation |",
                  "|---|---|--:|--:|--:|--:|"]
        for t_, o, d in sorted(bim):
            lines.append(f"| `{t_}` | `{o}` | {d['fast_share'] * 100:.1f}% | "
                         f"{fmt_ns(d['fast_median_ns'])} | {fmt_ns(d['slow_median_ns'])} | "
                         f"{d['centroid_separation']:.0f}× |")

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


def render_pred2_4(pred2: dict, pred4: dict) -> str:
    lines = ["## Predictions 2 and 4 (FUSE arms)", "",
             f"- **P2 JuiceFS vs EFS:** `{pred2['status']}` — {pred2['reason']}"]
    if "juicefs_over_efs" in pred2:
        lines.append(f"  - JuiceFS/EFS stat p50: {pred2['juicefs_over_efs']:.3f}x; "
                     f"JuiceFS/local: {pred2['juicefs_over_local']:.2f}x")
    lines.append(f"- **P4 Mountpoint conformance:** `{pred4['status']}` — {pred4['reason']}")
    for f in pred4.get("fails", []):
        lines.append(f"  - FAIL `{f['check']}` {f['detail']}".rstrip())
    return "\n".join(lines) + "\n"


def main(run_dir: Path) -> int:
    pooled = collect(run_dir)
    stats = {tier: {op: summarize(v) for op, v in ops.items()} for tier, ops in pooled.items()}
    agreement = per_rep_medians(run_dir)
    pred5 = grade_prediction_5(stats)
    pred2 = grade_prediction_2(stats)
    pred4 = grade_prediction_4(run_dir)
    pred3 = grade_prediction_3(stats)
    pred1 = grade_prediction_1(run_dir)
    pred1_explore = explore_prediction_1_bound(run_dir)
    floors = noise_floor(agreement)
    comps = comparisons(stats, floors)
    clus = clusters(run_dir, pooled)

    out = {
        "experiment": "E2",
        "run_id": run_dir.name,
        "replications": len(list(run_dir.glob("rep-*"))),
        "tiers": stats,
        "between_rep_medians": {t: dict(o) for t, o in agreement.items()},
        "noise_floor": floors,
        "comparisons": comps,
        "clusters": clus,
        "prediction_5": pred5,
        "prediction_2": pred2,
        "prediction_4": pred4,
        "prediction_3": pred3,
        "prediction_1": pred1,
        "prediction_1_exploratory_bound": pred1_explore,
    }
    (run_dir / "summary.json").write_text(json.dumps(out, indent=2) + "\n")
    table = (render(stats, agreement, pred5, comps, clus) + "\n"
             + "\n".join(render_p1_p3({**pred1, "_explore": pred1_explore}, pred3))
             + "\n\n" + render_pred2_4(pred2, pred4))
    (run_dir / "summary.md").write_text(table + "\n")
    print(table)
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(main(Path(sys.argv[1])))
