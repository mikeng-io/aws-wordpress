# E4 hydration — 20261029T091909Z-842d596

3 replication(s). Lower is better. Hydrated = task-start copy of the read-only tree; EFS = fresh client reading the same tree over NFS.

## Per-replication p50

| Rep | stat EFS | stat hydrated | ratio | open_read EFS | open_read hydrated | ratio | hydration |
|---|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1.51 ms | 3.1 µs | 0.002 | 2.87 ms | 11.7 µs | 0.004 | 0.22 s |
| 2 | 1.38 ms | 3.0 µs | 0.002 | 2.84 ms | 11.5 µs | 0.004 | 0.44 s |
| 3 | 1.17 ms | 3.1 µs | 0.003 | 2.38 ms | 11.8 µs | 0.005 | 0.43 s |

## Grades

- **P1, hydration removes the metadata penalty:** `SUPPORTED`
- **P2, hydration is not free:** `REFUTED`
- **P3, conformance:** `SUPPORTED`
- **H2 kill-condition proxy:** `MET`

P2 failures:
- rep-1: hydration 0.218s < 0.5s
- rep-1: start extra 0.051s < hydration 0.218s
- rep-2: hydration 0.444s < 0.5s
- rep-2: start extra 0.192s < hydration 0.444s
- rep-3: hydration 0.429s < 0.5s
- rep-3: start extra 0.265s < hydration 0.429s

## Pooled

| op | EFS p50 | hydrated p50 | ratio |
|---|--:|--:|--:|
| `stat` | 1.39 ms | 3.1 µs | 0.002 |
| `stat_enoent` | 1.08 ms | 7.4 µs | 0.007 |
| `open_read` | 2.71 ms | 11.7 µs | 0.004 |

## Hydration and break-even

| Rep | bytes | hydration s | EFS start→bench | hydrated start→bench | start extra | one-request penalty | break-even requests |
|---|--:|--:|--:|--:|--:|--:|--:|
| 1 | 27412480 | 0.218 | 1.45 | 1.50 | 0.05 | 6.48 | 0.03 |
| 2 | 27412480 | 0.444 | 1.49 | 1.68 | 0.19 | 5.92 | 0.08 |
| 3 | 27412480 | 0.429 | 1.41 | 1.67 | 0.27 | 5.02 | 0.09 |

Break-even uses E0's 4,300 filesystem syscalls per warm request and the measured
`stat` p50 difference; it is an extrapolation, not an end-to-end request measurement.

## Per-replication conformance

| Rep | EFS | hydrated | EFS fails | hydrated fails |
|---|--:|--:|---|---|
| 1 | SUPPORTED | SUPPORTED | — | — |
| 2 | SUPPORTED | SUPPORTED | — | — |
| 3 | SUPPORTED | SUPPORTED | — | — |

## Distribution and replication diagnostics

CIs below are operation-level order-statistic intervals (binomial-rank normal
approximation); they do not quantify uncertainty across three deployments.

| Arm | op | n | p50 CI95 | geometric mean | p95 | p99 | IQR/p50 | p99/p50 | rep p50 max/min | modes |
|---|---|--:|---|--:|--:|--:|--:|--:|--:|---|
| efs | stat | 3000 | 1.38 ms–1.40 ms | 1.41 ms | 1.74 ms | 5.11 ms | 0.188 | 3.678 | 1.290 | bimodal |
<!-- efs/stat fast: share=0.9743, median_ns=1381924, CI95_ns=[1373597, 1391586] -->
<!-- efs/stat slow: share=0.0257, median_ns=4963419, CI95_ns=[4677805, 5150013] -->
| efs | stat_enoent | 60 | 1.03 ms–1.15 ms | 1.10 ms | 1.47 ms | 1.65 ms | 0.200 | 1.527 | 1.339 | unimodal |
| efs | open_read | 3000 | 2.69 ms–2.73 ms | 2.69 ms | 3.34 ms | 4.05 ms | 0.201 | 1.494 | 1.205 | unimodal |
| hydrated | stat | 3000 | 3.1 µs–3.1 µs | 3.2 µs | 3.9 µs | 6.0 µs | 0.123 | 1.968 | 1.011 | unimodal |
| hydrated | stat_enoent | 60 | 7.1 µs–7.7 µs | 7.8 µs | 18.8 µs | 22.6 µs | 0.150 | 3.067 | 1.045 | unimodal |
| hydrated | open_read | 3000 | 11.5 µs–11.8 µs | 11.9 µs | 17.1 µs | 21.6 µs | 0.283 | 1.848 | 1.023 | unimodal |

Per-replication distributions and cluster diagnostics are in summary.json.

