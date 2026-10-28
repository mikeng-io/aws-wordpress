# Formal replication 3 — 2026-10-28

**Status:** `COMPLETE; PROTOCOL ELIGIBLE; FULL-METHOD VALIDATION PASS`.
Per-replication P7 is **SUPPORTED**. Aggregate remains **NOT EVALUABLE**: two of
three evaluable replications.

## Protocol

- Method `isolation-formal-v3`, one fresh deployment
  (`deployment_id 50551b0f…1e84`), source `f6659e0`.
- Apparatus hashes are identical to replication 2 and the frozen formal run;
  `image_digest` unchanged.
- 6/6 conformance PASS; **83/83** status rows `ok` (A, B and D cells); no late or
  short cell.
- Seed age: protocol records **242 s** (this run is not pinned at the 120 s gate).
- Formal phases 938/912/903/901/892/81 s = **77.1 min**; teardown verified
  15:00:07; zero remaining stacks or backups.
- 21 A/B bindings and 12 matched-control cells; `nosharecache` on every NFS
  mount, `acregmin=0` only on `.forced` mounts (same as replication 2).

## P7

| Δ | target slow share | control rate ≥ boundary | control centroid | Lustre threshold |
|---:|---:|---:|---:|---:|
| 0.1 s | 0.231% | 0.0108% | 10,917 ns | 17,979 ns |
| 1 s | 0.231% | 0.0030% | 15,250 ns | 19,043 ns |
| 10 s | 0.273% | 0.0000% | 15,210 ns | 22,381 ns |

All target shares are below 1% and all control rates are far below 0.2%; P7 is
**SUPPORTED** on every delta. The 10 s control had no operation at or above the
boundary. Centroids stay below their Lustre thresholds this time, but the rate is
the deciding quantity.

## Other predictions

P1–P3 `REFUTED`; P4–P6 and P8–P10 `SUPPORTED` — the same pattern as replications 1
and 2.

## Disposition and cost

- Study replication 3; **2 of 3** evaluable formal replications.
- Wall time 12:54:18–15:00:07 = 2 h 06 m; ~US$2.01 at the standing subtotal, inside
  the US$2.60 envelope. Actual billing is not invoice-verified.
- Next: formal run 4 (the third evaluable replication), then pool all three with
  `analysis/e5_formal_stats.py` for the only admissible aggregate P7.
