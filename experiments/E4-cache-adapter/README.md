# E4 — the cache adapter

**Status:** `GATED — NO BUILD AS SPECIFIED` (2026-10-29). E2 is complete; the
transparent-adapter design cannot be mounted on Fargate and is redundant on EC2.
See [Gate review after E2](#gate-review-after-e2-2026-10-29). No AWS spend has been
authorised for E4.

**Bears on:** [H2](../../hypotheses/H2-fargate-forbids-caching.md),
[H4](../../hypotheses/H4-cold-start-is-the-metric.md),
[H6](../../hypotheses/H6-writeback-cannot-be-correct.md).

## The idea

Applications solved this problem once already, one layer up. Nobody puts Postgres
on the request path for every read; they put Redis in front of it and accept an
explicit consistency contract in exchange for the latency. The filesystem layer
never got that treatment — the choice is still "mount the slow shared thing" or
"don't share."

E3 measured the two numbers that make the analogy concrete:

| tier | `stat` | role in the analogy |
|---|--:|---|
| Fargate ephemeral | **3.1 µs** | the Redis |
| EFS | **0.84 ms** | the Postgres |

**~271× apart, on the same task, at the same moment.** That is a wider gap than
most application-layer cache/database pairs, which is what makes a filesystem cache
tier worth building rather than merely describing.

One caveat carried from E3: Fargate ephemeral is itself network-backed, so that
3.1 µs is the kernel answering from its dentry cache, not a disk being fast. The
cache tier being proposed here is therefore *the kernel's own caches over a block
device* — which is precisely why it works, and also why E2 must check whether a
physically attached NVMe (EC2 instance store) does any better before this is
built.

## What would be built

A read-through cache adapter: **local ephemeral storage as the cache tier, a
durable mountable backend (S3, EFS, or whichever tier E2 selects) as the origin.**
The application sees one POSIX path and is not modified — which is the study's
governing constraint, and the whole reason this has to live below the application
rather than in it.

Fargate is the interesting target precisely because of H2's finding: it *has* a
fast local tier and cannot share it. A cache adapter does not need to share it. Each
task keeps its own cache, and the origin is the only shared thing — which is exactly
the isolation model a per-task cache wants.

### Two substrates — and E2 showed they are interchangeable after all

> **Superseded by measurement, 2026-09-10.** The table below was written expecting
> attached NVMe to outperform a network-backed ephemeral volume.
> [E2 measured it](../../docs/findings/E2-block-backed.md) and they are the same
> tier: instance store, EBS and Fargate ephemeral fall within 1.5× of each other on
> every op, while EFS sits 638× away on `stat`. So the substrate question is
> **closed** — a cache adapter needs no `d`-class instance and no special device,
> just a block device with a local filesystem, which every platform already has.
>
> What survives is the right-hand column only: **sharing and persistence**, not
> speed. Instance store is a host resource that outlives a task; Fargate ephemeral
> is per-task and does not. That is an amortisation question, and it is the whole
> of what E4 still has to answer.

### The original two-substrate table, kept as the audit record

The cache tier has two candidate substrates, and [E2](../E2-storage-matrix/) exists
partly to tell them apart:

| | Fargate task ephemeral | EC2 instance store |
|---|---|---|
| what it is | network-backed volume, per task | NVMe physically attached to the host |
| capacity | 20 GiB default, 200 GiB max | 118 GB on `*.large` |
| shared across tasks | **no**, by construction | **yes**, it is a host resource |
| hydration cost | paid **once per task** | paid **once per host** |
| survives task restart | no | yes, until the instance goes |
| cost for 118 GB | +$0.0130/hr **per task** | +$0.0225/hr **flat** |
| cost if the working set fits in 20 GiB | **free** | still +$0.0225/hr |

(Prices: `results/pricing/20260918T080950Z-c94ac10/`, on-demand, `ap-southeast-1`.)

That third and fourth row change the economics rather than the design. A per-task
cache pays the full cold-hydration cost every time a task starts, which is why
[H4](../../hypotheses/H4-cold-start-is-the-metric.md) is a gate on this experiment
and not a side issue — E0 measured a cold request at ~15,400 syscalls against
~4,300 warm. A per-host cache amortises that across every task on the instance and
survives task churn, so the same adapter has a materially different hit rate
depending on which substrate it sits on.

It also inverts the usual reading of the compute choice. Fargate is the *harder*
target for a cache adapter, not the easier one: the platform that most needs a
local cache tier is the one that can least amortise it. If that turns out to
dominate, the honest finding is that the cache adapter is an argument for EC2 —
which would be a result about the platform, not about the adapter.

## The hard part is correctness, not speed

[H6](../../hypotheses/H6-writeback-cannot-be-correct.md) pre-registers the claim
that bidirectional write-back between a local cache and a shared origin cannot be
made correct without a single-writer assumption: two tasks write locally, both
flush, last writer wins silently.

**E4 either refutes H6 by exhibiting a correct design, or is disqualified by it.**
That is the experiment. A cache adapter that is fast and loses writes is not a
result worth having, and the correctness suite runs before any latency number is
recorded.

The design space to test, in rough order of how much they concede:

| design | write path | correctness cost |
|---|---|---|
| read-only cache | writes bypass cache, go straight to origin | none — but no write acceleration |
| write-through | write to both, ack on origin | none — write latency stays at origin speed |
| single-writer write-back | one designated writer per path | correct *if* the assumption holds |
| multi-writer write-back | any task writes locally, flushes async | H6 says this is where it breaks |

The read-only variant is the honest baseline: for a workload like WordPress's,
where the ~3,900 `stat` calls per request hit read-mostly *code* rather than
mutable state, a read-only cache may capture nearly all the benefit at zero
correctness cost. That would be the useful finding, and it is deliberately the
cheapest thing to test first.

## Predictions

Pre-registered before any build:

1. **A read-only cache captures most of the available gain** for a
   WordPress-shaped workload, because the metadata storm is overwhelmingly against
   read-mostly paths.
2. **Cache warming dominates the cost model**, not steady-state latency — which is
   why this depends on H4. A per-task cache is cold on every scale-out event, and
   E0 measured a cold request at ~15,400 syscalls against ~4,300 warm.
3. **Multi-writer write-back fails the correctness suite** (H6 holds).

## Kill conditions

- Prediction 1 refuted if a read-only cache captures less than half the gap
  between origin and local.
- The whole approach is refuted if warming cost exceeds the steady-state saving
  across realistic task lifetimes — i.e. if tasks never live long enough to amortise
  a cold cache. That would make this a worse answer than simply baking the code into
  the image, which needs no adapter at all.

## Prior art to check before building

Not to be built in ignorance of: JuiceFS and SeaweedFS both already implement local
caching over object storage, and E2 measures them. **If an existing tier already
delivers this, E4 should not be built** — the finding would be "this problem is
solved, use JuiceFS," which is a perfectly good result and much cheaper than a
bespoke adapter.

E4 is therefore explicitly gated on E2: build only if the matrix shows a gap that
nothing existing fills.


## Gate review after E2 (2026-10-29)

E2's FUSE arms are complete, so the prior-art gate can be read instead of guessed.
The result is not "build it":

- **On EC2**, JuiceFS and SeaweedFS already provide a conformant local-cache-over-
  object-storage tier. JuiceFS `stat` was 104.6 µs and SeaweedFS 20.2 µs; both
  passed single-node conformance; both are 15–76× slower than instance store on
  `stat` but far ahead of EFS's cache-miss path. A bespoke adapter would have to
  beat an existing, measured implementation to justify itself. That is the case the
  prior-art gate says not to build.
- **On Fargate**, none of the three FUSE tiers can even be mounted: the platform
  withholds `CAP_SYS_ADMIN`. E4's "one POSIX path" adapter needs a filesystem layer
  below the application; without mount capability, there is no transparent path to
  put the cache on. The remaining Fargate-only mechanism is **hydration at task
  start** (copy a code tree onto ephemeral storage, serve from there, never sync
  back), which is [H6](../../hypotheses/H6-writeback-cannot-be-correct.md)'s
  single-writer alternative, not the bidirectional adapter this experiment was
  specified to build.

So E4 as written is **not built**: on EC2 it is prior art, and on Fargate it is
blocked by the isolation model. This is a result about the platform, not a missing
measurement.

If H2/H4 still need a Fargate number, the honest replacement in place is a
**read-only task-start hydration** experiment: one arm serves from EFS, one from a
local copy hydrated from a tarball, with cold-task and warm-task cohorts reported
separately (H4), and no write-back path (H6). That is infrastructure-only, needs no
`CAP_SYS_ADMIN`, and can reuse E0's WordPress instrument. It is a new apparatus and
a new ceiling; it is not authorised by E2's US$12 FUSE approval.
