# Retention and cost follow-up

This is the operational boundary of the 2026-10-29 study closeout. It does not
claim that destroying an experiment stack makes the whole AWS account free.
No AWS resource or retention/lifecycle configuration was changed by the offline
publication work.

## Evidence custody

| Evidence/resource | Decision for this closeout | Condition before later deletion |
|---|---|---|
| Committed raw experiment files and metadata | Preserve immutably | No deletion as cleanup; corrections get dated notes or new observations |
| Frozen derived grades | Preserve with their original method | Recompute in scratch; never apply a future rule to an old result |
| Referenced runtime image digests | Retain as reproducibility evidence | Export/preserve an independently verified image and source/toolchain first; a rebuild need not be bit-identical |
| Diagnostics buckets and provisioning logs | Retain pending evidence review | Export and compare required artifacts, then decide retention; a metadata inventory is not that comparison |
| Shared CDK bootstrap buckets/repository | Preserve | Check other users/projects and future build requirements before pruning |
| Unattributed images or old non-study data | Outside study cleanup authority | Establish ownership and explicit disposition; absence from one result's metadata does not prove safe deletion |
| Private account-wide audit/billing receipts | Keep on operator-controlled storage | Do not commit resource inventories, unrelated project details or local configuration to the public repository |

The operator-held 2026-10-29 audit found both retained study artifacts and
unrelated resources. This document deliberately carries no account-wide resource
IDs, bucket inventory or private billing ledger. The E4 [campaign cost receipt](../results/E4/20261029T091909Z-842d596/campaign-summary.json)
and [teardown receipt](../results/E4/20261029T091909Z-842d596/campaign-verification.json)
remain public evidence for their specific scope. They do not certify absence of
all account resources or all possible backup types.

## Cost interpretation

- The E4 [finding](findings/E4-hydration.md) labels task/endpoint cost as a proxy
  with ancillary exclusions, separately recording the failed readiness attempt.
- E5's [campaign envelope](../experiments/E5-attribute-cache/README.md#current-status-and-handoff-2026-10-28)
  is a spending plan, not an invoice or a per-request price.
- Account billing, workload spending and retained shared storage are different
  scopes. Do not add a study envelope to an account ledger total.
- A quiet day's bill extrapolated over a month is not a forecast for new images,
  growing logs, future traffic or minimum storage durations.
- The operational audit has permission/endpoint and timestamp coverage limits.
  An unsuccessful list is not proof of zero resources.

## Explicit follow-up, not a new experiment queue

| Item | State | Next action |
|---|---|---|
| Reference workload stack/EFS teardown | Recorded for each completed campaign | Preserve the dated receipts; do not present them as perpetual live account state |
| Account audit scope gaps | Documented in the private audit | Resolve permissions/service availability if a stronger all-clear is required; no IAM changes in this task |
| Retained diagnostics/images/logs | Disposition review deferred | Use the custody rules above before an authorised cleanup |
| Unrelated incomplete uploads/old backups/MicroVM images | Outside this study's mutation scope | Route to their owners; this closeout executes no abort/delete |
| Final cost reconciliation | Pending a later billing refresh | Use account-filtered data, retain the time window/estimated flag, and attribute usage before calling it per-run actual cost |
| Additional paid E0–E5 collection | Frozen | New question, pre-registration and spending approval required |

No schedule or automation has been created for these follow-ups. A later audit
must use fresh receipts rather than overwriting the private observation set.
