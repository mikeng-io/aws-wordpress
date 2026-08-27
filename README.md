# WordPress on AWS, 2026 — a study

A successor to [aws-serverless-wordpress](https://github.com/mikeng-io/aws-serverless-wordpress)
(2020: CDK v1, Fargate + EFS + Aurora Serverless v1 + Memcached).

This is **not** a reference architecture. It is a study, and nothing in it is
confirmed until it has been benchmarked and deployed. The output is knowledge about
which infrastructure choices actually determine WordPress performance and cost on
AWS — measured, not asserted.

## The premise

Everyone says WordPress is legacy. Everyone still runs WordPress. Real estates are
too large to refactor, so the levers available to their operators are *infrastructure*
levers, not application ones.

So the governing constraint is: **infrastructure is in scope, the application is a
black box.** No S3-offload plugin, no HyperDB, no object-cache plugin. If a problem
can only be solved by changing WordPress, that is a finding, not a fix.

## The question

The 2020 architecture paired Fargate with a shared filesystem. Those pull in opposite
directions, and this study is an attempt to say precisely why, and what replaces it.

The working thesis — **untested, and the study is built to be able to refute it** —
is that shared-filesystem performance is dominated by *cache locality* rather than
filesystem choice, and that the compute platform silently determines storage
performance by deciding which cache tiers are reachable at all.

If that is right, "which filesystem is fastest for WordPress" is the wrong question.

## Register

See [`hypotheses/`](hypotheses/) — seven pre-registered claims, each with the outcome
that would falsify it, recorded before any experiment runs.

## Status

One result recorded, provisional. See
[docs/findings/E0-n10.md](docs/findings/E0-n10.md) — E0 at n=10. Syscall counts are
deterministic; a warm WordPress request issues ~4,300 filesystem syscalls that
`php.ini` cannot reduce.

E0 counts syscalls; it does not time them. Latency belongs to E1-E3, on real
infrastructure. No timing from a laptop should ever be quoted about EFS.

| Experiment | Question | Cost | Status |
|---|---|---|---|
| [E0](experiments/E0-syscall-census/) | What does a heavy WP request actually do to the filesystem? | none (local Docker) | **done, n=10** |
| [E1](experiments/E1-mount-topology/) | Does ECS on EC2 mount EFS per host or per task? | ~$0.30/hr | specced, blocked on AWS access |
| E2 | Placement differential: N tasks on 1 host vs N hosts, identical EFS | small | not specced |
| E3 | Fargate ephemeral storage metadata latency | small | not specced |

E0–E3 are ordered by kill-power per dollar. Between them they either support the
central thesis or destroy it, cheaply and early.

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
