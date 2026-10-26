#!/usr/bin/env python3
"""E5's grader, run against synthetic runs that must reach every grade.

Required by experiments/E5-attribute-cache/README.md ("Apparatus to build", item 8)
before the first deploy: for every prediction, a synthetic run reaching SUPPORTED,
REFUTED, INCONCLUSIVE and NOT EVALUABLE (an ERROR replication), plus the specific
ERROR paths the README names - a failed signature, a late cell, and broken phase attribution. Counter/latency
disagreement is diagnostic under the 2026-10-26 amendment. A grader that has only ever seen real data has only ever been checked
against the answer it gave.

The synthetic files have the shape agebench, e5-run.sh and the kernel produce:
`cohort,op,seq,ns` passes, one mountstats section per snapshot, the sidecar's Lustre
counter dump, status.csv, and gzipped per-request histograms.

Usage:  python3 analysis/e5_selftest.py        (exit 0 only if every case passes)
"""
from __future__ import annotations

import contextlib
import io
import copy
import gzip
import math
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import e5_stats as g  # noqa: E402

N = g.N
MEASURED = {"0.1": 60, "1": 100, "10": 20}   # smaller than a real run; the grader must not care
WARM = 2


def base_world() -> dict:
    """One replication in which every prediction is SUPPORTED."""
    a = {
        "efs_host_plain": {"A1": 1_000_000, "A2": 900_000, "A3": 827_000, "A4": 5_000, "A5": 2_000,
                           "A6": 1_500_000, "A7": 60_000, "A8": 850_000},
        "efs_host_tls": {"A1": 1_100_000, "A2": 950_000, "A3": 900_000, "A4": 5_000, "A5": 2_000,
                         "A6": 1_600_000, "A7": 60_000, "A8": 920_000},
        "fsx_openzfs": {"A1": 150_000, "A2": 120_000, "A3": 98_000, "A4": 3_000, "A5": 1_800,
                        "A6": 300_000, "A7": 2_000, "A8": 100_000},
        "fsx_ontap": {"A1": 120_000, "A2": 100_000, "A3": 90_000, "A4": 3_000, "A5": 1_700,
                      "A6": 250_000, "A7": 40_000, "A8": 95_000},
        "fsx_lustre": {"A1": 149_000, "A2": 140_000, "A3": 3_000, "A4": 2_500, "A5": 2_500,
                       "A6": 400_000, "A7": 5_000},
        "ebs": {c: 1_400 for c in g.A_COHORTS},
    }
    status = {t: {c: "ok" for c in (g.A_COHORTS + (["A8w", "A8"] if t in g.NFS_TIERS else []))
                  + [f"B-{d}" for d in g.DELTAS] + [f"D-{d}" for d in g.DELTAS]} for t in g.TIERS}
    # Signature RPC deltas per cohort, as the kernel would produce them.
    sig = {t: {"A1": {"LOOKUP": N + 40}, "A2": {"LOOKUP": N}, "A3": {"GETATTR": N + 41},
               "A4": {"GETATTR": 41}, "A5": {}, "A6": {"READ": N, "OPEN": N}, "A7": {"GETATTR": N},
               "A8": {"GETATTR": 10 * N}} for t in g.NFS_TIERS}
    frac = {"0.1": 0.002, "1": 0.017, "10": 0.15}
    b = {}
    for t in g.TIERS:
        for d in g.DELTAS:
            f = {"fsx_openzfs": 0.005, "fsx_lustre": 0.0, "ebs": 0.0}.get(t, frac[d])
            b[(t, d)] = {"miss": f, "counter": f, "enoent_miss": f / 2, "late": 0.0,
                         "hit_ns": 1_400 if t == "ebs" else 2_000, "miss_ns": g.E2_MISS_NS.get(t, 800_000),
                         "enoent_hit_ns": 1_500, "cluster": 2}
    return {"a": a, "status": status, "sig": sig, "b": b, "lustre_counter": "ldlm_enqueue", "lustre_delta": N}


