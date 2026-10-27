# Formal isolation method v3 — 2026-10-27

**Status: OFFLINE VERIFIED; LIVE FULL-METHOD VALIDATION OUTSTANDING. No new AWS run authorised or launched.**
Method identity: `isolation-formal-v3`. Instrument row identity stays
`rpc-phases-v2`. This is a new method, not a regrade or continuation of the pilot,
legacy diagnostic or short isolation candidate.

The [single accepted candidate](../../../../results/E5-isolation-validation/20261027T073803Z-647a811/review.md)
validated a two-probe quiet profile and isolated Lustre scheduling using short
windows. It did not validate the complete cohort-A method or the registered full
windows. This amendment makes the next full-method validation concrete and
reviewable before paying for it.

## Protocol fixed before the next paid run

1. Use one fresh, independently deployed E5 environment with the original six
   tiers, default mount options, per-family NFS superblocks, host seeding and
   at least 120 seconds seed age. Preserve mount/device checks and POSIX conformance.
   The main benchmark container stays unprivileged; the controller sidecar uses
   the opt-in host PID/config/root binds already tested by the candidate.
2. Capture original helper config, effective readahead on five TLS roots and the
   watchdog PID. Temporarily disable optimize_readahead and periodic stunnel
   health checks; retain one-second lifecycle supervision. No Lustre tuning.
3. Run the same **at least 360 actual monotonic seconds** of quiet idle with all
   five roots. Require zero GETATTR/LOOKUP/ACCESS increments and zero traced root
   statx/newfstatat calls. Check tracer liveness on every idle snapshot and at explicit stop; an early
   tracer exit is an error. Stop ptrace before cohort A or workload measurement.
4. Execute **complete cohort A**, one shuffled tier at a time: A1-A7, and A8w/A8
   on NFS tiers. Keep both 75-second expiry waits and ten A8 passes; A8w is recorded
   separately and not counted in A8. Record both actual monotonic-nanosecond waits per tier and bind them within
   the coordinator's cohort-A interval, with no overlapping waits.
   The original signature thresholds and Lustre counter semantics remain in force.
5. Execute four batches, each with **300 seconds warmup /600 seconds measured**:
   15 non-Lustre cells concurrently, then 0.1s, 1s and 10s Lustre/EBS pairs in order.
   The three EBS reference trees are fresh host-seeded `formal-lustre-control`
   subtrees, distinct from non-Lustre EBS trees. Wait for every child to be reaped
   before launching the next batch. Keep the validated opt-in CPU/wall/endpoint
   telemetry; never enable ptrace during workload measurement.
6. After all B readers stop, run the original post-B expiry probes on all twelve
   NFS cells, with at least **75 seconds measured idle**. These observe revalidation
   behaviour; they do not prove delegation state. The phase-D mount verification
   occurs before its idle timer starts, not during the idle interval.
7. Verify the quiet profile, effective readahead and stable watchdog PID outside
   measurement. Always attempt full original-byte restoration, including after
   phase or trace-stop failure, and verify restored config/readahead/PID. Upload
   partial receipts on failure; write a completion marker only after success.

The A/D phases reuse `e5-run` with explicit internal A/D dispatch; its ordinary
path retains A → concurrent B → D. The formal coordinator owns the new order and
never calls ordinary B. Full raw batch files remain separate from their canonical
cell exports. NFS exports contain exactly their own mount section; request and
CPU/wall exports must match the raw batch bytes (requests may be gzip wrapped).

## Grading and reference binding

`analysis/e5_formal_stats.py` is the only grader for this method. It validates
collector/method/completion identity, the runtime image digest, source commit,
unique deployment identity, packaged apparatus hashes, helper controls, idle
counters/trace, actual A wait coverage, conformance, A operation counts/sequences,
full B headers/windows, child commands/directories/lifetimes, exact export
bindings and post-B probe inputs before applying predictions.

- Keep original P1-P10 numerical thresholds, RPC phase/window reconciliation,
  histogram schema and **at most 5%** requests later than delta/2. No subtraction
  of background counters or relaxation of the lateness threshold.
- **P7 alone changes its EBS binding:** use the EBS cell from the same Lustre
  batch and interval. The non-Lustre EBS cell is ineligible as P7's reference.
  Keep both original P7 noise checks and its 1% support /5% kill thresholds.
