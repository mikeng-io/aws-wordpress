#!/usr/bin/env python3
"""E5 attribute cache: cohort statistics and verdicts on predictions 1-10.

Reads results/E5/<run-id>/rep-*/ec2/<tier>/ and writes summary.json and summary.md
into the run directory. Every rule below is transcribed from
experiments/E5-attribute-cache/README.md ("Method", "Predictions", and the
2026-10-16 and 2026-10-26 amendments). Historical local checks predate the latter. The constants are those
rules, not tuned to data.

Fail-closed throughout. A cohort is graded only if:
  - its instrument reported `ok` (agebench exits non-zero on any wrong answer),
  - it has the expected number of operations, and
  - its RPC signature matches (NFS: /proc/self/mountstats deltas; Lustre: mdc
    counters read by the sidecar). This is the gate E2 lacked: "this measured the
    cache, not the server" becomes an ERROR here rather than a later discovery.
A cohort-B cell is graded only if it is `ok`, no more than 5% of its measured
requests started later than delta/2, and (NFS) its per-phase counters are complete
and reconcile with independent window snapshots. Latency disagreement is diagnostic.

Any prediction that reads an ERROR cohort or cell is ERROR for that replication.
Across replications: SUPPORTED if every evaluable replication supports it, REFUTED if
every one refutes it, INCONCLUSIVE otherwise, NOT EVALUABLE with fewer than 3
evaluable replications.

Usage:  python3 analysis/e5_stats.py results/E5/<run-id>
"""
from __future__ import annotations

import gzip
import json
import math
import re
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from e2_stats import summarize  # noqa: E402  same summary statistics as E2/E3

N = 1000
NFS_TIERS = ["efs_host_plain", "efs_host_tls", "fsx_openzfs", "fsx_ontap"]
TIERS = ["ebs", *NFS_TIERS, "fsx_lustre"]
DELTAS = ["0.1", "1", "10"]
A_COHORTS = ["A1", "A2", "A3", "A4", "A5", "A6", "A7"]

# --- signatures (README, "Cohort A") ----------------------------------------------
SIG_MIN = 0.95   # "Δ >= 0.95 N"
SIG_MAX = 0.05   # "Δ <= 0.05 N"
# Lustre's counter names are UNVERIFIED until the pilot replication reads them
# (README, "Cohort A"). A miss is an intent-lock enqueue or a getattr RPC on an mdc
# device. If none of these names appears, the cohort is ERROR, never a pass.
LUSTRE_MISS_COUNTERS = ("ldlm_enqueue", "mds_getattr", "mds_getattr_name")

# --- cohort B cell gates (README, "Cohort B" and the 2026-10-16 amendment) ---------
LATE_MAX_SHARE = 0.05          # >5% of requests later than delta/2 -> ERROR
XCHECK_REL = 0.20              # counter vs latency, relative ...
XCHECK_ABS = 0.002             # ... or absolute, whichever is larger (amendment)
MIN_LOG10_SEPARATION = 0.5     # E3's gate: a slow cluster must sit >=~3.2x above
BINS_PER_DECADE = 20
BIN0_NS = 100

# --- predictions --------------------------------------------------------------------
# P1: E2's slow-cluster medians, results/E2/20261015T000959Z-85382cc
#     (docs/findings/E2-server-backed.md, "Cache-miss cost").
E2_MISS_NS = {"efs_host_plain": 827_000, "fsx_openzfs": 98_000, "fsx_lustre": 149_000}
P1_BAND = (0.5, 2.0)
P2_BAND = (0.5, 2.0)
P2_EFS_MAX = 0.25
P3_SUPPORT = (1.0, 3.0)
P3_KILL = (0.9, 3.0)
P4_TOL = 0.25
P5_TIERS = ["efs_host_plain", "efs_host_tls", "fsx_ontap"]
P5_BANDS = {"0.1": (0.0, 0.005), "1": (0.010, 0.030), "10": (0.10, 0.25)}
P5_KILL = {"0.1": 0.02, "1": 0.05}
P6_SUPPORT_MAX = 0.02
P6_KILL_D10 = 0.05
P7_SUPPORT_MAX = 0.01
P7_KILL = 0.05
P8_KILL_RATIO = 2.0
P9_SUPPORT_MAX = 50.0
P9_KILL_MIN = 200.0
P10_TOP = 0.05
P10_SUPPORT_MIN = 0.50
P10_KILL_MAX = 0.20


