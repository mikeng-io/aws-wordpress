# E5 pilot preflight — 2026-10-26

**Decision: CONDITIONAL_PILOT_READY. No pilot launched.**

Observed from clean source `55d483ad90b770adb09cdcf1bed5131e95c45325` starting at `2026-10-26T14:58:22.512400+00:00`.
The [machine report](report.json) includes the source-script hash. Raw account
responses remain private in the ignored watchdog preflight directory.

## Verified

- **18 enabled regions**, 11 direct inventory checks per region, **zero API
  errors and zero live E5 matches**: CloudFormation, FSx filesystems/volumes/SVMs/
  backups, EFS, EC2 instances/volumes/NAT/endpoints and ECS clusters. These are
  direct service queries, not a lagging tag-index verdict.
- No E5 bucket remains. Seven E2 diagnostics buckets and four E5 Lambda log
  groups remain; they were not deleted. Other projects' resources are outside
  the E5 counts.
- Host credentials authenticate as an IAM user. All **12 watchdog API actions**
  simulate `allowed` with resource `*` and no missing context. This is policy
  simulation, not proof of live resource-policy/service-role/deletion behaviour.
- Host AWS CLI v2, Docker daemon, pinned runner image and region configuration
  checks pass; there is no unresolved local guarded run.
- Two historical E5 stacks are DELETE_COMPLETE. Root terminal events give
  approximately **74.8 and 18.4 minutes** from creation to deletion completion.
  These are stack lifecycle spans, not complete billing intervals; final backups
  and billing minimums can extend cost beyond them.

## Price and budget

Fresh snapshot: [`results/pricing/20261026T144948Z-71ece42`](../../../../results/pricing/20261026T144948Z-71ece42/).
The selected standing components remain unchanged: c7gd.large, twelve interface
endpoints and the three FSx arms total **$0.95475/hour**, rounded to ~$0.955/hr.
This subtotal excludes the root EBS volume, small EFS/S3/log usage, transfer/request
charges and billing-minimum effects.

At the existing 80–100 minute planning range plus the new 75-second probe, that
subtotal is **$1.29–1.61**. A **$2 pilot target plus $1 reserve**, added to the
attempt log's **estimated $1.55**, projects **$4.55** against the unchanged **$10
ceiling**. Estimated remaining before the pilot is **$8.45**. These are planning
figures, not a verified invoice balance or automatic spending cap.

Both `Study` and `Experiment` cost allocation tags are **Inactive**, and E5 is
absent from Cost Explorer tag values. Its filtered $0 response cannot establish
zero spend or complete historical attribution. The actual remaining budget is
therefore **UNVERIFIED**. No tags or billing settings were changed.

## Validation and next action

`make e5-preflight-selftest`: **6/6 checks passed**, covering permission/context
omissions, stale prices, active resources/API failures, unresolved state, budget
headroom and rejection of destructive/tag-activation API actions.

Reproduce with `make e5-preflight` on the pilot day. A deployment still needs the
recorded planning assumptions to be accepted, plus the runtime guarded preflight;
this receipt does not itself run or broaden the historical pilot-only go-ahead.
Run **one** pilot (`STOP_AFTER_REP=1 make e5-container REPS=3`), inspect conformance,
phase counters, probes, Lustre names, 18-process overhead and complete teardown,
then stop. Replications 2 and 3 retain their separate recorded go-ahead gate.

References: [simulation limitations](https://docs.aws.amazon.com/IAM/latest/UserGuide/access_policies_testing-policies.html),
[cost allocation tag activation](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/cost-alloc-tags.html).