- Structural/profile/provenance failures make every prediction ERROR for that
  replication. Original per-cohort/per-cell validity failures continue to make
  affected predictions ERROR. `full_method_validation=PASS` additionally requires
  all A/B/reference cells to be valid; it is separate from prediction grades.
- Aggregation still requires at least three evaluable independent deployments.
  The grader can read separately collected run directories, but rejects duplicate
  deployment IDs, mixed method inputs and different image/apparatus fingerprints.
  It records the exact current grader hashes and each replication's source/image.
  An n=1 pass cannot produce an aggregate hypothesis verdict.
- The legacy grader explicitly rejects formal-layout data, preventing accidental
  reuse of its original concurrent EBS reference binding. Prior analysis outputs
  remain frozen; offline reproduction is checked separately.

Sequential batches have different background loads. Do not interpret their raw
wall times as a fair cross-filesystem performance ranking or the quiet profile as
untouched EFS production defaults. P7 remains a latency test, not proof of DLM
lock state. No H1 conclusion follows solely from this amendment or the candidate.

## Deployment boundary and budget

The opt-in CDK context is `e5Formal=1`, mutually exclusive with diagnostic contexts.
The guarded collector kind is `formal-isolation`: **one fresh deployment only**,
no resume or automatic retry, results in `results/E5-formal/<run>/rep-1/formal/`.
No paid Make target is added. Merely running an offline selftest never deploys.

The formal guard allows 10800 seconds (three hours), including local build,
provisioning, measurement, normal deletion and collection; its independent cleanup
allowance stays 5400 seconds. ECS task polling allows 7200 seconds. Diagnostic
75-minute and ordinary-study six-hour guard ceilings stay separate. Expected
measurement work is roughly 85-95 minutes plus setup/deletion; live full-method
runtime is not yet measured.

The current total study ceiling is **US$20**, including failed attempts. At the
[latest existing pricing snapshot](../../../../results/pricing/20261027T072938Z-f8d53fd/pricing.json),
the maximum three-hour run plus 90-minute cleanup envelope is about US$4.3564
standing cost, with endpoint partial hours rounded separately; adding $0.50
ancillary reserve gives US$4.8564. This is an engineering estimate, not a bill or
verified remaining budget. Refresh allocation/billing, pricing and baseline before
any paid launch; the generic pilot preflight's historical $1.55 constant is stale.

This step authorises **zero paid runs**. The next approval should bind one fresh
full-method validation, its exact committed source, budget and teardown guard.
Only after checking full-method evidence should independently authorised runs be
considered for formal aggregation. Do not silently count prior methods toward n=3.

## Offline verification

```sh
make e5-selftest
make e5-diagnostic-selftest
make e5-formal-selftest
make e5-instrument-selftest
make e5-watchdog-synth-check
```

The full-window synthetic fixture validates all 21 cells and complete A/D inputs.
Negative controls cover profile/restore/trace, short/missing/overlapping windows,
wrong reference commands, conformance, A operation/expiry waits, NFS residuals,
the exact 5% lateness boundary, P7 matched-control noise, duplicate deployments,
method mixing and apparatus drift. Three independent synthetic deployments can
aggregate; one cannot. Linux tests exercise real short instrument loops and
packaging; they do not claim a full-duration NFS/Lustre or AWS run.

The first offline round caught a prediction-key mismatch (`P7` versus the legacy
`7` key); the aggregate test failed rather than silently approving the wrong
reference binding. [Failure receipt](initial-offline-failure.txt) is retained. The
coordinator-success fixture initially omitted the controller's trace file; that
fixture was corrected, preserving the check that a missing trace is ineligible.
The controller now also fails if an attached tracer exits early, so an empty trace
from a dead tracer cannot be accepted as a completed idle control.

Final receipts: [regression and full-window fixtures](selftest.txt),
[Linux instrument/packaging checks](instrument.txt), [credentialless offline CDK
synth/typecheck](synth.txt), [frozen evidence preservation](preservation.json),
[source hashes](sources.json) and [validation summary](validation.json).

Fourteen formal tests and ten Linux instrument tests pass. Existing grader,
attribution, diagnostic, controller and guard checks also pass. The 819 files in
all three retained runs are unchanged, both diagnostic analysis outputs reproduce
byte for byte, and current pilot grading matches the pre-amendment grader source.
No live AWS APIs or paid deployment were used in this implementation step.
