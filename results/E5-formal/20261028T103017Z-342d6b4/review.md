# Formal replication 2 — 2026-10-28

**Status:** `COMPLETE; PROTOCOL ELIGIBLE; FULL-METHOD VALIDATION PASS`.
Per-replication P7 is **SUPPORTED**. The aggregate is still **NOT EVALUABLE**:
this is one evaluable replication of the three the amendment requires.

## Protocol

- Method `isolation-formal-v3`, one fresh deployment
  (`deployment_id 3003a1aabfe918964d178abe5c5fd8865eab276dd70cb4c5d91ecc214e532eb4`).
- Apparatus hashes are byte-identical to the frozen 2026-10-27 formal run, and
  `image_digest` is the same `sha256:c42cef…8ec6`. The meta's `source_commit` is
  `e597dd1` (the tree at meta write); the apparatus files did not change between
  launch and that commit.
- 6/6 POSIX conformance checks PASS; cohort A order was randomised; all 21 A/B
  bindings and 12 matched-control cells are `ok`; no B cell was late or short.
- Mount facts: `nosharecache` on every NFS mount; `acregmin=0,acregmax=0` only on
  the four `.forced` mounts (plain, TLS, OpenZFS, ONTAP).
- Seed age: protocol records the 120 s gate value (same as the frozen run); the
  task's own check at 11:00:03 logged **485 s since seeding**.
- Formal phases: 935/912/902/901/892/81 s = **77.1 min**; task 10:53–12:15;
  teardown verified 12:37:55; watchdog `cleanup_verified: true`, zero remaining
  stacks or backups.
- 508 files, 116 MB, including the full batch, control, idle and quiet data.

## P7

| Δ | target slow share | control rate ≥ boundary | control centroid | Lustre threshold |
|---:|---:|---:|---:|---:|
| 0.1 s | 0.256% | 0.0075% | 10,495 ns | 17,308 ns |
| 1 s | 0.238% | 0.0243% | 15,887 ns | 17,771 ns |
| 10 s | 0.275% | 0.0017% | 10,759 ns | 22,834 ns |

All target shares are below the 1% support bound and all control rates are far
below the 0.2% veto, so P7 is **SUPPORTED**. The centroid diagnostic is retained:
the 1 s control centroid is 15.9 µs, below but not far from its 17.8 µs threshold;
the rate rule, not the centroid, decides.

For contrast, the frozen run's control rates were 0.083%/0.075%/0.050% and its
centroids crossed the boundary; this run's rates are 5–30× lower. That is the
behaviour the amendment was written to separate from storage attribution.

## Other predictions

P1–P3 `REFUTED`; P4–P6 and P8–P10 `SUPPORTED` — the same pattern as the frozen
run.

## Disposition and cost

- Study replication 2; **1 of 3** evaluable formal replications.
- Wall time 10:30:17–12:37:55 = 2 h 08 m; at the US$0.955/h standing subtotal that
  is ~US$2.03 before FSx minimums, inside the US$2.60 planning envelope. Actual
  billing is not invoice-verified.
- Next: formal run 3 (study replication 3) from a clean tree with
  `E5_RUN_KIND=formal-isolation make e5-container REPS=1`. Do not pool this run
  with the frozen one for a verdict until three independent runs are evaluable.
