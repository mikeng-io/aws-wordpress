# E4 — task-start hydration as a read-only cache

**Status:** `COMPLETE — 3/3 formal replications` (2026-10-29).
Formal result [`20261029T091909Z-842d596`](../../results/E4/20261029T091909Z-842d596/):
**P1 SUPPORTED, P2 REFUTED, P3 SUPPORTED; H2 read-only proxy MET**.
See [the finding](../../docs/findings/E4-hydration.md) for per-rep/pooled results,
cache-mode and request-extrapolation caveats, cost estimates and teardown receipts.
All three stacks and EFS filesystems are verified gone. Design replaced in place
2026-10-29 after E2 gated the original transparent adapter. Ceiling **US$2**,
approved 2026-10-29; the failed DNS-readiness attempt is archived separately.
H2's broader verdict is unchanged; H6 is not tested.

**Bears on:** [H2](../../hypotheses/H2-fargate-forbids-caching.md),
[H4](../../hypotheses/H4-cold-start-is-the-metric.md),
[H6](../../hypotheses/H6-writeback-cannot-be-correct.md).

## Question

On Fargate, does serving an application's read-only code tree from a task-start
local copy capture most of the metadata-latency gap to EFS, and what does the
hydration cost in cold-start time?

This is narrower than the original E4. It does **not** build a cache adapter and
does **not** test write-back. It tests the single-writer alternative H6 already
names: hydrate code once at task start from a durable origin, serve reads locally,
never sync back. The application remains unmodified; the task definition chooses
the path.

## Why the design changed

The original E4 was a transparent read-through/write-back adapter presenting one
POSIX path. E2 completed the FUSE matrix on 2026-10-29:

- On EC2, JuiceFS and SeaweedFS already provide conformant local caches; a bespoke
  adapter would be prior art.
- On Fargate, all three FUSE tiers require `CAP_SYS_ADMIN`, which the platform does
  not grant. There is no transparent filesystem layer to put a cache on.

So the adapter is not buildable on the target platform. Hydration is the remaining
Fargate-only, infrastructure-only mechanism. The old design is preserved in git
history and summarised at the bottom of this file.

## Method

One synthetic WordPress-shaped code tree, three one-shot Fargate tasks per
replication, all in one isolated VPC with an EFS file system:

1. **Seed** — a task builds the tree on EFS (`20` directories × `50` files,
   2–50 KB, deterministic sizes) with the shared `bench` instrument, then writes a
   tar of the tree to the EFS root. Its timing output is ignored; this task only
   creates the origin.
2. **EFS arm** — a **fresh** task mounts the same EFS and runs the benchmark in
   `BENCH_EXISTING` mode against the seeded tree. No create pass, so this measures
   reads of files the client did not just write. No unlink pass.
3. **Hydrated arm** — a **fresh** task mounts EFS, downloads the tar to its own
   ephemeral storage, extracts it to `/local-bench/tree`, records download+extract
   wall time, then runs the same `BENCH_EXISTING` benchmark against the local copy.

Each task runs in its own Fargate task and reports its own CloudWatch stream, so
the EFS arm is not contaminated by the seed task's writes or the hydrated arm's
copy. The controlled variable is **which storage serves the read**; the tree,
instrument, CPU architecture, kernel, AZ, and time window are held as constant as
separate one-shot tasks allow. The hydration cost is the treatment, not noise.

The tree is deliberately the same shape as E2/E3's instrument rather than a real
WordPress install. That keeps the comparison to E2/E3 exact and makes the
extrapolation to a request explicit: E0 measured ~4,300 filesystem syscalls for a
warm request, so the per-request saving is an E0-multiplier estimate, not an
end-to-end measurement. A future app-level experiment would be needed to turn it
into request latency; this experiment does not pretend to.

### Read-only, by construction

The hydrated arm never writes back. Writes, uploads, and mutable state are out of
scope and would stay on the durable tier in a real deployment. This means H6 is
**not tested** here; the experiment deliberately chooses the branch H6 says is
correct (single writer, hydration only), rather than trying to refute H6 with a
bidirectional design on a platform that cannot mount one.

## Pre-registered predictions

Written before the first deployment:

1. **Hydration removes the metadata penalty.** In every replication, hydrated
   `stat` p50 is ≤ **0.10×** the EFS arm's `stat` p50, and hydrated `open_read`
   p50 is ≤ **0.20×** EFS's.
2. **Hydration is not free.** Download+extract takes at least **0.5 s**, and the
   hydrated task's start-to-benchmark time exceeds the EFS task's by at least the
   measured hydration time. Report the break-even number of requests using E0's
   ~4,300 ops/request.
3. **The read-only tree is conformant on both arms.** The shared conformance gate
   passes on EFS and on the local copy (it may create its own probe files); no
   benchmark number counts if it fails.
4. **H2's kill condition is evaluated, not assumed.** If prediction 1 holds and
   hydration costs less than the EFS metadata penalty of a single E0-sized request,
   then a Fargate-only, infrastructure-only design closes most of the gap at a
   start-latency cost below one request; that meets H2's kill condition for the
   read-only code path. If not, H2's surviving claim stands.

Prediction 4 is deliberately conditional: "acceptable start latency" is not
defined by this experiment, so the result reports the crossover and lets H4's
task-lifetime question decide the operational reading.

## Kill conditions

- **Prediction 1 fails** if the hydrated/EFS `stat` ratio is > 0.10 in any
  replication, or `open_read` > 0.20. Then local hydration does not remove the
  metadata penalty and E4 has no result worth extrapolating.
- **Prediction 2 fails** if hydration is under 0.5 s (the tree is too small to
  represent a code bundle) or if the task-time difference is smaller than the
  measured hydration time (the measurement is not attributable).
