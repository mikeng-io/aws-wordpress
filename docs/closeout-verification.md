# Offline closeout verification — 2026-10-29

**19/19 reference checks PASS. All 5,082 pre-existing Git-tracked result files
retain their original SHA-256.** This is offline analysis replay, not a new AWS
experiment or additional independent replication. See the
[final receipt](../results/closeout/20261029T114956Z-40cdb91/verification.json),
[input manifest](../results/closeout/20261029T114956Z-40cdb91/inputs.sha256.json) and
[publication checks](../results/closeout/20261029T114956Z-40cdb91/publication-checks.json).

## What was checked

| Check group | Checks | Required agreement |
|---|--:|---|
| E0 baseline and corrected-cart census | 2 | Reparse 264 + 330 tracked straces; compare every recorded census JSON, summary and aggregate |
| E1 host topology | 1 | Two distinct recorded NFS mounts and two TLS proxy processes |
| E2 block/mount/FSx/FUSE reference collections | 4 | Every recorded JSON field agrees; current extra diagnostics do not become new historical grades |
| E3 statistics and clustering | 2 | Recorded stats/cluster JSON fields agree |
| E4 formal hydration and both campaign cost proxies | 3 | Recorded formal statistics and cost-estimate fields agree; no task/endpoint proxy becomes actual invoiced spend |
| E5 frozen validation, three formal-v3 runs and pooled set | 5 | Full recorded JSON fields agree under the hash-selected grader and matching-revision helpers |
| E5 P4 pass diagnostic | 1 | Diagnostic command completes with 12 tier/run rows; it does not alter the v3 grade |
| Published E2 chart | 1 | HTML reproduces byte-for-byte from its declared block-group source run |

The E5 check includes **per-replication grades and aggregate eligibility**.
An individual run's aggregate is NOT EVALUABLE at n<3, even when its per-rep P7
is SUPPORTED. The older validation's per-rep P7 remains ERROR; the later pooled
three-run P7 is SUPPORTED. [Grade scope](../results/closeout/20261029T114956Z-40cdb91/grade-scope.json)
shows this distinction without reinterpreting a single-run aggregate as a pass.

## Failed verifier attempt and bounded reuse

The [initial attempt](../results/closeout/20261029T114956Z-40cdb91/initial-verification.json)
passed 14 checks but failed five E5 imports: the replay utility extracted the
recorded graders without their transitive E2 statistics helper. The
[sanitised exception](../results/closeout/20261029T114956Z-40cdb91/initial-e5-import-error.txt)
is retained. This was an orchestration error, not a changed observation, failed
benchmark or reason to weaken a grade.

The utility now restores E2/E3 helper files from the same Git revision matching
the three recorded E5 grader hashes. Their hashes are recorded in the final
receipt; the original E5 records did not include transitive-helper hashes.
Missing historical source fails closed rather than silently selecting today's
rules.

The second attempt reran 17 checks. It reused only the two expensive E0 PASS
checks after verifying that the complete frozen input manifest and both
census/aggregate source hashes were identical. The final receipt binds the
initial report by SHA-256. Guards also prove reuse is refused when the parser
hash changes. This is disclosed reuse of a completed check, not two new data
collections or a second parse of the traces.

## Reproduce from a fresh checkout

```sh
make study-index
make study-verify OUT=/tmp/a-new-study-closeout
```

The default command executes all checks without reuse. Full local Git history
is needed to recover hash-selected historical E5 graders. The tool strips AWS
environment credentials, invokes only local Python analysis/Git, copies only
Git-tracked result inputs into disposable directories and refuses an existing
output directory or an output nested in a frozen experiment/pricing run.
It does not invoke make collectors, Docker, CDK, AWS CLI or pricing refreshes.

A local operator can explicitly use `--reuse-e0 <prior-verification.json>` with
the Python entrypoint; reuse requires an exact input manifest and unchanged E0
analysis source. Adding/changing tracked result files invalidates that reuse.
The normal fresh replay does not require the prior local scratch directory.

Verbose stdout/stderr remain local; published receipts carry the comparisons,
source hashes and input hashes without generated host paths. The source_head in
the receipt is the prior repository/data head; analysis_sha256 records the new
utility while it was being added. This is not a new clean-apparatus measurement.

## Limits of this closeout check

- Failed/partial campaigns, smoke/pilot/diagnostic methods and spot checks are
  classified in [the index](evidence-index.md), not pooled or retrospectively
  validated as formal collections. The check list above defines replay scope.
- Reproducing a statistic does not remove a construct problem: NFS cache mode,
  Lustre throughput residency, P4 phase mismatch and count-to-request composition
  remain limitations even when replay is exact.
- JSON comparison requires all existing fields to match, including negative
  grades and exclusions. Additional diagnostics may appear under current analysis
  without changing the original record. HTML comparison is byte-for-byte.
- This is not a CDK/build gate, hosted CI, live runtime test, fresh teardown audit,
  billing reconciliation or production application benchmark.
- The index renderer reproduces byte-for-byte and refuses unclassified/duplicated
  runs. Its role labels are reviewed interpretation, not inferred from file counts.

The [study closeout](study-status.md) retains these limits and the unresolved
hypotheses. [Operational retention/cost follow-up](retention-and-cost.md) is
separate; no deletion or new paid collection was executed.
