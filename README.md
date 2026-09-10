# WordPress on AWS — a study

A successor to [aws-serverless-wordpress](https://github.com/mikeng-io/aws-serverless-wordpress)
(2020: CDK v1, Fargate + EFS + Aurora Serverless v1 + Memcached).

This is **not** a reference architecture. It is a study, and nothing in it is
confirmed until it has been benchmarked and deployed. The output is knowledge about
which infrastructure choices actually determine WordPress performance and cost on
AWS — measured, not asserted.

## The premise

WordPress is the **instrument**, not the subject.

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

E4 then asks the obvious follow-up: if the fast tier is local and the durable
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

Four experiments complete.

[E0 at n=10](docs/findings/E0-n10.md): syscall counts are deterministic; a warm
WordPress request issues ~4,300 filesystem syscalls that `php.ini` cannot reduce.
Counts, not latency — E0 says nothing about EFS timing, only about the multiplier
that timing gets applied to.

[E3](docs/findings/E3-fargate-ephemeral.md) supplies the other half of that
multiplication: on the same Fargate task, a `stat()` costs **3.1 µs** on local
ephemeral storage against **0.84 ms** on EFS — **~271×** once the measured 24.4%
attribute-cache hit rate is accounted for — with a local-disk-shaped tail
(p99 4.6 µs). Fargate's ephemeral tier is genuinely fast, so the constraint on
Fargate is not that it lacks a fast local disk; it is that it cannot *share* one.
The gap is also metadata-shaped, not throughput-shaped: `open+read` is only ~91×,
which is the asymmetry this study has argued from E0 onward, now measured directly.

[E1](docs/findings/E1-mount-per-task.md): ECS mounts EFS once **per task**, not
once per host. Two co-located tasks on the identical instance get two fully
independent NFS4 client mounts and two independent TLS proxy processes — confirmed
directly on the host, not inferred. This refutes the shared-cache mechanism the
study originally proposed: there is no host-level cache to share, so placement is
not a lever. [H1](hypotheses/H1-cache-locality.md) records what survived that
refutation — the tier, not the placement, is what sets the per-op cost.

[E2](docs/findings/E2-block-backed.md) answers the study's central question for the
block-backed tiers, and refutes its own pre-registered prediction doing it. EC2
instance store (118 GB attached NVMe), an EBS gp3 root volume, and Fargate's task
ephemeral storage are **the same tier**: within 1.5× of each other on `stat`,
`open+read`, `create` and `unlink`, with EBS and instance store matching to 1.00–1.03×
including tails. Against EFS the same block-backed tiers are **638× faster on
`stat`**. So the boundary is not fast-disk versus slow-disk — it is whether the
kernel owns the filesystem or a server does. E3's EFS bimodality also replicated on
independent hardware (28.6% / 30.7% attribute-cache hits, ~550× separation).

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
| [E2](experiments/E2-storage-matrix/) | What does each storage tier charge per metadata op, and which are reachable at all? | ~$0.29/hr, torn down | **block-backed group complete: the device does not matter, the protocol boundary does** |
| [E3](experiments/E3-fargate-ephemeral-latency/) | Fargate ephemeral storage metadata latency | ~$0.04/hr, torn down | **complete: ~271× faster than EFS for `stat`** |
| [E4](experiments/E4-cache-adapter/) | Can local ephemeral act as a cache tier over a durable origin? | not costed | specced; substrate question **answered by E2**, amortisation still open |

E0–E3 were ordered by kill-power per dollar; between them they either support the
central claim or destroy it, cheaply and early. E2 is where the study's actual
question gets answered. Its block-backed group is done; the server-backed group
(FSx OpenZFS / Lustre / ONTAP, JuiceFS, SeaweedFS, Mountpoint-S3) is specced and
costed at ~$0.96/hr for all four FSx arms, and not yet built.

E4 has already been narrowed by E2 without being built: a cache adapter needs no
special substrate, because every platform's block-backed tier performs the same.

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
