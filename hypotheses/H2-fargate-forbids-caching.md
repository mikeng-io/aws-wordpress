# H2 — Fargate's isolation model forbids every effective cache tier

**Status:** `PARTIALLY TESTED` — E3 resolved the gating unknown in H2's favour

## Claim

Fargate is not merely *worse* at shared filesystems; it is structurally excluded
from every mitigation, because the properties that make it serverless are the same
properties that forbid caching.

## Documented constraints (verified, not measured)

- One task per microVM: no cache shared across tasks. AWS documents ECS Managed
  Instances as running multiple tasks per instance "unlike Fargate which runs each
  task in its own isolated environment."
- `efsVolumeConfiguration` exposes only file system ID, root directory, transit
  encryption (+port), and auth config. No NFS mount options.
- Host sysctls unreachable, including `read_ahead_kb`, which AWS recommends raising
  from its 128 KB default to 15 MB.
- No `CAP_SYS_ADMIN`: no FUSE, no OverlayFS. ECS Managed Instances grants
  `CAP_SYS_ADMIN`, `CAP_BPF`, `CAP_PERFMON`; Fargate does not.
- Ephemeral storage is network-backed, not local NVMe.

Separately: EFS does not support `nconnect`, and AWS states `fsc` does not reduce
latency — so client-side tuning cannot substitute.

## Prediction

No Fargate-only mitigation closes the majority of the gap to a comparably sized
EC2/Managed Instances deployment. The best available Fargate design — hydrating
code onto ephemeral storage at task start, from a single tarball rather than by
traversing EFS — will improve on naive Fargate + EFS substantially, but will remain
measurably behind, and will pay for it in task start latency.

## Kill condition

**H2 is refuted if** an infrastructure-only Fargate design closes most of the gap
to EC2 at acceptable start latency.

## Open unknown that gates this — RESOLVED by E3

The small-file metadata latency of Fargate ephemeral storage was not documented
anywhere found. E3 measured it (`results/E3/20260910T113000Z-6016f58/`, 3 reps):

**Fargate ephemeral storage is genuinely fast.** `stat()` p50 of 3.1 µs against
EFS's 1.08 ms on the same task — ~348×. Critically the *tail* is local-disk-shaped
too (p99 4.6 µs, a 1.5× spread over p50), not the EFS-like tail that would have
meant "network volume wearing a local costume."

So the hydration family of designs does **not** collapse. Fargate has a genuinely
fast local tier; what it lacks is any way to *share* that tier across tasks, which
is a different constraint and the one H2's remaining claims rest on.

What E3 does **not** resolve: whether an actual hydrate-at-startup design closes
most of the gap to EC2 *at acceptable start latency*. That is H2's real kill
condition and still needs the design built and measured. E3 only establishes that
the substrate it would rely on is fast enough to be worth building on.

See [docs/findings/E3-fargate-ephemeral.md](../docs/findings/E3-fargate-ephemeral.md).

## Bearing experiments

- `E3-fargate-ephemeral-latency` — gates the whole branch
- `E2-placement-differential`
