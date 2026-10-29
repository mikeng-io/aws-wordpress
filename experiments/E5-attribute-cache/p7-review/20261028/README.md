# P7 control review — the 10s noise gate is the first stat of the request

**Status:** `REVIEW COMPLETE; PROPOSAL ADOPTED AND EXECUTED 2026-10-28; P7 SUPPORTED 3/3`.
Mike chose option 2 on 2026-10-28 and raised the study ceiling to **US$30**. The
dated [control-rate amendment](../../method-amendments/20261028-p7-control-rate/README.md)
became the binding rule for replications 2–4. Those three runs were protocol-eligible
and passed full-method validation; pooled P7 is **SUPPORTED**, with control rates
0.0075–0.0243%, 0.0000–0.0117% and 0.0000–0.0067% at 0.1/1/10 s. This review still
does **not** regrade the frozen formal-v3 run, drop any operation, warm the
benchmark, or change a target threshold. P7 stays **ERROR** for
`results/E5-formal/20261027T093314Z-b5b480f/`, and that run is not pooled with the
three new ones.

**Reproduce:** `python3 analysis/e5_p7_control_review.py` (no AWS, reads committed
raw data). Output: [review.json](review.json).

**Bears on:** [E5 P7](../../README.md#predictions), the
[formal-v3 amendment](../../method-amendments/20261027-formal-v3/README.md), and
[H4](../../../../hypotheses/H4-cold-start-is-the-metric.md) through the first-touch
cost it exposes.

## What the gate actually tests

The registered wording (E5 README, method notes) is:

> P7 still has latency evidence only; it is **NOT EVALUABLE** when the EBS control
> has a slow share above the original 1% support limit, or its slow population
> **overlaps** Lustre's classifier boundary.

The implementation (`analysis/e5_stats.py::p7`) tests something narrower:

```
noise = control.stat_split.slow_centroid_ns
if control.slow_share_stat > 0.01
   or (noise >= lustre_threshold_ns and control.slow_share_stat > 0):
       error(...)
```

So "overlap" is operationalised as "the centroid of the control's slow cluster is
at or above the target's boundary, and the cluster is non-empty". The consequence
is also emitted as `ERROR`, while the registered text says `NOT EVALUABLE`.

## Finding 1 — the 10s failure is a 2.8% margin

| Δ | control slow share | control slow centroid | Lustre threshold | gate |
|---|---:|---:|---:|---|
| 0.1 s | 0.2099% | 18,863 ns | 19,290 ns | pass |
| 1 s | 0.2918% | 7,639 ns | 13,638 ns | pass |
| **10 s** | **0.1100%** | **14,601 ns** | **14,208 ns** | **ERROR (+2.8%)** |

The 10s control's slow share (0.11%) is far below its own 1% share gate. The
centroid check, not the share check, is what fires.

## Finding 2 — that slow cluster is the first `stat` of the request

At 10s, using each cell's own classifier threshold:

| cell | slow ops | of which first op | first-op share of cluster | first p50 | later p50 | ratio |
|---|---:|---:|---:|---:|---:|---:|
| EBS matched control | 66 | 60 | **90.9%** | 14,070 ns | 1,536 ns | 9.16× |
| EBS batch control | 118 | 60 | 50.8% | 8,856 ns | 1,632 ns | 5.43× |
| Lustre | 527 | 60 | 11.4% | 66,200 ns | 7,405 ns | 8.94× |
| EFS plain | 9,482 | 30 | 0.3% | 222,484 ns | 2,027 ns | 109.76× |

The control has no server. Its first positive `stat` still costs 14.1 µs against
1.5 µs for the other 999 — a 9.2× penalty on a local block device. Removing the
first operations moves the 10s control centroid to 13,857 ns, 2.5% below the
14,208 ns boundary; that is what flips the gate. The residual non-first tail then
sits within 2.5% of the boundary, so the test is a knife-edge in both directions.

**The penalty is not "being first in a loop".** The `enoent` phase starts
immediately after 1,000 positive `stat`s, with no sleep. Its first operation costs
1.76 µs against 1.07 µs — 1.64×. The 9× penalty belongs to resuming from
`clock_nanosleep`, not to loop position.

## Finding 3 — it is a per-request wake cost, not cache cooling over the idle gap

Formal matched control, same instrument, three intervals:

| Δ | first p50 | later p50 | ratio |
|---|---:|---:|---:|
| 0.1 s | 14,661 ns | 1,540 ns | 9.52× |
| 1 s | 14,733 ns | 1,541 ns | 9.56× |
| 10 s | 14,070 ns | 1,536 ns | 9.16× |

The absolute cost and the ratio are flat across a 100× change in idle time. Lustre
shows the same flatness (67.4 / 67.8 / 66.2 µs; 9.50 / 9.41 / 8.94×). A mechanism
that scaled with idle time would not look like this; a fixed cost of waking the
process does.

This is a mechanism statement about *this instrument*: `agebench` times only
`clock_gettime → syscall → clock_gettime`, so the sleep is excluded, and what
remains is the first syscall after the process is rescheduled. The review does not
claim which CPU or scheduler component produces it.

## Finding 4 — it recurs in every deployment that has a 10s EBS cell

Frozen runs, measured window, not pooled with formal v3:

| run | first p50 | later p50 | ratio |
|---|---:|---:|---:|
| pilot | 8,831 ns | 1,606 ns | 5.50× |
| diagnostic round 2 | 9,400 ns | 1,676 ns | 5.61× |
| diagnostic round 3 | 9,871 ns | 1,757 ns | 5.62× |
| isolation, 15-way batch | 8,493 ns | 1,672 ns | 5.08× |
| isolation, paired batch | 15,660 ns | 1,567 ns | 9.99× |
| formal, matched (paired) | 14,070 ns | 1,536 ns | 9.16× |
| formal, batch (15-way) | 8,856 ns | 1,632 ns | 5.43× |

Five independent deployments, two batch shapes, same effect. The paired batches
sit at 14–16 µs; the 15-way batches at 8.5–9.9 µs. That difference is batch
context, not storage.

## Finding 5 — the centroid estimator is unstable at this tail size

The run contains **two** EBS cells at every interval. They disagree by 36–75%:

| Δ | matched slow centroid | batch slow centroid | spread | vs Lustre boundary |
|---|---:|---:|---:|---|
| 0.1 s | 18,863 ns | 10,777 ns | 75% | both below 19,290 |
| 1 s | 7,639 ns | 13,295 ns | 74% | both below 13,638 |
| 10 s | 14,601 ns | 10,717 ns | 36% | **one above, one below 14,208** |

At 10s the same run, same filesystem, same interval yields both a pass and a fail
depending on which EBS cell is designated the control. A statistic with that
spread cannot carry a binary veto at a 2.8% margin.

The rate of control operations **at or above** the Lustre boundary is stable and
small, and does not have this problem:

| Δ | EBS matched | EBS batch | Lustre |
|---|---:|---:|---:|
| 0.1 s | 0.083% | 0.006% | 0.140% |
| 1 s | 0.075% | 0.067% | 0.591% |
| 10 s | 0.050% | 0.033% | 0.882% |

At 10s the control contributes 30 operations at the boundary across 60,000, against
Lustre's 529. The control cannot account for Lustre's slow share by a factor of 17.

## Finding 6 — the gate is not even self-consistent about "overlap"

At 1s the control's first `stat` (14,733 ns) is **above** the Lustre boundary
(13,638 ns) on most requests, yet the centroid check passes. At 10s the first
`stat` (14,070 ns) is **below** the boundary (14,208 ns), yet the centroid check
fails. A rule described as "slow population overlaps the boundary" is doing
neither of the things that description implies.

## What this means

- There is no evidence here that EBS storage injects slow operations into Lustre's
  slow mode. The control's slow population is dominated by the cost of the first
  operation after a sleep, which exists on a tier with no server.
- Under the unchanged rule, another paired replication would reproduce the 10s
  ERROR: the first-op p50 has been 14–15.7 µs in every paired batch, and the
  boundary has been 13.6–14.2 µs. P7 would stay blocked at n=3 as well.
- Therefore the study is **not replication-ready for P7** under the current
  operationalisation, even though the rest of the formal method is.
- P7 is the only prediction blocked this way. This review changes no other grade.

## Proposal — adopted 2026-10-28 for future replications only

Replace the control-side centroid veto with the direct overlap measurement already
computed above:

1. **Control test.** Let `control_rate` be the share of measured-window control
   positive `stat`s whose latency is at or above the target's classifier threshold.
   The replication grades `ERROR` if `control_rate > 0.2%`, or if the control's slow
   share exceeds the existing 1% gate. Keep both checks. `ERROR` is the existing
   per-replication sentinel for "cannot grade"; `combine()` already reports the
   aggregate as `NOT EVALUABLE`.
   *Derivation:* 0.2% is one fifth of P7's own 1% SUPPORT bound. If the control
   cannot produce one fifth of the smallest target effect we would call supported,
   it cannot explain that effect. Observed margins are 2.4–4× below the bound.
2. **Diagnostics, not vetoes.** Report the control slow centroid and the
   first-operation decomposition alongside the grade. The centroid stays visible
   but no longer decides, because two control cells in the same run differ by 36%.
3. **No new grade string.** Keep the per-replication `ERROR` sentinel and let the
   existing aggregation produce `NOT EVALUABLE`. A new per-replication label would
   change the schema and every consumer for no gain.
4. **Unchanged.** Target thresholds (SUPPORT ≤1%, REFUTE >5%), the share gate, P9
   and P10, every raw operation, and the rule that the first `stat` remains in all
   summed-time costs. No operation is dropped or warmed away.

The amendment still does not apply to the 2026-10-27 result.

## Decision — 2026-10-28

Mike chose **option 2**: raise the study ceiling to **US$30** and chase n=3. This
adopts the control-rate amendment for future replications while leaving the
2026-10-27 result frozen at `P7 ERROR`. Remaining conditions before each paid run:

- refresh pricing and the allocation/pricing snapshot;
- run the replications sequentially, reviewing each before the next;
- stop on a protocol `ERROR`, a budget breach, or a teardown failure.

**Budget arithmetic.** Conservative post-run proxy US$16.996. The off-protocol
legacy run of 2026-10-28 (default collector; retained, not pooled) consumes one
~US$2.60 envelope. Three formal replications at the same envelope are ~US$7.80, for
a revised planning total of **US$27.396**, leaving **US$2.604** below the ceiling.
That still fits, but a fourth replication does not. If refreshed pricing puts a
replication above ~US$3.00, stop and re-plan rather than absorb it.
