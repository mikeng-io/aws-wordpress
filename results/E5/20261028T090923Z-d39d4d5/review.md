# Off-protocol E5 run — 2026-10-28

**Status:** `COMPLETE; TEARDOWN VERIFIED; NOT POOLED; NOT GRADED`.
This run is a valid legacy E5 collection, but it is **not** a formal-v3
replication. It was launched with the default `study` collector instead of
`E5_RUN_KIND=formal-isolation`, so `meta.json` records `experiment: E5` and no
`protocol_method`. `analysis/e5_formal_stats.py` refuses it, and it cannot
contribute to P7 or any aggregate verdict.

## What ran

- Run: `20261028T090923Z-d39d4d5`, source `342d6b4`, `git_dirty: false`.
- Deployment 09:09:37Z, runner exit 10:28Z; seed age 171 s.
- Legacy workload: cohort A on six tiers, cohort B on six tiers × 0.1/1/10 s
  (300 s warm-up, 600 s measured); all conformance checks PASS.
- All tiers uploaded 10:07:05Z; 282 files / 21 MB collected.
- Teardown: `cleanup_verified: true`, zero remaining stacks or backups, the
  diagnostics bucket was removed. Runner exit 0.
- Watchdog: `.e5-watchdog/c84319ce4db04b3ba7feded72d95f443`.

## Cost and disposition

- Counted at one replication envelope, **~US$2.60** planning (actual billing
  unverified; the envelope is conservative). The revised campaign total is in the
  [control-rate amendment](../../../experiments/E5-attribute-cache/method-amendments/20261028-p7-control-rate/README.md).
- The raw data is retained here unchanged as evidence of the mistake. It is not
  graded, not pooled with formal v3, and not counted as a replication.
- The formal series restarts with one fresh
  `E5_RUN_KIND=formal-isolation make e5-container REPS=1` deployment per
  replication, writing to `results/E5-formal/<run>/rep-1/formal/`.
