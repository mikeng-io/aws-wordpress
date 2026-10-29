# E4 — read-only task-start hydration removes this benchmark's EFS gap

**Formal result:** [`20261029T091909Z-842d596`](../../results/E4/20261029T091909Z-842d596/), three independent deployments.
**P1 SUPPORTED; P2 REFUTED; P3 SUPPORTED; H2 read-only kill-condition proxy MET.**
Grades are in [summary.json](../../results/E4/20261029T091909Z-842d596/summary.json), reproduced by
`python3 analysis/e4_stats.py results/E4/20261029T091909Z-842d596`. Predictions and thresholds remain
those registered before the smoke. No E2 campaign was rerun, no application or
plugin was changed, and H6 was not tested.

## Provenance and eligibility

| Field | Observed value |
|---|---|
| Run ID | `20261029T091909Z-842d596` |
| Apparatus `git_sha` | `842d596e8e36ba7381e6d109dc7ebd35aafc93f5` |
| `git_dirty` | `false` in every replication |
| Image digest | `sha256:f3606d18d7b5d18faa45da57c1e17857834c33e443a06606d98891fede8357dc` in all nine tasks |
| Region / AZ | `ap-southeast-1` / `ap-southeast-1a` (task JSON, all nine tasks) |
| Shape | Fargate 1.4.0, ARM64, 0.5 vCPU / 1 GiB, 20 GiB task ephemeral |
| Kernel | `6.1.188` (both arms' mount-facts.csv in every replication) |
| EFS | encrypted, one-zone, elastic throughput, general purpose; TLS mount |
| Stack | `E4-CacheAdapter-dev`, deployed and destroyed independently per replication |
| Pricing snapshot | `20261028T125335Z-5bb312a` (2026-10-28) |
| Samples | 1,000 `stat`, 1,000 `open_read`, 20 `stat_enoent` per arm per replication |

[Per-rep metadata/task records](../../results/E4/20261029T091909Z-842d596/) and
[campaign provenance](../../results/E4/20261029T091909Z-842d596/campaign-summary.json) retain the task/AZ/image evidence;
`meta.json` itself records the AZ only as “single-AZ (isolated subnet)”, so the exact
AZ above comes from the task records. Kernel and negotiated NFS options are in
`rep-*/{efs,hydrated}/mount-facts.csv`. The controlled variable is the read-serving
storage path. These are separate fresh tasks in the same AZ, not matched hardware.

The prescribed run from `3b8faf3`,
[`20261029T090427Z-3b8faf3`](../../results/E4/20261029T090427Z-3b8faf3/),
completed rep-1 but failed at rep-2 seed initialization: the new EFS DNS name did
not resolve. It is archived, incomplete, **ungraded and excluded** here. AWS
[documents this propagation race](https://docs.aws.amazon.com/efs/latest/ug/troubleshooting-efs-mounting.html).
Commit `913e08d` added an assertion that the mount target is available, then a
90-second wait before the seed task; `842d596` retained the failed-run logs.
The wait is apparatus readiness outside every measured task. Workload, image,
thresholds and measurement timing were unchanged. The new run began clean and
was not resumed from a partial run. The earlier interrupted formal and two
smoke attempts also remain outside this formal sample.

The host's `~/.nvm/nvm.sh` was absent. Collection used the official Node 22.17.0
Darwin ARM64 archive in `/tmp`, verified against its published SHA-256
`615dda58b5fb41fad2be43940b6398ca56554cbe05800953afadc724729cb09e`;
the `make e4` Docker/ECR wrapper remained in use
([toolchain receipt](../../results/E4/20261029T091909Z-842d596/toolchain.json)).

## Per-replication and pooled results

All ratios are hydrated/EFS ratios of medians, not ratios of geometric means.
CIs and distribution diagnostics for both arms are retained in the same summary.

| Rep | EFS stat p50 | Hydrated stat p50 | Ratio | EFS open_read p50 | Hydrated open_read p50 | Ratio |
|---|--:|--:|--:|--:|--:|--:|
| 1 | 1.5064 ms | 3.077 µs | 0.00204 | 2.8660 ms | 11.652 µs | 0.00407 |
| 2 | 1.3775 ms | 3.044 µs | 0.00221 | 2.8443 ms | 11.528 µs | 0.00405 |
| 3 | 1.1680 ms | 3.061 µs | 0.00262 | 2.3783 ms | 11.791 µs | 0.00496 |
| **pooled** | **1.3884 ms** | **3.061 µs** | **0.00220** | **2.7109 ms** | **11.667 µs** | **0.00430** |

P1's `stat` ≤0.10× and `open_read` ≤0.20× bars hold in every replication;
both conformance gates pass all 11 probes in every replication (P3 SUPPORTED).
“Read-only” describes the code-tree workload and absence of write-back: the
conformance instrument deliberately creates and mutates its own probe files.
It does not demonstrate enforcement of an immutable application tree.

### Distribution and between-replication spread

| Arm | Op | p50 CI95 | Geometric mean | p95 | p99 | IQR/p50 | p99/p50 | Rep p50 max/min | Cluster verdict |
|---|---|---|--:|--:|--:|--:|--:|--:|---|
| efs | `stat` | 1.3801 ms–1.3973 ms | 1.4099 ms | 1.7450 ms | 5.1062 ms | 0.188 | 3.678 | 1.290× | bimodal |
| efs | `stat_enoent` | 1.0339 ms–1.1514 ms | 1.0970 ms | 1.4660 ms | 1.6530 ms | 0.200 | 1.527 | 1.339× | unimodal |
| efs | `open_read` | 2.6919 ms–2.7267 ms | 2.6872 ms | 3.3372 ms | 4.0489 ms | 0.201 | 1.494 | 1.205× | unimodal |
| hydrated | `stat` | 3.052 µs–3.069 µs | 3.165 µs | 3.938 µs | 6.023 µs | 0.123 | 1.968 | 1.011× | unimodal |
| hydrated | `stat_enoent` | 7.089 µs–7.713 µs | 7.805 µs | 18.782 µs | 22.572 µs | 0.150 | 3.067 | 1.045× | unimodal |
| hydrated | `open_read` | 11.545 µs–11.782 µs | 11.916 µs | 17.075 µs | 21.555 µs | 0.283 | 1.848 | 1.023× | unimodal |

These CIs use distribution-free order statistics with the binomial-rank normal
approximation used elsewhere in the study. They describe within-run operations,
not a confidence interval over three deployments; serial/cache dependence can
make them overconfident. Per-replication distributions and clusters are also in
`summary.json`. Three deployments establish observed agreement, not broad
population precision. The 20 ENOENT samples per arm/rep are especially limited.

Clustering follows the protocol's deterministic log10 k-means with 10th/90th
initialization; a split needs ≥0.5 log10 centroid separation and ≥2% in each mode.
The following are the detected pooled modes; other rows above did not meet both gates.

| Arm/op | Fast share | Fast median | Slow median | Centroid separation |
|---|--:|--:|--:|--:|
| efs/stat | 97.43% | 1.3819 ms | 4.9634 ms | 3.6× |

**EFS cache-mode caveat:** a fresh client avoids inheriting seed-task cache state,
but it does not disable NFS caching within the benchmark. A pooled p50 can move
between attribute-cache hits and server-backed calls as the mode weights change,
as [E2 showed](E2-fuse.md). The grade is the registered p50 comparison, not proof
that an EFS server miss always costs that p50 or that production sees this ratio.
In this run, the EFS `stat` split is 97.43% at 1.382 ms versus 2.57% at
4.963 ms: both are millisecond-scale, so this is not E2's microsecond attribute-
cache-hit versus remote-miss split. It is a detected remote-latency tail whose
physical cause (server, network, proxy or scheduling) is not isolated. The
clustering gate passing alone cannot establish two different cache mechanisms.
All hydrated pooled distributions are unimodal under these gates. Fresh-client
first-touch timing still cannot predict the cache-mode mixture of a warm fleet.

## P2 is mechanically refuted

| Rep | Hydration bytes | Hydration seconds | EFS first-log→bench | Hydrated first-log→bench | Delta | P2 |
|---|--:|--:|--:|--:|--:|---|
| 1 | 27,412,480 | 0.217687 | 1.446 s | 1.497 s | 0.051 s | REFUTED |
| 2 | 27,412,480 | 0.443723 | 1.487 s | 1.679 s | 0.192 s | REFUTED |
| 3 | 27,412,480 | 0.429324 | 1.408 s | 1.673 s | 0.265 s | REFUTED |

Mechanical failures from the unchanged grader:

- rep-1: hydration 0.218s < 0.5s
- rep-1: start extra 0.051s < hydration 0.218s
- rep-2: hydration 0.444s < 0.5s
- rep-2: start extra 0.192s < hydration 0.444s
- rep-3: hydration 0.429s < 0.5s
- rep-3: start extra 0.265s < hydration 0.429s

Hydration spans **0.218–0.444 s** across deployments
(max/min 2.038×),
for the identical 27,412,480-byte tar. This measures `tar -xf` reading the mounted
EFS archive and writing/extracting locally, not a separate S3 download. It excludes
image pull, task scheduling, EFS mount setup and subsequent conformance probes.
The guessed 0.5-s bundle-size floor is not revised after observing a smaller cost.

“Start-to-benchmark” is the first application log timestamp to the `benchmarking`
line. It includes preflight and conformance work and log/scheduling variation;
it is neither ECS task creation nor first HTTP 200. In particular the EFS arm's
conformance probes involve remote writes. Therefore this difference does not
isolate hydration's causal overhead. P2's negative grade is published, not
repaired by subtracting conformance time or changing the floor. The grader's
human-readable rule now says start-to-benchmark, matching its existing computation
and pre-registration, rather than the stale “task duration” label; grades and
thresholds did not change.

## Break-even extrapolation and H2 scope

E0's warm workload has approximately 4,300 filesystem syscalls per request
([E0 n=10](E0-n10.md), raw [`results/E0/`](../../results/E0/)). Treating all of them
as serial `stat` calls at E4's p50 yields the registered proxy:

`one-request EFS penalty = 4300 × EFS stat p50`

`break-even requests = hydration seconds / [4300 × (EFS stat p50 − hydrated stat p50)]`

| Rep | EFS-only penalty proxy | Saving/request proxy | Break-even requests | H2 read-only proxy |
|---|--:|--:|--:|---|
| 1 | 6.4774 s | 6.4642 s | 0.03368 | MET |
| 2 | 5.9232 s | 5.9101 s | 0.07508 | MET |
| 3 | 5.0226 s | 5.0094 s | 0.08570 | MET |

This is **an extrapolation, not measured request latency or a bound on it**.
It assigns one p50 to a mix of syscall types, assumes sequential costs, and
ignores the application's warm NFS/opcache/page-cache mix, CPU and database work.
A fractional request means only that this proxy amortizes hydration within one
modeled request; it is not a request-level performance result. The apparent
saving would shrink if most production metadata checks were client-cache hits.

The conditional proxy is MET in all three replications: P1 holds, and hydration
costs less than 4,300 × EFS `stat` p50. This weakens H2's universal wording for
**the read-only code path only**. It does not settle the whole hypothesis or
operationally acceptable startup latency. There is no concurrent EC2 arm, full
application hydrate-and-serve design, mutable-state policy, refresh/invalidation,
propagation or fleet replacement measurement. H2's existing verdict is retained;
its original broader kill condition is not replaced with this proxy. H6 remains
UNTESTED. H4 receives measured startup-component evidence, while its ranking and
first-200-OK prediction remain untested.

## Cost and teardown evidence

The successful campaign's [cost proxy](../../results/E4/20261029T091909Z-842d596/campaign-summary.json) uses the
[committed pricing snapshot](../../results/pricing/20261028T125335Z-5bb312a/pricing.json):
ARM task shape US$0.024645/hour and interface endpoints
US$0.013/hour each. Task created-to-stopped durations
with a 60-second minimum sum to 603.015 seconds; this
conservative duration proxy costs US$0.004128. Reserving a full
hour for each of nine endpoints gives US$0.117,
for a **US$0.1211 task-plus-endpoint estimate**.
The full-hour reserve is a planning assumption, not a claim about billing granularity.

The [failed attempt's separate proxy](../../results/E4/20261029T090427Z-3b8faf3/campaign-summary.json)
is US$0.0797; together the two attempts' task-plus-endpoint
estimates are **US$0.2009**.
These are **not invoices or all-in actual costs**: EFS storage/elastic IO,
S3 requests/storage, log ingestion, endpoint data processing and shared CDK/ECR
asset storage are excluded. The successful campaign remains consistent with the
pre-run under-US$0.20 estimate; the retry adds cost separately. The combined
proxy leaves substantial headroom under the authorized US$2 ceiling, but final
billing has not been reconciled. No claim of a measured all-in spend is made.

[Collector log](../../results/E4/20261029T091909Z-842d596/collector.log) records destroy progression
and three `teardown verified: stack gone` checks.
[Independent verification](../../results/E4/20261029T091909Z-842d596/campaign-verification.json) retains three
`DELETE_COMPLETE` stack identities, all selected EFS/mount-target/endpoint/S3/VPC/
ECS/log resources `DELETE_COMPLETE`, each filesystem ID returning
`FileSystemNotFound`, and `describe-stacks` returning “does not exist”.
The failed attempt has its own equivalent verification. No E4 workload stack or
EFS filesystem from either attempt remains. Shared CDK bootstrap/ECR artifacts
are not workload stacks and are not claimed destroyed.

## Threats to validity

- One region/AZ, one task shape/architecture/kernel and three deployments within
  one short collection window; hardware placement and scheduling are not controlled.
- Synthetic 1,000-file tree and fixed traversal order, not a full WordPress install;
  a 27.4-MB tar does not represent every production code bundle or compressibility.
- Fresh-task EFS first reads versus an immediately extracted local tree; local
  page-cache warming is part of treatment, not an independently controlled device test.
- NFS cache modes and mode weighting can dominate p50. No forced cache-miss
  protocol or warmed/TTL-crossing steady-state cohort was added after the fact.
- First-log timing includes unrelated preflight/conformance and timestamp noise;
  it cannot establish full cold start or hydration's causal marginal delay.
- Conformance probes verify single-node filesystem semantics; not tree identity,
  concurrent writers, deployment invalidation, persistence or crash recovery.
- Operation-level CIs cannot substitute for uncertainty across deployments;
  syscall-to-request extrapolation is especially workload dependent.
- The failed initialization was a readiness failure and was excluded as a whole
  campaign; no successful replication from it was selected into the formal sample.

## Reproduce

```sh
# Collection deploys billable resources; requires a fresh authorization/ceiling.
# Use Node 22.17.0 and working AWS CLI v2.
REPS=3 make e4

# Analysis only, no AWS calls:
python3 analysis/e4_stats.py results/E4/20261029T091909Z-842d596
make e4-stats RUN=results/E4/20261029T091909Z-842d596
python3 analysis/e4_campaign.py results/E4/20261029T091909Z-842d596
```

Analysis may regenerate derived summaries; raw CSVs, logs, task records and
verification receipts are immutable. No threshold was fitted to the outcome.
