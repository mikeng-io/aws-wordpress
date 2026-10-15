#!/usr/bin/env python3
"""E5 grading: what an NFS stat costs on a tree the client did not just create.

Reads a committed run (results/E5/<run-id>/rep-*/ec2/) and writes summary.json and
summary.md beside it. Every rule here was fixed in experiments/E5-attribute-cache/
README.md before any E5 data existed; the constants below are those rules, and a
change to one is a change to the pre-registration, which the README must record.

Three layers, each fail-closed:

1. Cohort A signatures. A cohort counts only if the RPC counters show it measured
   what it claims (a cold stat sent a LOOKUP, a revalidation a GETATTR, a hit
   nothing). A mismatch is ERROR for that tier and replication: never graded, never
   pooled, never reported as a latency. This is the check E2 lacked.
2. Cohort B cells. A cell (tier x interval) is ERROR if more than 5% of its
   deadlines were skipped, if any request overran a counter snapshot, or (NFS) if
   the counter miss fraction and the latency miss fraction disagree.
3. Predictions. Each is graded per replication as SUPPORTS / REFUTES / INCONCLUSIVE
   / NOT EVALUABLE (an input was ERROR). Across replications: SUPPORTED if every
   evaluable replication supports, REFUTED if every one refutes, NOT EVALUABLE with
   fewer than 3 evaluable, INCONCLUSIVE otherwise.

Usage: e5_stats.py <run-dir>        (exit 0 even when predictions fail: a REFUTED
                                     grade is a result, not an error)
"""
from __future__ import annotations

import csv
import gzip
import io
import json
import math
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from e2_stats import geo_mean, median_ci95, pct  # noqa: E402  (shared, unchanged)
from e3_clusters import MIN_CLUSTER_SHARE, MIN_LOG10_SEPARATION  # noqa: E402

# --- pre-registered constants (README, "Predictions" and "Method") ---------------
N = 1000                        # files per tree, and missing names per tree
SIG_MIN = 0.95                  # "at least 0.95 N" RPCs
SIG_MAX = 0.05                  # "at most 0.05 N" RPCs
FORCED_PASSES = 10
B_MAX_SKIP_FRACTION = 0.05      # a cell with more skipped deadlines is ERROR
B_AGREE_REL = 0.20              # counter vs latency miss fraction, relative...
B_AGREE_ABS = 0.002             # ...or absolute, whichever is looser
NFS_TIERS = ["efs_host_plain", "efs_host_tls", "fsx_openzfs", "fsx_ontap"]
E2_MISS_NS = {"efs_host_plain": 827_000, "fsx_openzfs": 98_000, "fsx_lustre": 149_000}
MIN_EVALUABLE_REPS = 3
BINS_PER_DECADE = 20
BIN_FLOOR_NS = 100

NFS_RPC_LOOKUPS = ("GETATTR", "LOOKUP", "ACCESS")


# --- loading ----------------------------------------------------------------------
def read_text(path: Path) -> str:
    if path.suffix == ".gz":
        with gzip.open(path, "rt") as fh:
            return fh.read()
    return path.read_text()


def kind(tier: str) -> str:
    return "block" if tier == "ebs" else "lustre" if tier == "fsx_lustre" else "nfs"


def parse_mountstats(path: Path) -> dict[str, dict[str, int]]:
    """Per mount point, per NFS op: the cumulative op count (first field)."""
    out: dict[str, dict[str, int]] = {}
    cur = None
    in_ops = False
    for line in read_text(path).splitlines():
        if line.startswith("device "):
            m = re.search(r" mounted on (\S+) ", line)
            cur = m.group(1) if m else None
            if cur:
                out[cur] = {}
            in_ops = False
            continue
        if cur is None:
            continue
        if "per-op statistics" in line:
            in_ops = True
            continue
        m = re.match(r"\s+([A-Z_0-9]+):\s+(\d+)", line)
        if in_ops and m:
            out[cur][m.group(1)] = int(m.group(2))
    return out


def ms_delta(rep_ec2: Path, pre: str, post: str, mount: str) -> dict[str, int] | None:
    a, b = rep_ec2 / "ms" / f"{pre}.txt", rep_ec2 / "ms" / f"{post}.txt"
    if not a.exists() or not b.exists():
        return None
    pa, pb = parse_mountstats(a), parse_mountstats(b)
    if mount not in pa or mount not in pb:
        return None
    return {op: pb[mount][op] - pa[mount].get(op, 0) for op in pb[mount]}


