# E2 — the storage matrix

**Status:** `BLOCK-BACKED GROUP COMPLETE` — server-backed group specced and costed,
not yet built.

> **Result:** [docs/findings/E2-block-backed.md](../../docs/findings/E2-block-backed.md).
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
- Prediction 3 is refuted if any server-backed tier reaches within one order of
  magnitude of the block-backed group on `stat` p50.
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

## Cost

Snapshot `results/pricing/20260910T155953Z-52175fd/` (on-demand list prices, `ap-southeast-1`,
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
| OpenZFS Single-AZ 1 | 64 GiB | 64 MBps | $0.0352 | $0.84 |
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
near the actual working set — and, at $0.035/hr, cheaper than the `c7gd.large`
carrying the benchmark.

### What the whole matrix costs to run

All four FSx arms simultaneously come to **~$0.96/hr**. With the compute arms and
endpoints, a full matrix run is on the order of **$1.50/hr**, and the protocol's
three replications are hours, not days.

**FSx is a teardown risk, not a run-cost risk.** $0.96/hr is $690/month if something
is left standing. Every FSx arm therefore deploys and destroys inside one `make`
target, tagged `Experiment=E2`, and no arm is created without its destroy path
tested first — the trap `CLAUDE.md` names is forgetting, not spending.