# --- writers ----------------------------------------------------------------------
def mountstats(ops: dict[str, int], mountpoint: str) -> str:
    lines = [f"device server:/e5 mounted on {mountpoint} with fstype nfs4 statvers=1.1",
             "\topts:\trw,vers=4.1,nosharecache", "\tper-op statistics"]
    for op in ("NULL", "READ", "OPEN", "GETATTR", "LOOKUP", "ACCESS"):
        lines.append(f"\t        {op}: {ops.get(op, 0)} {ops.get(op, 0)} 0 0 0 0 0 0 0")
    return "\n".join(lines) + "\n"


def lustre_dump(name: str, count: int) -> str:
    return (f"=== /proc/fs/lustre/mdc/fsx-MDT0000-mdc-ffff/stats\nsnapshot_time 1.0 secs.nsecs\n"
            f"{name} {count} samples [usecs] 1 900 12345\nmds_close 3 samples [usecs] 1 2 3\n"
            # The same device again under debugfs must not be counted twice.
            f"=== /sys/kernel/debug/lustre/mdc/fsx-MDT0000-mdc-ffff/stats\n{name} {count} samples [usecs] 1 9 9\n")


def bin_of(ns: int) -> int:
    if ns < 100:
        return -1
    return min(int(math.floor(20 * math.log10(ns / 100))), 140)


def spread(total: int, n_req: int, cluster: int) -> list[int]:
    """Misses per measured request: all in the first `cluster` requests."""
    if total == 0:
        return [0] * n_req
    cluster = min(max(cluster, math.ceil(total / N)), n_req)
    out = [0] * n_req
    for i in range(total):
        out[i % cluster] += 1
    return out


def write_rep(rep_dir: Path, w: dict) -> None:
    for t in g.TIERS:
        td = rep_dir / "ec2" / t
        td.mkdir(parents=True, exist_ok=True)
        (td / "status.csv").write_text("".join(f"{c},{s}\n" for c, s in w["status"][t].items()))
        (td / "conformance.csv").write_text("rename,PASS\n")
        for c, med in w["a"][t].items():
            n = 10 * N if c == "A8" else N
            if w["status"][t].get(c) != "ok":
                continue
            (td / f"{c}.csv").write_text("".join(
                f"{c},stat,{i},{int(med * (1 + 0.02 * ((i % 21) - 10) / 10))}\n" for i in range(n)))
            if t in g.NFS_TIERS:
                mp = f"/bench/{t}.{'forced' if c == 'A8' else 'default'}"
                base = {"GETATTR": 5000, "LOOKUP": 7000, "READ": 100, "OPEN": 10, "ACCESS": 50}
                post = {k: v + w["sig"][t].get(c, {}).get(k, 0) for k, v in base.items()}
                (td / f"{c}.pre.mountstats").write_text(mountstats(base, mp))
                (td / f"{c}.post.mountstats").write_text(mountstats(post, mp))
            elif t == "fsx_lustre":
                (td / f"{c}.pre.lustre").write_text(lustre_dump(w["lustre_counter"], 100))
                (td / f"{c}.post.lustre").write_text(lustre_dump(w["lustre_counter"], 100 + w["lustre_delta"]))
        for d in g.DELTAS:
            p = w["b"][(t, d)]
            n = MEASURED[d]
            dn = int(float(d) * 1e9)
            ms = spread(round(p["miss"] * n * N), n, p["cluster"])
            me = spread(round(p["enoent_miss"] * n * N), n, p["cluster"])
            late_n = round(p["late"] * n)
            rpc_ms = spread(round(p["counter"] * n * N), n, p["cluster"])
            rows = [f"# cohort=B-{d} delta_ns={dn} warm_requests={WARM} measured_requests={n} raw_every=1 "
                    f"bins_per_decade=20 bin0_ns=100 method=rpc-phases-v2 rpc_mount=/bench/{t}.ss-{d}",
                    "k,phase,lateness_ns,stat_sum_ns,enoent_sum_ns,stat_bins,enoent_bins,stat_rpc,enoent_rpc,counter_ns"]
            for k in range(WARM + n):
                phase = "w" if k < WARM else "m"
                j = k - WARM
                s_miss = ms[j] if phase == "m" else 0
                e_miss = me[j] if phase == "m" else 0
                hb, mb = bin_of(p["hit_ns"]), bin_of(p["miss_ns"])
                eb, emb = bin_of(p["enoent_hit_ns"]), bin_of(p["miss_ns"])
                sb = {hb: N - s_miss}
                if s_miss:
                    sb[mb] = sb.get(mb, 0) + s_miss
                ebins = {eb: N - e_miss}
                if e_miss:
                    ebins[emb] = ebins.get(emb, 0) + e_miss
                fmt = lambda h: "|".join(f"{b}:{c}" for b, c in sorted(h.items()) if c)  # noqa: E731
                late = dn if (phase == "m" and j < late_n) else 1000
                ssum = (N - s_miss) * p["hit_ns"] + s_miss * p["miss_ns"]
                esum = (N - e_miss) * p["enoent_hit_ns"] + e_miss * p["miss_ns"]
                # Counters are independent of latency; disagreement is a valid test world.
                sr = f"{rpc_ms[j] if phase == 'm' else 0}:0:0" if t in g.NFS_TIERS else "-"
                er = f"{e_miss}:0:0" if t in g.NFS_TIERS else "-"
                rows.append(f"{k},{phase},{late},{ssum},{esum},{fmt(sb)},{fmt(ebins)},{sr},{er},10000")
            if w["status"][t].get(f"B-{d}") == "ok":
                with gzip.open(td / f"B-{d}.req.csv.gz", "wt") as f:
                    f.write("\n".join(rows) + "\n")
                if t in g.NFS_TIERS:
                    mp = f"/bench/{t}.ss-{d}"
                    base = {"GETATTR": 900, "LOOKUP": 1100, "ACCESS": 40}
                    rpcs = round(p["counter"] * n * N) + sum(me)
                    (td / f"B-{d}.mountstats.warm").write_text(mountstats(base, mp))
                    (td / f"B-{d}.mountstats.end").write_text(mountstats({**base, "GETATTR": base["GETATTR"] + rpcs}, mp))
                    if p.get("bad_counter"):
                        (td / f"B-{d}.mountstats.end").write_text(mountstats({**base, "GETATTR": 0}, mp))
                    probe = f"D-{d}"
                    (td / f"{probe}.idle-seconds").write_text("75.01\n")
                    (td / f"{probe}.csv").write_text("".join(f"{probe},stat,{i},2000\n" for i in range(N)))
                    (td / f"{probe}.pre.mountstats").write_text(mountstats(base, mp))
                    probe_ops = 0 if t == "fsx_openzfs" else N
                    (td / f"{probe}.post.mountstats").write_text(mountstats({**base, "GETATTR": base["GETATTR"] + probe_ops}, mp))



