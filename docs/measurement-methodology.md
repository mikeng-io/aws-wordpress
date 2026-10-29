# Measurement methodology

Current interpretation consolidated 2026-10-29. The instrument/method below is
part of each claim: counts, cache-hit/miss latency, RPC rates, hydration and
request latency are different quantities. See [the evidence index](evidence-index.md)
for eligible runs and [offline verification](closeout-verification.md) for replay
scope. No new live collection is needed to publish the existing negative results.

## E0 — syscall counts (local, no AWS)

**Instrument.** `strace -f -qq -s 512 -e trace=file` attached to the php-fpm
**worker** process (not the master: workers are forked children that already exist
when strace attaches, and `-f` only follows forks created afterwards, so tracing
the master captures nothing). `-s 512` is required — strace's 32-char default
truncates the deep plugin paths being counted.

**Isolation.** `pm = static`, `pm.max_children = 1`, so exactly one worker handles
the request and the trace is unambiguously attributable. Requests are issued with
`cgi-fcgi` straight to the FastCGI socket, so no web server contributes syscalls.

**Cohorts.** *cold* = first request after a php-fpm master restart (opcache empty —
restarting a worker is insufficient, opcache lives in shared memory across the
pool). *warm* = after 5 warmups. *warm-aged* = after waiting past the profile's
`opcache.revalidate_freq` window, which is the only way `tuned` is meaningfully
different from `max`.

**Parsing.** `analysis/e0_census.py`. Path-component classification counts only
genuine lookup syscalls (stat/open/readdir/readlink families); `getcwd` and
`chdir` carry a quoted path argument but are process-state bookkeeping, not
filesystem lookups, and including them previously inflated the figure.

**Statistical character.** Syscall counts are **deterministic** — at n=10 nearly
every cell has a zero-width range. This is why E0 reports medians without
confidence intervals: there is no sampling variability to quantify. Any non-zero
range in `aggregate.md` is real and worth reading.

**What E0 does not measure.** Latency. Docker volumes on a laptop say nothing
about EFS. E0 produces the *op count*; E3 produces the *per-op cost*.

## E3 — per-syscall latency (AWS Fargate)

**Instrument.** A purpose-built C microbenchmark (`infra/lib/stacks/e3-bench/bench.c`),
not `fio`. `fio`'s default patterns are throughput-oriented, and the workload E0
measured is small-file *metadata* operations. Timing is
`clock_gettime(CLOCK_MONOTONIC)` around **each individual syscall**, never around a
batch — a batch average would hide exactly the tail behaviour being investigated.

**Workload.** A deterministic tree of 20 directories × 50 files, sizes 2–50 KB
derived from a fixed hash so every mount and every run sees an identical tree.
Passes: create → stat → open+read → stat(ENOENT) → unlink.

**Controlled comparison.** Both mounts are measured **inside the same task, in the
same run, on the same vCPU**, sequentially. The only variable between the two arms
is which mount serves the request.

**Sampling.** 3 independent Fargate task runs (not 3 loops inside one task), 4,020
ops per mount per run, pooled to n=3,000 per op per mount for the timed passes.
The main passes pool to 3,000 observations per mount; ENOENT has 60, not 3,000.
Between-run agreement is reported explicitly in `stats.md`; if independent runs
disagreed, no single-run percentile would be quotable.

### Statistical treatment and why

| Choice | Reason |
|---|---|
| **Median**, not arithmetic mean | Latency is right-skewed; the mean is dominated by the tail and describes no typical operation. |
| **Geometric mean** reported alongside | Latency is approximately log-normal; the geometric mean is the appropriate centre for multiplicative data. Where it diverges sharply from the median, that divergence is itself diagnostic — it is what first exposed the bimodality below. |
| **Distribution-free median CI** (order statistic, normal approximation to the binomial) | The data are not normal, so a t-interval would be unjustified. |
| **p99/p50 tail ratio** | Distinguishes a tight, local-disk-shaped distribution from a heavy-tailed network one — the question E3 exists to answer. |
| **IQR/median** | Spread that is independent of the extreme tail. |
| **1-D k-means (k=2) on log10(latency)** | Modes separated by orders of magnitude; log space is the correct domain, since Euclidean distance on raw nanoseconds lets the slow mode dominate. Deterministically initialised at the 10th/90th percentiles, so the result is reproducible rather than seed-dependent. |
| **Bimodality gate** | A split is only reported as bimodal if centroids differ by ≥0.5 log10 (≥3.2×) **and** each cluster holds ≥2% of the sample. This is what correctly rejects `open_read`/local — 64× separation, but the fast cluster is <2%, so it is outliers, not a population. |

### Threats to validity, stated

- **Single AZ, single region, single instance size.** ap-southeast-1a, Fargate
  1.4.0, 512 CPU / 1024 MiB, ARM64. Nothing here establishes behaviour elsewhere.
- **EFS was Elastic throughput, One Zone, General Purpose, transit encryption on,
  no access point, no IAM auth.** Other configurations are not covered.
- **The benchmark's access pattern is not WordPress's.** It touches each path once
  in sequence. Real WordPress re-stats the same paths repeatedly within a request,
  which can change attribute-cache behaviour. The benchmark share is neither a
  measured production hit rate nor a proven lower bound for it.
- **Local ephemeral is not a persistent tier.** It is measured as a hydration
  target, not as durable storage.

<a id="composing-e0-and-e3"></a>

## Composing counts and latency

E0 gives demand counts; E2/E3/E4/E5 measure different filesystem cohorts. A
count-times-p50 calculation is an **extrapolation with assumptions**, not a
measured page latency and not automatically an upper/lower bound. E0 mixes
syscall types; one p50 cannot represent all operations, repeated accesses,
concurrency, opcache, the database and warm NFS state. A measured cache-hit share
in a synthetic tree does not establish a production floor.

