# E5 single AWS diagnostic review — 2026-10-27

**Decision: diagnose the remaining attribution and amend isolation before formal replications.**
The authorised single diagnostic completed all planned phases and retained every
cell. It confirms helper-induced background root activity and reproduces Lustre's
concurrency sensitivity. It is not a registered E5 replication and cannot be
pooled with the original pilot or used for an aggregate/H1 verdict.

Source `7d9be14ee89fd8b8ebd1f4a55daf6c1ec166b979`; run
`20261027T042037Z-7d9be14`. Singapore ap-southeast-1a, c7gd.large. Kernel
6.1.188-233.393.amzn2023.aarch64, efs-utils 3.3.2-1 and Lustre client
2.15.6-32 match the original pilot. Seed age was 201s at diagnostic start.
All six conformance summaries have TOTAL_FAILURES=0 and TOTAL_ERRORS=0.
All 44 cells have complete, internally consistent diagnostic inputs, including
request counts/operation counts, CPU/wall telemetry and RPC endpoint wiring.
This does not mean they pass the unchanged registered validity gates.

See [analysis-v1.json](analysis-v1.json), [runtime protocol](rep-1/diagnostic/protocol.json),
[collection metadata](rep-1/meta.json) and the [authorised plan](../../../experiments/E5-attribute-cache/diagnostic-plan/20261027/README.md).
After the first read-only analysis, the 327 raw diagnostic files were hashed and
verified byte-identical through subsequent analysis and final preservation. Empty off-arm traces are retained as evidence.

## TLS: one interference mechanism confirmed; residual remains

Three steady-state TLS mount roots show GETATTR increments **2 / 0 / 0 / 2**
for readahead-verification **on / off / off / on**. Each observed idle window is
about 126.3 seconds (120s requested plus control handshakes). Effective
read_ahead_kb stayed identical across switches. The watchdog stayed enabled.

The actual watchdog and its descendants were traced only in idle windows:
600 root statx calls in each on arm, zero in both off arms. There are additionally
10 and 8 root newfstatat calls in the on traces, arranged in same-child pairs.
The installed helper source is preserved with boot diagnostics for version matching;
its SHA-256 is recorded in analysis provenance. Its readahead and health-check
function ASTs match the inspected upstream v3.3.2 functions, although the whole
installed script is not byte-identical to that upstream checkout.
These are direct observations of helper-descendant root activity, separate from
application data-file stats.

Active windows were 60s warmup +180s measured, three intervals concurrently per
arm, fresh data subtrees and no ptrace. Positive+negative phase RPC counts do
**not** reconcile with independent windows even when readahead verification is off:

| Interval | On: window minus phases, GETATTR | Off: window minus phases, GETATTR |
|---|---:|---:|
| 0.1s | 4 | 2 |
| 1s | 4 | 2 |
| 10s | 3 | 2 |

Every difference is visible in the independently recorded inter-request endpoint
gaps. This locates the operations outside request phases; it does not identify
their producer or exclude background operations inside phases. No subtraction,
tolerance or modified validity gate has been applied.

Off-arm pairs occur together around 05:03:09 UTC. Extra on-arm pairs occur around
04:58:09 UTC, approximately five minutes earlier. The restored selected config
confirms a five-minute df health check remained enabled. Idle traces show paired
newfstatat calls around 04:48:06-07 and 04:53:07-08. The helper source's separate
df health-check path and the cadence make it a strong residual-source candidate.
Active windows were not traced, and execve was not recorded: attributing each
active residual operation specifically to df remains an inference, not a direct
per-RPC producer proof. The original pilot had no trace, so its ten historical
operations cannot be individually attributed retrospectively.

[Original selected helper config and host clock pair](helper-original-config.json)
were read after restoration, during the Lustre phase. RPC gap timestamps in the
analysis are monotonic; use unix-minus-monotonic from that clock pair to reproduce
the UTC comparison. The original config had optimize_readahead=true, watchdog
poll_interval_sec=1, enabled=true and health-check interval 5 minutes.

## Lustre: the concurrency effect is reproducible

Same 1000 positive +1000 negative stats/request; target interval 0.1s, 60s warmup
and 180s measured. Each round has 1800 measured target requests and a fresh target
subtree. Concurrent rounds also have fresh subtrees for the other 17 cells.

| Round | Mode | Requests >50ms late | Mean request service wall | Mean thread CPU |
|---|---|---:|---:|---:|
| 1 | isolated | 0/1800 (0%) | 9.055ms | 9.036ms |
| 2 | 18 cells | 417/1800 (23.17%) | 51.270ms | 16.111ms |
| 3 | 18 cells | 387/1800 (21.50%) | 49.565ms | 16.133ms |
| 4 | isolated | 0/1800 (0%) | 9.755ms | 9.732ms |

Only the two concurrent Lustre 0.1s cells exceed the existing 5% lateness limit.
351 and 304 requests respectively have syscall sums already exceeding 100ms;
none do in isolated rounds. The original pilot's 25.7% lateness is therefore
reproduced under concurrency without changing its threshold.

Thread CPU/service wall shares are about 99.8%, 31.4%, 32.5%, 99.8%. These are
ratios of request service times, not host CPU utilisation. Off-CPU time cannot
separate client/server waits, client locks and scheduler descheduling. No claim
that CPU pressure has been excluded is justified.

### Exploratory shared lock-cache evidence

