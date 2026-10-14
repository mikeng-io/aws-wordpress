# E2 — the storage matrix

**Status:** `BLOCK-BACKED GROUP + EFS MOUNT MATRIX COMPLETE` — FSx arms and the
prediction-1 throughput probe are built and locally tested, not yet run (see
[Run plan for the FSx arms](#run-plan-for-the-fsx-arms)).

> **Result:** [docs/findings/E2-block-backed.md](../../docs/findings/E2-block-backed.md)
> · [figures](../../docs/charts/e2-storage-matrix.html).
> Prediction 5 **failed**: instance store and Fargate ephemeral tied on every op,
> and EBS tied with them to within 3%. The device is irrelevant for this workload
> shape; the tier boundary is a protocol boundary. Block-backed → EFS is 638× on
> `stat`. E3's EFS bimodality replicated on independent hardware.

**Bears on:** [H1](../../hypotheses/H1-cache-locality.md) (which tier is reachable
decides performance), [H7](../../hypotheses/H7-cheapest-storage-loses.md) (cost at
equal performance).

> **Note on this number.** E2 formerly meant "placement differential: N tasks on
> one host vs N hosts." That question died when [E1](../E1-mount-topology/) showed
> ECS mounts EFS per task, so there is no shared client and no placement effect to
> detect. It produced no committed results, so the number was free to redefine —
> see [docs/scope-audit.md](../../docs/scope-audit.md).

## Question

For a metadata-heavy, filesystem-bound workload, what does each mountable storage
tier actually cost per operation — and which are even *available* on which compute
platform?

This is the core of the study. E0 established the demand (how many ops). E3
established one tier's cost. E2 fills in the rest of the row.

## Why this is the real subject

WordPress here is an instrument, not the subject. It is a widely-deployed,
unmodifiable, filesystem-bound application that generates a realistic and
reproducible metadata workload on demand. The subject is every application shaped
like it: bolting on object storage and a CDN relocates some traffic but leaves the
code path on the filesystem untouched.

So the question is not "which filesystem is fastest" in the abstract. It is which
tier can serve *this shape* of demand, on the compute platform you are actually
allowed to run.

## The matrix

Two groups, and the split is the mechanism. In the first, **the kernel owns the
filesystem** — a block device with a local ext4/xfs on top, so a `stat` that hits
the dentry cache never leaves the machine and a miss costs one device I/O. In the
second, **a server owns the filesystem** — every miss is a protocol round trip.
E3's ~271× is a measurement of that boundary, not of "SSD vs network".

### Block-backed (kernel owns the filesystem)

| Tier | What it physically is | Sharable across tasks | Size | Fargate? |
|---|---|---|---|---|
| **EC2 instance store** | NVMe SSD physically attached to the host | **yes — per host** | 118 GB on `*.large` | **no** |
| **EC2 EBS gp3** | network block device | yes — per host | as provisioned | no |
| **Fargate task ephemeral** | network-backed block device, per task | **no — per task** | 20 GiB default, 200 GiB max | yes |

### Server-backed (a server owns the filesystem)

| Tier | Mechanism | Fargate? | Notes |
|---|---|---|---|
| **EFS** | NFSv4.1 + TLS proxy | yes | Measured in E3: `stat` ~0.84 ms cache-aware. The incumbent. |
| **FSx for OpenZFS** | NFS | **no** | No Fargate support; EC2 / Managed Instances only. |
| **FSx for Lustre** | Lustre kernel client | **no** | EC2 only. Designed for throughput, not small-file metadata — that mismatch is the hypothesis. |
| **FSx for NetApp ONTAP** | NFS/SMB | **no** | EC2 only. |
| **JuiceFS** | FUSE; metadata engine (Redis/DB) + object storage for data | **no** | Needs `CAP_SYS_ADMIN`. Metadata is a *database*, not the object store, which is the whole point of testing it against a metadata-heavy load. |
| **SeaweedFS** | FUSE; own volume servers + filer, optionally S3-backed | **no** | Needs `CAP_SYS_ADMIN`. Different split from JuiceFS: its own storage layer rather than a metadata engine over S3. |
| **Mountpoint for S3** | FUSE over S3 | **no** | Needs `CAP_SYS_ADMIN`. Not POSIX-complete — no in-place writes, no rename. Expected to fail correctness before latency matters, which is a result, not a disqualification. |

**The availability column is itself a finding.** Everything Fargate cannot reach —
four FUSE tiers needing `CAP_SYS_ADMIN`, all three FSx tiers, and the entire
instance-store row — is removed by the *compute* choice, before performance is
discussed. That is H1's surviving claim stated as a table.

### Why the block-backed group is three rows and not one

E3 called its fast mount "local ephemeral" and measured `stat` at 3.1 µs. That name
was doing too much work. Per
[AWS's documentation](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/fargate-task-storage.html),
Fargate task ephemeral storage is a per-task, AES-256-encrypted volume of 20 GiB
(200 GiB max) — **it is not a physically attached disk.** E3's own finding noted
this and correctly reported only that it does not *behave* like a network
filesystem for metadata.

EC2 instance store is the row that separates the two explanations, because it *is*
physically attached: `c7gd.large` and `m7gd.large` each carry 1 × 118 GB NVMe SSD
rated 33,542 read / 16,771 write IOPS at 4 KiB
([compute](https://docs.aws.amazon.com/ec2/latest/instancetypes/co.html),
[general purpose](https://docs.aws.amazon.com/ec2/latest/instancetypes/gp.html)
specifications; `r7gd.large` follows the same 59 GB/vCPU sizing). If E3's 3.1 µs was
the kernel's dentry cache, instance store will tie it. If it was the device,
instance store will beat it.

**Sharing is the other axis, and it is the one that matters for [E4](../E4-cache-adapter/).**
Instance store is a host resource: every task on the instance can be given the same
path, so one hydration serves all of them. Fargate ephemeral cannot be shared by
construction — it is per task, which is the same shape [E1](../E1-mount-topology/)
found for EFS mounts. 118 GB shared per host against 20 GiB private per task is not
a tuning difference; it decides whether a cache tier is buildable at all.

## Predictions

Pre-registered, per the [protocol](../../docs/benchmark-protocol.md):

1. **Metadata latency, not throughput, separates the tiers.** Ranking by `stat`
   p50 will differ substantially from ranking by bulk-read throughput. Any tier
   marketed on throughput (Lustre especially) will rank worse on this workload
   than its headline numbers suggest.
2. **JuiceFS beats EFS on metadata** by a wide margin when its metadata engine is
   in-memory (Redis), because a metadata lookup becomes a database query on a warm
   cache rather than an NFS round trip — and will still lose to local ephemeral.
3. **No server-backed tier reaches the block-backed group's ~3 µs.** The floor for
   anything crossing a network is bounded by RTT, and E3 measured 3.1 µs with a
   1.5× tail.
4. **Mountpoint for S3 fails the correctness suite**, not the latency test.
5. **Within the block-backed group, the split is by operation, not by tier.**
   Instance store and Fargate ephemeral will be statistically indistinguishable on
   `stat` p50 — both are answered by the kernel's dentry cache and never reach a
   device — while instance store wins measurably on the device-touching ops E3
   already recorded: `create` (38.2 µs), `unlink` (19.7 µs), and cold `open+read`
   (local p99 711 µs against a p50 of 11.3 µs). This is the sharpest prediction in
   the set because it is *differential*: the same pair of tiers must tie on one op
   and separate on another. A uniform win for either tier refutes it, and a uniform
   win for instance store would mean E3's headline was a device result rather than
   a metadata-path result.

## Kill conditions

- Prediction 1 is refuted if metadata and throughput rankings substantially agree.
  "Substantially agree" was not decidable as first written. It is made numeric in
  [Prediction 1: the throughput measurement](#prediction-1-the-throughput-measurement),
  fixed 2026-10-15, before any FSx or throughput data exists.
- Prediction 3 is refuted if any server-backed tier reaches within one order of
  magnitude of the block-backed group on `stat` p50. Made exact on the same date:
  the block-backed group's `stat` p50 is the median of the three block tiers' pooled
  p50s, and a server-backed tier (every EFS configuration and every FSx tier) refutes
  it if its pooled `stat` p50 is less than 10× that value.
- Prediction 5 is refuted by any uniform ranking across ops within the block-backed
  group — either tier winning everything.
- The premise of the whole matrix is refuted if all tiers land within ~2× of each
  other, which would mean storage choice is not the lever this study assumes.

## Method

Same instrument as E3 (`bench.c`): per-syscall timing via
`clock_gettime(CLOCK_MONOTONIC)` on a deterministic tree shaped like E0's measured
plugin-file profile. Reusing E3's benchmark unchanged is deliberate — it makes
every tier directly comparable to the two already measured.

**Correctness gate first, per [H6](../../hypotheses/H6-writeback-cannot-be-correct.md).**
A tier that cannot hold POSIX semantics is not eligible for a latency number:
cross-node `flock`, atomic rename, close-to-open consistency, `fsync` durability,
concurrent same-file writes. A fast filesystem that loses a write is disqualified,
and reporting its latency alongside correct ones would be misleading.

**Replication:** ≥3 independent deployments per tier, per protocol.

## Method note: instance store is not mounted for you

Unlike EBS, an instance-store NVMe device arrives raw. Amazon Linux 2023 does not
partition, format, or mount it, so the ASG user data has to do it before the ECS
agent starts, and the ECS task needs a bind mount to the host path. That is
apparatus work, not a footnote, and it is the reason this row costs more to build
than its price delta suggests.

The `d` variants also carry a price premium over their storeless siblings, so the
instance-store row is not free even before the engineering. That premium is
`UNVERIFIED` here — the pricing API was unreachable when this was written — and
lands in the cost table below rather than being guessed at.

## Method decisions for the FSx arms

Fixed before the run. These are *method*, not new predictions — predictions 1 and 3
already cover FSx and are unchanged.

- **Mount options are held identical to the EFS arms** wherever the protocol allows:
  `nfsvers=4.1,rsize=1048576,wsize=1048576,hard,timeo=600,retrans=2,noresvport`. If
  the tiers were tuned differently the comparison would measure tuning rather than
  protocol, which is the confound this whole experiment exists to avoid.
- **Lustre arm is Scratch 2**, not Persistent-2. It is the throughput-marketed
  configuration prediction 1 names explicitly, and the cheaper of the two.
- **Lustre is mounted `-o flock`.** POSIX locking is off by default on Lustre, and
  without the option `flock(2)` silently succeeds while excluding nobody. Mounting
  with it measures the sane production configuration; the default is noted here
  because "the default does not lock" is itself worth knowing.
- **OpenZFS exports `no_root_squash`.** The benchmark container runs as root and
  would otherwise be squashed to `nobody`, turning every write into a permission
  error that looks like a filesystem defect.
- **ONTAP is first-generation Single-AZ**, whose throughput floor is 128 MBps
  against second-generation's 384 — the cheaper arm for an identical measurement.
- **The ONTAP NFS endpoint is queried from the API at boot**, not assembled from
  resource ids. A mis-built DNS name fails as a mount timeout rather than an error,
  which is expensive to diagnose and easy to misread as the tier being slow.

### Configuration cross-checked against official AWS guidance

Every FSx arm was re-checked against AWS's own documentation rather than left at
whatever the API default produced. What changed, and what deliberately did not:

| Setting | Decision | Why |
|---|---|---|
| Lustre `fileSystemTypeVersion` | **2.15**, explicit | API default for SCRATCH_2 is 2.10, which AL2023's 2.15-only client cannot mount |
| OpenZFS `throughputCapacity` | **128 MBps**, not the 64 floor | Provisioned throughput sizes the file server's in-memory *metadata* cache, and AWS recommends ≥128 MBps for metadata-intensive workloads |
| OpenZFS `dataCompressionType` | **NONE**, pinned | An inherited default differing between tiers would be measured as a property of the filesystem |
| OpenZFS export `sync` | left at default | `async` acknowledges writes before durability — a different guarantee, not a faster filesystem |
| ONTAP `snapshotPolicy` | **none** | The default takes hourly/daily/weekly snapshots; background I/O during a latency run surfaces as unattributable tail latency |
| ONTAP `storageEfficiencyEnabled` | **false** | Dedup/compression would be measured instead of the filesystem |
| NFS version | **4.1 everywhere** | AWS's OpenZFS example uses 4.2 and its ONTAP example 4.1; holding one version across all NFS arms keeps EFS usable as the common ruler. Comparability beats per-tier optimisation in a comparison study. |

**`noresvport` is dropped on FSx and kept on EFS**, and that asymmetry is forced
rather than chosen: it is an EFS-specific recommendation (EFS ignores source ports),
and OpenZFS rejects it outright by enforcing the standard reserved-port export
default. It selects a source port and does not touch the data path.

**One documented cap deliberately *not* acted on.** OpenZFS at 64/128 MBps caps
`rsize` at 256/512 KiB rather than the 1 MiB requested. It cannot bind here —
`bench.c` writes files of 2–50 KB, five times under even the lowest cap — so raising
throughput to "fix" `rsize` would have been cargo-cult. The throughput change above
is for the metadata cache, which is a different mechanism.

**Two things the docs do not settle, so they are measured instead.** The negotiated
(not requested) mount options are recorded per tier to `mount-facts.csv` in every
run, because a client can ask for 1 MiB and be silently given 256 KiB. And the
conformance gate now includes `root_not_squashed`: OpenZFS's documented default is
`root_squash` and this study overrides it, while FSx ONTAP's default `superuser`
setting is not documented by AWS anywhere findable. If one tier squashes root and
another does not, the arms run as different users and every write is compared across
different permission paths — so it is checked per tier rather than assumed.

### The conformance gate, and what it is scoped to

`analysis`-adjacent apparatus now exists (`infra/lib/stacks/bench/conformance.sh`)
and runs on every mount **before any timing**, per H6. Ten checks, chosen for what
actually breaks on object-store-backed FUSE rather than for coverage: rename over an
existing file, in-place write at an offset, append, truncate, `fsync`, hardlink,
symlink, directory rename, an `flock` that genuinely excludes a second holder, and
`mtime` advancing on write — the last because opcache revalidation is a
stat-and-compare-`mtime`, so a filesystem that does not move it serves stale
bytecode silently.

It is the **single-node** gate and says so. Cross-node consistency — two hosts, one
file, close-to-open ordering — needs a second instance and belongs to H6/E4.
Conflating the two would let a tier fail here for a reason unrelated to whether it
earns a latency number.

`PASS` / `FAIL` / `ERROR` are kept distinct and an `ERROR` is never counted as a
`PASS`: `FAIL` is a verdict about the tier, `ERROR` means the check could not be
performed and says nothing about the filesystem. A failure does not abort the run —
for Mountpoint-S3 the failure *is* the pre-registered result.

## Prediction 1: the throughput measurement

Fixed 2026-10-15, before any throughput or FSx data exists. Until this date
`bench.c` measured only per-operation latency on 2–50 KB files, so the second
ranking prediction 1 compares against did not exist, and the prediction could not
be graded. The alternative was to mark it not evaluable, which would have dropped a
pre-registered test because the apparatus could not run it. The study's central
claim is "metadata latency, not throughput, separates the tiers", and that cannot be
argued without measuring throughput. So it is measured.

One caveat is stated up front because it cannot be fixed. The `stat` p50 of the
three block-backed tiers is already known from the 2026-09-10 runs, and their
throughput is not. The thresholds below were set with that half of the data in view,
and with nothing at all known about FSx.

### Probe

`tput` (`infra/lib/stacks/bench/tput.c`) runs once per tier, after the latency
benchmark, in the same task and the same shuffled order:

1. **Write:** 4 threads each write one 1 GiB file with 1 MiB `write(2)` calls,
   then `fsync` and close. 4 GiB total, timed as the 4-stream write.
2. **Two read phases, in an order shuffled per tier and recorded:**
   - **1-stream:** one thread reads all four files in sequence.
   - **4-stream:** four threads each read one file.
   Both use buffered 1 MiB `read(2)`, which is what an application gets.
3. **Before each read phase,** `posix_fadvise(POSIX_FADV_DONTNEED)` is applied to
   every file, and then `mincore(2)` measures how much of each file is still
   resident in the client page cache. A phase that starts with more than 1%
   resident is recorded with its residency and reported as `ERROR`. That phase
   measured RAM, not the tier, and an `ERROR` is never ranked.
4. The files are deleted.

Throughput is bytes divided by wall time, from the release of a start barrier to
the last thread finishing. **The graded metric is 4-stream read MB/s.** 1-stream
read and 4-stream write are reported but not graded.

### Decisions, and why

- **Eviction is verified, not inferred from file size.** The usual trick of a file
  twice the size of RAM assumes the cache behaves. `mincore` checks whether it did,
  which turns a silent confound into an `ERROR`.
- **Server-side caches are not controlled.** OpenZFS's ARC, ONTAP's buffer cache
  and Lustre's OSS cache are part of the tier as sold, and the client cannot evict
  them. A read straight after a write may be partly served from them, and that is
  stated as part of what the number means.
- **4 GiB is a transfer, not a sustained load.** It is media-file scale for a
  WordPress estate. OpenZFS and ONTAP at 128 MBps, and Lustre Scratch, may serve
  part of it from burst credit. The ranking is "what a 4 GiB transfer sees", not
  the tier's sustained ceiling.
- **The FSx results are mostly the provisioned cap.** OpenZFS and ONTAP are bought
  at 128 MBps, so their throughput result will be close to that number. The
  ranking compares tiers as configured at their cheapest defensible settings, not
  each tier's best.
- **One EFS configuration, not six.** `ec2/efs_host_plain` is measured because it
  uses the same client path as the FSx tiers: mounted on the host, no TLS,
  bind-mounted into the container. The 2026-09-10 runs showed mount topology and
  TLS do not move `stat` ([finding](../../docs/findings/E2-block-backed.md)).
  Measuring throughput on all six would multiply EFS's per-GB transfer charge for
  no question this study asks.
- **4 streams, not more.** `c7gd.large` has 2 vCPUs. Four streams is enough to show
  whether a tier scales with parallelism without making the client the
  bottleneck.

### Tiers ranked, and the grading rule

Seven tiers, one ranking each: `ec2/instance_store`, `ec2/ebs`, `fargate/ephemeral`,
`ec2/efs_host_plain`, `ec2/fsx_openzfs`, `ec2/fsx_lustre`, `ec2/fsx_ontap`.

For each replication, compute Spearman's ρ between rank by `stat` p50 (fastest =
1) and rank by 4-stream read MB/s (highest = 1). Ties take average ranks. A
positive ρ means the two rankings agree.

| Per-replication ρ | Reading |
|---|---|
| ≥ 0.7 | AGREE |
| ≤ 0.3 | DIFFER |
| between | INCONCLUSIVE |

- **Prediction 1 is SUPPORTED** if every evaluable replication reads DIFFER.
- **It is REFUTED** if every evaluable replication reads AGREE.
- **Otherwise it is INCONCLUSIVE.**
- **It is NOT EVALUABLE** if fewer than three replications are evaluable. A
  replication is not evaluable if any of the seven tiers has an `ERROR` read.

With n = 7, ρ ≥ 0.7 is close to the conventional significance bound (0.786 at
p < 0.05, one-tailed). The thresholds are a judgement about "substantially", fixed
here, and not a significance test.

**The Lustre clause** ("ranks worse on this workload than its headline numbers
suggest") is graded on its own. It is supported if Lustre's `stat` rank is at least
two places worse than its throughput rank in every evaluable replication. It is
refuted if Lustre's `stat` rank is the same as or better than its throughput rank
in every evaluable replication. Anything else is inconclusive.

## Cost

Snapshot `results/pricing/20260918T080950Z-c94ac10/` (on-demand list prices, `ap-southeast-1`,
regenerate with `make pricing`). No savings plans, no reserved capacity, no free
tier. Every priced row in that snapshot carries its own `location` field, and the
generator refuses any product not in `Asia Pacific (Singapore)` — so the region is
verifiable from the artifact rather than asserted by this sentence. These are apparatus costs for running the matrix, not a cost model of
production — that is [H7](../../hypotheses/H7-cheapest-storage-loses.md)'s job.

### Compute arms

| Instance | vCPU / mem | Instance store | $/hr | Premium |
|---|---|---|--:|--:|
| `t4g.small` | 2 / 2 GiB | — | $0.0212 | — |
| `c7g.large` | 2 / 4 GiB | — | $0.0833 | — |
| `c7gd.large` | 2 / 4 GiB | 1 × 118 GB NVMe | $0.1058 | **+27.0%** |
| `m7g.large` | 2 / 8 GiB | — | $0.1020 | — |
| `m7gd.large` | 2 / 8 GiB | 1 × 118 GB NVMe | $0.1332 | **+30.6%** |
| `r7g.large` | 2 / 16 GiB | — | $0.1292 | — |
| `r7gd.large` | 2 / 16 GiB | 1 × 118 GB NVMe | $0.1644 | **+27.2%** |

The instance-store premium is **~27–31%**, not the single-digit rounding error it
is often assumed to be. That is a real number the cache-adapter argument has to
clear.

### Fargate, at the same shape

| Line item | Rate |
|---|--:|
| vCPU (ARM) | $0.040450 / vCPU-hr |
| Memory (ARM) | $0.004420 / GB-hr |
| Ephemeral storage above the included 20 GiB | $0.000133 / GB-hr |

A 2 vCPU / 4 GiB ARM task is **$0.0986/hr** against `c7g.large`'s $0.0833 for the
same shape — Fargate costs **18% more** before any storage is attached.

### The cache-capacity comparison, which is E4's actual economics

| | EC2 instance store | Fargate ephemeral |
|---|---|---|
| 118 GB costs | **+$0.0225/hr, flat** | **+$0.0130/hr, per task** |
| shared across tasks on the host | yes | no |
| included free | none | first 20 GiB |
| crossover | \-- | **1.73 tasks/host** |

Two readings, and they disagree, which is why this belongs in a measured
experiment rather than an argument:

- **At 2+ tasks per host, instance store is cheaper** for the same cache capacity,
  and it also amortises hydration once per host instead of once per task.
- **But if the working set fits in 20 GiB, Fargate's ephemeral cache is free**, and
  the instance-store premium is +27% for capacity nobody needed. A WordPress code
  tree is single-digit GB, so this is the likely case rather than the edge case.

So the honest current position is that the cost argument favours Fargate and the
amortisation argument favours EC2, and which one dominates is an empirical question
about hydration cost — [H4](../../hypotheses/H4-cold-start-is-the-metric.md), and
the reason it is a gate on E4 rather than a footnote.

### Storage tiers

EFS is known from the E1/E3 runs: elastic throughput, near-zero at benchmark
volumes — $0.04/GB read, $0.07/GB write, plus storage.

FSx cost is **not** driven by its per-GB rate. It is driven by minimum provisioned
capacity and throughput floors that differ per file-system type and generation, and
that the Pricing API does not express. Those floors are declared in
`analysis/aws_pricing.py` with the documentation that fixes each one, and the hourly
figure is computed from the snapshot's own rates:

| FSx arm | Minimum capacity | Minimum throughput | $/hr | $/day |
|---|--:|--:|--:|--:|
| OpenZFS Single-AZ 1 | 64 GiB | 128 MBps | $0.0608 | $1.46 |
| Lustre Scratch (SSD) | 1200 GiB | bundled | $0.2762 | $6.63 |
| Lustre Persistent-2 (125 MB/s/TiB) | 1200 GiB | bundled | $0.2910 | $6.98 |
| ONTAP Single-AZ gen-1 | 1024 GiB | 128 MBps | $0.3559 | $8.54 |

Each is the cheapest *defensible* configuration: Single-AZ throughout, since this is
apparatus rather than production and replication would only add cost without
changing what is being measured; first-generation ONTAP because its throughput floor
is 128 MBps against second-generation's 384.

**The floors bite on capacity, not on price.** Lustre cannot be provisioned below
1200 GiB and ONTAP below 1024 GiB, so both arms must rent roughly a terabyte to
benchmark a working set of a few gigabytes. That is a distortion worth stating
plainly in any writeup: the metadata numbers are measured on a file system far
larger than the workload needs, because no smaller one can be bought.

OpenZFS is the outlier at 64 GiB, which makes it the only FSx arm that can be sized
near the actual working set. At the 128 MBps chosen above it costs $0.0608/hr, still
cheaper than the `c7gd.large` carrying the benchmark. (An earlier draft of this
section said $0.035/hr; that was the 64 MBps floor, before the throughput decision.)

### What the whole matrix costs to run

Three FSx arms are built, not four: Persistent-2 Lustre is costed above for
comparison only. From the same snapshot, the standing cost of one deployment is:

| Line item | $/hr |
|---|--:|
| `c7gd.large` | 0.1058 |
| 12 interface endpoints × 1 AZ × $0.013 | 0.1560 |
| FSx OpenZFS + Lustre Scratch + ONTAP gen-1 | 0.6929 |
| EFS, S3, CloudWatch Logs at benchmark volumes | ~0 |
| **Standing total** | **~0.955** |

The Fargate task adds ~$0.05/hr only while it runs, which is minutes. An earlier
version of this section said ~$0.98/hr for FSx alone and ~$1.50/hr in total. Both
counted a fourth FSx arm that was never built, and both are superseded by this table.

**FSx is a teardown risk, not a run-cost risk.** ~$0.955/hr is ~$700/month if the
stack is left standing, and ~$506/month of that is FSx alone. A leaked FSx final
backup bills separately, and no stack destroy will catch it.

## Run plan for the FSx arms

Written 2026-10-15, before any FSx replication has completed. Durations are
`UNVERIFIED` estimates until replication 1 measures them.

### Budget

| | Estimate |
|---|---|
| One replication (deploy → latency → throughput → destroy → sweep) | 70–100 min, `UNVERIFIED`. Block-only replications took 10–14 min. FSx creation and deletion are most of the rest, with ONTAP slowest, and the throughput probe adds ~10 min (4 GiB written and read twice per tier, ~1.5 min per tier at 128 MBps). |
| EFS transfer from the probe | 4 GiB written + 8 GiB read per replication ≈ $0.60 at $0.07/$0.04 per GB |
| Three replications | ~3.5–5 h at ~$0.955/hr, plus ~$1.80 of EFS transfer → **~$5–7** |
| Hard ceiling for this run | **$12**. Past that, stop and diagnose rather than retry. |

### Blockers before the first deploy: status

All seven were fixed on 2026-10-15. They are not yet committed, and none has been
exercised against real FSx. The first real test is replication 1.

1. **Teardown trap installed after deploy: FIXED.** `collect.sh` installs the
   `destroy` trap *before* `cdk deploy`, so a failed or rolled-back deploy is torn
   down and swept. Checked: a failing step followed by a clean teardown still
   exits non-zero, so `make e2` cannot report success for a failed deploy. The
   teardown verdict is whether the stack still exists afterwards, not `cdk
   destroy`'s exit code.
2. **Region-wide backup sweep: FIXED.** A backup is swept only if its source file
   system or volume ID came from this stack, or it carries
   `Study=aws-wordpress` + `Experiment=E2`. The IDs come from the stack's resource
   list and from its event history, so a rolled-back stack still yields them. The
   stack now sets `CopyTagsToBackups` on the OpenZFS file system and the ONTAP
   volume; both are confirmed in the synthesized template. Checked against a mocked
   account holding a foreign backup: matches by file system, by volume, by
   rolled-back ID, and by tag were deleted, and the foreign backup was never touched.
3. **Unverified sweep: FIXED.** The sweep polls until no matching backup exists,
   and requires seeing that twice, 60 s apart. It waits out `CREATING`, and after
   40 minutes it exits 3 and names every backup still billing. Checked against a
   mocked backup stuck in `CREATING`: exit 3, ID printed.
4. **Broken `aws` on PATH: FIXED.** `collect.sh` and `make doctor` both use the
   first `aws` on PATH that reports `aws-cli/2`, and refuse to start if there is
   none. Checked: on this machine they skip the broken v1 and resolve to
   `/usr/local/bin/aws`. `collect.sh` also refuses to run on a dirty tree, or if
   `E2-StorageMatrix-dev` already exists (an unknown leftover). The dirty-tree
   refusal was checked live and stopped before any AWS call.
5. **Provenance gaps: FIXED.** `meta.json` now records the image digest for each
   arm (from `describe-tasks`), the FSx source IDs, the CDK CLI version, the
   `aws-cdk-lib` version and the AWS CLI version. `fsx-provenance.json` records
   `describe-file-systems` for the run's file systems, as built.
6. **Prediction 1 ungradable: FIXED by measuring, not by dropping it.** See
   [Prediction 1: the throughput measurement](#prediction-1-the-throughput-measurement).
   The probe (`tput.c`, installed as `throughput`) was run in the real image:
   - After eviction, residency read 0%.
   - With eviction skipped (`TPUT_SKIP_EVICT`, test-only), it read 100% and the
     reads ran about twice as fast. The guard can fire, and it matters.
   - On tmpfs it reads 100%, because tmpfs *is* RAM. A tier like that grades as
     `ERROR`, not as fast.
   - A probe failure becomes an error row and the run continues.
7. **FSx comparisons not pre-registered: FIXED.** `e2_stats.py` declares four FSx
   pairs (OpenZFS, ONTAP and Lustre against `efs_host_plain`, and OpenZFS against
   ONTAP), and grades predictions 1 and 3 by the rules above.
   - Regression-checked on copies of both committed runs: every existing output is
     identical.
   - Synthetic runs reach every outcome: SUPPORTED, REFUTED, and NOT EVALUABLE on a
     cache-resident read and on a probe error.

The stale hourly figures in the `Makefile` and `apparatus.ts` are corrected to
~$0.96/hr.

### Pre-flight, immediately before deploying

- Working tree clean. `collect.sh` now refuses otherwise.
- **Node 22.17.0 is not installed** on this machine (`nvm` has 14, 16 and 18; the
  active Node is 26.8.1). Install it and run `nvm use`, or deploy from a
  `node:22.17.0` container. `make doctor` must pass. Typecheck and synth of E2 and
  E3 were verified under Node 22.17.0 in a container (`node:22.17.0-slim`, fresh
  `npm ci` from the lockfile) on 2026-10-15.
- Credentials come from `.env`: account `163703054402`, user `aws-wordpress`.
- Baseline is clean: no stack `E2-StorageMatrix-dev`, no FSx file systems, no FSx
  backups, nothing tagged `Study=aws-wordpress` beyond inactive task definitions.
  Last verified clean 2026-10-15, all 18 regions. Record it again on the day.
- `make pricing` refreshes the snapshot.
- The machine stays awake for the whole run (`caffeinate -i`), and the run is
  launched in a way that survives the terminal closing. If the laptop sleeps
  mid-replication, the stack stays up with nothing tearing it down.

### Run order

1. **`make e2 REPS=3`.** Each replication is an independent deploy → EC2 arm (block,
   EFS and FSx tiers, run in randomized order) → Fargate arm → collect → destroy →
   scoped sweep. Replication 1 doubles as the smoke test. A failed mount, a missing
   conformance CSV, or a missing `mount-facts.csv` stops the run and tears it down.
   That failure is a result about the apparatus, and the run is not retried around it.
2. **After replication 1 completes, check before letting 2 and 3 count.** Per tier,
   `mount-facts.csv` shows the negotiated `rsize`/`wsize`, NFS version, Lustre
   `flock`, and whether OpenZFS granted a delegation. The conformance CSV shows
   `PASS` on all ten checks, or a `FAIL` that is itself the finding. Also check
   whether the FSx final backups carried the tags (blocker 2). Each throughput
   tier must have both read phases starting at ≤1% residency. Record the measured
   replication duration in this README.
3. **If anything in step 2 is wrong,** stop. Replications 2 and 3 have not cost
   anything yet, and a run with a known confound is not worth finishing.

### Teardown, and how it is verified

Teardown is not done until a check, other than `cdk destroy`'s exit code, shows it.

- After every replication: `cdk destroy`, then a scoped backup sweep that polls to
  zero.
- After the run, sweeping every region: no stack `E2-StorageMatrix-dev`; no FSx
  file systems; no FSx backups from this stack; nothing tagged `Study=aws-wordpress`
  except inactive task definitions. The tagging index still lists deleted FSx SVMs,
  so an SVM is confirmed against `describe-storage-virtual-machines` before it is
  counted as live.
- The result of that sweep is recorded here with its timestamp.
- Backstop for an interrupted run: anything still standing is billing at ~$0.955/hr,
  and `make e2` resumes nothing. Recovery is `cdk destroy E2-StorageMatrix-dev`
  followed by the scoped sweep, run by hand.

### After the run

Extend `e2_chart.py` and `e2_stats.py` with the FSx tiers, then grade predictions 3
and (if it is evaluable) 1 against the pre-registered thresholds, publish
`docs/findings/`, and update H1 and H7. A verdict change cites the run directory.
