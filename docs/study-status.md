# Study closeout — 2026-10-29

**Current phase: collection closed; no additional paid experiment is queued or authorised.**
The E0–E5 observation set is ready to publish with negative results and explicit
limits. Closing this phase does not make every hypothesis true or every
prediction evaluable. WordPress remains the workload instrument; a production
WordPress deployment is not the acceptance target.

Start with the [evidence index](evidence-index.md) for every retained run and the
[measurement methodology](measurement-methodology.md) for comparison boundaries.
Predictions remain those registered for each campaign. Raw results are frozen.

## What the completed collections establish

| Collection | Evidence | Mechanical result / scope |
|---|---|---|
| E0 census | [n=10 baseline](../results/E0/20260827T185901Z-bff2d22/), [corrected cart n=10](../results/E0/20260902T105746Z-f62a686/) | Counts per request, not latency; aged cohorts n=3. Earlier cart/checkout observed an empty cart. |
| E1 topology | [host inspection](../results/E1/20260902T060000Z-24d9bb9/) | Two tasks on one host had separate NFS mounts/TLS proxies. Refutes the proposed shared-client mechanism for the tested configuration. |
| E2 block/mount | [block](../results/E2/20260910T163206Z-66dcff8/), [mount](../results/E2/20260910T182051Z-53b5423/) | Three deployments each. P5 PARTIALLY SUPPORTED (1/4); the predicted separation on device-touching operations did not hold. |
| E2 FSx | [three deployments](../results/E2/20261015T000959Z-85382cc/) | P1 NOT EVALUABLE because of Lustre read residency; P3 mechanically REFUTED with an NFS-cache construct caveat; P5 PARTIALLY SUPPORTED. |
| E2 FUSE | [three deployments](../results/E2/20261029T070456Z-a2041d6/) | JuiceFS P2 INCONCLUSIVE at the registered bar; Mountpoint conformance P4 SUPPORTED. The collection did not isolate all metadata cache modes. |
| E3 substrate | [three Fargate tasks](../results/E3/20260910T113000Z-6016f58/) | Fast ephemeral metadata path. The EFS comparison is a fresh-file/cache mixture, not production request latency. |
| E4 hydration | [three deployments](../results/E4/20261029T091909Z-842d596/) | P1/P3 SUPPORTED, P2 REFUTED, read-only H2 proxy MET. Neither a transparent write-back adapter nor an end-to-end application test. |
| E5 old-file/cache behaviour | [pooled formal-v3](../results/E5-formal/20261028T160106Z-dd5fce0/analysis-pooled-3.json) | Three eligible deployments: P1–P3 REFUTED, P4 INCONCLUSIVE, P5–P10 SUPPORTED. |

Prediction numbers belong to their experiment and campaign. E2 P2 and E4 P2 are
not the same claim. A successful collector exit, a conformance pass and a
SUPPORTED prediction are separate facts.

## Comparison boundaries

| Quantity | What it represents | Do not turn it into |
|---|---|---|
| E0 syscall counts | Application demand for the tested profiles/endpoints | Request latency, RPC count or storage cost |
| E2/E3 fresh-file stat p50 | The benchmark's mix of cache hits and remote work | A stable server lookup latency or warmed-production ratio |
| E2 open_read on newly written NFS files | Open/revalidation plus mostly cached bytes | Uncached storage throughput |
| E5 A phases | Attributed first-touch/revalidation/forced-miss cohorts | A single universal cost for every application stat |
| E5 B cohorts | Repeated access at registered intervals and windows | A direct trace of WordPress or proof of Lustre lock state |
| E4 hydration timer | Extracting an EFS tar onto task ephemeral storage | Complete ECS cold start or first HTTP 200 |
| E0 count × E4 stat p50 | A conditional extrapolation | Measured request latency or a mathematical upper/lower bound |

These distinctions are why there is no single cross-campaign filesystem
leaderboard here. Use each matched comparison with its sample sizes,
between-replication spread, distributions and cache state.

## Claims that remain open

- **H1:** the original shared-client mechanism is refuted. The retained reframed
  verdict is qualified by E2's within-tier differences and cache effects; no
  production steady-state cost model has been validated.
- **H2:** E3 established the substrate and E4 met a read-only proxy. The broader
  infrastructure-only kill condition, acceptable application startup, mutable
  state and refresh behaviour remain unresolved. INCONCLUSIVE is the current
  whole-claim label, not a claim of whole-H2 refutation.
- **H3:** INCONCLUSIVE. E0 did not test actual preloading or a cross-backend warm
  request ranking.
- **H4:** UNTESTED. E4 measured a startup component, not task-create-to-first-200,
  fleet rollout, propagation/recovery or cold/warm request rankings.
- **H5/H6/H7:** UNTESTED and parked for this phase: DB topology, bidirectional
  write-back correctness and equal-p95 request economics were not measured.

A complete production hydrate-and-serve design or an application load test would
be a new research decision, with new pre-registration, scope and spending
approval. Neither is a hidden prerequisite to publishing this filesystem study.

## E5 P4 closes as INCONCLUSIVE

The [v3 finding](findings/E5-attribute-cache.md) records two SUPPORTED runs and one
REFUTED run. A8's ten pooled passes are not a matched single-pass comparison with
A3, and the EFS phase effects do not disappear by selecting one pass. The
[first-pass amendment](../experiments/E5-attribute-cache/method-amendments/20261029-p4-first-pass/README.md)
applies only to a future formal-v4. It does not regrade any completed v3 result
and authorises no run. No further paid collection is needed to honestly report
this unresolved manipulation check.

The older [2026-10-27 validation](../results/E5-formal/20261027T093314Z-b5b480f/)
remains P7 ERROR under its recorded grader. It is excluded from the later pool,
as are the pilot, diagnostic, short-validation and off-protocol campaigns.

## Offline verification and publication

The [closeout replay receipt](../results/closeout/20261029T114956Z-40cdb91/verification.json)
names every check and any drift. It uses Git-tracked inputs in disposable copies,
selects historical E5 graders by recorded hashes, and hashes the original input
files before/after. It does not execute collectors or query AWS. Replay details
and limitations are in [the verification note](closeout-verification.md).

```sh
make study-index
make study-verify OUT=/tmp/a-new-closeout-receipt
```

Use a new output path. Do not run a writing analysis entrypoint directly against
frozen runs for a publication check. The index includes all observations; the
replay only claims the reference/frozen checks named in its receipt, not a new
validation of every archived pilot or failed apparatus iteration.

## Operational closeout

[Retention and cost follow-up](retention-and-cost.md) distinguishes workload
teardown from retained diagnostics/images/logs and from an account-wide zero-cost
claim. The private operational audit stays private. No resource deletion,
retention mutation or new live billing query is part of this offline closeout.
The next billing-refresh reconciliation remains an operational follow-up; cost
planning envelopes are not invoices.