# =====================================================================================
# parsing
# =====================================================================================
def load_pass(path: Path) -> list[int]:
    """agebench pass output: cohort,op,seq,ns."""
    out = []
    for line in path.read_text().splitlines():
        parts = line.split(",")
        if len(parts) == 4:
            out.append(int(parts[3]))
    return out


def mountstats_ops(path: Path) -> dict[str, int] | None:
    """Per-op RPC counts from one mount's section of /proc/self/mountstats."""
    if not path.is_file():
        return None
    ops: dict[str, int] = {}
    in_ops = False
    devices = 0
    for line in path.read_text().splitlines():
        if line.startswith("device "):
            devices += 1
        if "per-op statistics" in line:
            in_ops = True
            continue
        if in_ops:
            m = re.match(r"^\s+([A-Z_0-9]+):\s+(\d+)", line)
            if m:
                if m.group(1) in ops:
                    return None
                ops[m.group(1)] = int(m.group(2))
    return ops if in_ops and devices == 1 else None


def lustre_counters(path: Path) -> dict[str, int] | None:
    """Sum of the miss counters over mdc devices. Each device counted once, from the
    first root that exposes it, because the sidecar reads every candidate root."""
    if not path.is_file():
        return None
    seen: set[tuple[str, str]] = set()
    totals: dict[str, int] = {}
    current = None
    for line in path.read_text().splitlines():
        if line.startswith("=== "):
            p = line[4:].strip()
            m = re.search(r"/mdc/([^/]+)/(stats|md_stats)$", p)
            key = (m.group(1), m.group(2)) if m else None
            current = key if key and key not in seen else None
            if current:
                seen.add(current)
            continue
        if current and current[1] == "stats":
            m = re.match(r"^(\S+)\s+(\d+)\s+samples", line)
            if m:
                totals[m.group(1)] = totals.get(m.group(1), 0) + int(m.group(2))
    return totals if seen else None


def delta(pre: dict, post: dict, *names: str) -> int:
    """Callers check for a missing snapshot first; a missing one is an ERROR, not 0."""
    return sum(post.get(n, 0) - pre.get(n, 0) for n in names)


def status_of(tier_dir: Path) -> dict[str, str]:
    p = tier_dir / "status.csv"
    if not p.is_file():
        return {}
    return dict(line.split(",", 1) for line in p.read_text().split() if "," in line)


# =====================================================================================
# cohort A
# =====================================================================================
def check_signature(tier: str, cohort: str, tdir: Path, n_ops: int) -> tuple[str, str]:
    """Returns (PASS|FAIL|ERROR|N/A, detail)."""
    if tier == "ebs":
        return "N/A", "block reference, no signature"
    if tier == "fsx_lustre":
        if cohort != "A1":
            return "N/A", "only A1 is checked on Lustre (A3 waived: locks do not expire at 75 s)"
        pre, post = lustre_counters(tdir / "A1.pre.lustre"), lustre_counters(tdir / "A1.post.lustre")
        if pre is None or post is None:
            return "ERROR", "no Lustre mdc counters"
        if not any(n in pre or n in post for n in LUSTRE_MISS_COUNTERS):
            return "ERROR", f"none of {LUSTRE_MISS_COUNTERS} present - confirm counter names on the pilot"
        d = delta(pre, post, *LUSTRE_MISS_COUNTERS)
        ok = d >= SIG_MIN * n_ops
        return ("PASS" if ok else "FAIL"), f"mdc miss RPCs Δ={d} for {n_ops} ops"
    pre = mountstats_ops(tdir / f"{cohort}.pre.mountstats")
    post = mountstats_ops(tdir / f"{cohort}.post.mountstats")
    if pre is None or post is None:
        return "ERROR", "mountstats snapshot missing"
    g, lk, rd = delta(pre, post, "GETATTR"), delta(pre, post, "LOOKUP"), delta(pre, post, "READ")
    detail = f"GETATTR Δ={g} LOOKUP Δ={lk} READ Δ={rd} for {n_ops} ops"
    rules = {
        "A1": lk >= SIG_MIN * n_ops,
        "A2": lk >= SIG_MIN * n_ops,
        "A3": g >= SIG_MIN * n_ops and lk <= SIG_MAX * n_ops,
        "A5": g + lk <= SIG_MAX * n_ops,
        "A6": rd >= SIG_MIN * n_ops,
        "A8": g >= SIG_MIN * n_ops,
    }
    if cohort not in rules:
        return "N/A", "recorded, not gated: " + detail
    return ("PASS" if rules[cohort] else "FAIL"), detail


