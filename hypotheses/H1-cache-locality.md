# H1 — Cache locality dominates, not filesystem choice

**Status:** `UNTESTED`

## Claim

For WordPress, shared-filesystem performance is determined by *where metadata and
page caches are permitted to live*, not by which filesystem is mounted. The compute
platform decides which cache tiers are reachable, and therefore silently decides
storage performance.

## Why it would matter

If true, the entire "which filesystem is fastest for WordPress" genre is asking the
wrong question, and the correct question is "which compute platform lets me cache,
and what does that permit downstream."

## Mechanism proposed

NFS is a chatty request/response protocol. Cost is approximately
`(number of metadata ops) x (round-trip latency)`. WordPress issues a large number
of metadata ops per request. The only cure is caching ops closer to the compute.
Candidate cache tiers, in order of proximity:

1. NFS attribute cache and kernel page cache, shared per host across co-located tasks
2. Kernel readahead (`read_ahead_kb`), a host sysctl
3. Explicit local NVMe cache (requires FUSE, requires `CAP_SYS_ADMIN`)
4. No shared filesystem at all (image-baked code)

## Prediction

The **placement differential** — N identical tasks against one identical EFS
filesystem, run once as N tasks on 1 host and once as N tasks on N hosts — will show
a materially lower per-request metadata cost in the co-located arrangement, because
tasks 2..N are served from a cache task 1 warmed.

Magnitude is deliberately not predicted. Direction and significance are.

## Kill condition

**H1 is refuted if** the placement differential shows no statistically significant
gap (overlapping confidence intervals across repeated, order-randomised runs).

If refuted, H2 and much of the storage matrix lose their motivation, and the study
should be re-scoped early rather than late.

## Dependency that could invalidate the test

The mechanism assumes co-located ECS tasks on EC2 **share one NFS client**, and
therefore one attribute cache. If the ECS agent mounts EFS once per *task* rather
than once per *host*, they do not, and the predicted effect may not exist.

This must be established before E2 is interpreted. See E1.

## Bearing experiments

- `E1-mount-topology` — establishes whether the mechanism is even available
- `E2-placement-differential` — the direct test
- `E0-syscall-census` — supplies the op-count multiplier the effect scales by

## Multiplier from E0 (run `20260826T105956Z-c16d429`)

A warm request under maximum PHP tuning still issues ~4,300 filesystem syscalls,
~3,900 of them `stat`-family. A cold request issues ~15,400.

These are the numbers per-op latency gets multiplied by, and E0 shows they cannot be
reduced from inside `php.ini`. That does not confirm H1 — only E2 can — but it
establishes that the effect H1 proposes has something substantial to act on.
