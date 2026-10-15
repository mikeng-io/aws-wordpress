#!/usr/bin/env python3
"""Synthetic E5 runs, in the exact on-disk format the task writes, for checking that
analysis/e5_stats.py reaches every grade before any real data exists.

Nothing here is a measurement. The files are built from a spec - a median per
cohort, a miss fraction per steady-state cell - so that each pre-registered rule can
be pushed to SUPPORTED, REFUTED, INCONCLUSIVE and NOT EVALUABLE, and each ERROR
path (failed signature, late cell, counter/latency disagreement, Lustre counters
missing) can be shown to block grading rather than pass through it.

The format mirrors the real producers: agebench (A/B CSVs), e5-run.sh (mountstats
snapshots, filtered to /e5 mounts), and e5-host/hostctl.sh (lctl dumps).
"""
from __future__ import annotations

import copy
import gzip
import math
import random
from pathlib import Path

N = 1000
TIERS = ["ebs", "efs_host_plain", "efs_host_tls", "fsx_openzfs", "fsx_ontap", "fsx_lustre"]
NFS = ["efs_host_plain", "efs_host_tls", "fsx_openzfs", "fsx_ontap"]
INTERVALS = ["0.1", "1", "10"]


def bin_of(ns: float) -> int:
    """agebench.c's binning, exactly."""
    if ns < 100:
        return 0
    return min(139, 1 + math.floor(20 * math.log10(ns / 100)))


# --- the two reference specs --------------------------------------------------------
# Every value below is in ns or a fraction. SUPPORT is built to satisfy every
# prediction; REFUTE to violate every one.
US = 1000
SUPPORT = {
    "a": {  # cohort medians
        "ebs": {c: 1.5 * US for c in ("A1", "A2", "A3", "A4", "A5", "A6", "A7")},
        "efs_host_plain": {"A1": 1000 * US, "A2": 900 * US, "A3": 800 * US, "A4": 5 * US, "A5": 2 * US,
                           "A6": 2000 * US, "A7": 900 * US, "A8": 820 * US},
        "efs_host_tls": {"A1": 1100 * US, "A2": 1000 * US, "A3": 900 * US, "A4": 5 * US, "A5": 2 * US,
                         "A6": 2200 * US, "A7": 1000 * US, "A8": 900 * US},
        "fsx_openzfs": {"A1": 150 * US, "A2": 140 * US, "A3": 100 * US, "A4": 3 * US, "A5": 2 * US,
                        "A6": 400 * US, "A7": 3 * US, "A8": 100 * US},
        "fsx_ontap": {"A1": 150 * US, "A2": 140 * US, "A3": 120 * US, "A4": 3 * US, "A5": 2 * US,
                      "A6": 300 * US, "A7": 130 * US, "A8": 120 * US},
        "fsx_lustre": {"A1": 150 * US, "A2": 140 * US, "A3": 3 * US, "A4": 3 * US, "A5": 3 * US,
                       "A6": 500 * US, "A7": 5 * US},
    },
    "b": {  # miss fraction per tier per interval; enoent as a share of positive
        "efs_host_plain": {"0.1": 0.003, "1": 0.02, "10": 0.15},
        "efs_host_tls": {"0.1": 0.003, "1": 0.02, "10": 0.15},
        "fsx_ontap": {"0.1": 0.003, "1": 0.02, "10": 0.15},
        "fsx_openzfs": {"0.1": 0.005, "1": 0.005, "10": 0.005},
        "fsx_lustre": {"0.1": 0.002, "1": 0.002, "10": 0.002},
        "ebs": {"0.1": 0.0, "1": 0.0, "10": 0.0},
    },
    "enoent_ratio": 0.5,
    "concentrated": True,          # misses arrive together (P10)
    "skip": {},                    # (tier, iv) -> skipped deadlines
    "counter_scale": {},           # (tier, iv) -> counter RPCs / latency misses
    "break_signature": [],         # (tier, cohort) whose counters show the wrong RPCs
    "lustre_error": False,
    "overrun": [],                 # (tier, iv)
}