def cohort_a(rep_dir: Path) -> dict:
    out: dict[str, dict] = {}
    for tier in TIERS:
        tdir = rep_dir / "ec2" / tier
        st = status_of(tdir)
        cohorts = A_COHORTS + (["A8"] if tier in NFS_TIERS else [])
        for c in cohorts:
            entry: dict = {"status": "ERROR"}
            expected = N * (10 if c == "A8" else 1)
            if st.get(c) != "ok":
                entry["reason"] = f"instrument status {st.get(c, 'absent')}"
            else:
                vals = load_pass(tdir / f"{c}.csv")
                if len(vals) != expected:
                    entry["reason"] = f"{len(vals)} ops, expected {expected}"
                else:
                    sig, detail = check_signature(tier, c, tdir, len(vals))
                    entry = {"signature": sig, "signature_detail": detail, **summarize(vals)}
                    entry["status"] = "ERROR" if sig in ("FAIL", "ERROR") else "OK"
                    if sig in ("FAIL", "ERROR"):
                        entry["reason"] = f"signature {sig}: {detail}"
            out.setdefault(tier, {})[c] = entry
    return out


def a_median(a: dict, tier: str, cohort: str) -> int | None:
    e = a.get(tier, {}).get(cohort, {})
    return e.get("p50_ns") if e.get("status") == "OK" else None


# =====================================================================================
# cohort B
# =====================================================================================
def bin_center_log10(b: int) -> float:
    if b < 0:
        return math.log10(BIN0_NS) - 0.5 / BINS_PER_DECADE
    return math.log10(BIN0_NS) + (b + 0.5) / BINS_PER_DECADE


def parse_bins(field: str) -> dict[int, int]:
    if not field:
        return {}
    out = {}
    for item in field.split("|"):
        b, c = (int(v) for v in item.split(":"))
        if b in out:
            raise ValueError("duplicate histogram bin")
        out[b] = c
    return out


def kmeans2_weighted(hist: dict[int, int]) -> tuple[float, float] | None:
    """k=2 on log10 bin centres, weighted by count. Initialised at the extremes so a
    rare, well-separated miss mode is isolated rather than the hit mode being split.
    Returns (fast centroid, slow centroid) or None if there is one bin."""
    pts = sorted((bin_center_log10(b), c) for b, c in hist.items() if c > 0)
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
    return c1, c2


def slow_threshold(hist: dict[int, int]) -> float | None:
    """log10 boundary above which an op is a miss, or None if the cell has no slow
    cluster (one bin, or centroids closer than E3's separation gate)."""
    km = kmeans2_weighted(hist)
    if not km or km[1] - km[0] < MIN_LOG10_SEPARATION:
        return None
    return (km[0] + km[1]) / 2


def slow_count(hist: dict[int, int], thr: float | None) -> int:
    if thr is None:
        return 0
    return sum(c for b, c in hist.items() if bin_center_log10(b) > thr)


def load_req(path: Path) -> tuple[dict, list[dict]]:
    header: dict = {}
    rows = []
    with gzip.open(path, "rt") as f:
        for line in f:
            line = line.rstrip("\n")
            if line.startswith("#"):
                header = dict(kv.split("=", 1) for kv in line[1:].split())
                continue
            if line.startswith("k,"):
                continue
            parts = line.split(",")
            if len(parts) not in (7, 10):
                raise ValueError("bad per-request column count")
            k, phase, late, ssum, esum, sb, eb = parts[:7]
            row = {"k": int(k), "phase": phase, "late": int(late), "stat_sum": int(ssum),
                   "enoent_sum": int(esum), "sb": parse_bins(sb), "eb": parse_bins(eb)}
            if len(parts) == 10:
                def rpc(text):
                    if text == "-":
                        return None
                    counts = [int(x) for x in text.split(":")]
                    if len(counts) != 3 or min(counts) < 0:
                        raise ValueError("bad phase RPC counts")
                    return dict(zip(("GETATTR", "LOOKUP", "ACCESS"), counts))
                row.update(sr=rpc(parts[7]), er=rpc(parts[8]), counter_ns=int(parts[9]))
            rows.append(row)
    return header, rows


