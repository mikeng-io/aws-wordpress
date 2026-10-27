# Authorised single AWS diagnostic — 2026-10-27

User authorised the proposed TLS/Lustre diagnostic and budget reconciliation with
`ok go`. This is one fresh guarded deployment, not replications 2/3 or a study
method amendment. Baseline apparatus `56295b7`; launch uses the subsequent clean
implementation commit recorded in run metadata. Output is under
`results/E5-diagnostic/`, never the registered study's result directory.

## Protocol

Same six tiers, c7gd.large, Singapore AZ and default filesystem mounts as the pilot.
The main container remains unprivileged. Diagnostic mode alone adds host PID mode,
privileged sidecar access to helper config, and a read-only bind of TLS mount roots.
Normal study mode has none of those additions. Existing seed age ≥120s, file-size
verification and POSIX conformance checks remain in force.

1. TLS idle, **on/off/off/on** for readahead verification, 120 seconds per arm
   plus observed handshake overhead. Record actual watchdog descendant statx/
   newfstatat calls on the five TLS mount roots using path-filtered strace, and
   independent mount-scoped RPC timelines. Trace only idle windows.
2. TLS active, **on/off**, three intervals concurrently per arm, 60s warmup +
   180s measured. Fresh subtree per arm. Record identical read_ahead_kb across
   switches, selected effective config, CPU/wall and existing RPC endpoints.
3. Restore original helper config. Lustre **isolated/concurrent/concurrent/isolated**,
   60s warmup +180s measured per round. Isolated means the Lustre 0.1s cell only;
   concurrent means all six tiers × three intervals. Fresh seeded subtree per
   cell/round, preseeded through the host's seed mount and aged before use.

The watchdog stays enabled; its configuration is reloaded each poll. Only the
`mount.optimize_readahead` option is changed; original bytes are restored afterward.
No TLS private key, certificate, credential or complete helper-state export.
Selected config and read_ahead_kb metadata reads occur outside measured windows.
The helper's installed script (public program source) is retained for version
matching. Runtime package/kernel/image identities come from host provenance.

Short diagnostic windows do not equal the registered 300+600s windows. TLS active
on/off is not counterbalanced; idle controls and Lustre scheduling use ABBA order.
All these are diagnostic observations at n=1. No aggregate/H1 claim, no dropped
slow requests, no threshold changes and no relabelling RPC intensity as a literal
miss probability. Counter gaps still do not identify background activity inside
a request phase; use the idle trace/control as separate causal evidence.

## Stops, cost and cleanup

- Exactly one fresh deployment; diagnostic resume/replicate requests are rejected.
- Detached host watchdog enforces a **4500s run ceiling**, including setup,
  collection and normal teardown, then fences/stops the runner and retries scoped
  cleanup for up to 5400s. Stack ARN/account/region/token ownership is unchanged.
- Each serve child has its own warmup+measure+60s deadline. Config/trace errors,
  conformance/data errors and output failures fail the diagnostic, preserve partial
  files where possible, and trigger teardown. No automatic second attempt.
- Only explicit fixed host verbs are accepted: config on/off/restore, counters,
  trace start/stop. Trace filenames are restricted labels. No arbitrary host command.
- Collect FSx final backups and diagnostics, verify two empty observations ≥60s
  apart and runner stopped, then independently audit direct-service inventories.

[Budget receipt](budget.json) uses all reported regional account spending as a
conservative starting point rather than zero tag-filtered E5 spend. Planned total
including reserves is below the standing US$10 study ceiling. Billing is delayed;
these are planning assumptions, not an invoice or a guaranteed payment cap.
The generic pilot preflight's historical budget constants predate this diagnostic;
this receipt supersedes those constants for this run, not its inventory/IAM checks.

Validation retained here: control restoration/command rejection/mount identity,
watchdog fault injection including diagnostic launch guards/deadline, Linux
instrument integration, and offline credentialless diagnostic/study synthesis.

Launch only from the clean implementation commit:

```sh
make e5-diagnostic
```

The result review must distinguish TLS on/off effects actually observed, installed
version correspondence with the original pilot, and Lustre off-CPU versus CPU
evidence. A process's wall-minus-thread-CPU cannot distinguish network waits,
client lock waits or scheduler contention on its own. Failure to finish is an
apparatus failure to preserve, not evidence for a filesystem prediction.
