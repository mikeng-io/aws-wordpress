#!/usr/bin/env python3
"""Checks that analysis/e5_stats.py reaches every grade, and that every ERROR path
blocks grading instead of passing through it. Synthetic runs only; no real data.

Run: python3 analysis/test_e5_stats.py     (exit 0 = every check passed)
"""
from __future__ import annotations

import copy
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import e5_stats  # noqa: E402
from e5_synthetic import REFUTE, SUPPORT, make_run  # noqa: E402

PREDICTIONS = [f"P{i}" for i in range(1, 11)]
failures: list[str] = []


def check(name: str, specs: list[dict], expect: dict[str, str]) -> dict:
    with tempfile.TemporaryDirectory() as d:
        res = e5_stats.analyse(make_run(Path(d), specs))
    got = {p: v["verdict"] for p, v in res["predictions"].items()}
    for p, want in expect.items():
        if got[p] != want:
            failures.append(f"{name}: {p} expected {want}, got {got[p]} ({res['predictions'][p]})")
    print(f"{'ok ' if all(got[p] == w for p, w in expect.items()) else 'FAIL'} {name}")
    return res


def variant(base: dict, **changes) -> dict:
    s = copy.deepcopy(base)
    s.update(changes)
    return s


# 1. Every prediction can be SUPPORTED, and every one REFUTED.
check("all supported", [SUPPORT] * 3, {p: "SUPPORTED" for p in PREDICTIONS})
check("all refuted", [REFUTE] * 3, {p: "REFUTED" for p in PREDICTIONS})

# 2. Disagreeing replications are INCONCLUSIVE, never averaged into a verdict.
check("replications disagree", [SUPPORT, REFUTE, SUPPORT], {p: "INCONCLUSIVE" for p in PREDICTIONS})

# 3. Fewer than three evaluable replications: NOT EVALUABLE.
check("two replications", [SUPPORT] * 2, {p: "NOT EVALUABLE" for p in PREDICTIONS})

# 4. A failed signature blocks everything that rests on that cohort, and nothing else.
#    EFS-plain's A3 shows no GETATTR: P1-P4 lose an input; its B threshold is gone, so
#    P5, P8, P9, P10 lose theirs. P6 (OpenZFS) and P7 (Lustre) still grade.
broken = variant(SUPPORT, break_signature=[("efs_host_plain", "A3")])
res = check("A3 signature fails on EFS", [broken] * 3, {
    **{p: "NOT EVALUABLE" for p in ("P1", "P2", "P3", "P4", "P5", "P8", "P9", "P10")},
    "P6": "SUPPORTED", "P7": "SUPPORTED"})
a3 = res["replications"]["rep-1"]["cohort_a"]["efs_host_plain"]["A3"]
if "latency" in a3:
    failures.append("a FAILed cohort still reported a latency")

# 5. A late cell is ERROR: >5% of deadlines skipped on EFS-plain at 1 s.
check("late cell", [variant(SUPPORT, skip={("efs_host_plain", "1"): 10})] * 3, {
    "P5": "NOT EVALUABLE", "P8": "NOT EVALUABLE", "P9": "NOT EVALUABLE", "P10": "NOT EVALUABLE",
    "P6": "SUPPORTED", "P1": "SUPPORTED"})
# ...and 5% exactly is not (3 skipped of 63 deadlines = 4.8%).
check("skips under the limit", [variant(SUPPORT, skip={("efs_host_plain", "1"): 3})] * 3,
      {p: "SUPPORTED" for p in PREDICTIONS})

# 6. Counters and latency disagree on ONTAP at 10 s: ERROR, P5 not evaluable.
check("counter/latency disagree", [variant(SUPPORT, counter_scale={("fsx_ontap", "10"): 2.0})] * 3,
      {"P5": "NOT EVALUABLE", "P6": "SUPPORTED", "P9": "SUPPORTED"})

# 7. A request overran a counter snapshot: ERROR.
check("overrun", [variant(SUPPORT, overrun=[("fsx_openzfs", "10")])] * 3, {"P6": "NOT EVALUABLE"})

# 8. Lustre's host counter service did not answer: Lustre's A1 cannot be trusted, so
#    P1 and P7 are not evaluable. NFS predictions are untouched.
check("Lustre counters ERROR", [variant(SUPPORT, lustre_error=True)] * 3, {
    "P1": "NOT EVALUABLE", "P7": "NOT EVALUABLE", "P2": "SUPPORTED", "P5": "SUPPORTED"})

# 9. A8's first pass (the forced mount's cold first touch) must be excluded. The
#    generator makes pass 1 three times slower; P4 would fail if it were kept.
res = check("A8 first pass excluded", [SUPPORT] * 3, {"P4": "SUPPORTED"})
n8 = res["replications"]["rep-1"]["cohort_a"]["efs_host_plain"]["A8"]["latency"]["n"]
if n8 != 9000:
    failures.append(f"A8 should keep 9 passes x 1000, kept {n8}")

if failures:
    print("\n".join(["", "FAILURES:"] + failures))
    sys.exit(1)
print("\nall checks passed")
