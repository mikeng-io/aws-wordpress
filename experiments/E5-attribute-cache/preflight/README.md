# E5 pilot preflight

`make e5-preflight` refreshes the immutable pricing snapshot, then performs only
read-only AWS operations. It does not deploy, delete, enable billing tags, or
change IAM permissions. `make e5-preflight-selftest` checks eligibility rules and
the mutation allowlist without live calls.

Raw account-specific responses are private under
`.e5-watchdog/preflight/<UTC>/` (ignored by Git). Public reports contain counts,
permission decisions, timestamps and scoped planning figures, without principal
ARNs, account IDs, resource IDs or credentials.

A report is a point-in-time observation. Re-run on the pilot day; the guarded
launcher also rechecks identity, stack absence and its lease at deploy time.
`CONDITIONAL_PILOT_READY` means the enumerated baseline/tool/simulation/price checks
passed. It does not certify actual remaining spend, service-role permissions,
resource policies, real deletion timing or the measurement pilot itself.

The historical E5 spend remains the attempt log's **estimated $1.55**, not a verified
invoice. The planning target is **$2 for one pilot plus $1 reserve**, within the
existing $10 study ceiling if the historical estimate holds. These are planning
assumptions, not AWS Budgets settings or an automatic cost cap. Actual attribution
requires usable billing evidence; a zero result from inactive allocation tags is
not evidence of zero cost. Tags were not activated during this read-only step.

References: [IAM simulation limits](https://docs.aws.amazon.com/IAM/latest/UserGuide/access_policies_testing-policies.html)
and [billing tag activation](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/cost-alloc-tags.html).