def parse_lustre(path: Path) -> dict[str, int] | None:
    """Sum of 'samples' per (class, counter) over every device, e.g. ('mdc','obd_ping').

    None if the host service answered ERROR: Lustre checks then grade ERROR."""
    if not path.exists():
        return None
    text = read_text(path)
    if text.startswith("ERROR"):
        return None
    out: dict[str, int] = defaultdict(int)
    cls = None
    for line in text.splitlines():
        m = re.match(r"^([a-z]+)\.[^=\s]+\.(\w+)=", line)
        if m:
            cls = f"{m.group(1)}.{m.group(2)}"   # e.g. mdc.stats, osc.stats, mdc.md_stats
            continue
        m = re.match(r"^(\w+)\s+(\d+)\s+samples", line)
        if m and cls:
            out[f"{cls}.{m.group(1)}"] += int(m.group(2))
    return dict(out)


def lustre_delta(rep_ec2: Path, pre: str, post: str) -> dict[str, int] | None:
    a = parse_lustre(rep_ec2 / "lustre" / f"{pre}.txt")
    b = parse_lustre(rep_ec2 / "lustre" / f"{post}.txt")
    if a is None or b is None:
        return None
    return {k: b[k] - a.get(k, 0) for k in b}


def lustre_rpcs(d: dict[str, int], cls: str) -> int:
    """RPCs a Lustre client class sent, net of keep-alive pings."""
    return d.get(f"{cls}.stats.req_waittime", 0) - d.get(f"{cls}.stats.obd_ping", 0)


# --- latency statistics -------------------------------------------------------------
def summarize(vals: list[int]) -> dict:
    if not vals:
        return {"n": 0}
    p50 = pct(vals, 50)
    lo, hi = median_ci95(vals)
    gm = geo_mean(vals)
    return {
        "n": len(vals), "p50_ns": p50, "median_ci95_ns": [lo, hi],
        "p10_ns": pct(vals, 10), "p25_ns": pct(vals, 25), "p75_ns": pct(vals, 75),
        "p90_ns": pct(vals, 90), "p99_ns": pct(vals, 99), "max_ns": max(vals),
        "geomean_ns": round(gm, 1),
        "iqr_over_median": round((pct(vals, 75) - pct(vals, 25)) / p50, 3) if p50 else None,
        "p99_over_p50": round(pct(vals, 99) / p50, 2) if p50 else None,
        "bimodality": bimodality([(math.log10(v), 1) for v in vals if v > 0]),
    }


def kmeans2_weighted(points: list[tuple[float, int]]) -> tuple[float, float, int, int]:
    """1-D k=2 on log10 values with weights, initialised at the weighted 10th/90th
    percentiles (the protocol's deterministic initialisation)."""
    pts = sorted(points)
    total = sum(w for _, w in pts)

    def wq(q: float) -> float:
        acc = 0
        for x, w in pts:
            acc += w
            if acc >= q * total:
                return x
        return pts[-1][0]

    c1, c2 = wq(0.10), wq(0.90)
    for _ in range(100):
        a = [(x, w) for x, w in pts if abs(x - c1) <= abs(x - c2)]
        b = [(x, w) for x, w in pts if abs(x - c1) > abs(x - c2)]
        if not a or not b:
            break
        n1 = sum(x * w for x, w in a) / sum(w for _, w in a)
        n2 = sum(x * w for x, w in b) / sum(w for _, w in b)
        if abs(n1 - c1) < 1e-12 and abs(n2 - c2) < 1e-12:
            break
        c1, c2 = n1, n2
    wa = sum(w for x, w in pts if abs(x - c1) <= abs(x - c2))
    return c1, c2, wa, total - wa


def bimodality(points: list[tuple[float, int]]) -> dict:
    """The protocol's test: separation >= 0.5 log10 AND each cluster >= 2%."""
    total = sum(w for _, w in points)
    if total < 30:
        return {"verdict": "too few samples"}
    c1, c2, w1, w2 = kmeans2_weighted(points)
    sep = c2 - c1
    share = min(w1, w2) / total
    bimodal = sep >= MIN_LOG10_SEPARATION and share >= MIN_CLUSTER_SHARE
    return {
        "verdict": "bimodal" if bimodal else "unimodal",
        "centroids_ns": [round(10 ** c1), round(10 ** c2)],
        "log10_separation": round(sep, 3), "minor_share": round(share, 4),
    }


