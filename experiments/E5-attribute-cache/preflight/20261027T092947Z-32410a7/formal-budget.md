# Single formal v3 validation — live launch clearance

Mike's current `go` authorises **one fresh full-method validation** of
`isolation-formal-v3`, with the previously authorised **US$20 total ceiling**.
It does not authorise retries or further replications.

Fresh baseline: 18 regions /198 checks, zero E5 matches or API errors, no retained
E5 bucket, previous guard complete. Required identity-policy simulation actions
are allowed; simulation is not live deletion-timing proof. Pricing is refreshed
at `results/pricing/20261027T092919Z-32410a7`.

Conservative launch planning:

- Regional all-account CE, estimated: US$5.538209.
- All five known billable E5 attempt standing envelopes, additionally reserved
  in full: US$5.360960.
- Their ancillary reserves: US$2.50.
- New maximum 180-minute run plus 90-minute independent cleanup envelope:
  US$4.356375, plus US$0.50 ancillary reserve.
- Additional uncertainty reserve: US$1.00.
- **Total planning proxy: US$19.255544; below US$20 by US$0.744456.**

The fresh standing rate is $0.95475/hour, including $0.12/hour of interface
endpoints. [PrivateLink partial hours](https://aws.amazon.com/privatelink/pricing/)
are rounded up per attempt, separately from other standing components. Full stack
lifetimes bound historical standing cost despite staggered provisioning/deletion.
The short review-only placeholder is excluded after verifying its event history
contains only the CloudFormation Stack resource, never underlying resources.

This proxy intentionally double counts posted E5 charges and other workloads
already in regional CE. It protects against missing allocation/delayed posting;
it is **not actual E5 spend, an invoice or a guaranteed bill cap**. All five actual
attempts receive a $0.50 ancillary reserve plus the additional $1 uncertainty
reserve. No measurement or cleanup window was shortened. The generic preflight's
$1.55 historical estimate is stale and is not used for clearance.

The collector/host guard will use one fresh `formal-isolation` deployment,
10800-second run /5400-second cleanup ceilings, and 7200-second ECS task polling.
Preserve partial data and tear down on failure; never rerun automatically.