Read-only lctl snapshots were added during the diagnostic; they were not a
predeclared protocol gate and do not alter tuning. Cumulative MDC IBITS enqueue
samples increase from 976941 at 05:11:38 to 1873183 in the later concurrent
snapshot. In isolated round 4 they stay at **1915200** between 05:17:16 and
05:19:32. During concurrent snapshots metadata/object lock counts are around 1600;
lru_size reads 1600 and lru_max_age 600000ms. Negotiated import flags include
lru_resize and the advertised metadata pool limit is much larger.

This is evidence of metadata lock churn accompanying concurrency, rather than
proof of a CPU-only explanation. All three Lustre intervals share one client
lock namespace, unlike the distinct NFS superblocks used for their intervals.
The three separate 1000-file working sets can interact through that cache.
A particular eviction policy or a fixed 1600-lock cap has **not** been proved.
The version-matched upstream [lru_size getter](https://github.com/lustre/lustre-release/blob/f7948c626181cda1f72d148adc73ad499eb60307/lustre/ldlm/ldlm_resource.c#L294)
can report either an unused count or a configured cap depending on resize mode;
its numeric readback alone cannot distinguish those cases. The same source shows
that writing `clear` flushes unused locks without selecting a numeric cache size.
No cache-size intervention was performed, and the deployed AWS package's patch
set has not been fully audited.

Snapshots: [round 2](lustre-locks-during-round2.txt),
[round 3](lustre-locks-during-round3.txt), [round 4 early](lustre-locks-round4-start.txt),
[round 4 late](lustre-locks-round4-late.txt). Periodic read-only SSM status checks
and these exploratory local kernel reads are additional observers; their overhead
has not been quantified. Neither the host metadata reads nor these snapshots
change filesystem tuning.

## What to change next

1. Specify and validate how measurement will separate both readahead verification
   and the five-minute helper path from data-file RPCs. Keep independent window
   reconciliation. A proposed isolation mode may retain TLS lifecycle supervision
   while controlling both probes, but it must be labelled as an explicit method
   amendment and preserve effective read_ahead_kb. Alternatively use file-identity
   instrumentation to attribute background traffic under production defaults.
2. Isolate Lustre interval cells (serial intervals or independent clients) before
   evaluating per-interval cache behaviour. Distinguish the 1000-file question
   from the shared three-working-set contention question. Do not silently tune
   cache capacity or treat the concurrent cells as independent cache experiments.
3. Predeclare the amended method, validate it, reconcile the remaining budget,
   and start a new independent study run only with its own authorisation. This
   short diagnostic cannot fill replications 2/3 of the original method.

The filesystem research objective is unchanged. WordPress remains the motivating
entry point; no WordPress polish, cache-adapter implementation or production
recommendation follows from this diagnostic. The present issue is validity and
isolation of the filesystem measurements.

## Preservation, validation and costs

The original pilot's raw data, summaries, thresholds and 289 manifest entries are
unchanged. Diagnostic analysis writes a separate JSON report and stdout only.
Seven analysis fixture tests cover phase/window/gap separation, invalid clocks,
truncation, resets, incomplete protocols, independent window coverage and missing planned cells. Preparation retained 34 watchdog,
four controller and seven Linux instrument tests plus credentialless synthesis.

The [budget receipt](../../../experiments/E5-attribute-cache/diagnostic-plan/20261027/budget.json)
uses reported all-account Singapore spending (US$5.5382) as a conservative starting
point, US$1 unposted reserve, the maximum run+cleanup standing subtotal and US$0.50
ancillary reserve, for a planning total of about US$9.66 against the US$10 study
ceiling. It is not verified E5 allocation, an invoice, or an enforced payment cap.
Final billed dollars remain unverified because Cost Explorer is delayed and E5
allocation tags are not a reliable historical attribution source.

## Final teardown and operational outcome

The benchmark container exited **0**; [runtime image evidence](image-provenance.json)
records the actual ECS image digest. All raw diagnostic data and completion marker
were collected before deletion. The 75-minute host run ceiling was then reached
while normal CloudFormation deletion was still pending on ONTAP. The watchdog
fenced and killed the collector (Docker exit **137**) and completed cleanup itself.
This is not a claim that the collector exited successfully, nor a failed benchmark
being silently relabelled as success. See [guard summary](guard-summary.json).

CloudFormation creation: 04:21:42 UTC; DELETE_COMPLETE: 05:37:05 UTC, about
75.4 minutes including provisioning/deletion. The guard required its two empty
observations at least 60 seconds apart, verified the runner stopped, deleted scoped
final backups, and copied/deleted the diagnostics bucket. The recovered host
diagnostics are retained under rep-1/boot-diagnostics.

The subsequent independent read-only audit covered **18 enabled regions ×11 direct
service inventories =198 checks**, with **zero API errors**, no selected E5
resources and no E5 diagnostics buckets. See [teardown receipt](teardown.json).
Tag/name-selected inventories and the guard's source-ID backup sweep have distinct
scopes; the latter also covers owned untagged final backups. Retained shared CDK/ECR
assets and log storage are not a claim of zero future billing. The owned bounded
host sleep inhibitor was stopped after cleanup. No new diagnostic or formal
replication was launched.

[Post-run cost check](cost-review.json) still reports the same US$5.5382 regional
account total with estimated periods, so the new run is not independently billed
and allocated by this receipt. Applying the standing subtotal to the entire
75.39-minute stack lifetime gives an engineering envelope of about **US$1.20**,
excluding the separate ancillary/minimum-billing qualifications. It must not be
presented as actual incremental spend or added to Cost Explorer as if both were
verified disjoint charges.

Authored code/documentation pass the whitespace diff check. Retained raw proc
snapshots and runtime logs contain their original trailing spaces/blank lines;
these were preserved byte-for-byte rather than normalised to satisfy that check.
