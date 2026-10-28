# Amendment — P7 control overlap as a rate (2026-10-28)

**Status:** `ADOPTED 2026-10-28 BY MIKE; APPLIES TO REPLICATIONS 2–4 ONLY`.
This amendment replaces the control-side centroid veto in P7 with a direct overlap
rate. It does **not** apply to
`results/E5-formal/20261027T093314Z-b5b480f/`, which stays `P7 ERROR`, and it does
not change any target-side threshold. No replication has been run under it yet.

**Authority:** Mike, 2026-10-28: chose option 2 from the
[P7 control review](../../p7-review/20261028/README.md) and raised the E5 study
ceiling from US$20 to **US$30**.

**Evidence:** [P7 control review](../../p7-review/20261028/README.md) and its
[reproducible output](../../p7-review/20261028/review.json), computed from the
committed formal-v3 raw data.

## The problem this fixes

The registered rule says P7 is not evaluable when the EBS control's slow population
*overlaps* Lustre's classifier boundary. The implementation tested that the
**centroid** of the control's slow cluster was at or above the boundary. Those are
not the same statement:

- The 10s matched control's slow cluster is 60/66 first operations. Its centroid
  (14,601 ns) crosses the boundary (14,208 ns) by 2.8%, so the run errors.
- The same run's other EBS control has a centroid of 10,717 ns — 36% away, on the
  other side of the same boundary.
- At 1s the control's first operation (14,733 ns) is *above* that interval's
  boundary (13,638 ns) on most requests, yet the centroid test passes.
- The overlap *rate* is stable across intervals: 0.05–0.08% of control operations
  reach the boundary, against Lustre's 0.14–0.88%.

The centroid of a tiny tail cluster is dominated by how many non-first outliers
happen to be sampled, not by how much the control overlaps the target. A rate is
the direct measurement of the quantity the rule names.

## The rule (binding for future replications)

For each Δ in {0.1 s, 1 s, 10 s}:

1. `boundary` is the target's `stat_split.threshold_ns`, unchanged.
2. `control_rate` is the number of measured-window control positive `stat`
   operations whose histogram bin centre is strictly above `boundary`, divided by
   all measured-window control positive `stat` operations. This is the same bin
   centre and comparison used by `slow_count`.
3. The replication grades `ERROR` — the existing sentinel for "cannot grade" — if:
   - `control.slow_share_stat > 0.01` (unchanged), **or**
   - `control_rate > 0.002`.
4. Otherwise P7 grades the target shares exactly as before: `SUPPORTED` if every Δ
   is ≤ 1%, `REFUTED` if any Δ is > 5%, `INCONCLUSIVE` between. Aggregate status
   still requires three evaluable replications and is produced by `combine()`.
5. The control slow centroid and the first-operation decomposition are reported as
   diagnostics. They no longer veto.

The 0.2% limit is one fifth of P7's own 1% SUPPORT bound: a control that cannot
produce one fifth of the smallest effect we would call supported cannot explain a
supported effect. It is not fitted to the observed 0.05–0.08%; the observed margin
is 2.4–4× below the limit.

## Pre-registered expectation

Under this rule the formal-v3 data would give control rates of 0.083%, 0.075% and
0.050% at 0.1/1/10s, all below 0.2%, and target shares of 0.140%, 0.591% and 0.882%,
all below 1%. The expected per-replication grade is therefore `SUPPORTED`. That is
a prediction about the rule's behaviour on data already seen; it is **not** a
verdict and it is not applied to the frozen run. The test of the rule is whether
three future replications grade cleanly without a control-side stop.

## What does not change

- Instrument, mount topology, tiers, 300 s/600 s windows, 0.1/1/10 s intervals.
- Target thresholds: SUPPORT ≤ 1% at every Δ, REFUTE > 5% at any Δ.
- The control's 1% slow-share gate.
- P9 and P10, and every other prediction.
- Every raw operation. The first `stat` stays in all summed-time costs; it is
  separated only for diagnosis, never deleted or warmed away.
- The frozen 2026-10-27 result and all earlier evidence.

## Code change

- `analysis/e5_stats.py`: new `P7_CONTROL_MAX_RATE = 0.002`; `p7()` accepts a
  per-Δ control histogram, computes the rate and uses it as the veto; the centroid
  becomes an output field.
- `analysis/e5_stats.py::analyse` and `analysis/e5_formal_stats.py::analyse` pass
  the matched control histograms into `p7`.
- `analysis/test_e5_formal.py`: a direct fixture where a control centroid is far
  above the boundary but the rate is 0.1% (must pass), and 0.3% (must error).

No change to the benchmark binary, CDK, or result schema beyond P7's diagnostic
fields.

## Budget and authorisation

- New ceiling: **US$30**, including failed attempts.
- Planning proxy after formal v3: **US$16.996**.
- Three replications at ~US$2.60: **US$7.80**; total **US$24.796**; margin
  **US$5.204**.
- Run them **sequentially**, one at a time, with a review and a fresh pricing
  snapshot between runs. Stop on a protocol `ERROR`, a teardown failure, or if the
  refreshed envelope for one replication exceeds ~US$3.00.
- This authorises replications 2, 3 and 4 under this rule. It does not authorise a
  fifth, automatic retries, or any other experiment.

Actual billing allocation is still not invoice-verified; the proxy is conservative
and the margin is the guard.

## Limitations

- This is a post-hoc operationalisation change, made after seeing the formal-v3
  result. It is admissible only because it is dated and pre-registered before any
  run it governs, leaves the frozen run untouched, changes no target threshold, and
  is justified by a mechanism measured on a no-server tier — not by the desired
  outcome.
- The 0.2% limit is a materiality choice, not a confidence interval. At 60,000
  control operations it corresponds to 120 operations; the observed 10s count is 30.
- The rule does not establish why the first operation costs 9×; it only stops that
  cost from deciding a storage-attribution question.
