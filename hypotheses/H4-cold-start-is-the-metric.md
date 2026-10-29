# H4 — Time-to-first-useful-request is the metric, not steady-state RPS

**Status:** `UNTESTED — PROMOTED`

> Historical priority rationale, before E4 collection: more central under the reframed study, not less: a cache tier's warming cost
> *is* a cold-start cost, so E4 cannot be evaluated without settling this. E0 already
> supplies the relevant magnitude — a cold request issues ~15,400 syscalls against
> ~4,300 warm.

**Closeout clarification (2026-10-29):** E4's registered syscall/hydration
predictions can be graded without settling this broader request-ranking claim.
The current phase closes with this hypothesis UNTESTED; a first-200-OK study is
future research, not a hidden requirement to make the completed E4 result valid.
See [study closeout](../docs/study-status.md).

## Claim

Under autoscaling, a fleet absorbing a traffic spike is mostly *cold* tasks. The
metric that separates infrastructure choices is therefore task start to first
200 OK, not steady-state throughput — which is where most published benchmarks live
and where differences largely vanish.

## Prediction

Ranking of configurations by cold-path metrics will differ from ranking by
steady-state RPS. Specifically, configurations that hydrate or cache locally will
rank worse on start latency and better on warm latency, and the crossover point will
depend on task lifetime.

## Kill condition

**H4 is refuted if** the two rankings agree, making the distinction academic.

## Measurements required

- Task start to first 200 OK, with mount/hydration time broken out
- Rollout time for a full fleet replacement
- Propagation lag: change written to shared storage, to last task serving it
- Spot interruption to recovery, including whether an in-flight write survived

Cold-task and warm-task requests are reported as separate cohorts. They are never
blended into a single average.

## E4 startup-component evidence (2026-10-29)

The [formal E4 finding](../docs/findings/E4-hydration.md),
[`results/E4/20261029T091909Z-842d596/`](../results/E4/20261029T091909Z-842d596/),
measured three independent task-start hydrations of the same 27,412,480-byte EFS
tar: **0.218–0.444 s**. First-application-log-to-benchmark times were
**1.408–1.487 s on EFS** and **1.497–1.679 s hydrated**, with paired differences
**0.051–0.265 s**. These intervals include preflight/conformance work and
log/scheduling variation, and exclude image pull, EFS mount initialization and
ECS task provisioning before the first log. The 90-second EFS DNS readiness wait
was outside the tasks. E4 P2 is mechanically **REFUTED**: hydration misses the
registered 0.5-s floor and the timing difference is below hydration time in all
three reps. Those thresholds remain unchanged.

This supplies a measured hydration component, **not task-start-to-first-200-OK**,
fleet rollout, propagation or recovery evidence. No cold-versus-warm request/RPS
ranking was measured, and the syscall-based break-even is an extrapolation.
H4's verdict remains `UNTESTED — PROMOTED`; this evidence cannot grade its ranking
prediction or kill condition.
