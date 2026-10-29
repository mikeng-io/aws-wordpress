# E4 hydration — 20261029T084344Z-ec1e5b2

1 replication(s). Lower is better. Hydrated = task-start copy of the read-only tree; EFS = fresh client reading the same tree over NFS.

## Per-replication p50

| Rep | stat EFS | stat hydrated | ratio | open_read EFS | open_read hydrated | ratio | hydration |
|---|--:|--:|--:|--:|--:|--:|--:|
| 1 | 1.60 ms | 3.2 µs | 0.002 | 3.59 ms | 14.0 µs | 0.004 | 0.21 s |

## Grades

- **P1, hydration removes the metadata penalty:** `SUPPORTED`
- **P2, hydration is not free:** `REFUTED`
- **P3, conformance:** `SUPPORTED`
- **H2 kill-condition proxy:** `MET`

P2 failures:
- rep-1: hydration 0.214s < 0.5s
- rep-1: start extra 0.021s < hydration 0.214s

## Pooled

| op | EFS p50 | hydrated p50 | ratio |
|---|--:|--:|--:|
| `stat` | 1.60 ms | 3.2 µs | 0.002 |
| `stat_enoent` | 1.35 ms | 11.1 µs | 0.008 |
| `open_read` | 3.59 ms | 14.0 µs | 0.004 |

## Hydration and break-even

| Rep | bytes | hydration s | EFS start→bench | hydrated start→bench | start extra | one-request penalty | break-even requests |
|---|--:|--:|--:|--:|--:|--:|--:|
| 1 | 27412480 | 0.214 | 1.49 | 1.51 | 0.02 | 6.88 | 0.03 |

Break-even uses E0's 4,300 filesystem syscalls per warm request and the measured
`stat` p50 difference; it is an extrapolation, not an end-to-end request measurement.

## Per-replication conformance

| Rep | EFS | hydrated | EFS fails | hydrated fails |
|---|--:|--:|---|---|
| 1 | SUPPORTED | SUPPORTED | — | — |
