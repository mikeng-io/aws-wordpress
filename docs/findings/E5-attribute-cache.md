# E5 — NFS attribute cache: Lustre repeats are free, EFS repeats are not

**Result:** three independent `isolation-formal-v3` replications, 2026-10-28:
[rep 2](../../results/E5-formal/20261028T103017Z-342d6b4/review.md),
[rep 3](../../results/E5-formal/20261028T125412Z-f6659e0/review.md),
[rep 4](../../results/E5-formal/20261028T160106Z-dd5fce0/review.md). Pooled:
[analysis-pooled-3.json](../../results/E5-formal/20261028T160106Z-dd5fce0/analysis-pooled-3.json).
**Bears on:** [H1](../../hypotheses/H1-cache-locality.md), its per-op cost factor.

## Question

What does an NFS `stat` cost once the file is old — the miss that revalidates it,
and the steady-state rate at which those misses arrive? E5 holds the application
demand fixed (the E0 ~3,900 `stat` per warm request) and varies the storage tier and
the interval between requests.

## Method

`isolation-formal-v3`: one fresh deployment per replication, six tiers, cohort A
for miss/first-touch/forced-miss/revalidation cost, cohort B for all tiers at
0.1/1/10 s (300 s warm-up, 600 s measured), same-time EBS controls, quiet profile,
300 s idle evidence. Three protocol-eligible deployments, each independently torn
down and verified. The frozen 2026-10-27 run is not pooled: it remains `P7 ERROR`
under the rule in force at the time.

## Headline: P7 is SUPPORTED (3/3)

P7 asks whether Lustre's slow-cluster share stays ≤1% at every interval. It does:

| run | 0.1 s | 1 s | 10 s |
|---|---:|---:|---:|
| rep 2 | 0.256% | 0.238% | 0.275% |
| rep 3 | 0.231% | 0.231% | 0.273% |
| rep 4 | 0.335% | 0.285% | 0.157% |

The matched-EBS control rate at or above the target boundary — the quantity the
2026-10-28 amendment made binding — stayed at **0.0000–0.0243%**, far below the
0.2% veto in every cell. The old centroid veto never decided a replication in this
set. This is consistent with Lustre repeats being served without a per-`stat`
server round trip at these timescales. It is a latency result, not proof of DLM
lock state.

## The other predictions

- P1–P3 **REFUTED**. E2's 827/98/149 µs miss-cost cluster, ONTAP's unobserved-miss
  class, and the first-touch/revalidation ratio did not reproduce as registered.
- **P4 INCONCLUSIVE.** See below. Two runs passed the forced-miss check, one failed.
- P5, P6, P8–P10 **SUPPORTED**. P5's RPCs per `stat` were ≈0.0017 / 0.017 / 0.16 at
  0.1/1/10 s, tracking Δ/`acregmax`; P6's OpenZFS miss fraction stayed ≤0.57% even
  at 10 s, consistent with delegations; P9's amortised EFS/EBS per-request ratio was
  3.9× / 4.4× / 5.2×, far below the 50× support bound; P10's miss concentration
  held, which is why the amortised mean is not quoted without the tail.

## P4 is now the open instrument question

P4 is a manipulation check: A8 (forced-miss mount) should be within ±25% of A3
(real revalidation) on each NFS tier. It passed in reps 2 and 3 and failed in rep 4:

| tier | A3 p50, reps 2/3/4 | A8 p50, reps 2/3/4 | A8/A3, rep 4 |
|---|---|---:|---:|
| EFS plain | 263 / 274 / **357 µs** | 233 / 258 / 255 µs | 0.716 |
| EFS TLS | 311 / 334 / 336 µs | 352 / 339 / **432 µs** | 1.287 |
| OpenZFS | 69 / 97 / **98 µs** | 70 / 98 / 69 µs | 0.701 |
| ONTAP | 109 / 111 / 110 µs | 108 / 111 / 107 µs | 0.969 |

A8 runs **ten passes** over the tree (`E5_A8_PASSES=10`, Δ=10000) while A3 is a
**single pass** after 75 s idle, so pooling all A8 passes is not a like-for-like
comparison. Splitting rep 4 by pass makes the problem explicit:

| tier, rep 4 | A3 | A8 pass 1 | A8 passes 2–10 | A8 all / A3 |
|---|---:|---:|---:|---:|
| EFS plain | 356.5 µs | 259.1 µs | 254.9 µs | 0.716 |
| EFS TLS | 335.7 µs | 431.5 µs | 432.1 µs | 1.287 |
| OpenZFS | 98.0 µs | **98.0 µs** | 68.3 µs | 0.701 |

On OpenZFS the first A8 pass matches A3 exactly (98.0 vs 98.0); the 0.701 failure is
the nine warmed passes, not a different measurement. That correction does not rescue
the other tiers: on EFS plain A8 is ~255 µs on every pass while A3 is 357 µs (A3
elevated against 263/274 µs in reps 2/3), and on EFS TLS A8 is ~432 µs while A3 is
336 µs. Reps 2 and 3 show the same directions at smaller amplitude. No single
pass-selection rule makes P4 pass on all tiers.

The registered ±25% check is therefore confounded by pass count on OpenZFS and by
tier/phase behaviour on EFS. P4 is **INCONCLUSIVE**, not a P7 failure: P7 reads
cohort-B positive `stat` cost and same-time EBS controls, not the A8/A3 ratio.

## What this changes for H1

Nothing in H1's verdict. The per-op factor is still a tier property: Lustre does
not pay a repeat `stat` cost at these intervals, while EFS's 10 s miss fraction
stays near the `acregmax` model. The remaining work is a production cost model,
not a filesystem ranking.

## Limits

Three replications, one region/AZ, one instance type, a synthetic `agebench` tree
(20 directories × 50 files) rather than a live WordPress request path. P7 is a
latency test. P4's manipulation check is now itself under review. Billing figures
are planning envelopes, not invoices.

## Reproduce

```
python3 analysis/e5_formal_stats.py \
  results/E5-formal/20261028T103017Z-342d6b4 \
  results/E5-formal/20261028T125412Z-f6659e0 \
  results/E5-formal/20261028T160106Z-dd5fce0

make e5-p4-passes   # A3 vs A8's first and later passes
```