def grade(worlds: list[dict]) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        run = Path(tmp) / "run"
        for i, w in enumerate(worlds, 1):
            write_rep(run / f"rep-{i}", w)
        res = g.analyse(run)
        # main() also serializes and renders; a crash there loses a real run's grade.
        with contextlib.redirect_stdout(io.StringIO()):
            g.main(run)
        serialized = g.json.loads((run / "summary.json").read_text())
        assert serialized["predictions"] == g.json.loads(g.json.dumps(res["predictions"]))
        assert "phase-attributed" in (run / "summary.md").read_text()
        return res


# --- mutations: each returns a world that pushes ONE prediction to a grade ------------
def m(fn):
    def apply(w):
        w = copy.deepcopy(w)
        fn(w)
        return w
    return apply


def setb(t, d, **kv):
    return m(lambda w: w["b"][(t, d)].update(kv))


def seta(t, c, v):
    return m(lambda w: w["a"][t].__setitem__(c, v))


def setsig(t, c, ops):
    return m(lambda w: w["sig"][t].__setitem__(c, ops))


def setstatus(t, c, v):
    return m(lambda w: w["status"][t].__setitem__(c, v))


# prediction -> {per-rep grade: mutation}. ERROR is the per-replication grade that
# makes the aggregate NOT EVALUABLE.
CASES = {
    "1": {"REFUTED": seta("efs_host_plain", "A3", 2_000_000),
          "ERROR": setsig("efs_host_plain", "A3", {"GETATTR": N, "LOOKUP": N})},       # failed signature
    "2": {"REFUTED": seta("fsx_ontap", "A3", 300_000),
          "ERROR": setstatus("fsx_ontap", "A3", "error")},
    "3": {"REFUTED": seta("fsx_openzfs", "A1", 500_000),
          "INCONCLUSIVE": seta("fsx_openzfs", "A1", 93_000),
          "ERROR": setsig("efs_host_tls", "A1", {"LOOKUP": 10})},
    "4": {"REFUTED": seta("fsx_ontap", "A8", 180_000),
          "ERROR": setsig("fsx_ontap", "A8", {"GETATTR": 5 * N})},
    "5": {"REFUTED": setb("efs_host_plain", "1", miss=0.08, counter=0.08, enoent_miss=0.04),
          "INCONCLUSIVE": setb("efs_host_tls", "10", miss=0.30, counter=0.30, enoent_miss=0.1),
          "ERROR": setb("efs_host_tls", "1", late=0.10)},                                   # late cell
    "6": {"REFUTED": setb("fsx_openzfs", "10", miss=0.10, counter=0.10, enoent_miss=0.05),
          "INCONCLUSIVE": setb("fsx_openzfs", "1", miss=0.03, counter=0.03, enoent_miss=0.01),
          "ERROR": setb("fsx_openzfs", "10", bad_counter=True)},                                # broken counters
    "7": {"REFUTED": setb("fsx_lustre", "1", miss=0.10),
          "INCONCLUSIVE": setb("fsx_lustre", "0.1", miss=0.02),
          "ERROR": setstatus("fsx_lustre", "B-1", "error")},
    "8": {"REFUTED": setb("fsx_ontap", "1", enoent_miss=0.017 * 3),
          "INCONCLUSIVE": setb("fsx_ontap", "1", enoent_miss=0.017 * 1.5),
          "ERROR": setstatus("fsx_ontap", "B-1", "error")},
    "9": {"REFUTED": setb("ebs", "1", hit_ns=50),
          "INCONCLUSIVE": setb("ebs", "1", hit_ns=150),
          "ERROR": setb("ebs", "1", late=0.5)},
    "10": {"REFUTED": setb("efs_host_plain", "1", cluster=100),
           "INCONCLUSIVE": setb("efs_host_plain", "1", cluster=15),
           "ERROR": setstatus("efs_host_plain", "B-1", "error")},
}