REFUTE = copy.deepcopy(SUPPORT)
REFUTE["a"]["ebs"] = {c: 0.5 * US for c in SUPPORT["a"]["ebs"]}
REFUTE["a"]["efs_host_plain"].update({"A3": 2000 * US, "A1": 1000 * US, "A8": 4000 * US})   # P1, P3, P4
REFUTE["a"]["fsx_ontap"].update({"A3": 400 * US})                                          # P2
REFUTE["b"]["efs_host_plain"] = {"0.1": 0.03, "1": 0.08, "10": 0.3}                        # P5, P9
REFUTE["b"]["fsx_openzfs"] = {"0.1": 0.01, "1": 0.05, "10": 0.15}                          # P6
REFUTE["b"]["fsx_lustre"] = {"0.1": 0.5, "1": 0.5, "10": 0.5}                              # P7
REFUTE["enoent_ratio"] = 3.0                                                              # P8
REFUTE["concentrated"] = False                                                            # P10


# --- writers ---------------------------------------------------------------------------
def _gz(path: Path, text: str) -> None:
    with gzip.open(path, "wt") as fh:
        fh.write(text)


def _mountstats(counts: dict[str, dict[str, int]]) -> str:
    out = []
    for mount, ops in counts.items():
        out.append(f"device server:/x mounted on {mount} with fstype nfs4 statvers=1.1")
        out.append("\topts:\trw,vers=4.1")
        out.append("\tper-op statistics")
        for op, n in ops.items():
            out.append(f"\t{op:>12}: {n} {n} 0 0 0 0 0 0 0")
        out.append("")
    return "\n".join(out) + "\n"


def _lustre(mdc: int, ost_read: int) -> str:
    return (
        "tag x\nepoch 0\n"
        "mdc.fs-MDT0000-mdc-ffff.stats=\n"
        "snapshot_time             1.0 secs.nsecs\n"
        f"req_waittime              {mdc + 3} samples [usec] 1 2 3 4\n"
        "obd_ping                  3 samples [usec] 1 2 3 4\n"
        "osc.fs-OST0000-osc-ffff.stats=\n"
        f"req_waittime              {ost_read + 2} samples [usec] 1 2 3 4\n"
        "obd_ping                  2 samples [usec] 1 2 3 4\n"
        f"ost_read                  {ost_read} samples [usec] 1 2 3 4\n"
    )


EXPECTED_NFS = {  # what a correct cohort's counters look like
    "A1": {"LOOKUP": 1040, "ACCESS": 40}, "A2": {"LOOKUP": 1000}, "A3": {"GETATTR": 1040},
    "A4": {"GETATTR": 40}, "A5": {}, "A6": {"OPEN_NOATTR": 1000, "READ": 1000, "CLOSE": 1000},
    "A7": {"GETATTR": 1000}, "A8": {"LOOKUP": 1040, "GETATTR": 10000},
}
EXPECTED_LUSTRE = {"A1": (1000, 0), "A6": (0, 1000)}


