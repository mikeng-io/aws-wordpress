# E2 — the storage matrix

**Status:** `SPECCED` — apparatus not yet written.

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

**`UNVERIFIED` — not yet costed per tier.** FSx and the JuiceFS/SeaweedFS control
planes are the expensive arms; FSx in particular is the trap flagged in
`CLAUDE.md`, since Lustre and ONTAP carry minimum-capacity floors that make the
cheapest possible deployment considerably more than an hourly rate suggests.

Per `CLAUDE.md`, nothing here deploys until this section holds real per-tier hourly
figures with a pricing snapshot date. Those come from a script in `analysis/` that
queries the pricing API, not from hand-typed numbers, so the table can be
regenerated rather than trusted.