def expiry_probe(tdir: Path, d: str, mountpoint: str) -> dict:
    """Observable revalidation behaviour, never direct proof of delegation state."""
    try:
        c = f"D-{d}"
        idle = float((tdir / f"{c}.idle-seconds").read_text())
        if not math.isfinite(idle) or idle <= 60:
            raise ValueError("idle interval must exceed 60 seconds")
        if status_of(tdir).get(c) != "ok":
            raise ValueError("probe instrument did not report ok")
        lines = (tdir / f"{c}.csv").read_text().splitlines()
        vals = []
        for i, line in enumerate(lines):
            label, op, seq, value = line.split(",")
            if label != c or op != "stat" or int(seq) != i:
                raise ValueError("probe operation/sequence does not match cohort")
            vals.append(int(value))
        if len(vals) != N or any(v < 0 for v in vals):
            raise ValueError("probe must contain N valid stats")
        paths = [tdir / f"{c}.{when}.mountstats" for when in ("pre", "post")]
        for path in paths:
            devices = [line for line in path.read_text().splitlines() if line.startswith("device ")]
            if len(devices) != 1 or f" mounted on {mountpoint} with fstype nfs" not in devices[0]:
                raise ValueError("probe mountstats do not match measurement mount")
        pre, post = (mountstats_ops(path) for path in paths)
        counts = validated_delta(pre, post)
        if counts["GETATTR"] >= SIG_MIN * N and counts["LOOKUP"] <= SIG_MAX * N:
            state = "REVALIDATION_OBSERVED"
        elif sum(counts.values()) <= SIG_MAX * N:
            state = "REVALIDATION_SUPPRESSED"
        else:
            state = "UNKNOWN"
        return {"state": state, "idle_seconds": idle, "rpc_ops": counts,
                "note": "suppression is consistent with delegations; does not prove held state"}
    except (OSError, ValueError, TypeError) as exc:
        return {"state": "UNKNOWN", "reason": str(exc)}


def validated_delta(pre: dict | None, post: dict | None) -> dict:
    names = ("GETATTR", "LOOKUP", "ACCESS")
    if pre is None or post is None or any(k not in pre or k not in post for k in names):
        raise ValueError("missing required mountstats counters")
    out = {k: post[k] - pre[k] for k in names}
    if min(out.values()) < 0:
        raise ValueError("mountstats counters reset")
    return out


def cohort_b_cell(tier: str, d: str, tdir: Path) -> dict:
    try:
        return _cohort_b_cell(tier, d, tdir)
    except (OSError, ValueError, TypeError, KeyError, ZeroDivisionError, OverflowError) as exc:
        return {"status": "ERROR", "reason": str(exc)}


