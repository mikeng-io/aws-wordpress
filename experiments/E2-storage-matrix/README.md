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

| Tier | Mechanism | Fargate? | Notes |
|---|---|---|---|
| **local ephemeral** | task-local disk | yes | Reference tier. Measured in E3: `stat` 3.1 µs, local-disk tail. Not durable, not shared — the baseline everything else is judged against. |
| **EFS** | NFSv4.1 + TLS proxy | yes | Measured in E3: `stat` ~0.84 ms cache-aware. The incumbent. |
| **FSx for OpenZFS** | NFS | **no** | No Fargate support; EC2/Managed Instances only. |
| **FSx for Lustre** | Lustre client | **no** | Kernel client; EC2 only. Designed for throughput, not small-file metadata — that mismatch is the hypothesis. |
| **FSx for NetApp ONTAP** | NFS/SMB | **no** | EC2 only. |
| **JuiceFS** | FUSE; metadata engine (Redis/DB) + object storage for data | **no** | Needs `CAP_SYS_ADMIN` → EC2 or ECS Managed Instances. Metadata is a *database*, not the object store, which is the whole point of testing it against a metadata-heavy load. |
| **SeaweedFS** | FUSE; own volume servers + filer, optionally S3-backed | **no** | Needs `CAP_SYS_ADMIN`. Different split from JuiceFS: its own storage layer rather than a metadata engine over S3. |
| **Mountpoint for S3** | FUSE over S3 | **no** | Needs `CAP_SYS_ADMIN`. Not POSIX-complete — no in-place writes, no rename. Expected to fail correctness before latency matters, which is a result, not a disqualification. |

**The availability column is itself a finding.** Four of these need FUSE, which
needs `CAP_SYS_ADMIN`, which Fargate does not grant. So the compute platform
silently removes most of the matrix before performance is even discussed — which is
H1's surviving claim stated as a table.

## Predictions

Pre-registered, per the [protocol](../../docs/benchmark-protocol.md):

1. **Metadata latency, not throughput, separates the tiers.** Ranking by `stat`
   p50 will differ substantially from ranking by bulk-read throughput. Any tier
   marketed on throughput (Lustre especially) will rank worse on this workload
   than its headline numbers suggest.
2. **JuiceFS beats EFS on metadata** by a wide margin when its metadata engine is
   in-memory (Redis), because a metadata lookup becomes a database query on a warm
   cache rather than an NFS round trip — and will still lose to local ephemeral.
3. **No network tier reaches local ephemeral's ~3 µs.** The floor for anything
   crossing a network is bounded by RTT, and E3 measured local at 3.1 µs with a
   1.5× tail.
4. **Mountpoint for S3 fails the correctness suite**, not the latency test.

## Kill conditions

- Prediction 1 is refuted if metadata and throughput rankings substantially agree.
- Prediction 3 is refuted if any network-backed tier reaches within one order of
  magnitude of local ephemeral on `stat` p50.
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

## Cost

Not yet estimated per tier. FSx and the JuiceFS/SeaweedFS control planes are the
expensive arms and will be costed and declared before anything is deployed. FSx in
particular is the trap flagged in `CLAUDE.md`.