def bin_center_ns(b: int) -> float:
    if b == 0:
        return BIN_FLOOR_NS / 2
    return BIN_FLOOR_NS * 10 ** ((b - 0.5) / BINS_PER_DECADE)


def bin_upper_ns(b: int) -> float:
    return BIN_FLOOR_NS * 10 ** (b / BINS_PER_DECADE)


# --- cohort A ------------------------------------------------------------------------
def load_a(rep_ec2: Path, tier: str) -> dict[str, list[int]]:
    """Cohort -> latencies. A8 keeps only passes 2..10: pass 1 on the forced mount
    is that mount's first touch (LOOKUP + GETATTR), not a forced revalidation - seen
    in the local NFS check, where pass 1 sent 1,040 LOOKUPs as well."""
    out: dict[str, list[int]] = defaultdict(list)
    a8_seen = 0
    path = rep_ec2 / f"A.{tier}.csv.gz"
    for row in csv.reader(io.StringIO(read_text(path))):
        if len(row) != 4:
            continue
        cohort, _op, _seq, ns = row
        if cohort == "A8":
            a8_seen += 1
            if a8_seen <= N:
                continue
        out[cohort].append(int(ns))
    return out


def a_signature(rep_ec2: Path, tier: str, cohort: str) -> dict:
    """PASS / FAIL / ERROR for one cohort, with the counter deltas it rests on."""
    k = kind(tier)
    if k == "block":
        return {"status": "PASS", "basis": "no counters for a block tier; latency is the reference"}
    if k == "nfs":
        mount = f"/e5/{tier}/{'forced' if cohort == 'A8' else 'default'}"
        d = ms_delta(rep_ec2, f"A.{tier}.{cohort}.pre", f"A.{tier}.{cohort}.post", mount)
        if d is None:
            return {"status": "ERROR", "basis": f"no mountstats for {mount}"}
        g, lk, ac = d.get("GETATTR", 0), d.get("LOOKUP", 0), d.get("ACCESS", 0)
        rd = d.get("READ", 0)
        rule, ok = {
            "A1": ("LOOKUP >= 0.95N", lk >= SIG_MIN * N),
            "A2": ("LOOKUP >= 0.95N", lk >= SIG_MIN * N),
            "A3": ("GETATTR+LOOKUP >= 0.95N", g + lk >= SIG_MIN * N),
            "A5": ("GETATTR+LOOKUP+ACCESS <= 0.05N", g + lk + ac <= SIG_MAX * N),
            "A6": ("READ >= 0.95N", rd >= SIG_MIN * N),
            "A8": ("GETATTR >= 0.95 x 10N", g >= SIG_MIN * FORCED_PASSES * N),
        }.get(cohort, ("recorded only", True))
        nonzero = {op: v for op, v in d.items() if v}
        return {"status": "PASS" if ok else "FAIL", "rule": rule, "deltas": nonzero}
    # Lustre: MDC RPCs for a cold stat, OST reads for a cold read. Other cohorts are
    # recorded; A3 is expected to be a hit (locks do not expire at 75 s).
    d = lustre_delta(rep_ec2, f"A.{tier}.{cohort}.pre", f"A.{tier}.{cohort}.post")
    if d is None:
        return {"status": "ERROR", "basis": "Lustre counter snapshot missing or ERROR"}
    mdc, osc = lustre_rpcs(d, "mdc"), lustre_rpcs(d, "osc")
    rule, ok = {
        "A1": ("MDC RPCs >= 0.95N", mdc >= SIG_MIN * N),
        "A5": ("MDC+OSC RPCs <= 0.05N", mdc + osc <= SIG_MAX * N),
        "A6": ("OST reads >= 0.95N", d.get("osc.stats.ost_read", 0) >= SIG_MIN * N),
    }.get(cohort, ("recorded only", True))
    return {"status": "PASS" if ok else "FAIL", "rule": rule,
            "deltas": {"mdc_rpcs": mdc, "osc_rpcs": osc, "ost_read": d.get("osc.stats.ost_read", 0)}}


