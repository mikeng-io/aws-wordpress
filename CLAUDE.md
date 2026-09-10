# CLAUDE.md — working agreement

## What this repo is

A **study**, not a product. The output is knowledge: which infrastructure choices
actually determine WordPress performance on AWS, measured rather than asserted.

Code here is **apparatus**. It exists to answer a question in `hypotheses/`.
If a piece of code isn't serving an experiment, it shouldn't be written yet.

There is no "the platform" to build. There is a queue of experiments.

## The governing constraint

**Infrastructure is in scope. The application is a black box.**

WordPress core, plugins, and themes are treated as unmodifiable legacy. This is
the entire premise: real WordPress estates are too large to refactor, so the only
available levers are compute, network, storage, database topology, and edge.

**WordPress is the instrument, not the subject.** It stands in for the large class
of applications that predate object storage, assume a POSIX filesystem, and consult
it thousands of times per request. Findings should be written so they hold for that
class — a result that only means something to WordPress operators is a weaker
result than the same measurement framed as a property of the storage tier.

This is also why content-layer answers are out of scope rather than merely
disallowed: S3 offload, a CDN, and an object cache move *content*. They do not move
the application's own code, which is what the ~3,900 `stat` calls per warm request
are actually looking at.

In scope: task definitions, mount topology, instance selection, container images,
`php.ini` / opcache (ships in the image, not the app), proxies, load balancer
routing, CDN, WAF.

Out of scope: anything requiring a WordPress plugin or a code change inside
`wp-content` that a site owner wouldn't already have. S3-offload plugins,
HyperDB/LudicrousDB, and object-cache plugins are **not** valid solutions here —
if a problem can only be solved with one, that's a finding, not a fix.

## The discipline

**[`docs/benchmark-protocol.md`](docs/benchmark-protocol.md) is binding on every
experiment** — design, execution, statistics, storage schema, and reporting, with a
completion checklist. Read it before specifying an experiment, not after collecting
data. The rules below are its summary, not a substitute for it.

1. **No claim without a result file.** Every statement in a README, doc, or commit
   message that asserts a performance or cost fact must cite a file in `results/`.
   Statements without one are marked `HYPOTHESIS` or `UNVERIFIED`.
2. **Pre-register predictions.** Each hypothesis records what we expect and what
   outcome would falsify it, written *before* the experiment runs. No retrofitting
   a story onto whatever the numbers turned out to be.
3. **Negative results ship.** "This design corrupts data" and "this made no
   difference" are outcomes, not failures. They're often the most useful ones.
4. **Results are immutable.** Never edit a file under `results/`. Re-running
   produces a new run ID. Analysis reads; it does not rewrite.
   *One narrow exception, for reference data only:* a pricing snapshot under
   `results/pricing/` may supersede an earlier one from the same day when every
   price is verified identical key-by-key and the new snapshot only adds fields.
   That is enrichment of one observation, not a second observation. It never
   applies to experiment output, where a re-run is always a new run.
5. **Provenance or it didn't happen.** Every result carries: run ID, UTC timestamp,
   region, AZ, instance type, kernel version, image digest, CDK stack version,
   and a pricing snapshot date.

## The thesis under test

**HYPOTHESIS (H1), partially refuted and reframed:** cost is
`(metadata ops per request) × (per-op cost of the tier serving them)`. E0 fixed the
first factor and showed the application cannot reduce it. So the only lever is the
second — and the compute platform decides which tiers are reachable at all, since
FUSE-backed tiers need `CAP_SYS_ADMIN` that Fargate does not grant.

The study's original mechanism — co-located tasks sharing a host NFS cache — was
**refuted by E1**: ECS mounts EFS per task, not per host. That refutation is the
model for how this file should be read: the thesis is a target, not a commitment.
Design experiments that can say it is wrong; do not design experiments that can
only confirm it.

## Layout

| Path | Holds |
|---|---|
| `hypotheses/` | One file per hypothesis. Pre-registered predictions and kill conditions. |
| `experiments/` | One directory per experiment. Question, method, apparatus, how to run. |
| `infra/` | CDK v2 app. Apparatus for experiments needing real AWS resources. |
| `results/` | Immutable raw output, committed. Never edited. |
| `analysis/` | Scripts turning results into findings. Reads `results/`, writes `docs/`. Every published statistic must be recomputable by running one of these against committed raw data. |
| `docs/` | Study design, protocol, and findings. |

## Conventions

- Experiments are `E<n>-<slug>`; hypotheses are `H<n>-<slug>`. Both are stable once
  assigned — never renumber, since results reference them.
- **One number each, forever.** There is no `E2v2`, no `E2a`/`E2b`, no `-new` or
  `-final` suffix. When an experiment's design changes, its apparatus is **replaced
  in place** and its README records what changed and why; when its question is
  answered or abandoned, it is retired in place, not superseded by a sibling. The
  same applies to apparatus files: edit `e1-mount-topology.ts`, never create
  `e1-mount-topology-v2.ts`. Version history is git's job.
- Result paths: `results/E<n>/<run-id>/rep-<k>/` with a `meta.json` carrying
  provenance. Full schema and required fields in the benchmark protocol, §4.
- Hypothesis status is a **verdict**, optionally followed by a **priority
  qualifier** after an em dash. Verdicts: `UNTESTED` / `SUPPORTED` / `REFUTED` /
  `INCONCLUSIVE`, plus `MECHANISM REFUTED, CLAIM <OPEN|REFRAMED>` where a claim and
  its proposed mechanism diverge. Qualifiers say what the study is doing about it —
  `PROMOTED`, `PARKED`, `PERIPHERAL`, `CENTRAL TO E<n>` — and are never a substitute
  for a verdict. A qualifier change needs a line saying why; a verdict change needs
  a result file.
- CDK stack IDs: `<ExperimentId>-<PascalSlug>-<topology>`, e.g. `E1-MountTopology-dev`.
  Stack IDs are load-bearing — renaming one orphans the CloudFormation stack — so
  they are decided before the first deploy, never after.
- Every experiment README states its question, prediction, method, and the
  hypothesis it bears on, before any code.

## Toolchain

- Node pinned in `.nvmrc` (22.17.0). CDK v2 will not run on the system default.
  Always `nvm use` before touching `infra/`.
- `make` is the entrypoint for everything. If a step isn't in the Makefile, it
  isn't reproducible.
- AWS CLI v2 required. The system currently has v1 from 2021 — upgrade before any
  deployment work.

## Spending

No experiment deploys billable resources without an explicit decision recorded in
its README: what it costs per hour, and how it gets torn down. FSx and NAT
Gateways are the expensive traps. Tag every resource with its experiment ID.
