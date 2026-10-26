# E5 host teardown watchdog

Implemented 2026-10-26 after the Docker-loss failure recorded in the E5 attempt
log. The supported billable entrypoint is `make e5-container`; direct `make e5`
is now an internal runner command and refuses without a live host lease.
No AWS pilot or live deletion was performed to validate this change.

## Launch and observe

Host requirements are Python 3 with POSIX `fcntl`, AWS CLI v2, working credentials
from the local `.env`, and Docker for launching the pinned runner. Cleanup itself
uses host Python and AWS CLI, without Docker, Node or CDK.

After the study's pricing/budget/baseline preflight, the pilot command remains:

```sh
STOP_AFTER_REP=1 make e5-container REPS=3
make e5-watchdog-status
```

The launcher prints the exact container ID for `docker logs -f`. It creates a
stopped container, acquires the study lock and starts an independent host process
with a new session and inherited lock descriptor. Only that supervisor starts the
container. The lock serialises local guarded launches and recovery. State and boot
evidence are under `.e5-watchdog/<token>/`, ignored by Git; credentials are inherited
in memory, never put in state or command arguments.

`state.json` carries the phase, heartbeat, supervisor PID, container ID, observed
Stack ARNs, source IDs and remaining resources. `complete` plus `cleanup_verified`
means cleanup was verified, **not** that the experiment succeeded. Check
`runner_exit`, `stop_reason`, replication output and grading separately.

## Failure handling and ownership

- E5 deploys with `--method direct`: default change sets create an untagged
  REVIEW_IN_PROGRESS placeholder before execution. The guard never assumes
  ownership of such a placeholder, and an unowned same-name stack prevents a
  successful cleanup verdict.
- The E5-only `E5WatchdogRun` tag binds each launch to its CloudFormation stack,
  FSx resources and buckets. The guard verifies account, region and tags, then
  deletes by unique Stack ARN, not a reusable stack name. Unrelated E5 tags alone
  never select a stack or backup. The collector's tag-based backup sweep now also
  requires the launch token.
- Every replication checks the read-only host state, a fresh heartbeat, account
  identity and genuine stack absence before arming its deploy trap. Permissions
  errors are not absence. The host writes `cleaning` before stopping the runner
  or mutating AWS, so a daemon-restored runner cannot start another replication.
- Runner exit (including exit 0), Docker unavailability for 60 seconds, an AWS
  observation error or the six-hour run limit enters cleanup. Operational timers
  are monotonic; heartbeat timestamps are for cross-process lease checks.
- Cleanup re-discovers owned stack history and persists resource and rollback-event
  IDs. It deletes owned stacks, then sweeps backups by captured FSx source IDs or
  this run's exact tags. AVAILABLE/FAILED backups are deleted; other lifecycles
  remain pending. Two empty observations at least 60 seconds apart are required
  after stacks disappear. The cleanup budget is 90 minutes, with bounded CLI calls.
- A captured diagnostics bucket is copied to the private host evidence directory
  before deletion, after checking its ownership tag and expected account. Copy or
  ownership failure preserves it and prevents a successful verdict.
- Success also requires Docker to confirm the old runner is stopped/absent. AWS
  cleanup continues while Docker is down; permanently unconfirmed runner state
  ends `failed`, even if the AWS lists were empty. A new launch refuses unresolved
  previous state.

CloudFormation accepts a unique Stack ID for
[DeleteStack](https://docs.aws.amazon.com/AWSCloudFormation/latest/APIReference/API_DeleteStack.html).
The E5-only resource tags use the standard
[CDK tagging mechanism](https://docs.aws.amazon.com/cdk/v2/guide/tagging.html).

## Recovery and limits

After restarting Docker or restoring host AWS credentials:

```sh
make e5-watchdog-status
make e5-watchdog-recover
```

Recovery reuses the latest persisted ownership/source IDs, obtains the host lock,
checks the original account and retries cleanup; it never deploys. The internal
CLI also accepts `recover --directory <saved-directory>` for an older saved run.
Retain state until its resources have been reconciled. It is operational evidence,
not immutable benchmark output.

This is a host backstop. It cannot execute while the workstation is powered off,
asleep, disconnected, or its supervisor is killed. After reboot, recovery must be
run; the unresolved-state check prevents a new guarded launch from bypassing it.
Expired credentials, missing AWS permissions, service errors or a stuck deletion
remain explicit failures. This adds no remote scheduler or cloud safety service.
Keep the existing `caffeinate -i` preflight. The guard is not a dollar-denominated
budget controller; historical cost estimates and the study's $10 ceiling still
need operator reconciliation before a pilot.

## Reproduce validation

```sh
make e5-watchdog-selftest
make e5-watchdog-synth-check
```

Fault injection uses fake AWS/Docker backends and a real detached-process/parent-
kill/lock-inheritance check. The synth check installs locked public npm dependencies in a temporary isolated
volume, then runs pinned Node 22.17 with networking disabled, dummy account/AZ
context, typechecking, tagged and untagged syntheses,
resource-tag assertions and invalid-token rejection. These verify implementation
behaviour, not IAM permissions or real CloudFormation/FSx deletion timing.
The dated [validation receipt](../experiments/E5-attribute-cache/watchdog-validation/20261026/README.md)
records the checks. Real AWS cleanup and the pilot-specific measurement checks
remain unverified until a scoped live run.
