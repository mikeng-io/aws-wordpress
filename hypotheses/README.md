# Hypothesis register

Pre-registered. Each file states a prediction and the outcome that would falsify it,
written before the experiment runs.

| ID | Claim | Status |
|---|---|---|
| [H1](H1-cache-locality.md) | Cache locality, not filesystem choice, dominates WordPress FS performance | `MECHANISM REFUTED, CLAIM OPEN` |
| [H2](H2-fargate-forbids-caching.md) | Fargate's isolation model forbids every effective cache tier | `UNTESTED` |
| [H3](H3-opcache-dominates.md) | opcache/realpath tuning makes filesystem choice largely irrelevant at steady state | `INCONCLUSIVE` (E0 contradicts) |
| [H4](H4-cold-start-is-the-metric.md) | Time-to-first-useful-request separates options under autoscaling; steady-state RPS does not | `UNTESTED` |
| [H5](H5-db-is-the-same-shape.md) | Host-level pooling and query caching beats per-task; the DB axis is H1 again | `UNTESTED` |
| [H6](H6-writeback-cannot-be-correct.md) | Bidirectional write-back caching between ephemeral and EFS cannot be made correct | `UNTESTED` |
| [H7](H7-cheapest-storage-loses.md) | At equal p95, the cheapest configuration is not the one with the cheapest storage line item | `UNTESTED` |

Status values: `UNTESTED`, `SUPPORTED`, `REFUTED`, `INCONCLUSIVE`.
