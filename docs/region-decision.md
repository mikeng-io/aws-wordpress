# Region: ap-southeast-1 (Singapore)

Fixed for the whole study. Recorded here because region is provenance, not
preference — every latency and every cost figure is region-specific and cannot be
quoted as if it were universal.

## Verified available (2026-08-28)

| Service | Status |
|---|---|
| CloudFront VPC origins | supported, **no AZ exclusions** |
| Amazon ECS | available |
| ECS Managed Instances | available (all commercial regions since 2025-10) |
| AWS Fargate | available |
| AWS App Runner | available |
| Amazon EFS | available |
| FSx for OpenZFS | available |
| FSx for NetApp ONTAP | available |
| FSx for Lustre | available |
| Amazon Aurora | available |

The AZ point matters specifically for
[E2](../experiments/E1-mount-topology/README.md)'s successor: several regions
exclude an AZ from VPC origin support (`us-east-1`/`use1-az3`,
`ap-northeast-1`/`apne1-az3`, `ca-central-1`/`cac1-az3`, `us-west-1`/`usw1-az2`).
ap-southeast-1 excludes none, so AZ pinning for placement experiments is
unconstrained and the topology stays constant across every experiment.

## Consequence for cost figures

ap-southeast-1 is priced above us-east-1 — commonly 10–20% higher on EC2. Every
figure this study produces is **Singapore pricing** and must be labelled so.
Comparisons between configurations remain valid, because all of them pay the same
regional premium; absolute numbers do not transfer to other regions.

Pricing snapshot dates are recorded per result, per [H7](../hypotheses/H7-cheapest-storage-loses.md).

## Use of AZ identifiers

Pin by **AZ ID** (`apse1-az1`), not AZ name (`ap-southeast-1a`). AZ names are mapped
per account, so `ap-southeast-1a` is a different physical zone in a different
account — which would silently break reproducibility of any placement result.