def cohort_a(rep_ec2: Path, tiers: list[str]) -> dict:
    out = {}
    for t in tiers:
        lat = load_a(rep_ec2, t)
        cohorts = ["A1", "A2", "A3", "A4", "A5", "A6", "A7"] + (["A8"] if kind(t) == "nfs" else [])
        out[t] = {}
        for c in cohorts:
            sig = a_signature(rep_ec2, t, c)
            entry = {"signature": sig}
            # A FAIL or ERROR cohort keeps its counters as evidence, never a latency.
            if sig["status"] == "PASS":
                entry["latency"] = summarize(lat.get(c, []))
            out[t][c] = entry
    return out


def a_median(a: dict, tier: str, cohort: str) -> int | None:
    e = a.get(tier, {}).get(cohort)
    if not e or e["signature"]["status"] != "PASS":
        return None
    return e["latency"].get("p50_ns")


# --- cohort B ------------------------------------------------------------------------
def load_b(path: Path) -> dict:
    reqs: dict[int, dict] = {}
    skips = {"warmup": 0, "measure": 0}
    overruns = []
    for row in csv.reader(io.StringIO(read_text(path))):
        if not row:
            continue
        if row[0] == "req":
            k, phase, late, dur, op, n, sm, bins = row[1:9]
            hist = {}
            if bins:
                for pair in bins.split(";"):
                    b, c = pair.split(":")
                    hist[int(b)] = int(c)
            r = reqs.setdefault(int(k), {"phase": phase, "late": int(late), "dur": int(dur)})
            r[op] = {"n": int(n), "sum": int(sm), "hist": hist}
        elif row[0] == "skip":
            skips[row[2]] += 1
        elif row[0] == "overrun":
            overruns.append((int(row[1]), row[2]))
    return {"reqs": reqs, "skips": skips, "overruns": overruns}


def cell_b(rep_ec2: Path, tier: str, iv: str, a: dict) -> dict:
    b = load_b(rep_ec2 / f"B.{tier}.{iv}.csv.gz")
    meas = {k: r for k, r in b["reqs"].items() if r["phase"] == "measure"}
    n_req = len(meas)
    deadlines = n_req + b["skips"]["measure"]
    out: dict = {"requests": n_req, "skipped": b["skips"]["measure"]}
    errors = []
    if deadlines == 0:
        return {**out, "status": "ERROR", "errors": ["no measured requests"]}
    skip_frac = b["skips"]["measure"] / deadlines
    out["skip_fraction"] = round(skip_frac, 4)
    if skip_frac > B_MAX_SKIP_FRACTION:
        errors.append(f"skipped {skip_frac:.1%} of deadlines (> {B_MAX_SKIP_FRACTION:.0%})")
    if b["overruns"]:
        errors.append(f"{len(b['overruns'])} request(s) overran a counter snapshot")

    stats_issued = sum(r["stat"]["n"] for r in meas.values())
    enoent_issued = sum(r["enoent"]["n"] for r in meas.values())
    out["stats_issued"], out["enoent_issued"] = stats_issued, enoent_issued

    # Per-request summed stat time: the cost a request pays. Amortised = total / n.
    sums = sorted(r["stat"]["sum"] for r in meas.values())
    out["per_request_stat_ns"] = {
        "amortised": round(sum(sums) / n_req) if n_req else None,
        "median": pct(sums, 50), "p99": pct(sums, 99), "max": max(sums) if sums else None,
    }
    esums = sorted(r["enoent"]["sum"] for r in meas.values())
    out["per_request_enoent_ns"] = {"amortised": round(sum(esums) / n_req) if n_req else None,
                                    "median": pct(esums, 50), "p99": pct(esums, 99)}

    # Hit/miss threshold from the SAME replication's cohort A: the geometric midpoint
    # of this tier's hit (A5) and miss (A3 on NFS, A1 on Lustre) medians.
    k = kind(tier)
    thr = None
    if k in ("nfs", "lustre"):
        hit = a_median(a, tier, "A5")
        miss = a_median(a, tier, "A3" if k == "nfs" else "A1")
        if hit and miss and miss > hit:
            thr = math.sqrt(hit * miss)
        else:
            errors.append("no hit/miss threshold: cohort A5 or the miss cohort is not PASS")
    out["miss_threshold_ns"] = round(thr) if thr else None

    def slow(hist: dict[int, int]) -> int:
        return sum(c for bn, c in hist.items() if bin_center_ns(bn) > thr) if thr else 0

    pooled = defaultdict(int)
    for r in meas.values():
        for bn, c in r["stat"]["hist"].items():
            pooled[bn] += c
    out["stat_bimodality"] = bimodality([(math.log10(bin_center_ns(bn)), c) for bn, c in pooled.items()])

    if thr:
        per_req_miss = sorted((slow(r["stat"]["hist"]) for r in meas.values()), reverse=True)
        total_miss = sum(per_req_miss)
        out["latency_miss_fraction"] = round(total_miss / stats_issued, 5) if stats_issued else None
        out["latency_enoent_miss_fraction"] = round(
            sum(slow(r["enoent"]["hist"]) for r in meas.values()) / enoent_issued, 5) if enoent_issued else None
        top = max(1, math.ceil(0.05 * n_req))
        out["top5pct_requests_miss_share"] = round(sum(per_req_miss[:top]) / total_miss, 4) if total_miss else None

    if k == "nfs":
        d = ms_delta(rep_ec2, "B.warm", "B.end", f"/e5/{tier}/ss-{iv}")
        if d is None:
            errors.append("no mountstats for the measurement window")
        else:
            rpcs = sum(d.get(op, 0) for op in NFS_RPC_LOOKUPS)
            out["window_rpcs"] = {op: d.get(op, 0) for op in NFS_RPC_LOOKUPS + ("DELEGRETURN", "OPEN")}
            # Includes the RPCs of ENOENT revalidation and of directories: an upper
            # bound on positive-stat misses, and what a production stat costs.
            cmf = rpcs / stats_issued if stats_issued else None
            out["counter_miss_fraction"] = round(cmf, 5) if cmf is not None else None
            lmf = out.get("latency_miss_fraction")
            if cmf is not None and lmf is not None:
                tol = max(B_AGREE_REL * cmf, B_AGREE_ABS)
                if abs(cmf - lmf) > tol:
                    errors.append(f"counter miss fraction {cmf:.4f} vs latency {lmf:.4f} disagree (> {tol:.4f})")
    out["miss_fraction"] = out.get("counter_miss_fraction", out.get("latency_miss_fraction"))
    out["status"] = "ERROR" if errors else "OK"
    if errors:
        out["errors"] = errors
    return out