def make_rep(ec2: Path, spec: dict, seed: int) -> None:
    rng = random.Random(seed)
    (ec2 / "ms").mkdir(parents=True, exist_ok=True)
    (ec2 / "lustre").mkdir(exist_ok=True)
    (ec2 / "manifest.txt").write_text("\n".join(TIERS) + "\n")
    (ec2 / "intervals.txt").write_text("\n".join(INTERVALS) + "\n")
    (ec2 / "mount-facts.csv").write_text("kernel,synthetic\n")
    (ec2 / "seed-manifest.csv").write_text("synthetic\n")

    # --- cohort A ---
    for t in TIERS:
        (ec2 / f"{t}.conformance.csv").write_text("rename_over,PASS\n")
        rows = []
        for c, med in spec["a"][t].items():
            passes = 10 if c == "A8" else 1
            for p in range(passes):
                for i in range(N):
                    # pass 1 of A8 is the forced mount's first touch: make it slower,
                    # so a grader that forgot to drop it would get a different median
                    m = med * (3 if c == "A8" and p == 0 else 1)
                    rows.append(f"{c},stat,{i},{max(1, round(m * math.exp(rng.gauss(0, 0.1))))}")
            mount = f"/e5/{t}/{'forced' if c == 'A8' else 'default'}"
            if t in NFS:
                d = dict(EXPECTED_NFS[c])
                if (t, c) in spec["break_signature"]:
                    d = {"OPEN": 7}        # nothing the rule looks for
                (ec2 / "ms" / f"A.{t}.{c}.pre.txt").write_text(_mountstats({mount: {"NULL": 0}}))
                (ec2 / "ms" / f"A.{t}.{c}.post.txt").write_text(_mountstats({mount: d}))
            else:
                (ec2 / "ms" / f"A.{t}.{c}.pre.txt").write_text("")
                (ec2 / "ms" / f"A.{t}.{c}.post.txt").write_text("")
            if t == "fsx_lustre":
                mdc, rd = EXPECTED_LUSTRE.get(c, (0, 0))
                if spec["lustre_error"]:
                    pre = post = "ERROR no answer from host lctl service\n"
                else:
                    pre, post = _lustre(0, 0), _lustre(mdc, rd)
                (ec2 / "lustre" / f"A.{t}.{c}.pre.txt").write_text(pre)
                (ec2 / "lustre" / f"A.{t}.{c}.post.txt").write_text(post)
        _gz(ec2 / f"A.{t}.csv.gz", "\n".join(rows) + "\n")

    # --- cohort B ---
    warm, end = {}, {}
    n_req = 60
    for t in TIERS:
        a = spec["a"][t]
        hit = a["A5"]
        miss = a["A3"] if t in NFS else a["A1"] if t == "fsx_lustre" else a["A5"]
        for iv in INTERVALS:
            mf = spec["b"][t][iv]
            emf = min(1.0, mf * spec["enoent_ratio"])
            total_miss = round(mf * N * n_req)
            total_emiss = round(emf * N * n_req)

            def spread(total: int) -> list[int]:
                if spec["concentrated"]:
                    # every miss in the first ceil(5%) of requests, as synchronized
                    # expiry would put them
                    # (or as few requests as can hold them: a request has N stats)
                    k = max(1, math.ceil(0.05 * n_req), math.ceil(total / N))
                    base = [total // k + (1 if i < total % k else 0) for i in range(k)]
                    return [min(N, x) for x in base] + [0] * (n_req - k)
                return [total // n_req + (1 if i < total % n_req else 0) for i in range(n_req)]

            per, eper = spread(total_miss), spread(total_emiss)
            lines = []
            for k in range(5):  # a few warm-up requests, which must be ignored
                lines.append(f"req,{k},warmup,1000,5000000,stat,{N},{round(N * miss)},{bin_of(miss)}:{N}")
                lines.append(f"req,{k},warmup,1000,5000000,enoent,{N},{round(N * miss)},{bin_of(miss)}:{N}")
            for j in range(n_req):
                k = 5 + j
                m, em = per[j], eper[j]

                def hist(misses: int) -> tuple[int, str]:
                    hb, mb = bin_of(hit), bin_of(miss)
                    h = {hb: N - misses}
                    if misses:
                        h[mb] = h.get(mb, 0) + misses
                    h = {b: c for b, c in h.items() if c}
                    return round((N - misses) * hit + misses * miss), ";".join(f"{b}:{c}" for b, c in sorted(h.items()))

                s, hs = hist(m)
                es, ehs = hist(em)
                lines.append(f"req,{k},measure,1000,5000000,stat,{N},{s},{hs}")
                lines.append(f"req,{k},measure,1000,5000000,enoent,{N},{es},{ehs}")
            for k in range(spec["skip"].get((t, iv), 0)):
                lines.append(f"skip,{1000 + k},measure")
            if (t, iv) in spec["overrun"]:
                lines.append("overrun,30,measure")
            _gz(ec2 / f"B.{t}.{iv}.csv.gz", "\n".join(lines) + "\n")
            if t in NFS:
                mount = f"/e5/{t}/ss-{iv}"
                scale = spec["counter_scale"].get((t, iv), 1.0)
                warm[mount] = {"GETATTR": 100, "LOOKUP": 2000}
                end[mount] = {"GETATTR": 100 + round(total_miss * scale), "LOOKUP": 2000}
    for name, counts in (("B.start", warm), ("B.warm", warm), ("B.end", end)):
        (ec2 / "ms" / f"{name}.txt").write_text(_mountstats(counts))


def make_run(root: Path, specs: list[dict]) -> Path:
    for i, spec in enumerate(specs, start=1):
        make_rep(root / f"rep-{i}" / "ec2", spec, seed=i)
    return root
