# E5 phase-attribution apparatus validation — 2026-10-26

This validates the amended instrument and classifier on a local kernel NFS server.
It is not an AWS experiment, latency finding, or steady-state prediction verdict.
The original full-timing local checks and all files under `results/` are untouched.

## Reproduce

```sh
make e5-selftest
make e5-local OUT=/tmp/e5-probe-on MODE=fast-probe
make e5-local OUT=/tmp/e5-probe-off MODE="fast-probe leases-off"
```

Run the two privileged NFS checks sequentially: the harness changes a Docker-VM
lease sysctl and restores its previous value on exit. Both saved runs started
from clean committed apparatus. They use the real image, seeder, entrypoint,
`e5-run.sh`, `agebench`, phase snapshots, local collection adapter and grader.
AWS `collect.sh` and S3 uploads are not exercised.

## Observations

| Server | Evidence | Recorded idle | Probe GETATTR at 0.1 / 1 / 10 s | Classification, all mounts | Server delegations sampled during idle |
|---|---|--:|---|---|---|
| leases on | [20261026T140455Z-bdd224f-probe-leases-on](20261026T140455Z-bdd224f-probe-leases-on/) | 75.01 s | 41 / 41 / 41 | REVALIDATION_SUPPRESSED | 4000–4000 |
| leases off | [20261026T140835Z-659cb32-probe-leases-off](20261026T140835Z-659cb32-probe-leases-off/) | 75.00 s | 1041 / 1041 / 1041 | REVALIDATION_OBSERVED | 0–0 |

All six NFS B cells across these two checks pass phase/window-counter integrity
and request-window gates. Counter operations are attributed independently to the
positive and negative phases; latency disagreement remains visible as diagnostic
output. Every saved probe contains N sequential positive stats and matching mount
sections. Server state independently agrees with the suppression/revalidation
classification in these local cases. The classifier itself does not claim direct
knowledge of delegations on AWS.

The implementation sources are the `git_commit` and image digest in each run's
`local-meta.csv`. Analysis was verified against `659cb32e2f133b7a5e14a56e865543b7f1311edd`. The two apparatus
commits differ only in compressed-input error handling/tests; C, runner and harness
are identical. All 164 copied evidence files are byte-identical
to their collection output. Each directory also retains CLI teardown output in
`harness.log`; its `SHA256SUMS` manifest covers the collected files and that log.

The [self-test log](20261026-selftest.log) records **59 synthetic grading cases and
25 regression tests**, including malformed/truncated compressed data, reset/missing
counters, wrong mounts, phase-boundary corruption, short/ambiguous probes and
noisy latency. Tests exercise `main()` writing both JSON and Markdown, not just
in-memory grading. Source comparison confirms all 19 original prediction constants
are unchanged; the dated amendment explicitly changes operational measurements.
Both tasks exited 0, their local containers exited, and both teardown logs record
restoring `fs.leases-enable` to 1.

## Limits and next gate

- `fast-probe` requests short A/B timings (2 s A waits, 6 s warm-up, 10 s measurement,
  seed-age gate skipped), but keeps a real 75 s idle probe. Request counts are
  rounded to the interval. Short A waits do not establish cohort A signatures;
  these checks do not establish P5 steady-state bands. Every aggregate prediction
  remains NOT EVALUABLE with one local replication and missing AWS tiers.
- Only the EBS-named block control and one loopback NFS mount family are present;
  six serve processes, not the 18-process AWS design. Local timings and measured
  counter-read overhead are not AWS estimates.
- Phase order makes positive stats pay shared-directory revalidation first.
  Rates count GETATTR/LOOKUP/ACCESS operations, not file-miss events; no binomial
  confidence interval or causal delegation verdict is produced.
- The idle probe can exclude an observed suppression regime from P5; observing
  revalidation after the window cannot prove absence of delegations throughout
  that earlier window. The timer-model verdict remains conditional on this limit.
- No AWS call, deploy or billable pilot was made. Add the Docker-external teardown
  watchdog next. Real EFS/TLS, ONTAP/OpenZFS, Lustre counters, canonical-duration
  windows and 18-process overhead still require the scoped AWS pilot checks.
