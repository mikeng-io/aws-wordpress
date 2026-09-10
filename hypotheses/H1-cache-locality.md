# H1 — Tier reachability dominates, not filesystem choice

**Status:** `MECHANISM REFUTED, CLAIM REFRAMED — SUPPORTED` — see E1, E2, and the rewrite below

> **Rewritten** after E1 and E3. The original claim was that co-located tasks share
> a warm NFS cache, so *placement* determines performance. E1 refuted that
> mechanism outright: ECS mounts EFS per task, with an independent NFS client and
> TLS proxy each, so there is nothing to share. The original text is kept below the
> rewrite as the audit record.

## The claim, restated

Performance is set by **which storage tier the compute platform lets you reach**,
not by which filesystem you choose among the tiers it permits, and not by where
tasks are placed.

Three measurements now support this shape:

- **The demand is fixed.** E0: ~3,900 `stat` per warm request, irreducible by
  `php.ini` because the floor is plugin code.
- **The per-op cost is a tier property.** E3: 3.1 µs local vs 0.84 ms EFS, ~271×,
  measured on the same task at the same moment.
- **You cannot share your way out of it.** E1: per-task mounts, no shared cache.
- **And you cannot buy your way out of it either.** E2: attached NVMe, network EBS
  and Fargate's ephemeral volume are all within 1.5× of each other, while EFS is
  638× away on `stat`. The boundary is whether the kernel or a server owns the
  filesystem — not how fast the disk is.

So the product of a fixed count and a tier-determined cost is the whole story, and
the only lever that moves it is which tier serves the ops.

**The platform decides that before performance is discussed.** Four of the tiers in
E2's matrix need FUSE, which needs `CAP_SYS_ADMIN`, which Fargate does not grant.
That is the claim's sharpest form: choosing Fargate removes most of the storage
matrix, silently, as a capability constraint rather than a performance one.

## Kill condition, restated

Refuted if E2's matrix shows tiers landing within ~2× of each other on
metadata latency — which would mean tier choice is not the dominant lever and
something else (the application, the network path, the instance) is.

---

## Original claim, retained as the audit record

### Claim

For WordPress, shared-filesystem performance is determined by *where metadata and
page caches are permitted to live*, not by which filesystem is mounted. The compute
platform decides which cache tiers are reachable, and therefore silently decides
storage performance.

### Why it would matter

If true, the entire "which filesystem is fastest for WordPress" genre is asking the
wrong question, and the correct question is "which compute platform lets me cache,
and what does that permit downstream."

### Mechanism proposed

NFS is a chatty request/response protocol. Cost is approximately
`(number of metadata ops) x (round-trip latency)`. WordPress issues a large number
of metadata ops per request. The only cure is caching ops closer to the compute.
Candidate cache tiers, in order of proximity:

1. NFS attribute cache and kernel page cache, shared per host across co-located tasks
2. Kernel readahead (`read_ahead_kb`), a host sysctl
3. Explicit local NVMe cache (requires FUSE, requires `CAP_SYS_ADMIN`)
4. No shared filesystem at all (image-baked code)

### Prediction

The **placement differential** — N identical tasks against one identical EFS
filesystem, run once as N tasks on 1 host and once as N tasks on N hosts — will show
a materially lower per-request metadata cost in the co-located arrangement, because
tasks 2..N are served from a cache task 1 warmed.

Magnitude is deliberately not predicted. Direction and significance are.

### Kill condition

**H1 is refuted if** the placement differential shows no statistically significant
gap (overlapping confidence intervals across repeated, order-randomised runs).

If refuted, H2 and much of the storage matrix lose their motivation, and the study
should be re-scoped early rather than late.

### Dependency that could invalidate the test

The mechanism assumes co-located ECS tasks on EC2 **share one NFS client**, and
therefore one attribute cache. If the ECS agent mounts EFS once per *task* rather
than once per *host*, they do not, and the predicted effect may not exist.

This must be established before E2 is interpreted. See E1.

### Bearing experiments

- `E1-mount-topology` — establishes whether the mechanism is even available
- `E2-placement-differential` — the direct test
- `E0-syscall-census` — supplies the op-count multiplier the effect scales by

### Multiplier from E0 (run `20260826T105956Z-c16d429`)

A warm request under maximum PHP tuning still issues ~4,300 filesystem syscalls,
~3,900 of them `stat`-family. A cold request issues ~15,400.

These are the numbers per-op latency gets multiplied by, and E0 shows they cannot be
reduced from inside `php.ini`. That does not confirm H1 — only E2 can — but it
establishes that the effect H1 proposes has something substantial to act on.

### E1 result: the proposed mechanism does not exist

E1 (run `20260902T060000Z-24d9bb9`) put two tasks on one host against one EFS
filesystem and inspected the host directly. Result: two fully independent NFS4
client mounts, two independent `efs-proxy` TLS sessions, one per task - not one
shared mount bind-mounted into both.

This refutes the specific mechanism proposed above (shared NFS attribute/page
cache across co-located tasks) for the standard ECS + EFS configuration
(`transitEncryption: ENABLED`, no IAM auth/access point, `awsvpc` mode).

It does **not** resolve H1's actual claim. A locality effect could still exist
through a different, weaker mechanism (shared network path to the same-AZ mount
target, shared host resources) that this result doesn't rule out. E2's placement
differential remains the direct test - but its design assumed the now-refuted
mechanism and should be revisited, not carried forward unchanged.

See [docs/findings/E1-mount-per-task.md](../docs/findings/E1-mount-per-task.md).
