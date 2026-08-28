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

In scope: task definitions, mount topology, instance selection, container images,
`php.ini` / opcache (ships in the image, not the app), proxies, load balancer
routing, CDN, WAF.

Out of scope: anything requiring a WordPress plugin or a code change inside
`wp-content` that a site owner wouldn't already have. S3-offload plugins,
HyperDB/LudicrousDB, and object-cache plugins are **not** valid solutions here —
if a problem can only be solved with one, that's a finding, not a fix.

## The discipline

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
5. **Provenance or it didn't happen.** Every result carries: run ID, UTC timestamp,
   region, AZ, instance type, kernel version, image digest, CDK stack version,
   and a pricing snapshot date.

## The thesis under test

**HYPOTHESIS (H1), not yet established:** WordPress shared-filesystem performance
is dominated by *cache locality* — where metadata and page caches are permitted to
live — rather than by filesystem choice. Compute platform determines which cache
tiers are reachable, so compute silently determines storage performance.

This is the idea the study was built to test. It may be wrong. Design experiments
that can say so; do not design experiments that can only confirm it.

## Layout

| Path | Holds |
|---|---|
| `hypotheses/` | One file per hypothesis. Pre-registered predictions and kill conditions. |
| `experiments/` | One directory per experiment. Question, method, apparatus, how to run. |
| `infra/` | CDK v2 app. Apparatus for experiments needing real AWS resources. |
| `results/` | Immutable raw output, committed. Never edited. |
| `analysis/` | Scripts turning results into findings. Reads `results/`, writes `docs/`. |
| `docs/` | Study design, protocol, and findings. |

## Conventions

- Experiments are `E<n>-<slug>`; hypotheses are `H<n>-<slug>`. Both are stable once
  assigned — never renumber, since results reference them.
- Result paths: `results/E<n>/<run-id>/` with a `meta.json` carrying provenance.
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
