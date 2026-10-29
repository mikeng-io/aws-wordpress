# Proposal — P4 checks A8's first pass, not ten pooled passes (2026-10-29)

**Status:** `PROPOSED 2026-10-29; NOT BINDING; COMPLETED RUNS NOT REGRADED`.
This is a proposal for a future E5 method version. It does **not** change the
registered P4 grade of the three 2026-10-28 replications, which remains
**INCONCLUSIVE**, and it authorises no run.

**Evidence:** [E5 finding](../../../../docs/findings/E5-attribute-cache.md#p4-is-now-the-open-instrument-question),
the three formal reviews, and `make e5-p4-passes` over the committed raw CSVs.

## The problem

P4 is the manipulation check for A8, the forced-miss mount: it asks whether A8
measures the same cost as A3, the real revalidation. The registered form is A8's
pooled median within ±25% of A3 on each NFS tier.

That comparison is not like-for-like. A8 runs **ten passes** (`E5_A8_PASSES=10`,
signature Δ=10000) while A3 runs **one pass** after the 75 s idle. Pooling all ten
A8 passes averages nine warmed passes into the estimate. In replication 4 this is
the whole OpenZFS failure:

| tier, rep 4 | A3 | A8 pass 1 | A8 passes 2–10 | A8 all / A3 |
|---|---:|---:|---:|---:|
| EFS plain | 356.5 µs | 259.1 µs | 254.9 µs | 0.716 |
| EFS TLS | 335.7 µs | 431.5 µs | 432.1 µs | 1.287 |
| OpenZFS | 98.0 µs | **98.0 µs** | 68.3 µs | 0.701 |

On OpenZFS the first pass matches A3 exactly (98.0 vs 98.0); the pooled 0.701 is
nine warm passes. First-pass ratios across all three runs are 0.727–1.285, inside a
factor-of-two band. The all-pass ratios reach 0.701–1.287 and fail ±25% on three
tier-cells.

First-pass selection alone does not make the old ±25% window pass: EFS plain is
0.727 and EFS TLS is 1.285 in rep 4. The tolerance, not just the pass selection, is
the issue. ±25% is an equivalence test; P4 is a manipulation check. It needs to
detect that A8 is not measuring forced misses, not to assert that two different
mount configurations agree to a quarter.

## Proposed rule, for a future method version only

For each NFS tier in a replication:

1. Keep the existing A8 signature check: `GETATTR Δ=10000 LOOKUP Δ=0 READ Δ=0`.
   A signature failure makes the replication **not evaluable for P4** (`ERROR`), as
   today.
2. Compute A8's median over its **first 1,000 `stat` operations** (indices 0–999)
   and A3's median over its 1,000 operations.
3. P4 is `SUPPORTED` if the ratio is in **[0.5, 2.0]** on every NFS tier, and
   `REFUTED` otherwise. A8 is then usable (or not) exactly as today.
4. Report the all-pass ratio and the pass-by-pass medians as diagnostics. They do
   not grade.
5. Preserve the full raw operation stream. This changes which operations are read
   for the check, not what was measured or stored.

The [0.5, 2.0] band is the same factor-of-two band P1 uses for tier-cost
reproduction. It is deliberately coarse: a cached A8 would sit near 0.01× and a
different operation would sit well above 2×, so the check still catches the failure
it exists to catch. It is not fitted to the observed 0.727–1.285; that range is a
consequence of mount and timing differences, and the band is wider than all of it.

## What does not change

- The completed three-run P4 verdict: **INCONCLUSIVE**. No run is regraded.
- P1–P3, P5–P10, P7's rule, the target thresholds and the 0.1/1/10 s design.
- The A8 mount, its ten passes, or the raw data. Only the read used by P4 changes.
- Budget: no run is authorised by this proposal.

## Implementation, deferred

No code change is made now. The v3 grader keeps the registered ±25% all-pass rule,
which is why the completed set remains INCONCLUSIVE. If a future replication is
authorised, the method identifier must be bumped and the new check implemented in
`analysis/e5_stats.py` behind that identifier, with a fixture that distinguishes
first-pass from all-pass. Re-running a v3 result under the new rule would be a
regrade and is forbidden.

## Limitation

This is a post-hoc proposal written after seeing the failure. It is admissible only
as a dated proposal for a future method: it leaves every completed verdict intact,
changes no target threshold, and is justified by a measured pass-count effect
(98.0 µs → 68.3 µs on OpenZFS), not by the desired outcome. It should be adopted or
rejected before any future paid replication.
