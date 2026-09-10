# H5 — The database axis is H1 again, on a different resource

**Status:** `UNTESTED — PARKED`

> Parked deliberately, not forgotten. The database is a different axis from
> storage, and the study's current line of enquiry is the filesystem matrix (E2)
> and the cache adapter (E4). This stays on the register because the claim is real;
> it is simply not what is being worked on. See
> [docs/scope-audit.md](../docs/scope-audit.md).

## Claim

PHP-FPM opens a connection per worker, so a fleet is a connection storm. Where the
pool and query cache *live* follows the same locality logic as the filesystem cache:

- On Fargate, one task per microVM, so a pooler is per-task and pools against itself
- On ECS Managed Instances, many tasks per host, so a pooler can run as a Managed
  Daemon (guaranteed running before application tasks are placed) and serve every
  task on the box

## Scope note

The database engine is a **control**, not a variable. The main matrix runs on a
fixed-capacity, oversized Aurora MySQL on Graviton, deliberately never the
bottleneck, so DB scaling never contaminates storage or compute signals.

Aurora Serverless v2 gets its own experiment — ACU ramp lag under spike, cold start
from scale-to-zero — rather than being the noisy baseline underneath everything else.

## The variable

| Connection layer | Pools | Caches queries | Splits reads |
|---|---|---|---|
| direct | no | no | no |
| RDS Proxy | yes | no | no |
| ProxySQL sidecar (per task) | yes | yes | yes |
| ProxySQL Managed Daemon (per host) | yes | yes | yes |

## Prediction

ProxySQL as a per-host daemon outperforms the per-task sidecar on connection
establishment cost and query cache hit ratio, by the same mechanism as H1.

## Kill condition

**H5 is refuted if** per-host and per-task pooling perform equivalently.

## Side finding available here

WordPress has no native read/write splitting — HyperDB and LudicrousDB are plugins,
which this study rules out of scope. ProxySQL splits reads to Aurora replicas at the
connection layer, transparently. If it works, that is read-replica scaling for a
legacy WordPress install with zero application change. Tracked as a side task, not a
blocker for the main queue.
