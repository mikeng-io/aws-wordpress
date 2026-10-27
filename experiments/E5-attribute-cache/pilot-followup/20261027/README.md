# E5 offline pilot follow-up — 2026-10-27

Baseline: `f8e3390`, pilot `20261026T152946Z-b1efcb2`. No AWS calls,
deployment or additional replication were made for this follow-up. The original
pilot directory, manifest, raw inputs and grading remain byte-identical.
**Still NOT READY for another paid run.** This fixes counter-name coverage and
narrows the remaining investigation; it does not establish an aggregate verdict.

## Lustre A1: counter coverage corrected

The deployed client reports `ldlm_ibits_enqueue` in MDC `stats`; its sample count
increases 8404 → 9445 (1041) during A1. `mds_getattr` stays at 2. The parser already
read these fields, but its signature allowlist omitted the IBITS name.

Upstream Lustre 2.15.6, pinned commit
`f7948c626181cda1f72d148adc73ad499eb60307`, establishes the counter path:

- [ldlm_cli_enqueue](https://github.com/lustre/lustre-release/blob/f7948c626181cda1f72d148adc73ad499eb60307/lustre/ldlm/ldlm_request.c#L1076)
  records extended enqueue types in client device statistics.
- [ldlm_svc_get_eopc](https://github.com/lustre/lustre-release/blob/f7948c626181cda1f72d148adc73ad499eb60307/lustre/include/lustre_dlm.h#L1640)
  increments the IBITS sample counter for inode-bit locks.
- [ptlrpc_lprocfs_rpc_sent](https://github.com/lustre/lustre-release/blob/f7948c626181cda1f72d148adc73ad499eb60307/lustre/ptlrpc/lproc_ptlrpc.c#L1268)
  suppresses the generic LDLM_ENQUEUE opcode statistic; the same file maps
  MDS_GETATTR_NAME to `mds_getattr_lock`, another missing recognized name.

The deployed AWS package is 2.15.6-32; this is upstream base-version source,
not an audit of every distribution patch. The observed raw counter names agree.
This is an enqueue/request signature, not a one-to-one file-miss probability or
proof that every enqueue completed a distinct successful server roundtrip.
The unchanged ≥0.95N gate now passes A1 with 1041 samples for 1000 stat operations.
The historical generic names remain supported. Sample counts are read, not
latency sums. A regression uses the actual frozen pre/post snapshots.

[Versioned A1-only reanalysis](lustre-a1-reanalysis-v1.json) retains original and
revised entries plus input/grader hashes. It does not overwrite `summary.json`
or revise P1 or any aggregate result. Future explicit full reanalysis must retain
its own version and provenance.

## Lustre 0.1s: measured service overruns propagate into lateness

[Scheduling diagnostics](scheduling.json) cover all 18 cells and hash their input
request files. For Lustre 0.1s:

- 1542/6000 requests start >50ms late (25.7%). The 5% gate is unchanged.
- 984 requests have positive + negative syscall elapsed sums >100ms.
- Syscall sum p50 9.956ms, p99 522.883ms, maximum 688.046ms.
- The existing lateness plus syscall sum of the previous request forces >50ms
  lateness on 1539 of the 5999 following requests. No lower-bound violations
  occur in any of the 18 cells.
- Recorded counter timing p99 is 416ns on Lustre, which has no per-request RPC
  snapshots. This field measures clock-call overhead there; it is not evidence
  that privileged snapshot polling is the cause of this cell's lateness.

For absolute deadlines, a lower bound on next lateness is
`max(0, current_lateness + stat_sum + enoent_sum - interval)`.
Histogram work, output and counters can only add time. The diagnostic includes
warmup-independent measured rows and makes no change to gates or grades.
Elapsed syscall time includes descheduling: these observations do not separate
server latency, client locks or host CPU pressure. Isolated versus concurrent
workloads and process CPU/wall telemetry are needed before choosing an apparatus
amendment. Do not silently increase the interval, discard slow requests or relax
the lateness limit. If 0.1s is genuinely overloaded, record that limitation rather
than treating its missing cache inference as a pass.

Reproduce without modifying the source run:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 analysis/e5_pilot_diagnose.py \
  results/E5/20261026T152946Z-b1efcb2 > /tmp/e5-scheduling.json
cmp /tmp/e5-scheduling.json experiments/E5-attribute-cache/pilot-followup/20261027/scheduling.json
make e5-selftest
```

Validation: all 59 synthetic grading cases, 26 attribution regressions and seven
scheduling diagnostics tests pass; see [test receipt](selftest.txt). Temporarily
removing IBITS recognition in memory makes the frozen-pilot regression fail;
restoring it passes. No tracked source file was changed for that mutation check.
All 289 original pilot manifest entries were verified unchanged. The scheduling
JSON was regenerated independently and compared byte-for-byte.

## TLS: concrete helper interference candidate, causality unresolved

efs-utils v3.3.2 resolves to commit
`39e24e4954342c3ef7b63498170761ae803d2ecd`:

- [check_efs_mounts and verify_and_update_readahead](https://github.com/aws/efs-utils/blob/39e24e4954342c3ef7b63498170761ae803d2ecd/src/watchdog/__init__.py#L1410)
  call `stat -c %d <mountpoint>` while verifying readahead. This happens in the
  mount loop when Linux/kernel/config checks permit readahead optimization.
- [Default configuration](https://github.com/aws/efs-utils/blob/39e24e4954342c3ef7b63498170761ae803d2ecd/dist/efs-utils.conf)
  enables optimize_readahead and a one-second watchdog poll. The separate `df`
  health check defaults to five minutes. These are distinct mechanisms.

Repeated root stat activity is consistent with periodic attribute revalidation,
but source inspection alone does not prove the producer/timestamps of the ten
extra GETATTRs per measured window. No effective host configuration or syscall
trace was captured in this pilot. Do not subtract ten or blame the five-minute
health check. Do not disable the watchdog as a whole: TLS lifecycle supervision
must stay functional.

Before another paid pilot, prepare a bounded idle/active reproduction that records
effective helper configuration, package/source identity, watchdog syscall timing
and the mount-scoped counter timeline. Compare readahead verification enabled
versus disabled while preserving and checking the same effective read_ahead_kb.
This is a proposed diagnostic intervention, not an approved study-method change.
Do not collect TLS private keys, credentials or complete helper state files.

## Next run prerequisites

1. Validate the TLS candidate and instrument inter-request counter activity;
   preserve independent window reconciliation. A gap counter alone cannot identify
   the producer or exclude concurrent helper activity inside a request phase.
2. Run an isolated/concurrent timing comparison for Lustre and document an
   apparatus amendment if the concurrency design changes. Existing raw evidence
   cannot reconstruct missing process CPU/wall/scheduler telemetry.
3. Reconcile billing/budget and record a separate go-ahead before any AWS retry.
   Replications 2/3 remain paused. No WordPress changes are needed for these gates.
