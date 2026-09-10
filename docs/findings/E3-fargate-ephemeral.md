# E3 — Fargate ephemeral storage is genuinely fast, and the gap is metadata-shaped

**Result:** `results/E3/20260910T113000Z-6016f58/` (3 reps, 4,020 ops per mount per rep)
**Bears on:** [H2](../../hypotheses/H2-fargate-forbids-caching.md)

## What was predicted

E3's README pre-registered two things:

1. Local ephemeral `stat()` p50 at least an order of magnitude below EFS's.
2. The tail was the real question — if local ephemeral is quietly a network volume,
   its p99 would show EFS-like behaviour, which would refute the
   hydrate-onto-ephemeral design outright.

**Both resolved in local ephemeral's favour, by a much wider margin than predicted.**

## Measured

Median of 3 reps, `naive` tree (20 dirs × 50 files, 2–50 KB):

| op | local p50 | EFS p50 | ratio |
|---|--:|--:|--:|
| **stat** | **3.1 µs** | **1.04 ms** (pooled median) | ~335×* |
| stat (ENOENT) | 7.2 µs | 1.29 ms | ~178× |
| create | 38.2 µs | 7.59 ms | ~199× |
| unlink | 19.7 µs | 3.20 ms | ~162× |
| open+read | 11.3 µs | 1.03 ms | ~91× |

\* Pooled medians. `stat` on EFS is bimodal — see the cluster analysis below,
which yields the defensible cache-aware figure of ~271×.

Run-to-run stability: local `stat` p50 was 3,085 / 3,094 / 3,142 ns across the three
reps — ±2%. EFS varied ~±10%, which is what a network filesystem should look like.
The effect is far larger than the variance.

## The tail question, answered

Local ephemeral's `stat` p99 is **4.6 µs** against a p50 of 3.1 µs — a 1.5× spread.
That is local-disk-shaped, not network-shaped. Fargate's ephemeral storage is
network-*backed* per AWS's documentation, but it does not behave like a network
filesystem for metadata: no EFS-like tail, no per-op round trip.

**The kill condition did not fire.** Local p99 is two to three orders of magnitude
below EFS's, not within the same one. The hydrate-onto-ephemeral branch of H2
survives, and is now supported by measurement rather than assumption.

## The nuance that matters more than the headline

The ratios are not uniform, and the shape is the finding:

- **Metadata ops (`stat`): ~271×** cache-aware (~335× on the naive pooled median).
- **Bulk read (`open+read`): ~91×**, and local's own `open_read` tail is much
  looser than its `stat` tail (p99 711 µs against a p50 of 11 µs — real disk I/O
  and page-cache misses on 2–50 KB files).

EFS is far less bad at moving bytes than at answering questions about files. That
is exactly the asymmetry the study has been arguing from E0 onward, now measured
directly on the same hardware in the same task rather than inferred.

## The distribution is bimodal, and that changes the headline

Pooled percentiles hid something. EFS `stat` has a geometric mean of 257 µs against
a median of 1.04 ms — a geometric mean *below* the median is the signature of two
populations, not one.

Formal test (`analysis/e3_clusters.py`; 1-D k-means, k=2, on log10 latency,
deterministically initialised at the 10th/90th percentiles):

| cluster | share | median | mechanism |
|---|--:|--:|---|
| fast | **24.4%** | **2.6 µs** | NFS attribute-cache hit — no network round trip |
| slow | **75.6%** | **1.11 ms** | cache miss — goes to the wire |

Centroid separation is **415×**. The fast cluster's 2.6 µs is statistically
indistinguishable from local ephemeral's 3.1 µs, which is the giveaway: those calls
never left the kernel.

This is the only genuinely bimodal distribution in the set. Every other op/mount
pair tested unimodal. `open_read` on local showed 64× centroid separation but was
correctly **rejected** as bimodal because its fast cluster holds under 2% of the
sample — that is a handful of outliers, not a second population.

### The cache-aware numbers

Weighting the clusters by their measured shares:

| figure | value |
|---|--:|
| EFS `stat`, effective mean cost | **0.840 ms** |
| EFS `stat`, naive pooled median | 1.04 ms |
| local `stat`, median | 3.1 µs |
| **cache-aware ratio** | **~271×** |
| naive median ratio | ~335× |

**271× is the defensible number**, not 335×. The naive median overstates the gap by
about 24% because it ignores the quarter of calls the attribute cache absorbs.

## What this composes to, with E0

E0 measured ~3,900 `stat` calls on a warm WordPress request that `php.ini` tuning
cannot remove. E3 measures what a `stat` costs on each tier.

**Illustrative bound, not a prediction:** using the cache-aware effective cost,
3,900 × 0.840 ms ≈ **3.3 s** of `stat` alone on EFS, against 3,900 × 3.1 µs ≈
**12 ms** on local ephemeral. (The naive median would have said 4.2 s; the cluster
analysis is what brings it down to 3.3 s.)

This is deliberately labelled a bound, not a forecast, and the cluster analysis
shows exactly why. E3's benchmark touches each path once in sequence and still saw
a 24.4% cache-hit rate. Real WordPress re-stats the *same* paths many times per
request, so its hit rate would be materially higher and its effective cost
correspondingly lower. **The 24.4% measured here is a floor for WordPress-like
access, not an estimate of it** — which is precisely why 3.3 s is an upper bound
and not a prediction. The honest claim is
narrower and still decisive — **the per-op multiplier between the two tiers is
~350× for exactly the operation WordPress issues thousands of times per request.**
Turning that bound into a measured page latency is a load-test question, not
something E0 or E3 can answer.

## Operational finding, recorded separately

The first task run failed with
`ResourceInitializationError: failed to invoke EFS utils commands ... Failed to
resolve fs-….efs.ap-southeast-1.amazonaws.com`. All three causes AWS documents for
that error were ruled out empirically: DNS hostnames were on, no custom DHCP
options, and the mount target was in the *same subnet* as the task.

A diagnostic task run minutes later proved the name resolved correctly
(`→ 10.43.0.33`) and TCP 2049 was reachable. Re-running the **identical, unchanged**
task definition then succeeded. The cause was mount-target DNS propagation lag:
CloudFormation reports `CREATE_COMPLETE` and the mount target reports `available`
before Fargate can actually resolve it. Anything automating deploy-then-immediately-
run against a fresh EFS mount target needs to tolerate this — it presents as a hard
task failure, not a retry-able warning.


## Where these numbers come from

- Raw per-op latencies: `results/E3/20260910T113000Z-6016f58/rep-{1,2,3}/{local,efs}.csv`
- Distribution statistics: `stats.md` / `stats.json` (`analysis/e3_stats.py`)
- Cluster analysis: `clusters.md` / `clusters.json` (`analysis/e3_clusters.py`)
- Percentile comparison: `percentiles.md` / `percentiles.json` (`analysis/e3_percentiles.py`)
- Full provenance: `meta.json` — region, AZ, Fargate platform version, CPU
  architecture, task size, ephemeral storage size, EFS configuration, tree shape
- Instrument, statistical choices, and threats to validity:
  [docs/measurement-methodology.md](../measurement-methodology.md)

Every figure above is recomputable from the committed CSVs by re-running the three
analysis scripts. Nothing is hand-transcribed.
