# Candidate launch budget review — 2026-10-27

**BUDGET CLEARANCE REQUIRED — no candidate launched.**

The authorised next action is one `isolation-validation` candidate using the
existing 4500-second run and 5400-second cleanup ceilings. No formal replications
are included. Source: `f8d53fd`.

Fresh baseline: 18 regions, 198 checks, zero E5 matches or API errors; no retained
E5 buckets. IAM simulation allows the required actions; simulation is not live
resource-policy or deletion-timing proof. The generic preflight report's $1.55
historical budget constant is stale and must not be treated as clearance.

Cost Explorer still reports US$5.5382 for the regional account, estimated,
with E5 cost-allocation tags inactive. The previous diagnostic's final allocation
is unverified. The regional number includes other workloads; the following is a
conservative launch-planning proxy, not actual E5 spend or an invoice.

- Reported regional proxy: US$5.5382.
- Previous diagnostic full-stack lifetime envelope: US$1.2889, plus $0.50
  ancillary reserve, conservatively treated as unposted (possible double counting).
- Candidate maximum run plus cleanup envelope: US$2.6556, plus $0.50
  ancillary reserve.
- Additional uncertainty reserve: US$1.00.
- Total planning proxy: **US$11.4827**, above the **US$10 study ceiling**.

The standing snapshot is $0.95475/hour including $0.12/hour for interface endpoints.
Endpoint hours are rounded up separately because [AWS PrivateLink pricing](https://aws.amazon.com/privatelink/pricing/)
bills partial endpoint-hours as full hours. All other standing components use the
full stack lifetime; ancillary usage and billing uncertainty remain estimated.
The prior diagnostic lifetime was 75.3928 minutes; the candidate maximum is 165
minutes. These are engineering envelopes, not guaranteed charge caps.

No measurement window, acceptance gate, run deadline or cleanup allowance has
been reduced to fit the ceiling. A new explicit ceiling (proposed US$15 for this
single candidate) or verified billing reconciliation is needed before launch.
Raw historical runs and their manifests remain unchanged.