def _cohort_b_cell(tier: str, d: str, tdir: Path) -> dict:
    st = status_of(tdir).get(f"B-{d}")
    if st != "ok":
        return {"status": "ERROR", "reason": f"instrument status {st or 'absent'}"}
    header, rows = load_req(tdir / f"B-{d}.req.csv.gz")
    if header.get("method") != "rpc-phases-v2":
        raise ValueError("legacy/unattributed B data; ineligible for rpc-phases-v2")
    n_warm, n_meas = int(header["warm_requests"]), int(header["measured_requests"])
    if n_warm < 0 or n_meas <= 0 or len(rows) != n_warm + n_meas:
        raise ValueError("request count differs from declared window")
    delta_ns = int(header["delta_ns"])
    if delta_ns != round(float(d) * 1e9) or header.get("cohort") != f"B-{d}":
        raise ValueError("interval/cohort header does not match cell")
    if header.get("bins_per_decade") != str(BINS_PER_DECADE) or header.get("bin0_ns") != str(BIN0_NS):
        raise ValueError("unsupported histogram schema")
    for k, r in enumerate(rows):
        if r["k"] != k or r["phase"] != ("w" if k < n_warm else "m"):
            raise ValueError("request sequence or warm-up boundary invalid")
        if any(r[v] < 0 for v in ("late", "stat_sum", "enoent_sum", "counter_ns")):
            raise ValueError("negative request timing")
        for h in (r["sb"], r["eb"]):
            if sum(h.values()) != N or any(c < 0 or b < -1 or b > 140 for b, c in h.items()):
                raise ValueError("each phase must contain N valid histogram operations")
        if tier in NFS_TIERS and (r.get("sr") is None or r.get("er") is None):
            raise ValueError("missing phase-attributed RPC counters")
    meas = rows[n_warm:]
    late = sum(r["late"] > delta_ns / 2 for r in meas)
    hs, he = {}, {}
    for r in meas:
        for target, source in ((hs, r["sb"]), (he, r["eb"])):
            for b, c in source.items():
                target[b] = target.get(b, 0) + c
    n_stat, n_enoent = sum(hs.values()), sum(he.values())
    thr_s, thr_e = slow_threshold(hs), slow_threshold(he)
    slow_s, slow_e = slow_count(hs, thr_s) / n_stat, slow_count(he, thr_e) / n_enoent
    sums = sorted(r["stat_sum"] for r in meas)
    km = kmeans2_weighted(hs)
    cell = {
        "status": "OK", "method": "rpc-phases-v2", "measured_requests": len(meas),
        "late_share": late / len(meas), "stat_ops": n_stat,
        "slow_share_stat": round(slow_s, 6), "slow_share_enoent": round(slow_e, 6),
        "counter_snapshot_ns_per_request": round(statistics.fmean(r["counter_ns"] for r in meas)),
        "stat_sum_per_request_ns": {
            "amortised": round(statistics.fmean(sums), 1), "median": sums[len(sums) // 2],
            "p99": sums[min(int(round(0.99 * (len(sums) - 1))), len(sums) - 1)], "max": sums[-1]},
        "stat_split": {"fast_centroid_ns": round(10 ** km[0]) if km else None,
                       "slow_centroid_ns": round(10 ** km[1]) if km else None,
                       "threshold_ns": round(10 ** thr_s) if thr_s is not None else None},
    }
    reasons = []
    if cell["late_share"] > LATE_MAX_SHARE:
        reasons.append(f"{cell['late_share']:.1%} of requests later than delta/2")
    if tier in NFS_TIERS:
        mp = header.get("rpc_mount", "-")
        if mp == "-":
            raise ValueError("missing RPC measurement mount")
        paths = [tdir / f"B-{d}.mountstats.{when}" for when in ("warm", "end")]
        for path in paths:
            devices = [line for line in path.read_text().splitlines() if line.startswith("device ")]
            if len(devices) != 1 or f" mounted on {mp} with fstype nfs" not in devices[0]:
                raise ValueError("mountstats section does not match RPC measurement mount")
        window = validated_delta(*(mountstats_ops(path) for path in paths))
        positive = {op: sum(r["sr"][op] for r in meas) for op in window}
        negative = {op: sum(r["er"][op] for r in meas) for op in window}
        if any(positive[k] + negative[k] != window[k] for k in window):
            raise ValueError("phase RPC totals disagree with independent window counters")
        frac = sum(positive.values()) / n_stat
        cell.update(counter_rpc_ops={"positive": positive, "negative": negative, "window": window},
                    rpc_ops_per_stat=frac, rpc_ops_per_enoent=sum(negative.values()) / n_enoent,
                    rpc_ops_per_request=[sum(r["sr"].values()) for r in meas],
                    expiry_probe=expiry_probe(tdir, d, mp))
        tol = max(XCHECK_REL * frac, XCHECK_ABS)
        cell["xcheck"] = {"counter": frac, "latency": round(slow_s, 6), "tolerance": tol,
                          "status": "AGREE" if abs(slow_s - frac) <= tol else "DISAGREE",
                          "role": "diagnostic only; RPC operations are not file-miss events"}
    if reasons:
        cell.update(status="ERROR", reason="; ".join(reasons))
    return cell


def cohort_b(rep_dir: Path) -> dict:
    return {tier: {d: cohort_b_cell(tier, d, rep_dir / "ec2" / tier) for d in DELTAS} for tier in TIERS}


def why_a(a: dict, *pairs: tuple[str, str]) -> str:
    return "; ".join(f"{t} {c}: {a.get(t, {}).get(c, {}).get('reason', 'absent')}"
                     for t, c in pairs if a_median(a, t, c) is None)


def why_b(b: dict, t: str, d: str) -> str:
    return f"{t} B-{d}: {b.get(t, {}).get(d, {}).get('reason', 'absent')}"


def b_ok(b: dict, tier: str, d: str) -> dict | None:
    c = b.get(tier, {}).get(d, {})
    return c if c.get("status") == "OK" else None


# =====================================================================================
# predictions, per replication
# =====================================================================================
S, R, I, E = "SUPPORTED", "REFUTED", "INCONCLUSIVE", "ERROR"


def err(why: str) -> dict:
    return {"grade": E, "why": why}


def p1(a, b):
    vals = {"efs_host_plain": a_median(a, "efs_host_plain", "A3"),
            "fsx_openzfs": a_median(a, "fsx_openzfs", "A3"),
            "fsx_lustre": a_median(a, "fsx_lustre", "A1")}
    if None in vals.values():
        return err(why_a(a, ("efs_host_plain", "A3"), ("fsx_openzfs", "A3"), ("fsx_lustre", "A1")))
    ratios = {k: round(v / E2_MISS_NS[k], 3) for k, v in vals.items()}
    ok = all(P1_BAND[0] <= r <= P1_BAND[1] for r in ratios.values())
    return {"grade": S if ok else R, "ratio_to_e2": ratios}


def p2(a, b):
    on, oz, ef = (a_median(a, t, "A3") for t in ("fsx_ontap", "fsx_openzfs", "efs_host_plain"))
    if None in (on, oz, ef):
        return err(why_a(a, ("fsx_ontap", "A3"), ("fsx_openzfs", "A3"), ("efs_host_plain", "A3")))
    r_oz, r_ef = on / oz, on / ef
    ok = P2_BAND[0] <= r_oz <= P2_BAND[1] and r_ef <= P2_EFS_MAX
    return {"grade": S if ok else R, "ontap_over_openzfs": round(r_oz, 3), "ontap_over_efs": round(r_ef, 3)}


def p3(a, b):
    ratios = {}
    for t in NFS_TIERS:
        a1, a3 = a_median(a, t, "A1"), a_median(a, t, "A3")
        if a1 is None or a3 is None:
            return err(why_a(a, (t, "A1"), (t, "A3")))
        ratios[t] = round(a1 / a3, 3)
    if any(r < P3_KILL[0] or r > P3_KILL[1] for r in ratios.values()):
        g = R
    elif all(P3_SUPPORT[0] <= r <= P3_SUPPORT[1] for r in ratios.values()):
        g = S
    else:
        g = I
    return {"grade": g, "a1_over_a3": ratios}


def p4(a, b):
    ratios = {}
    for t in NFS_TIERS:
        a8, a3 = a_median(a, t, "A8"), a_median(a, t, "A3")
        if a8 is None or a3 is None:
            return err(why_a(a, (t, "A8"), (t, "A3")))
        ratios[t] = round(a8 / a3, 3)
    ok = all(abs(r - 1) <= P4_TOL for r in ratios.values())
    return {"grade": S if ok else R, "a8_over_a3": ratios}


def p5(a, b):
    fr = {}
    for t in P5_TIERS:
        for d in DELTAS:
            c = b_ok(b, t, d)
            if c is None:
                return err(why_b(b, t, d))
            if c["expiry_probe"]["state"] != "REVALIDATION_OBSERVED":
                return err(f"{t}@{d}: timer-model precondition unproven: {c['expiry_probe']}")
            fr[f"{t}@{d}"] = c["rpc_ops_per_stat"]
    if any(fr[f"{t}@{d}"] > lim for t in P5_TIERS for d, lim in P5_KILL.items()):
        g = R
    elif all(P5_BANDS[d][0] <= fr[f"{t}@{d}"] <= P5_BANDS[d][1] for t in P5_TIERS for d in DELTAS):
        g = S
    else:
        g = I
    return {"grade": g, "rpc_ops_per_stat": fr}


def p6(a, b):
    fr = {}
    for d in DELTAS:
        c = b_ok(b, "fsx_openzfs", d)
        if c is None:
            return err(why_b(b, "fsx_openzfs", d))
        fr[d] = c["rpc_ops_per_stat"]
    g = R if fr["10"] >= P6_KILL_D10 else S if all(v <= P6_SUPPORT_MAX for v in fr.values()) else I
    return {"grade": g, "rpc_ops_per_stat": fr,
            "expiry_probes": {d: b["fsx_openzfs"][d]["expiry_probe"] for d in DELTAS},
            "note": "amended rate test; no causal delegation verdict"}


def p7(a, b):
    sh = {}
    for d in DELTAS:
        c = b_ok(b, "fsx_lustre", d)
        if c is None:
            return err(why_b(b, "fsx_lustre", d))
        control = b_ok(b, "ebs", d)
        if control is None:
            return err(why_b(b, "ebs", d))
        boundary = c["stat_split"]["threshold_ns"]
        noise = control["stat_split"]["slow_centroid_ns"]
        if control["slow_share_stat"] > P7_SUPPORT_MAX or (
            boundary is not None and noise is not None and noise >= boundary
            and control["slow_share_stat"] > 0
        ):
            return err(f"EBS noise makes Lustre slow-cluster attribution ambiguous at {d}s")
        sh[d] = c["slow_share_stat"]
    g = R if any(v > P7_KILL for v in sh.values()) else S if all(v <= P7_SUPPORT_MAX for v in sh.values()) else I
    return {"grade": g, "slow_share": sh, "note": "latency-only test; does not prove DLM lock state"}


def p8(a, b):
    out = {}
    for t in NFS_TIERS:
        c = b_ok(b, t, "1")
        if c is None:
            return err(why_b(b, t, "1"))
        out[t] = {"enoent": c["rpc_ops_per_enoent"], "stat": c["rpc_ops_per_stat"]}
    if any(v["enoent"] > P8_KILL_RATIO * v["stat"] for v in out.values()):
        g = R
    elif all(v["enoent"] <= v["stat"] for v in out.values()):
        g = S
    else:
        g = I
    return {"grade": g, "rpc_ops_per_call_at_1s": out, "note": "amended phase-attributed rate test; positive phase precedes ENOENT"}


def p9(a, b):
    e, k = b_ok(b, "efs_host_plain", "1"), b_ok(b, "ebs", "1")
    if e is None or k is None:
        return err("; ".join(why_b(b, t, "1") for t in ("efs_host_plain", "ebs") if b_ok(b, t, "1") is None))
    ratio = e["stat_sum_per_request_ns"]["amortised"] / k["stat_sum_per_request_ns"]["amortised"]
    g = S if ratio <= P9_SUPPORT_MAX else R if ratio >= P9_KILL_MIN else I
    return {"grade": g, "efs_over_ebs": round(ratio, 2),
            "efs_per_request_ns": e["stat_sum_per_request_ns"], "ebs_per_request_ns": k["stat_sum_per_request_ns"]}


def p10(a, b):
    c = b_ok(b, "efs_host_plain", "1")
    if c is None:
        return err(why_b(b, "efs_host_plain", "1"))
    m = sorted(c["rpc_ops_per_request"], reverse=True)
    total = sum(m)
    if total == 0:
        return {"grade": I, "why": "no positive-phase RPC operations observed in the measured window"}
    top = max(1, math.ceil(P10_TOP * len(m)))
    share = sum(m[:top]) / total
    g = S if share >= P10_SUPPORT_MIN else R if share < P10_KILL_MAX else I
    return {"grade": g, "top5pct_share_of_rpc_ops": round(share, 4), "requests": len(m), "rpc_ops": total}


PREDICTIONS = {"1": p1, "2": p2, "3": p3, "4": p4, "5": p5, "6": p6, "7": p7, "8": p8, "9": p9, "10": p10}


def combine(per_rep: list[dict]) -> str:
    evaluable = [r["grade"] for r in per_rep if r["grade"] != E]
    if len(evaluable) < 3:
        return "NOT EVALUABLE"
    if all(g == S for g in evaluable):
        return S
    if all(g == R for g in evaluable):
        return R
    return I


# =====================================================================================
def analyse(run_dir: Path) -> dict:
    reps = sorted((p for p in run_dir.glob("rep-*") if (p / "ec2").is_dir()), key=lambda p: int(p.name[4:]))
    per_rep = {}
    for rep in reps:
        a, b = cohort_a(rep), cohort_b(rep)
        per_rep[rep.name] = {"a": a, "b": b, "grades": {k: f(a, b) for k, f in PREDICTIONS.items()}}
    verdicts = {k: {"status": combine([per_rep[r]["grades"][k] for r in per_rep]),
                    "per_replication": {r: per_rep[r]["grades"][k] for r in per_rep}}
                for k in PREDICTIONS}
    # rpc_ops_per_request is kept for P10 but is long; drop it from the serialized cells.
    for r in per_rep.values():
        for tier in r["b"].values():
            for cell in tier.values():
                cell.pop("rpc_ops_per_request", None)
    return {"method": "rpc-phases-v2", "run_dir": str(run_dir), "replications": list(per_rep), "predictions": verdicts,
            "cohorts": {r: {"a": v["a"], "b": v["b"]} for r, v in per_rep.items()},
            # PREDICTIONS is uppercase but maps to functions, so it is not a constant;
            # including it made json.dumps raise on every real run (found by the local
            # NFS check, 2026-10-17; the self-test calls analyse(), never main()).
            "constants": {k: v for k, v in globals().items()
                          if k.isupper() and len(k) > 1 and k != "PREDICTIONS"
                          and isinstance(v, (int, float, tuple, list, dict))}}


def fmt_ns(ns) -> str:
    if ns is None:
        return "ERROR"
    return f"{ns / 1000:.1f} µs" if ns < 1_000_000 else f"{ns / 1e6:.2f} ms"


def render(res: dict) -> str:
    lines = ["# E5 attribute cache — graded", "", f"Run: `{res['run_dir']}`", "",
             "| Prediction | Status | Per replication |", "|---|---|---|"]
    for k, v in res["predictions"].items():
        per = " / ".join(g["grade"] for g in v["per_replication"].values())
        lines.append(f"| {k} | **{v['status']}** | {per} |")
    lines += ["", "## Cohort A medians (signature-gated)", "",
              "| Tier | " + " | ".join(A_COHORTS + ["A8"]) + " |", "|---" * 9 + "|"]
    for rep, c in res["cohorts"].items():
        for tier in TIERS:
            row = [fmt_ns(c["a"].get(tier, {}).get(x, {}).get("p50_ns")) if x in c["a"].get(tier, {}) else "—"
                   for x in A_COHORTS + ["A8"]]
            lines.append(f"| {rep}/{tier} | " + " | ".join(row) + " |")
    lines += ["", "## Cohort B (phase-attributed RPC operations per stat; latency is diagnostic)", "",
              "| Cell | Status | RPC ops/stat | Slow share stat | Slow share ENOENT | Amortised stat ns/request | Late |",
              "|---|---|--:|--:|--:|--:|--:|"]
    for rep, c in res["cohorts"].items():
        for tier in TIERS:
            for d in DELTAS:
                x = c["b"][tier][d]
                if x["status"] != "OK":
                    lines.append(f"| {rep}/{tier}@{d}s | ERROR: {x.get('reason', '')} | | | | | |")
                    continue
                lines.append(f"| {rep}/{tier}@{d}s | OK | {x.get('rpc_ops_per_stat', '—')} | {x['slow_share_stat']} | "
                             f"{x['slow_share_enoent']} | {x['stat_sum_per_request_ns']['amortised']:.0f} | {x['late_share']} |")
    lines += ["", "## NFS attribution diagnostics", "",
              "RPC-operation rates are not file-miss probabilities. Phase order: positive, then negative.", "",
              "| Cell | RPC ops/ENOENT | Latency cross-check | Expiry probe | Counter-read ns/request |",
              "|---|--:|---|---|--:|"]
    for rep, c in res["cohorts"].items():
        for tier in NFS_TIERS:
            for d in DELTAS:
                x = c["b"][tier][d]
                if "xcheck" in x:
                    lines.append(f"| {rep}/{tier}@{d}s | {x['rpc_ops_per_enoent']:.6f} | "
                                 f"{x['xcheck']['status']} (diagnostic) | {x['expiry_probe']['state']} | "
                                 f"{x['counter_snapshot_ns_per_request']} |")
    lines += ["", "Per-replication prediction details (including ineligibility reasons):", "", "```json",
              json.dumps({k: v["per_replication"] for k, v in res["predictions"].items()}, indent=2), "```"]
    errors = [(rep, t, k, e.get("reason")) for rep, c in res["cohorts"].items()
              for t, cs in c["a"].items() for k, e in cs.items() if e["status"] == "ERROR"]
    if errors:
        lines += ["", "## Cohort A ERRORs", ""] + [f"- `{r}/{t}/{k}`: {why}" for r, t, k, why in errors]
    return "\n".join(lines) + "\n"


def main(run_dir: Path) -> int:
    res = analyse(run_dir)
    (run_dir / "summary.json").write_text(json.dumps(res, indent=2, default=list) + "\n")
    md = render(res)
    (run_dir / "summary.md").write_text(md)
    print(md)
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: e5_stats.py results/E5/<run-id>")
    sys.exit(main(Path(sys.argv[1])))
