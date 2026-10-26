# E5 host watchdog validation — 2026-10-26

Source commit: `44b7645d6b236fca32c0dfa8f4c76508bb24bac3`. [Manifest](manifest.json) binds source and evidence hashes.
No live AWS call, deploy or deletion was used in these checks.

## Checks

- `make e5-watchdog-selftest`: **28/28 passed** ([log](tests.txt)). AWS and Docker
  operations are fake. One check spawns a real detached host child, kills its
  launcher parent, confirms the inherited lock survives, and completes fake-backed
  cleanup from that child. Other checks cover runner exit, temporary/permanent
  Docker loss, scoped ARN/token/source matching, delayed/CREATING backups,
  permission errors, monotonic deadlines, diagnostics preservation, partial
  provenance, recovery, stale/fenced leases and unresolved-run refusal.
- `make e5-watchdog-synth-check`: **passed** ([log](synth.txt)). Locked dependencies
  install into an isolated temporary Docker volume, removed on exit. Typecheck and
  synth then run with networking disabled, pinned Node 22.17.0, a dummy account and
  explicit dummy AZ context. Assertions verify the token on the E5 stack and its
  FSx/S3 resources, no token on other experiments or untagged synthesis, and invalid
  token rejection. No real account context or credentials are used for synthesis.
- Both shell scripts parse with `bash -n`; source whitespace checks pass.
- Existing `results/`, prior local NFS evidence, the grader and benchmark image
  sources remain unchanged from `0116a84`. Only the CDK ownership tag and guarded
  collection/launch lifecycle change.

## What remains unmeasured

This proves local control flow and offline tag generation. It does not prove the
host principal has every live AWS cleanup permission, that FSx final-backup tags
propagate in every failure mode, actual service deletion duration, a real Docker
VM restart, workstation reboot/sleep recovery, or an end-to-end AWS pilot.
Permanent Docker loss deliberately ends unresolved even after AWS lists empty:
runner quiescence must also be established. Host death requires manual recovery.
See [operations and limits](../../../../docs/e5-watchdog.md).

Next is the pilot-day baseline, pricing/budget and credential/permission preflight,
then the already-scoped single pilot replication. No experiment verdict changes.
