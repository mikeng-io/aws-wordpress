# Formal replication 4 — 2026-10-28

**Status:** `COMPLETE; PROTOCOL ELIGIBLE; FULL-METHOD VALIDATION PASS`.
Per-replication P7 is **SUPPORTED**. This is the third evaluable replication, so
the three-run aggregate is now admissible: **P7 SUPPORTED (3/3)**.

## Protocol

- Method `isolation-formal-v3`, one fresh deployment
  (`deployment_id c26d9bab…8f84`), source `dd5fce0`.
- Apparatus hashes identical to replications 2 and 3; image digest unchanged.
- 6/6 conformance PASS; **83/83** status rows `ok`; no late or short cell.
- Seed age **191 s**; phases 940/911/902/901/892/87 s = **77.2 min**; teardown
  verified 18:07:39; zero remaining stacks or backups.
- 508 files, 111 MB.

## P7

| Δ | target slow share | control rate ≥ boundary | control centroid | Lustre threshold |
|---:|---:|---:|---:|---:|
| 0.1 s | 0.335% | 0.0121% | 2,868 ns | 10,767 ns |
| 1 s | 0.285% | 0.0117% | 7,071 ns | 11,489 ns |
| 10 s | 0.157% | 0.0067% | 11,936 ns | 27,520 ns |

All target shares are below 1% and all control rates are well below 0.2%, so P7 is
**SUPPORTED**. The control centroid is far below the Lustre threshold at every
delta, so this replication would also have passed the old centroid veto.

## P4 diverges in this replication

P4 (the A8/A3 scaling ratio) is `SUPPORTED` in replications 2 and 3 but `REFUTED`
here: `efs_host_plain` 0.716 and `fsx_openzfs` 0.701, against 0.884/1.017 and
0.941/1.010 in the earlier runs. The pooled P4 verdict is therefore
**INCONCLUSIVE**, not SUPPORTED. This does not touch P7: P7 uses cohort-B positive
`stat` cost and same-time EBS controls, not the A8/A3 ratio.

## Aggregate over the three evaluable runs

- P1–P3 `REFUTED`
- P4 **`INCONCLUSIVE`** (2 SUPPORTED, 1 REFUTED)
- P5, P6 `SUPPORTED`
- **P7 `SUPPORTED` (3/3)**
- P8–P10 `SUPPORTED`

The pooled output is saved beside this review as `analysis-pooled-3.json`; the
per-run output is `analysis-v3.json`.

## Cost

16:01:06–18:07:39 = 2 h 06 m; ~US$2.01 at the standing subtotal,
inside the US$2.60 envelope. Actual billing is not invoice-verified. This closes
the three-replication campaign; no fourth run is authorised.
