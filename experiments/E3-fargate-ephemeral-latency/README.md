# E3 — Fargate ephemeral storage: small-file metadata latency

**Bears on:** [H2](../../hypotheses/H2-fargate-forbids-caching.md) — gates the
entire branch. If ephemeral storage is itself slow, the "hydrate onto local disk"
family of Fargate designs collapses before it's even worth building.

**Cost:** a single short-lived Fargate task, no fleet, no NAT. Estimated
under $0.05 for the whole run — see stack for the exact figure once specced.

## Question

Is Fargate's local ephemeral storage actually fast, or is "local" doing more work
in that sentence than the disk is? Nobody has published small-file metadata
latency for it. H2 assumes it's fast enough to make hydrate-at-startup designs
worthwhile; that assumption has never been checked.

## Why this is the right next experiment

E1 showed EFS gets no shared-cache benefit from co-location on EC2 — the
mechanism E2 was built to detect doesn't exist. E2 needs redesigning before it's
worth running. E3 doesn't depend on that: it's a direct, narrow test of a
documented unknown, independent of anything E1 or E2 touch. Cheapest thing left in
the queue with a real hypothesis behind it.

## Method

One Fargate task, two mount points, one benchmark, run against both:

1. **Local** — the task's own ephemeral storage (network-backed, per AWS docs;
   whether that shows up in small-file latency is exactly the question).
2. **EFS** — the same filesystem shape E1 used, mounted on the same task.

Same task, same run, same benchmark binary hitting both paths — the only variable
is which mount serves the request, so nothing else can explain a difference.

**Benchmark:** not `fio` — `fio`'s default I/O patterns are throughput-oriented
and EFS is not bad at throughput; the WordPress storm E0 measured is metadata
operations at small size. A purpose-built microbenchmark instead: a fixed
directory tree shaped like a realistic WordPress plugin layout (nested
directories, files in the 2–50 KB range — see `E0-syscall-census`'s catalog for
the profile to match), running create → stat → open+read → unlink in that mix,
timing each op individually via `clock_gettime(CLOCK_MONOTONIC)` around the
syscall, not around the whole batch. Report the full latency distribution
(p50/p95/p99/max), not a mean — a mean hides exactly the tail behavior that
would make hydration a bad trade.

## Prediction

Pre-registered before running:

- Local ephemeral p50 for a single `stat()` is at least an order of magnitude
  below EFS's, since even a network-backed local volume shouldn't carry EFS's
  full NFS-over-TLS round trip.
- Local ephemeral's *tail* (p99) is the real open question. If it's genuinely
  local-disk-shaped, p99 stays close to p50. If it's quietly a network volume
  with EFS-like tail behavior under contention, p99 will show it — this is the
  case that would refute the "hydrate and serve locally" design outright.

## Kill condition

**The ephemeral-hydration branch of H2 is refuted if** local ephemeral's p99 is
within the same order of magnitude as EFS's. That would mean Fargate has no fast
local tier at all — a materially different, more damaging finding than "Fargate
is merely worse," and one that would need its own write-up rather than folding
quietly into H2's existing framing.

## Status

`SPECCED` — apparatus not yet written.
