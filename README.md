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

The availability column of that matrix is itself a finding. Four of those tiers
need FUSE, FUSE needs `CAP_SYS_ADMIN`, and Fargate does not grant it — so the
compute choice deletes most of the storage matrix before any performance
discussion begins.

E5 now asks what that cost becomes after the client cache has warmed: first-touch
miss cost, revalidation cost and steady-state miss rate. E2 exposed a cache-window
confound in the earlier NFS measurements, so their ratios are benchmark-specific,
not production steady-state estimates. See
[the server-backed finding](docs/findings/E2-server-backed.md), based on
`results/E2/20261015T000959Z-85382cc/`.

E4 then asks the conditional follow-up: if the fast tier is local and the durable
tier is remote, can a **cache adapter** sit between them — local ephemeral in
front of S3/EFS, the way Redis sits in front of Postgres? E3 measured both ends
of that gap on the same task (3.1 µs vs 0.84 ms), which is what makes the
question worth asking rather than assuming.

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

E0, E1 and E3 have completed runs; E2 has completed block-backed, EFS mount and
FSx groups, with the FUSE-backed arms still open. E5 has one collected AWS pilot
with measurement blockers; its aggregate predictions remain NOT EVALUABLE.
Status reconciled on 2026-10-27 HKT; historical findings remain available with their
original measurements.

[E0 at n=10](docs/findings/E0-n10.md): syscall counts are deterministic; a warm
WordPress request issues ~4,300 filesystem syscalls that `php.ini` cannot reduce.
Counts, not latency — E0 says nothing about EFS timing, only about the multiplier
that timing gets applied to.

[E3](docs/findings/E3-fargate-ephemeral.md) measured local ephemeral and EFS on
the same Fargate task (`results/E3/20260910T113000Z-6016f58/`). It establishes a
fast block-backed metadata path. Its reported ~271× `stat` gap describes that
fresh-file benchmark's cache mix; E2 later showed why this is not a steady-state
production ratio. Its `open_read` comparison also includes client page caching.
E5 is designed to separate these mechanisms.

[E1](docs/findings/E1-mount-per-task.md): ECS mounts EFS once **per task**, not
once per host. Two co-located tasks on the identical instance get two fully
independent NFS4 client mounts and two independent TLS proxy processes — confirmed
directly on the host, not inferred. This refutes the shared-cache mechanism the
study originally proposed: there is no host-level cache to share, so placement is
not a lever. [H1](hypotheses/H1-cache-locality.md) records what survived that
refutation, and the later E2 evidence that puts its per-op cost model under review.

[E2's block-backed group](docs/findings/E2-block-backed.md) did not show the
predicted separation between instance store and Fargate on device-touching
operations, and found EBS close to instance store
(`results/E2/20260910T163206Z-66dcff8/`). This is agreement for this workload,
not evidence that the devices are interchangeable for all workloads.

[E2's FSx group](docs/findings/E2-server-backed.md) completed three independent
deployments (`results/E2/20261015T000959Z-85382cc/`). Its key finding is that the
NFS `stat` ranking was confounded by the client's attribute cache, and `open_read`
largely read cached data. Prediction 1 is NOT EVALUABLE, prediction 3 is mechanically
REFUTED with that construct caveat, and prediction 5 is PARTIALLY SUPPORTED.
The mutating-operation results remain useful; production steady-state metadata
cost is still open.

[E0's cart/checkout endpoints](docs/findings/E0-cart-checkout.md): fixed a
catalog bug that had made every WooCommerce cart/checkout trace measure an empty
cart since E0 was first built. Populated, both endpoints run 14–15% above
home/product/wp-admin, deterministic at n=10. An independent review (a subagent
with no context on this conversation, briefed to verify rather than take the
existing writeups on faith) then caught a real parsing bug and two overclaims in
the earlier findings — fixed and pushed; see that doc for the correction record.

| Experiment | Question | Cost | Status |
|---|---|---|---|
| [E0](experiments/E0-syscall-census/) | What does a heavy WP request actually do to the filesystem? | none (local Docker) | **done, n=10** |
| [E1](experiments/E1-mount-topology/) | Does ECS on EC2 mount EFS per host or per task? | ~$0.15/hr, torn down | **complete: per task, not per host** |
| [E2](experiments/E2-storage-matrix/) | What does each storage tier charge per metadata op, and which are reachable at all? | ~$0.96/hr FSx apparatus, torn down | **block-backed + EFS mount + FSx groups complete; FUSE arms open; NFS cache confound identified** |
| [E3](experiments/E3-fargate-ephemeral-latency/) | Fargate ephemeral storage metadata latency | ~$0.04/hr, torn down | **complete; fresh-file cache mix, not production steady state** |
| [E4](experiments/E4-cache-adapter/) | Can local ephemeral act as a cache tier over a durable origin? | not costed | specced; substrate question **answered by E2**, amortisation still open |
| [E5](experiments/E5-attribute-cache/) | What does an NFS `stat` cost on old files: miss cost, and steady-state hit rate? | ~$0.96/hr, torn down | single AWS pilot collected; 14/18 B cells valid; measurement blockers; n=1, no aggregate verdict |

The cost entries are historical apparatus estimates, not a current price quote;
E5's refreshed standing subtotal is $0.95475/hr from `results/pricing/20261026T144948Z-71ece42/`; ancillary usage/minimum billing excluded.

**Next: diagnose the E5 pilot's measurement gates before another paid run.**
The [single-pilot review](results/E5/20261026T152946Z-b1efcb2/pilot-review.md)
records EFS TLS RPC attribution errors, the original Lustre counter-name gap and
Lustre 0.1s schedule lateness. The unchanged grader has 14/18 valid B cells;
all ten aggregate predictions remain NOT EVALUABLE at n=1. AWS teardown is
verified by the host guard and fresh inventories across all 18 enabled regions.
Replications 2/3 remain behind the separate go-ahead. The filesystem research
objective and H1 verdict are unchanged.

The [offline follow-up](experiments/E5-attribute-cache/pilot-followup/20261027/README.md)
corrects Lustre A1 counter coverage, retains a versioned A1 reanalysis, and
quantifies schedule overruns. TLS attribution and Lustre timing remain open.

E4 remains specced. E2 narrowed its substrate question for the tested workload;
E5 must establish the remaining cache cost before deciding whether to build an
adapter. JuiceFS, SeaweedFS and Mountpoint-S3 remain unmeasured matrix arms.

See [docs/scope-audit.md](docs/scope-audit.md) for what each experiment and
hypothesis is currently worth, and why some are parked.

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
