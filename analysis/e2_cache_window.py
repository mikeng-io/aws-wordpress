#!/usr/bin/env python3
"""Derive E2's attribute-cache window numbers from the raw per-file CSVs.

docs/findings/E2-server-backed.md states, per tier, the create-pass duration, the
share of stat calls answered fast, and the age of the oldest fast file at the end
of the create pass. That analysis was never committed - the finding calls it "the
inline script recorded in the commit that adds this file", and no such script
exists in that commit. This script closes that provenance hole: it recomputes the
numbers mechanically from the immutable rep-N/<arm>/<tier>.csv latency files
(rows in file order within each op section) and writes a deterministic derived
JSON under analysis/derived/. The exported figure selectors then read the derived
file rather than the raw CSVs.

The exported classification is "answered in client memory": stat latency <
CACHE_HIT_NS (20 us). It is DESCRIPTIVE and POST-HOC - declared after looking at
the run's 12,000 stat samples, not pre-registered. It is not a tuned value:
only 4 samples lie between 10 and 60 us, so every absolute threshold in
15-30 us produces identical shares, and 20 us is the round midpoint of that
empty gap. The repo's registered rule - the lower-centroid cluster of
e3_clusters.kmeans2_log (deterministic 1-D k-means on log10 latency,
initialised at the 10th and 90th percentiles), meaningful only when E3's two
gates pass (centroid separation >= 0.5 in log10 AND each cluster >= 2% of the
sample) - is kept verbatim per rep under registered_rule as diagnostics. The
two rules disagree exactly where the gates fail: the registered rule leaves
ONTAP and Lustre undefined, while the absolute rule reports ONTAP 100% and
Lustre 0% - matching the finding's prose.

boundary_age_s is the create time strictly after the oldest locally answered
file's index - the age that file had reached when the create pass ended,
because create and stat rows share the same file order. Contiguity violations
(non-local files inside the local tail) are recorded as slow_in_tail, never
corrected. Where no stat row was answered locally (Lustre) there is no tail
and no boundary: oldest_local_index, boundary_age_s and slow_in_tail are null.

Usage:  python3 analysis/e2_cache_window.py
Writes: analysis/derived/e2-cache-window-20261015T000959Z-85382cc.json
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from e3_clusters import kmeans2_log, MIN_CLUSTER_SHARE, MIN_LOG10_SEPARATION


ROOT = Path(__file__).resolve().parents[1]
RUN = "results/E2/20261015T000959Z-85382cc"
RUN_ID = RUN.rsplit("/", 1)[-1]
OUT = ROOT / f"analysis/derived/e2-cache-window-{RUN_ID}.json"
# Selector tier name -> <arm>/<tier> under each rep directory. efs is the
# host-mounted plain EFS arm, the same client path as the FSx mounts.
TIERS = {
    "efs": "ec2/efs_host_plain",
    "fsx_openzfs": "ec2/fsx_openzfs",
    "fsx_ontap": "ec2/fsx_ontap",
    "fsx_lustre": "ec2/fsx_lustre",
}
REQUIRED_OPS = ("create", "stat")
# Declared post hoc, after inspecting this run's 12,000 stat samples - not a
# tuned value: only 4 samples land between 10 and 60 us (10911, 12628, 12852,
# 33133 ns), so every absolute threshold in 15-30 us classifies the run
# identically. 20 us is the round midpoint of that empty gap: every
# cache-answered sample is <= 12.9 us except one OpenZFS outlier at 33.1 us,
# and every server round trip is >= 62.8 us.
CACHE_HIT_NS = 20_000
SENSITIVITY_US = (15, 20, 25, 30)
BAND_NS = (10_000, 60_000)


class DeriveError(ValueError):
    """A raw input is missing or does not have the shape the rule requires."""


def load_csv(path: Path) -> dict[str, list[int]]:
    """Bare "op,ns" rows in file order; a header line is tolerated, as e2_stats."""
    ops: dict[str, list[int]] = {}
    try:
        fh = path.open()
    except OSError as exc:
        raise DeriveError(f"{path}: {exc}") from exc
    with fh:
        for row in csv.reader(fh):
            if len(row) != 2:
                continue
            op, ns = row[0].strip(), row[1].strip()
            if not ns.isdigit():   # skips a header line if one is present
                continue
            ops.setdefault(op, []).append(int(ns))
    return ops


def sha256_file(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise DeriveError(f"{path}: {exc}") from exc


def derive_rep(csv_path: Path) -> dict:
    ops = load_csv(csv_path)
    for op in REQUIRED_OPS:
        if not ops.get(op):
            raise DeriveError(f"{csv_path}: no {op} rows")
    create, stat = ops["create"], ops["stat"]
    if len(create) != len(stat):
        raise DeriveError(
            f"{csv_path}: {len(create)} create rows vs {len(stat)} stat rows; "
            "the rule needs one stat per created file in the same file order"
        )
    if any(v <= 0 for v in create + stat):
        raise DeriveError(f"{csv_path}: nonpositive latency; log10 clustering needs v > 0")

    lo, _, c_lo, c_hi = kmeans2_log(stat)
    share = len(lo) / len(stat)
    separation = c_hi - c_lo
    bimodal = (share >= MIN_CLUSTER_SHARE
               and (1 - share) >= MIN_CLUSTER_SHARE
               and separation >= MIN_LOG10_SEPARATION)
    registered = {
        "bimodal": bimodal,
        "centroid_separation_log10": separation,
        # The un-gated lower-cluster share, kept as evidence: on a unimodal
        # population this is a noise split, NOT a fast share.
        "ungated_lower_cluster_share": share,
    }
    if not bimodal:
        registered.update({
            "fast_stat_share": None,
            "oldest_fast_index": None,
            "boundary_age_s": None,
            "slow_in_tail": None,
            "undefined_reason": "stat is unimodal under the E3 gates "
                f"(centroid separation {10 ** separation:.1f}x < "
                f"{10 ** MIN_LOG10_SEPARATION:.1f}x, or a cluster below "
                f"{MIN_CLUSTER_SHARE:.0%}); the study defines no fast cluster "
                "for a single population",
        })
    else:
        fast = [abs(math.log10(v) - c_lo) <= abs(math.log10(v) - c_hi)
                for v in stat]
        oldest_fast = fast.index(True)
        registered.update({
            "fast_stat_share": share,
            "oldest_fast_index": oldest_fast,
            "boundary_age_s": sum(create[oldest_fast + 1:]) / 1e9,
            "slow_in_tail": sum(1 for f in fast[oldest_fast:] if not f),
            "undefined_reason": None,
        })

    local = [v < CACHE_HIT_NS for v in stat]
    entry = {
        "n_create": len(create),
        "n_stat": len(stat),
        "create_pass_s": sum(create) / 1e9,
        "answered_local_share": sum(local) / len(stat),
        "sensitivity": {
            "share_at_threshold_us": {
                str(us): sum(1 for v in stat if v < us * 1000) / len(stat)
                for us in SENSITIVITY_US},
            "samples_between_10_and_60us": sum(
                1 for v in stat if BAND_NS[0] <= v <= BAND_NS[1]),
        },
        "registered_rule": registered,
    }
    if not any(local):
        entry.update({
            "oldest_local_index": None,
            "boundary_age_s": None,
            "slow_in_tail": None,
            "undefined_reason": f"no stat row under {CACHE_HIT_NS} ns; "
                "nothing was answered in client memory, so there is no "
                "local tail and no boundary",
        })
        return entry
    oldest_local = local.index(True)
    entry.update({
        "oldest_local_index": oldest_local,
        "boundary_age_s": sum(create[oldest_local + 1:]) / 1e9,
        "slow_in_tail": sum(1 for f in local[oldest_local:] if not f),
        "undefined_reason": None,
    })
    return entry


def derive(root: Path = ROOT) -> dict:
    run_dir = root / RUN
    reps = sorted(p.name for p in run_dir.glob("rep-*") if p.is_dir())
    if not reps:
        raise DeriveError(f"no rep-* directories under {run_dir}")
    tiers: dict[str, dict] = {}
    inputs: dict[str, str] = {}
    band_total = 0
    for name, arm_tier in TIERS.items():
        arm, tier = arm_tier.split("/")
        replications: dict[str, dict] = {}
        for rep in reps:
            path = f"{RUN}/{rep}/{arm}/{tier}.csv"
            inputs[path] = sha256_file(root / path)
            entry = derive_rep(root / path)
            band_total += entry["sensitivity"]["samples_between_10_and_60us"]
            replications[rep] = entry
        tiers[name] = {"arm_tier": arm_tier, "replications": replications}
    return {
        "id": "e2-cache-window",
        "schema": "derived/0",
        # No commit or timestamp: the file is committed, so git is its own
        # provenance, and embedding HEAD would make regeneration drift.
        "produced_by": {"repo": "mikeng-io/aws-wordpress",
                        "command": "python3 analysis/e2_cache_window.py"},
        "run": RUN,
        "rule": {
            "classification": "answered in client memory: stat latency "
                              "< cache_hit_ns",
            "cache_hit_ns": CACHE_HIT_NS,
            # Descriptive rule declared after looking at the data, not
            # pre-registered. Not tuned: the band is empty - every
            # threshold in 15-30 us classifies this run identically.
            "post_hoc": True,
            "post_hoc_reason": "declared after inspecting the run's stat "
                "samples, not pre-registered; not a tuned value - only "
                f"{band_total} of the run's stat samples lie between "
                f"{BAND_NS[0] // 1000} and {BAND_NS[1] // 1000} us, so every "
                f"absolute threshold in {SENSITIVITY_US[0]}-"
                f"{SENSITIVITY_US[-1]} us produces identical shares, and "
                f"{CACHE_HIT_NS // 1000} us is the round midpoint of that "
                "empty gap",
            "create_pass_s": "sum of the create latencies, in seconds; create "
                             "rows are in file order so the sum is the create "
                             "pass",
            "answered_local_share": "fraction of stat rows answered in client "
                                    "memory, 0..1",
            "oldest_local_index": "file-order index of the oldest stat row "
                                  "answered in client memory; null when none "
                                  "was",
            "boundary_age_s": "sum of the create latencies strictly after "
                              "oldest_local_index, in seconds - that file's "
                              "age when the create pass ended; null when no "
                              "stat row was answered locally",
            "slow_in_tail": "stat rows at or after oldest_local_index that "
                            "were NOT answered in client memory; violations "
                            "of the contiguous-tail structure, recorded not "
                            "corrected; null when no local row exists",
            "sensitivity": "per rep, share_at_threshold_us is "
                           "answered_local_share recomputed at each absolute "
                           "threshold in us, and samples_between_10_and_60us "
                           "counts that rep's stat rows in the 10-60 us band",
            "registered_rule": {
                "note": "the repo's registered clustering rule, kept as "
                        "diagnostics; it disagrees with the exported rule on "
                        "ONTAP and Lustre - it leaves both undefined where "
                        "the absolute rule reports ONTAP 1.0 and Lustre 0.0",
                "fast_cluster": "lower-centroid cluster of "
                                "e3_clusters.kmeans2_log (deterministic 1-D "
                                "k-means on log10 latency, initialised at the "
                                "10th and 90th percentiles)",
                "gates": {"min_log10_separation": MIN_LOG10_SEPARATION,
                          "min_cluster_share": MIN_CLUSTER_SHARE},
                "unimodal": "when the gates fail the population is one "
                            "cluster and no fast share is defined; its "
                            "fast_stat_share, oldest_fast_index, "
                            "boundary_age_s and slow_in_tail are null",
                "fast_stat_share": "fraction of stat rows in the fast "
                                   "cluster, 0..1",
                "boundary_age_s": "sum of the create latencies strictly after "
                                  "the oldest fast file's index, in seconds - "
                                  "that file's age when the create pass ended",
                "slow_in_tail": "stat rows at or after oldest_fast_index that "
                                "are NOT in the fast cluster; violations of "
                                "the contiguous-tail structure, recorded not "
                                "corrected",
            },
        },
        # Whole-run count of stat rows in the 10-60 us band: the measured
        # basis for the post-hoc claim that no threshold in 15-30 us is tuned.
        "samples_between_10_and_60us": band_total,
        "inputs": inputs,
        "tiers": tiers,
    }


def write_output(document: dict, out: Path = OUT, root: Path = ROOT) -> None:
    # Same protection as the exporter: never under results/, even via a symlink.
    protected = (root / "results").resolve()
    if out.resolve() == protected or protected in out.resolve().parents:
        raise DeriveError(f"refusing to write under results/: {out}")
    data = (json.dumps(document, indent=2, sort_keys=True,
                       ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=out.parent, delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(data)
    temporary.replace(out)


def main(root: Path = ROOT) -> int:
    try:
        document = derive(root)
        write_output(document, OUT, root)
    except (DeriveError, OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
