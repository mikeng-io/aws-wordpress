# H4 — Time-to-first-useful-request is the metric, not steady-state RPS

**Status:** `UNTESTED`

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
