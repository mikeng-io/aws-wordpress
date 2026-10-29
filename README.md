# WordPress on AWS — a study

A successor to [aws-serverless-wordpress](https://github.com/mikeng-io/aws-serverless-wordpress)
(2020: CDK v1, Fargate + EFS + Aurora Serverless v1 + Memcached).

This is **not** a reference architecture. It is a study, and nothing in it is
confirmed until it has been benchmarked and deployed. The output is knowledge about
which filesystem, caching and compute choices determine performance and cost for
metadata-heavy applications on AWS — measured, not asserted.

## The premise

WordPress is the **entry point for readers and the workload instrument**. The
research subject is filesystem behaviour on AWS. A WordPress deployment is not
the deliverable, and end-to-end WordPress optimisation does not gate the
filesystem experiments.

It is here because it is an unusually pure specimen of a much larger class:
applications written before object storage was normal, which assume a POSIX
filesystem underneath them and issue enormous numbers of metadata operations
to it. That class is most of the software actually running in production. Its
owners cannot rewrite it, so the only levers they have are infrastructure levers.

This is why "just add S3 offload, a CDN and an object cache" is not an answer.
Those help with *content* delivery. They do not change the fact that the
application's own code — its core, its plugins, its themes, its templates —
lives on a filesystem and is consulted thousands of times per request. E0
measured that directly: ~4,300 filesystem syscalls on a warm request, ~3,900 of
them `stat`, and `php.ini` cannot reduce it because the floor is plugin code.

So the governing constraint is: **infrastructure is in scope, the application is
a black box.** No S3-offload plugin, no HyperDB, no object-cache plugin. If a
problem can only be solved by changing the application, that is a finding, not a
fix.

## The question

Given a fixed, irreducible demand for filesystem metadata operations, **what does
each storage tier charge per operation, and which tiers does the compute platform
actually let you reach?**

That is the study's core, and it is what E2 is built to answer across the full
matrix: local ephemeral, EFS, FSx (OpenZFS / Lustre / ONTAP), JuiceFS, SeaweedFS,
and Mountpoint-S3.

Reachability is part of the comparison. The three tested FUSE tiers require
`CAP_SYS_ADMIN`; the Fargate capability constraint used by the study excludes
those mount paths before their performance is considered. The observed EC2
mounts and the platform constraint are separate evidence, not a privileged-
Fargate failure test.

E5 measured what that cost becomes after the client cache has warmed: first-touch
miss cost, revalidation cost and steady-state miss rate. E2 exposed a cache-window
confound in the earlier NFS measurements, so their ratios are benchmark-specific,
not production steady-state estimates. See
[the server-backed finding](docs/findings/E2-server-backed.md), based on
`results/E2/20261015T000959Z-85382cc/`.

E4 tested the Fargate-reachable follow-up: hydrate a read-only code tree from an
EFS tar onto task ephemeral storage at startup, then serve reads locally.
The [three-replication finding](docs/findings/E4-hydration.md)
(`results/E4/20261029T091909Z-842d596/`) supports the registered read-latency and
conformance predictions, but **refutes the startup-cost prediction**. Its H2
kill-condition proxy is met for the read-only path only; it does not measure
request latency, write-back, or a complete production hydration design.

## Method

[`docs/benchmark-protocol.md`](docs/benchmark-protocol.md) — the standard every
experiment meets: pre-registration, replication vs repetition, which statistics
apply to which data, the clustering method and its gates, the results schema, and
a completion checklist.

[`docs/measurement-methodology.md`](docs/measurement-methodology.md) — how each
existing measurement was actually taken: instruments, isolation, statistical
choices with reasons, and threats to validity.

## Register

See [`hypotheses/`](hypotheses/) — seven pre-registered claims, each with the outcome
that would falsify it, recorded before any experiment runs.

## Status

**Collection closed — 2026-10-29.**

The current E0–E5 collection phase is complete with the limits below. **No new
paid experiment is queued or authorised.** A completed campaign can contain a
REFUTED or INCONCLUSIVE prediction; that does not require rerunning until it passes.
Production WordPress request latency, full startup and equal-p95 economics remain
outside this phase's acceptance target.

- [Study closeout and deferred questions](docs/study-status.md)
- [Evidence index: every retained run and pool membership](docs/evidence-index.md)
- [Offline reproduction checks](docs/closeout-verification.md)
- [Retention and cost follow-up](docs/retention-and-cost.md)

| Experiment | Collection | Result and principal limit |
|---|---|---|
| [E0](experiments/E0-syscall-census/) | [corrected n=10 census](results/E0/20260902T105746Z-f62a686/) | Counts, not latency; warm-aged n=3. Earlier cart/checkout traces were empty-cart measurements. [Finding](docs/findings/E0-cart-checkout.md). |
| [E1](experiments/E1-mount-topology/) | [direct host inspection](results/E1/20260902T060000Z-24d9bb9/) | Separate NFS clients for two co-located tasks; refutes the proposed shared-client mechanism for the tested configuration. [Finding](docs/findings/E1-mount-per-task.md). |
| [E2](experiments/E2-storage-matrix/) | Block, mount, FSx and FUSE groups complete; [run index](docs/evidence-index.md) | FSx P1 NOT EVALUABLE; P3 mechanically REFUTED with NFS cache confound. FUSE P2 INCONCLUSIVE, P4 SUPPORTED. Campaign grades must not be mixed. |
| [E3](experiments/E3-fargate-ephemeral-latency/) | [three Fargate tasks](results/E3/20260910T113000Z-6016f58/) | Fast ephemeral metadata path; EFS ratio is a fresh-file cache mixture, not production speedup. [Finding](docs/findings/E3-fargate-ephemeral.md). |
| [E4](experiments/E4-cache-adapter/) | [three clean independent deployments](results/E4/20261029T091909Z-842d596/) | P1/P3 SUPPORTED, P2 REFUTED; read-only H2 proxy MET. No write-back or measured request latency. [Finding](docs/findings/E4-hydration.md). |
| [E5](experiments/E5-attribute-cache/) | [three eligible formal-v3 deployments](results/E5-formal/20261028T160106Z-dd5fce0/analysis-pooled-3.json) | P1–P3 REFUTED, P4 INCONCLUSIVE, P5–P10 SUPPORTED. Frozen earlier methods are excluded. [Finding](docs/findings/E5-attribute-cache.md). |

The [FSx finding](docs/findings/E2-server-backed.md) explains why cached NFS
`stat` and cached `open_read` cannot rank server lookup/storage cost. The
[FUSE finding](docs/findings/E2-fuse.md) records the missed JuiceFS threshold and
Mountpoint's conformance failures. Neither is repaired by changing a threshold.
E5's [future P4 amendment](experiments/E5-attribute-cache/method-amendments/20261029-p4-first-pass/README.md)
is not applied retrospectively and authorises no paid run.

Workload teardown is different from removing retained diagnostics, images, logs
or unrelated account resources. Historical apparatus prices and campaign cost
proxies are documented with their result sources; none is a final invoice or a
production $/request model. See [retention and cost](docs/retention-and-cost.md).

## Region

`ap-southeast-1`, fixed for the study. See
[docs/region-decision.md](docs/region-decision.md) — region is provenance, and all
cost figures are Singapore pricing.

## Running it

```bash
nvm use          # Node is pinned in .nvmrc; CDK v2 will not run on older
make doctor      # verify toolchain
make bootstrap   # install dependencies
make help        # everything else
```

## Working agreement

[`CLAUDE.md`](CLAUDE.md) — what counts as in scope, why results are immutable, and
why no claim ships without a result file behind it.

## Licence

Apache-2.0, as with the original.