# --- predictions -------------------------------------------------------------------------
S, R, I, NE = "SUPPORTS", "REFUTES", "INCONCLUSIVE", "NOT EVALUABLE"


def within(x: float, lo: float, hi: float) -> bool:
    return lo <= x <= hi


def grade_rep(a: dict, b: dict) -> dict:
    g = {}

    def cell(t, iv):
        c = b.get(t, {}).get(iv)
        return c if c and c["status"] == "OK" else None

    # P1: E2's slow cluster was the real revalidation cost.
    vals = {t: a_median(a, t, "A1" if t == "fsx_lustre" else "A3") for t in E2_MISS_NS}
    if any(v is None for v in vals.values()):
        g["P1"] = {"grade": NE, "inputs": vals}
    else:
        ratios = {t: round(vals[t] / E2_MISS_NS[t], 3) for t in vals}
        g["P1"] = {"grade": S if all(within(r, 0.5, 2.0) for r in ratios.values()) else R, "ratios_to_e2": ratios}

    # P2: ONTAP's miss is OpenZFS-class, not EFS-class.
    on, oz, ef = (a_median(a, t, "A3") for t in ("fsx_ontap", "fsx_openzfs", "efs_host_plain"))
    if None in (on, oz, ef):
        g["P2"] = {"grade": NE}
    else:
        r_oz, r_ef = on / oz, on / ef
        ok = within(r_oz, 0.5, 2.0) and r_ef <= 0.25
        g["P2"] = {"grade": S if ok else R, "ontap_over_openzfs": round(r_oz, 3), "ontap_over_efs": round(r_ef, 3)}

    # P3: first touch / revalidation in [1.0, 3.0] on every NFS tier.
    ratios = {}
    for t in NFS_TIERS:
        x, y = a_median(a, t, "A1"), a_median(a, t, "A3")
        ratios[t] = None if x is None or y is None else round(x / y, 3)
    if any(v is None for v in ratios.values()):
        g["P3"] = {"grade": NE, "ratios": ratios}
    elif any(v < 0.9 or v > 3.0 for v in ratios.values()):
        g["P3"] = {"grade": R, "ratios": ratios}
    elif all(within(v, 1.0, 3.0) for v in ratios.values()):
        g["P3"] = {"grade": S, "ratios": ratios}
    else:
        g["P3"] = {"grade": I, "ratios": ratios}

    # P4: forced-miss instrument agrees with A3 to +-25% (passes 2..10 only).
    ratios = {}
    for t in NFS_TIERS:
        x, y = a_median(a, t, "A8"), a_median(a, t, "A3")
        ratios[t] = None if x is None or y is None else round(x / y, 3)
    if any(v is None for v in ratios.values()):
        g["P4"] = {"grade": NE, "ratios": ratios}
    else:
        g["P4"] = {"grade": S if all(within(v, 0.75, 1.25) for v in ratios.values()) else R, "ratios": ratios}

    # P5: no-delegation steady-state miss fraction ~ interval / acregmax.
    tiers5 = ["efs_host_plain", "efs_host_tls", "fsx_ontap"]
    mf = {t: {iv: (cell(t, iv) or {}).get("miss_fraction") for iv in ("0.1", "1", "10")} for t in tiers5}
    if any(v is None for t in mf for v in mf[t].values()):
        g["P5"] = {"grade": NE, "miss_fraction": mf}
    elif any(mf[t]["1"] > 0.05 or mf[t]["0.1"] > 0.02 for t in tiers5):
        g["P5"] = {"grade": R, "miss_fraction": mf}
    elif all(mf[t]["0.1"] <= 0.005 and within(mf[t]["1"], 0.01, 0.03) and within(mf[t]["10"], 0.10, 0.25)
             for t in tiers5):
        g["P5"] = {"grade": S, "miss_fraction": mf}
    else:
        g["P5"] = {"grade": I, "miss_fraction": mf}

    # P6: delegations stop the clock on OpenZFS.
    oz6 = {iv: (cell("fsx_openzfs", iv) or {}).get("miss_fraction") for iv in ("0.1", "1", "10")}
    if any(v is None for v in oz6.values()):
        g["P6"] = {"grade": NE, "miss_fraction": oz6}
    elif oz6["10"] >= 0.05:
        g["P6"] = {"grade": R, "miss_fraction": oz6}
    elif all(v <= 0.02 for v in oz6.values()):
        g["P6"] = {"grade": S, "miss_fraction": oz6}
    else:
        g["P6"] = {"grade": I, "miss_fraction": oz6}

    # P7: Lustre repeats are free (latency classification; counters are host-wide).
    lu = {iv: (cell("fsx_lustre", iv) or {}).get("latency_miss_fraction") for iv in ("0.1", "1", "10")}
    if any(v is None for v in lu.values()):
        g["P7"] = {"grade": NE, "slow_share": lu}
    elif any(v > 0.05 for v in lu.values()):
        g["P7"] = {"grade": R, "slow_share": lu}
    elif all(v <= 0.01 for v in lu.values()):
        g["P7"] = {"grade": S, "slow_share": lu}
    else:
        g["P7"] = {"grade": I, "slow_share": lu}

    # P8: missing files are cheaper to keep missing (latency clusters, at 1 s).
    p8 = {}
    for t in NFS_TIERS:
        c = cell(t, "1")
        p8[t] = None if not c or c.get("latency_enoent_miss_fraction") is None else \
            (c["latency_enoent_miss_fraction"], c["latency_miss_fraction"])
    if any(v is None for v in p8.values()):
        g["P8"] = {"grade": NE, "enoent_vs_positive": p8}
    elif any(e > 2 * p + 0.001 for e, p in p8.values()):
        g["P8"] = {"grade": R, "enoent_vs_positive": p8}
    elif all(e <= p for e, p in p8.values()):
        g["P8"] = {"grade": S, "enoent_vs_positive": p8}
    else:
        g["P8"] = {"grade": I, "enoent_vs_positive": p8}

    # P9: the headline. Amortised per-request stat time, EFS / EBS, at 1 s.
    e, k = cell("efs_host_plain", "1"), cell("ebs", "1")
    if not e or not k:
        g["P9"] = {"grade": NE}
    else:
        ratio = e["per_request_stat_ns"]["amortised"] / k["per_request_stat_ns"]["amortised"]
        g["P9"] = {"grade": S if ratio <= 50 else R if ratio >= 200 else I, "ratio": round(ratio, 2)}

    # P10: misses arrive together.
    c = cell("efs_host_plain", "1")
    share = c.get("top5pct_requests_miss_share") if c else None
    if share is None:
        g["P10"] = {"grade": NE}
    else:
        g["P10"] = {"grade": S if share >= 0.5 else R if share < 0.2 else I, "top5pct_share": share}
    return g