- **Prediction 3 fails** if conformance fails on either arm; latency is then
  reported as disqualified rather than averaged.

## Cost and teardown

Three Fargate tasks per replication (`0.5` vCPU / `1 GiB`, ARM64), one EFS file
system with ~26 MB, three interface endpoints, and a small S3 results bucket. No
NAT gateway, no FSx, no ALB, no EC2 instance. Fargate on-demand at the study's
pricing snapshot is a few cents per task-minute; the whole 3-replication campaign
is estimated **under US$0.20**, with a hard ceiling of **US$2**.

The collector deploys one stack, runs the three tasks sequentially, empties the S3
bucket, destroys the stack, and refuses to continue if the stack or EFS survives.
If a task fails, the collector still destroys the stack before exiting non-zero.
The stack's `EstimatedHourlyUsd` is `0.04` so a forgotten stack has a known burn
rate.

## Output

`results/E4/<run-id>/rep-<k>/` with:

- `seed/` — seed task log/S3 artefacts (timing ignored)
- `efs/efs.csv`, `efs/efs.conformance.csv`, `efs/mount-facts.csv`
- `hydrated/ephemeral.csv`, `hydrated/ephemeral.conformance.csv`,
  `hydrated/mount-facts.csv`, `hydrated/hydration.csv`
- `meta.json` per replication, plus `summary.json` / `summary.md`

`hydration.csv` is `hydrate,<ns>,<bytes>`; analysis computes seconds and the
break-even request count from E0's op count. Every published statistic is
recomputable with `python3 analysis/e4_stats.py results/E4/<run-id>`.

## Reproduce

```sh
REPS=3 make e4
python3 analysis/e4_stats.py results/E4/<run-id>
```

A one-replication smoke must pass before the formal three; the smoke is committed
separately and is not part of the formal statistic.

## History — the original adapter design

The experiment was originally specced as a transparent local cache in front of a
durable mount, with read-only, write-through, single-writer and multi-writer
variants. E2's FUSE result removed its target: the existing caches are EC2-only and
Fargate has no mount path. The full old text is in git history; the surviving
question is the one above. H6 remains `UNTESTED` and is not claimed by this run.


## Historical handoff — before formal completion

The smoke (`20261029T084344Z-ec1e5b2`, one replication) already shows the shape:
EFS `stat` p50 1.60 ms vs hydrated 3.2 µs (ratio 0.002); `open_read` 3.59 ms vs
14.0 µs (0.004); both conformance gates PASSED; hydration was 27,412,480 bytes in
0.214 s. P1 SUPPORTED, P3 SUPPORTED, H2 kill-condition proxy MET. P2 is REFUTED
mechanically because 0.214 s is below the pre-registered 0.5 s floor and the
start-to-benchmark delta (0.021 s) is below the hydration time; the floor was a
guess about bundle size, and the task-time comparison is dominated by scheduling.
Do not change the prediction retroactively.

Formal run `20261029T085327Z-31e9fa2` stopped after rep-1's EFS task, before the
hydrated task and before its `meta.json`. Its partial raw files are archived but
are **not** a formal result. The E4 stack was destroyed manually and verified gone.
To finish: `REPS=3 make e4`, then `python3 analysis/e4_stats.py results/E4/<run-id>`.
A prior failed smoke `20261029T083342Z-fe5f631` is also archived; it failed only
because `/tmp/hydration.csv` was not uploaded, fixed in `ec1e5b2`.

## Readiness correction — 2026-10-29

Run [`20261029T090427Z-3b8faf3`](../../results/E4/20261029T090427Z-3b8faf3/)
completed rep-1 but failed at rep-2's seed task before any measured arm: the
new EFS DNS name did not resolve (`ResourceInitializationError`). This is an
archived incomplete campaign, not a formal result; it is not graded or pooled.
The collector log and task failure are retained. Both stacks were destroyed.

AWS [documents the mount-target DNS propagation race](https://docs.aws.amazon.com/efs/latest/ug/troubleshooting-efs-mounting.html).
The collector now asserts one available mount target and waits 90 seconds before
starting the seed task. This readiness wait is outside the measured tasks and
does not change hydration timing, the workload, predictions or thresholds. A
fresh three-replication run replaces the failed campaign; no partial run is resumed.
Analysis also now reports operation-level median CIs, geometric means, dispersion
and deterministic log-space clustering, plus per-rep median spread. Existing
smoke numbers and all grades were checked unchanged on a temporary copy; the
smoke's committed output was not regenerated.

## Formal completion — 2026-10-29

[`20261029T091909Z-842d596`](../../results/E4/20261029T091909Z-842d596/) has three complete,
independent replications with `git_dirty: false`. Both latency thresholds and both
conformance gates hold in every rep. Hydration is 0.218–0.444 s for the same
27,412,480 bytes, and the first-log-to-benchmark deltas are 0.051–0.265 s: **both
P2 clauses fail in every rep**. Neither threshold was changed. The H2 proxy is
MET for the read-only code path; it is not a whole-H2 verdict or measured request
latency. Detailed distributions, replication spread, startup limitations and
cost/teardown evidence are in [the finding](../../docs/findings/E4-hydration.md).

The successful campaign's task-plus-endpoint estimate is US$0.1211; adding the
failed readiness attempt gives US$0.2009, excluding ancillary usage and not an
invoice ([cost evidence](../../results/E4/20261029T091909Z-842d596/campaign-summary.json),
[failed-attempt cost](../../results/E4/20261029T090427Z-3b8faf3/campaign-summary.json)).
Reproduce that estimate with `python3 analysis/e4_campaign.py results/E4/20261029T091909Z-842d596`.
