# E5 preflight — 2026-10-28 (post-P7 amendment)

**Status:** `CONDITIONAL_PILOT_READY`. Read-only: `live_mutations=false`, no
deployment, no resource created. Source commit `966105f`; raw evidence in
[report.json](report.json).

**Pricing:** [results/pricing/20261028T090558Z-966105f](../../../../results/pricing/20261028T090558Z-966105f/)
(fresh today, `ap-southeast-1`). Standing subtotal **US$0.95475/h**, unchanged
from the 2026-10-27 snapshot.

## Budget under the new ceiling

| Item | US$ |
|---|---:|
| Conservative post-run proxy (through formal v3) | 16.996 |
| One replication planning target | 2.600 |
| Reserve | 0.400 |
| **Projected total with one run** | **19.996** |
| **Hard ceiling** | **30.000** |
| Remaining before this run | 13.004 |

The amendment's three-replication campaign is **US$24.796** (16.996 + 3 × 2.600),
leaving **US$5.204**. The 80–100 minute subtotal alone is US$1.29–1.61; the US$2.60
target is the conservative envelope and is the number the stop rule uses.

## Checks

- IAM simulation: **12/12** required actions allowed, no missing context.
- Baseline: all listed regions report zero E5 resources; retained E5 buckets **0**.
- Host tools: AWS CLI v2, Docker daemon, pinned runner, region all OK.
- Local guard: phase `complete`, resolved.
- Existing E2 diagnostics buckets: 7 retained, untouched.

## Conditions carried forward

1. `Study` / `Experiment` cost-allocation tags are **inactive**, so the zero
   tag-filtered Cost Explorer result does not verify historical spend. The
   US$16.996 figure is a conservative planning proxy, not an invoice balance.
2. The IAM simulator is not live resource-policy or deletion-timing proof.
3. Recheck transient baseline and credentials immediately before launch.

## Campaign this preflight covers

[Control-rate amendment](../../method-amendments/20261028-p7-control-rate/README.md):
three sequential replications, review between each, stop on protocol ERROR,
teardown failure or budget breach.

```
STOP_AFTER_REP=1 make e5-container REPS=3     # replication 2 of the study
# review rep-1 (campaign), verify teardown, then:
RESUME_RUN_ID=<run-id> make e5-container REPS=3
```

No replication has been launched from this preflight when the report was written.

## Launch

First campaign replication launched 2026-10-28 from `d39d4d5` with
`STOP_AFTER_REP=1 REPS=3`, host watchdog
`.e5-watchdog/c84319ce4db04b3ba7feded72d95f443`, runner container
`b4a806b546e8`, 6-hour guard. The agent sandbox cannot write the host's `~/.docker`,
so the runner image was built and launched with
`DOCKER_CONFIG=/tmp/e5-docker-config`; this changes no run input or apparatus file.
Outcome and review are recorded separately when the replication completes.
