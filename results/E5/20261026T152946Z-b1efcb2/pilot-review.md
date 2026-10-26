# E5 single AWS pilot review — 2026-10-26 UTC

**Decision: NOT READY for replications 2/3.** The authorised single pilot collected
all six tiers, both cohorts and expiry probes. Keep the hard gates and diagnose
the instrumentation before seeking another run. This is filesystem research;
WordPress supplies the motivating workload and entry point, not the acceptance metric.

Run: `20261026T152946Z-b1efcb2`; source `b1efcb205379395f950e1872d4cb441e5db9d0a7`,
clean at launch. See [provenance](rep-1/meta.json), [machine-readable grading](summary.json)
and [grading tables](summary.md). Singapore, `ap-southeast-1a`, `c7gd.large`;
AL2023 kernel `6.1.188-233.393.amzn2023.aarch64`, amazon-efs-utils 3.3.2,
Lustre client 2.15.6-32. All six filesystem conformance checks passed; seed age
was 133 seconds. The bench completed and raw data were downloaded before deletion.

## Validity gates

- **Cohort B: 14/18 cells OK, four ERROR.** All three EFS TLS cells fail exact
  phase/window RPC reconciliation. Each independent 600-second window contains
  **10 more GETATTR** operations than the sum of the attributed request phases:
  10420 versus 10410 at 0.1s and 1s, 9617 versus 9607 at 10s.
  Background mount activity is a hypothesis; this run does not identify its
  producer. Do not subtract ten, allow a tolerance, or claim a watchdog cause.
- **Lustre A1 signature ERROR:** the current parser reports zero miss RPCs.
  The raw pre/post MDC stats instead show `ldlm_ibits_enqueue` increasing from
  8404 to 9445 (delta 1041), while `mds_getattr` stays at 2. This is a candidate
  counter-name coverage issue, not a validated replacement. Confirm its semantics
  against the deployed Lustre version before changing the parser or regrading.
- **Lustre B at 0.1s ERROR:** 25.7% of requests are later than delta/2; the
  predeclared limit is 5%. Separate workload time, concurrent-process pressure
  and instrumentation overhead before choosing an apparatus change. Do not
  increase the lateness limit to accommodate this run.
- Latency/RPC cross-check disagreement remains diagnostic, as amended before
  launch: EFS plain 0.1s and all OpenZFS cells disagree. Counter snapshots cost
  roughly 2.2–2.6ms/request in the valid NFS cells; their effect is not assumed zero.

## What can be learned

All ten aggregate predictions are **NOT EVALUABLE**, because only one replication
exists. Per-replication outputs are observations, not study verdicts: P2/P3/P4
refuted their specified thresholds; P6/P9/P10 supported theirs; the remaining
predictions hit errors. No H1 verdict or production recommendation changes.

At 1s, EFS plain positive-stat amortised time was 7.905ms/request versus EBS
1.944ms/request (4.07x). The busiest 5% of EFS plain requests carried 85.15% of
positive-phase RPC operations. These are single-pilot observations under this
specific aged-file workload, not measured WordPress request latency.

OpenZFS had low B RPC intensity, but each post-idle probe issued 1041 GETATTR
operations after about 75 seconds idle. Revalidation was observed; this does not
establish whether delegation caused the earlier low rate. RPC operations/stat
must not be described as a literal file-miss probability.

## Next actionable work

1. Attribute TLS GETATTR activity outside the request phases using version-matched
   helper/proxy evidence and an isolated reproduction where possible.
   Preserve the independent window check; any method change needs a dated rationale.
2. Validate Lustre intent-counter semantics and add a raw-fixture regression for
   its deployed counter names. Preserve this pilot's original grading alongside
   any explicitly versioned reanalysis.
3. Measure why Lustre misses the 0.1s schedule and the effect of all 18 concurrent
   B processes. Decide an apparatus amendment before another paid run.
4. Reconcile pricing/budget and obtain the separately recorded go-ahead before
   any retry or replications 2/3. No automatic continuation.

## Verification and preservation

The committed grader generated the summaries without edits to raw input or
thresholds. `make e5-selftest` passed all 59 synthetic grading cases and 25
attribution regression tests. Raw files, runtime logs, provenance and a SHA-256
manifest are retained with this review. See [teardown evidence](teardown.json)
for the final direct-service inventory and host guard result.

Pricing uses the refreshed `20261026T144948Z-71ece42` snapshot: standing subtotal
$0.95475/hour, excluding ancillary usage and minimum-billing effects. Billing
allocation tags were inactive in preflight, so this is not an invoice and actual
study spending/remaining budget is not verified. The $10 study ceiling remains.

Final live receipt: stack creation 15:30:06 UTC, DELETE_COMPLETE 16:44:26 UTC
(about 74.3 minutes including deployment/deletion). Collector exit 0 at 16:46:33;
host guard completed its separate empty observations and confirmed the runner
stopped. Final read-only audit covered 18 regions x 11 service inventories:
198 checks, zero API errors, zero E5 residuals, zero E5 diagnostics buckets.
This resource cleanup evidence does not measure final billed dollars.
