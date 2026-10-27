# Isolation candidate v1 — 2026-10-27

**Status: OFFLINE VERIFIED; LIVE ACCEPTANCE AND BUDGET CLEARANCE OUTSTANDING.**
This prepares the next validation method from baseline `e0a1013`; no live AWS account API call,
new deployment, current host-config change or paid run was performed in this step.
The original study path, grader, timings and thresholds remain unchanged. The
candidate is diagnostic-only and cannot be resumed into or pooled with either
frozen run. No formal replication has been authorised by this amendment.

## Why this change

The [AWS diagnostic](../../../../results/E5-diagnostic/20261027T042037Z-7d9be14/review.md)
observed TLS root activity controlled by readahead verification, but active off
windows still had two GETATTRs near the separate five-minute helper path. Lustre
lateness reproduced under 18-cell concurrency (23.2%/21.5%) versus isolated
execution (0%/0%). Shared metadata lock churn is a candidate mechanism, not a
proven fixed cache-capacity limit or a CPU-only explanation.

## Candidate protocol

Outer method identity is `isolation-candidate-v1`; the unchanged C request format
is still `rpc-phases-v2`. New results must be labelled `E5-isolation-validation`,
with `study_replication=false` and a fresh deployment. The candidate requires the
validated one-second watchdog poll, stable watchdog PID, the existing mount/seed
layout and seed age at least 120 seconds.

1. Capture selected original helper config and effective read_ahead_kb. Apply a
   temporary **quiet** profile: optimize_readahead=false and
   stunnel_health_check_enabled=false. The watchdog itself stays enabled, so its
   process/certificate lifecycle supervision remains active. This is an explicit
   measurement configuration, not untouched production defaults.
2. Observe at least **360 measured idle seconds**, crossing the five-minute probe
   cadence. Record all five TLS root counters and path-filtered watchdog descendant
   statx/newfstatat calls. Require zero GETATTR/LOOKUP/ACCESS increments and zero
   traced root stat calls. This does not require all NFS traffic, such as lease
   renewal, to disappear. Metadata reads happen before/after windows.
3. Stop ptrace. Run the 15 non-Lustre cells concurrently (EBS plus four NFS tiers ×
   three intervals), with 60s warmup /360s measured. Keep every cell and its
   independent window counters, per-request endpoints and CPU/wall diagnostics.
4. Run **three sequential Lustre/EBS pairs**, one interval at a time: 0.1s, 1s,
   then 10s; 60s warmup /180s measured per pair. One Lustre working set is active
   at a time, with a same-time EBS noise reference. No other tier workloads overlap
   these pairs. EBS references have fresh `diag-lustre-control` subtrees, separate
   from the EBS data in the non-Lustre batch. All 21 cell subtrees are seeded by
   the host and aged before use. No Lustre cache parameter is tuned.
5. Recheck the quiet config, effective readahead and watchdog PID outside measured
   windows. Attempt original-byte restoration even if trace shutdown fails. Verify
   selected original config/read_ahead_kb and full-byte restoration, without
   exporting complete config or secrets. Always retain partial receipts on errors.

About 25 minutes of requested idle/workload windows, plus compilation, control
handshakes, conformance, provisioning and cleanup. The short windows are validation
windows, not the registered 300s/600s study windows. Non-Lustre versus Lustre cells
have different background loads and must not be used as a fair cross-filesystem
latency comparison. Matched EBS references are retained for future P7 noise
eligibility; this candidate checker does not issue P1-P10 or H1 verdicts.

## Candidate acceptance

`analysis/e5_diagnostic_stats.py` reports `PASS_CANDIDATE_ONLY` only when:

- The method/completion identities agree and all raw inputs are complete and valid.
- Exactly 18 target cells plus three matched EBS references exist, with the declared
  intervals, warmup and measured counts. Missing cells or references are errors.
- The idle control spans at least 360 seconds and has all five TLS roots; its
  GETATTR/LOOKUP/ACCESS deltas and helper root trace are zero.
- Both probes are off, lifecycle supervision remains on with stable PID, effective
  read_ahead_kb is unchanged, and original bytes/config are restored.
- **The original hard gates remain**: no more than 5% of requests later than
  delta/2, and exact positive+negative phase reconciliation with independent NFS
  window counters. No residual subtraction, gap allowance or larger lateness limit.
- Batch identities/timings match and the next batch's launch follows the previous
  batch's last observed child reap. Reap timestamps are observations, not exact
  process exit timestamps. One Lustre interval plus its EBS reference per pair.

A synthetic fixture pass is not live acceptance. Even a future live candidate pass
will not validate the full cohort-A/expiry-probe method or amend the formal P7
reference binding automatically. Those require an explicit new study-method
version and grader provenance before independent formal replications.

## Implementation and guard separation

The host controller now writes config atomically, preserves permissions/ownership,
whitelists metadata, honours CACHE_CTL_DIR consistently and restores original bytes
on exit. The sidecar's TERM/INT handler exits instead of resuming its polling loop;
its exit handler stops/reaps the controller. The Linux integration test exercises
an actual failed profile metadata read followed by SIGTERM and byte restoration
inside an ephemeral container, with no host config bind or privileges.

The opt-in CDK context `e5IsolationValidation=1` requires diagnostic mode, selects
only candidate seed subtrees/profile and rejects use as an ordinary study stack.
The collector/guard run kind `isolation-validation` accepts one fresh deployment
only, disallows resume, retains the 4500s run /5400s cleanup ceilings and uses the
separate result directory. The old diagnostic profile and ordinary study defaults
remain separate. No paid Make target has been added for this candidate.

## Verification and next step

Reproduce offline checks:

```sh
make e5-diagnostic-selftest
make e5-instrument-selftest
make e5-watchdog-synth-check
```

Receipts: [targeted checks](selftest.txt), [Linux integration](instrument.txt),
[credentialless offline synth](synth.txt), [preservation proof](preservation.json).
The first Linux run [caught an IPC-directory mismatch](initial-ipc-failure.txt);
after fixing the controller to honour the shared override, the new shutdown test
and the full targeted Linux set pass. The synthetic fixture initially omitted a
required host metadata field; that fixture error was corrected before acceptance.

Before any AWS validation, refresh Cost Explorer, the engineering envelope and
unposted-spend reserve against the US$10 study ceiling. The prior run's US$9.66
planning receipt/approval must not be reused: that diagnostic is already complete
and its final billed allocation is still unverified. Existing generic pilot
preflight budget constants are not a current candidate budget clearance. Then
record authorisation for one candidate run, verify its raw acceptance and teardown,
and only afterward decide the formal method, matched-control binding and budget
for independent replications. No candidate launch was performed here.
