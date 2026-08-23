# H2 — Fargate's isolation model forbids every effective cache tier

**Status:** `UNTESTED`

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

## Open unknown that gates this

The small-file metadata latency of Fargate ephemeral storage is not documented
anywhere found so far. If it is poor, the hydration family of designs collapses and
the finding becomes "Fargate has no fast local tier at all." See E3.

## Bearing experiments

- `E3-fargate-ephemeral-latency` — gates the whole branch
- `E2-placement-differential`
