# Measurement methodology

How every number in this study was produced. A benchmark without this section is
an assertion, not a measurement.

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
  which would raise the attribute-cache hit rate materially above the 24.4%
  measured here. The measured hit rate is therefore a *floor* for WordPress-like
  access, not an estimate of it.
- **Local ephemeral is not a persistent tier.** It is measured as a hydration
  target, not as durable storage.

## Composing E0 and E3

E0 gives ops per request; E3 gives cost per op. Multiplying them is legitimate only
with the cache behaviour accounted for, and only as a **bound**, because the two
were measured on different substrates and real requests do not issue their stats
serially against a cold cache.

Both figures are recorded in `docs/findings/E3-fargate-ephemeral.md` and labelled
as bounds. Neither is a measured page latency. Producing one requires an
end-to-end load test that this study has not yet run.