def aggregate(per_rep: dict[str, dict]) -> dict:
    out = {}
    for p in [f"P{i}" for i in range(1, 11)]:
        grades = [per_rep[r][p]["grade"] for r in per_rep]
        ev = [x for x in grades if x != NE]
        if len(ev) < MIN_EVALUABLE_REPS:
            v = "NOT EVALUABLE"
        elif all(x == S for x in ev):
            v = "SUPPORTED"
        elif all(x == R for x in ev):
            v = "REFUTED"
        else:
            v = "INCONCLUSIVE"
        out[p] = {"verdict": v, "per_replication": grades}
    return out


# --- driver ------------------------------------------------------------------------------
def analyse(run_dir: Path) -> dict:
    reps = sorted(p for p in run_dir.glob("rep-*") if (p / "ec2" / "manifest.txt").exists())
    result: dict = {"run": run_dir.name, "replications": {}, "rules": "experiments/E5-attribute-cache/README.md"}
    per_rep_grades = {}
    for rep in reps:
        ec2 = rep / "ec2"
        tiers = [t for t in (ec2 / "manifest.txt").read_text().split() if t]
        intervals = [i for i in (ec2 / "intervals.txt").read_text().split() if i]
        a = cohort_a(ec2, tiers)
        b = {t: {iv: cell_b(ec2, t, iv, a) for iv in intervals} for t in tiers}
        grades = grade_rep(a, b)
        conf = {}
        for t in tiers:
            f = ec2 / f"{t}.conformance.csv"
            conf[t] = sum(1 for line in f.read_text().splitlines() if ",FAIL" in line) if f.exists() else None
        result["replications"][rep.name] = {
            "conformance_failures": conf, "cohort_a": a, "cohort_b": b, "grades": grades}
        per_rep_grades[rep.name] = grades
    result["predictions"] = aggregate(per_rep_grades)
    return result


