# Hypothesis register

Pre-registered. Each file states a prediction and the outcome that would falsify it,
written before the experiment runs.

| ID | Claim | Status |
|---|---|---|
| [H1](H1-cache-locality.md) | Tier reachability dominates metadata-heavy filesystem performance (reframed) | `MECHANISM REFUTED, CLAIM REFRAMED — SUPPORTED`; E5 P7 SUPPORTED 3/3, P4 INCONCLUSIVE; production cost model still unvalidated |
| [H2](H2-fargate-forbids-caching.md) | Fargate's isolation model forbids every effective cache tier | `INCONCLUSIVE`; E3 substrate measured, E4 read-only proxy MET; broader H2 kill condition unresolved |
| [H3](H3-opcache-dominates.md) | opcache/realpath tuning makes filesystem choice largely irrelevant at steady state | `INCONCLUSIVE — PERIPHERAL`; counts constrain the claim; no cross-backend max/preload test |
| [H4](H4-cold-start-is-the-metric.md) | Time-to-first-useful-request separates options under autoscaling; steady-state RPS does not | `UNTESTED — PROMOTED`; E4 startup component only, no first-200-OK/ranking test |
| [H5](H5-db-is-the-same-shape.md) | Host-level pooling and query caching beats per-task; the DB axis is H1 again | `UNTESTED — PARKED` |
| [H6](H6-writeback-cannot-be-correct.md) | Bidirectional write-back caching between ephemeral and EFS cannot be made correct | `UNTESTED — PARKED`; original E4 write-back gate no longer applies to read-only hydration |
| [H7](H7-cheapest-storage-loses.md) | At equal p95, the cheapest configuration is not the one with the cheapest storage line item | `UNTESTED — PARKED`; no equal-p95 request economics measured |

Status values: `UNTESTED`, `SUPPORTED`, `REFUTED`, `INCONCLUSIVE`.

## Closeout interpretation — 2026-10-29

The [current phase](../docs/study-status.md) closes with unresolved questions; no
new paid run is queued. H2's former register/header mismatch (UNTESTED versus
PARTIALLY TESTED) is expressed as INCONCLUSIVE using the existing E3/E4 evidence,
without changing its kill condition or declaring the whole claim settled. H6's
priority qualifier changes because E4 completed a read-only workload; its UNTESTED
verdict is unchanged. H4/H5/H7 require new research scope, not editorial inference.
Original predictions remain in each hypothesis file.
