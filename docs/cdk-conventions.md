# CDK conventions — inherited and departed from

Reviewed against the 2020 original
([`lib/aws-serverless-wordpress-stack.ts`](https://github.com/mikeng-io/aws-serverless-wordpress/blob/master/lib/aws-serverless-wordpress-stack.ts),
1,304 lines, single stack, CDK v1).

## Kept

| Convention | Why |
|---|---|
| PascalCase construct IDs naming the resource (`EfsFileSystemSecurityGroup`) | Verbose but greppable, and stable across refactors — changing an ID replaces the resource. |
| Typed props interface on the stack | Deploy-time config is explicit and type-checked rather than pulled from context by string key. |
| `removalPolicy` + `resourceDeletionProtection` threaded through props | One flag flips a whole stack between throwaway and protected. Exactly right for a study where everything is torn down. |
| Tagging applied at app level | Matches the `CLAUDE.md` rule that every resource is attributable to an experiment. |
| `CfnOutput` for endpoints the harness needs | The run scripts consume them; 8 in the original. |

## Dead in CDK v2

| Original | Now |
|---|---|
| `@aws-cdk/core`, `@aws-cdk/aws-*` | single `aws-cdk-lib` |
| `import cdk = require('...')` | ESM imports |
| `ServerlessCluster` (Aurora Serverless **v1**) | v1 is end-of-life; `DatabaseCluster` with Serverless v2 capacity |
| `SubnetType.PRIVATE` / `ISOLATED` | `PRIVATE_WITH_EGRESS` / `PRIVATE_ISOLATED` |
| `Domain` (Elasticsearch) | OpenSearch |
| `aws-sdk` v2 in the custom-resource Lambda | SDK v3 — v2 is absent from current Lambda runtimes |
| `BastionHostLinux` + Client VPN for admin access | SSM Session Manager — no bastion, no VPN, no inbound ports |
| Custom resource to empty the logging bucket on delete | `autoDeleteObjects: true` on `Bucket` |

## Departures, deliberate

**Monolithic stack → per-experiment stacks.** 1,304 lines in one file is untestable and
unreasonable to hold in context. This repo builds one stack per experiment and
resists generalising until at least three exist.

**Custom-header origin protection → CloudFront VPC origins.** The original derives
`cloudFrontHashHeader` as
`Buffer.from(`${stackName}.${domainName}`).toString('base64')` and sends it as
`X_Request_From_CloudFront`, with WAF rules matching on it, to prove a request came
via CloudFront.

Base64 is encoding, not encryption, and the input is the stack name plus the domain
— both discoverable. The header is therefore derivable by anyone who wants it, and
the origin ALB was internet-facing. **The protection was decorative.**

This is not a criticism of the original; it was the best pattern available in 2020.
It is, though, a concrete reason the 2026 answer differs: VPC origins remove the
public path entirely rather than asking the origin to check a guessable header. And
it matters directly for the AI-bot dimension — edge metering is worthless if the
origin can be reached around it.

## Bugs in the original worth not repeating

1. **`env: {region: 'us-east-1', ...}` is hardcoded in `bin/`** even though
   `config.toml` carries a `region` field, which is silently ignored.
2. **Hardcoded ELB account ID `127311923021`** with a comment warning it is
   us-east-1 only. A portability landmine; modern CDK derives the access-log bucket
   policy itself.
3. **`props.cloudFrontHashHeader = ...` mutates the props object** it was handed.

## This repo's additions

- `ExperimentStack` base class enforcing `Experiment` tagging and a declared
  `EstimatedHourlyUsd`, per the spending rule in `CLAUDE.md`.
- Topology profile (`dev` / `prod`) recorded into result provenance, because
  single-AZ and multi-AZ are not the same measurement.
- Synthesized templates committed per variant, so a result can be traced to the
  exact CloudFormation that produced it.