The older E3 finding used “bound” and “floor”; its dated closeout correction
supersedes that interpretation while preserving the historical calculation.
E4's break-even is explicitly a proxy for a read-only code path. Neither grades
H4's time-to-first-200-OK/ranking prediction or H7's equal-p95 economics.

## E2 — storage matrix, then FUSE arms

[Block](../results/E2/20260910T163206Z-66dcff8/),
[mount](../results/E2/20260910T182051Z-53b5423/),
[FSx](../results/E2/20261015T000959Z-85382cc/) and
[FUSE](../results/E2/20261029T070456Z-a2041d6/) are separate three-deployment
collections. The shared bench records each syscall, deterministic small-file
trees, conformance and mount facts. EC2 and Fargate arms use separate tasks;
comparisons are not perfectly matched CPU/hardware experiments.

**Fresh-file confound.** The original create→stat/read order warms the NFS
attribute/page caches. `stat` p50 therefore depends on file age and the proportion
of cache hits; `open_read` often reads newly written bytes from client memory.
The [server-backed finding](findings/E2-server-backed.md) uses RPC/mount evidence
to identify this confound. It cannot be repaired by relabelling cached ONTAP
latency as server latency.

**Throughput is separate.** E2's declared residency guard disqualified Lustre
read phases for the FSx ranking prediction. Throughput bounds/diagnostics are
exploratory; they do not change P1 NOT EVALUABLE. Mutation operations remain
useful matched observations but do not establish a production workload winner.

**FUSE scope.** JuiceFS/SeaweedFS/Mountpoint run through EC2-host FUSE mounts and
an unprivileged benchmark container. The registered JuiceFS comparison did not
meet its bar; SeaweedFS is an additional design point, not a second P2 attempt.
Mountpoint is conformance-only because its semantics disqualify the write path;
missing latency is not zero. The collection shows what ran on EC2, while Fargate
reachability also rests on the platform capability constraint; it did not launch
a deliberate privileged-Fargate failure test.

**Provenance.** The FSx rep-3 collector resume exception and FUSE git_dirty=true
note remain visible. Predictions are scoped per campaign; newer analysis may
emit additional diagnostics when replaying an older run, but it must preserve
its recorded fields/grades rather than turning those extras into new evidence.

## E4 — read-only task-start hydration

[Formal run](../results/E4/20261029T091909Z-842d596/) has three independent fresh
stacks. Each runs seed → fresh EFS task → fresh hydrated task. The seed builds
one deterministic tree and an EFS tar. The hydrated task reads/extracts that tar
onto task ephemeral storage, then benchmarks existing files locally; its tier
name is `ephemeral`, though the task arm is `hydrated`.

There is no create/unlink workload or reverse sync. Conformance deliberately
mutates its own probe files; this does not prove an enforced immutable code tree,
cross-node write correctness or deployment propagation. Images/AZ/task shape,
operation counts and per-rep metadata are retained. All formal reps record a
clean apparatus; failed/interrupted/smoke attempts are excluded.

The hydration timer is the `tar -xf` wall time, including reads from mounted EFS
and local extraction. It excludes image pull, ECS provisioning, mount setup and
conformance. First-log→benchmark includes preflight/conformance/log scheduling;
its between-arm delta is not hydration's isolated causal overhead. The DNS
readiness wait is outside the tasks. P2 remains REFUTED under its original floor
and delta requirements. Full task-create→HTTP-200 was never measured.

Current E4 analysis reports per-rep/pooled p50 and tails, geometric means,
order-statistic CI rank approximations, dispersion and deterministic log-space
clustering. Operation-level intervals are not uncertainty over three deployments;
serial/cache dependence matters. E4's millisecond EFS stat split is a tail with
unisolated cause, not E2's microsecond-hit/remote-miss split.

## E5 — old-file, revalidation and repeat-access cohorts

The [three-run formal-v3 pool](../results/E5-formal/20261028T160106Z-dd5fce0/analysis-pooled-3.json)
requires a fresh deployment identity, completion/protocol markers, apparatus
hashes, full windows, independent counter evidence and matched same-time EBS
controls. Cohort A separates first-touch/revalidation/forced-miss questions.
Cohort B separates warm-up from measured repeated access at registered intervals.
This is still a synthetic tree, not a WordPress request path.

P7's rate-based control veto was registered before the three later runs. The
older formal validation retains its original centroid-rule ERROR and is not
pooled. The verifier selects those original graders by hash, never applying the
latest rule to every old directory. Pilot/diagnostic/short/off-protocol methods
are separate evidence roles.

P4's A8 ten-pass pool and A3 single pass are not like-for-like. The completed v3
result stays INCONCLUSIVE; [first-pass diagnostics](../analysis/e5_p4_passes.py)
explain part of it without changing the grade. The future-v4 amendment changes
neither the old samples nor the old thresholds. P7 is a latency/attribution result,
not direct proof of Lustre DLM state; a small amortised cost must be reported with
its miss/tail concentration, not presented as uniformly free operations.

## Publication and cost boundaries

Frozen raw data, original derived grades, exclusions, method changes and dated
interpretation corrections are separate artifacts. Reproduction runs in scratch;
collection completion does not imply every protocol prediction was evaluable.
The current phase carries its construct/provenance limits rather than requiring
new paid runs to erase them.

Pricing snapshots, task/endpoint proxies, campaign envelopes, actual billed
usage and production cost per request are different quantities. No equal-p95
request economics were measured. Workload teardown receipts do not certify an
account-wide zero-cost state; [retention/cost follow-up](retention-and-cost.md)
keeps that operational question separate from the filesystem findings.