def main() -> int:
    base = base_world()
    failures = []

    def expect(label, worlds, pred, want):
        got = grade(worlds)["predictions"][pred]
        ok = got["status"] == want
        print(f"{'PASS' if ok else 'FAIL'}  P{pred:<3} {label:<28} -> {got['status']}")
        if not ok:
            failures.append((pred, label, want, got))

    for pred, muts in CASES.items():
        expect("all supported", [base] * 3, pred, "SUPPORTED")
        r = muts["REFUTED"](base)
        expect("all refuted", [r] * 3, pred, "REFUTED")
        expect("mixed S/R/S", [base, r, base], pred, "INCONCLUSIVE")
        if "INCONCLUSIVE" in muts:
            expect("per-rep inconclusive", [muts["INCONCLUSIVE"](base)] * 3, pred, "INCONCLUSIVE")
        e = muts["ERROR"](base)
        expect("one ERROR replication", [base, e, base], pred, "NOT EVALUABLE")
        expect("two replications only", [base, base], pred, "NOT EVALUABLE")

    # Lustre counters under unconfirmed names are an ERROR, never a pass.
    w = copy.deepcopy(base)
    w["lustre_counter"] = "some_other_counter"
    expect("unknown Lustre counter", [base, w, base], "1", "NOT EVALUABLE")
    # The debugfs duplicate must not double the count: half the RPCs is a FAIL.
    w = copy.deepcopy(base)
    w["lustre_delta"] = N // 2
    expect("Lustre half the RPCs", [base, w, base], "1", "NOT EVALUABLE")

    if failures:
        print(f"\n{len(failures)} case(s) failed")
        for pred, label, want, got in failures:
            print(f"  P{pred} {label}: wanted {want}, got {got['status']}: {got['per_replication']}")
        return 1
    print("\nall cases reached their intended grade")
    return 0


if __name__ == "__main__":
    sys.exit(main())