def render_md(res: dict) -> str:
    lines = [f"# E5 summary — `{res['run']}`", "",
             "Generated by `analysis/e5_stats.py`; rules from the experiment README.", "",
             "## Predictions", "", "| # | Verdict | Per replication |", "|---|---|---|"]
    for p, v in res["predictions"].items():
        lines.append(f"| {p} | **{v['verdict']}** | {' / '.join(v['per_replication'])} |")
    for rep, r in res["replications"].items():
        lines += ["", f"## {rep}: cohort A (median, µs; signature)", "",
                  "| Tier | " + " | ".join(f"A{i}" for i in range(1, 9)) + " |",
                  "|---|" + "---|" * 8]
        for t, cs in r["cohort_a"].items():
            cells = []
            for i in range(1, 9):
                e = cs.get(f"A{i}")
                if not e:
                    cells.append("—")
                elif e["signature"]["status"] != "PASS":
                    cells.append(e["signature"]["status"])
                else:
                    cells.append(f"{e['latency']['p50_ns'] / 1000:.1f}")
            lines.append(f"| {t} | " + " | ".join(cells) + " |")
        lines += ["", f"## {rep}: cohort B (miss fraction; amortised per-request stat ms)", "",
                  "| Tier | Interval | Status | Miss fraction | Per-request ms | Top-5% miss share |",
                  "|---|---|---|--:|--:|--:|"]
        for t, ivs in r["cohort_b"].items():
            for iv, c in ivs.items():
                mf = c.get("miss_fraction")
                amort = c.get("per_request_stat_ns", {}).get("amortised")
                lines.append(f"| {t} | {iv} s | {c['status']} | "
                             f"{'—' if mf is None else f'{mf:.4f}'} | "
                             f"{'—' if amort is None else f'{amort / 1e6:.2f}'} | "
                             f"{c.get('top5pct_requests_miss_share', '—')} |")
    return "\n".join(lines) + "\n"


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        return 64
    run_dir = Path(sys.argv[1])
    res = analyse(run_dir)
    (run_dir / "summary.json").write_text(json.dumps(res, indent=1) + "\n")
    (run_dir / "summary.md").write_text(render_md(res))
    for p, v in res["predictions"].items():
        print(f"{p}: {v['verdict']}  ({' / '.join(v['per_replication'])})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
