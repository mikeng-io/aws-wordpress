# E5 diagnostic apparatus — 2026-10-27

This follow-up starts from `062c8ef`. No AWS run or replication was launched.
The original pilot, grading and validity thresholds remain unchanged. These tools
prepare a diagnostic intervention; they do not amend the registered study method.

## Local root-stat mechanism control

The local kernel NFS harness now has a `helper-probe` mode. It mounts the same
loopback NFSv4.1 export twice with `nosharecache`, verifies different st_dev values,
warms both roots once, then compares 75 seconds of idle versus one
`stat -c %d <mount-root>` every second. `/proc/self/mountstats` sampling touches
neither measurement root. Both mounts have identical options; leases are disabled
for this check and restored afterward.

This models the command executed by the upstream efs-utils watchdog's readahead
verification, identified in the [source investigation](../20261027/README.md).
It is **not execution of the real watchdog, TLS or EFS**. A local GETATTR difference
supports the possibility of helper-induced root revalidation, but cannot identify
the producer of the pilot's ten extra GETATTRs. The exact effective helper config
and a syscall/counter timeline on EFS are still required. The five-minute `df`
health check is a separate mechanism.

Reproduce (local privileged Docker VM NFS only):

```sh
experiments/E5-attribute-cache/scripts/local-nfs-check.sh \
  /tmp/e5-root-stat-new helper-probe leases-off
```

The first attempt collected the counters but exited 1 during cleanup: the optional
SAMPLER variable was unset in this new branch and the embedded shell had lost its
test quotes. It briefly left a container waiting in kernel NFS shutdown. The
variable guard is now quoted correctly. Docker was not restarted. A targeted
SIGKILL was requested for the blocked process; it remained blocked immediately
afterward, then eventually exited. leases-enable was independently restored to 1.
The corrected harness was rerun to verify normal teardown. Use the corrected run
receipt here, not the first attempt as a successful cleanup claim.

Both attempts observed **0 GETATTR on idle versus 1 on the root-stat mount**,
with no LOOKUP or ACCESS increments. The corrected attempt exited 0, printed
`leases-enable restored to 1`, and its named container was absent afterward.
See [counter timeline](root-stat-probe.json), [mount options](probe-mounts.txt),
[local provenance](local-meta.csv) and [validation receipt](validation.json).
The captured wrapper metadata's `mode=full` and `timing=pre-registered defaults`
were dormant cohort settings: `helper_probe=1` selected only the 75-second probe.
The wrapper now labels this mode explicitly to prevent that ambiguity.

## Opt-in per-request telemetry

`E5_DIAGNOSTICS=1 agebench serve ...` adds `<prefix>.diagnostics.csv`:

- `start_ns`, `end_ns`: CLOCK_MONOTONIC around request processing, excluding the
  deadline sleep and following request/diagnostic CSV writes. Includes histogram
  work, raw CSV writes and counter snapshots. Other process output and boundary
  snapshots can still affect scheduling between requests.
- `thread_cpu_ns`: CLOCK_THREAD_CPUTIME_ID over that processing interval.
  Wall minus thread CPU is off-CPU time; it cannot separate server/client waits,
  lock contention and scheduler descheduling by itself. Kernel worker CPU is not
  this thread's CPU time.
- `rpc_start`, `rpc_end`: the existing r0/r2 mount counter samples, in
  GETATTR:LOOKUP:ACCESS order. No extra mountstats reads are introduced. Non-NFS
  cells emit `-`. Consecutive endpoints expose operations between request phases;
  they do not identify the process that caused them. The first measured request
  and window tail still require independent boundary reconciliation.

Telemetry defaults off. The normal request CSV remains `rpc-phases-v2`, and the
existing grader neither consumes the diagnostic CSV nor relaxes its window gate.
The extra clocks/output have overhead; a future study method that enables them
needs explicit documentation and comparison. Diagnostic output errors fail the
instrument. Invalid opt-in values fail rather than silently disabling capture.

## Isolated/concurrent runner for existing mounts

`scripts/diagnostic-serve.py` accepts a JSON list of explicit cells:

```json
[
  {"tier":"fsx_lustre", "directory":"/bench/fsx_lustre/ss-0.1", "delta":"0.1"},
  {"tier":"efs_host_plain", "directory":"/bench/efs_host_plain.ss-1", "delta":"1", "nfs_mount":"/bench/efs_host_plain.ss-1"}
]
```

This illustrates the format, not a complete 18-cell plan. Prepare all six tiers
and three intervals explicitly when reproducing the pilot's concurrency.

```sh
python3 experiments/E5-attribute-cache/scripts/diagnostic-serve.py \
  /tmp/cells.json /tmp/isolated-new --mode isolated
python3 experiments/E5-attribute-cache/scripts/diagnostic-serve.py \
  /tmp/cells.json /tmp/concurrent-new --mode concurrent
```

The runner mounts nothing, calls no AWS API and deploys nothing. It preserves
pilot raw-sampling cadence and defaults to 300s warmup / 600s measured. Isolated
executes each cell sequentially; concurrent launches all cells. Each command has
a warmup+measure+60s wall deadline, with cleanup on exceptions/interruption.
Existing output directories and duplicate cell identities are rejected.
Receipts record the plan, command, launch/reap timestamps, exit status, and
`study_replication=false`. Reap time is observation time, not exact process exit.

Before a real comparison, use fresh equivalent mounts/seed trees with the same
age gate, record mount/client versions and host CPU configuration, counterbalance
arm order, and retain both arms even on overload. Running sequentially after a
concurrent arm on warmed mounts is not a controlled comparison. This harness
does not enforce these environmental prerequisites or implement an AWS launcher.
Keep diagnostic receipts local until paths are checked for private values.

## Validation and remaining gates

`make e5-instrument-selftest` compiles current C with `-O2 -Wall -Werror` in the
Linux bench image and runs seven integration tests: real syscall/wall/CPU capture,
default-off behavior, bad opt-in, diagnostic disk failure, synthetic RPC endpoint
wiring, both runner modes with real agebench, failed children and output guards.
The RPC fixture is synthetic; it is not NFS/TLS causality evidence.

The existing attribution and scheduling diagnostics regressions also pass.
No registered gate was changed. TLS attribution, actual Lustre isolated versus
18-cell concurrency behavior, and budget reconciliation remain prerequisites
before a separately authorized paid diagnostic run. Replications 2/3 remain paused.
