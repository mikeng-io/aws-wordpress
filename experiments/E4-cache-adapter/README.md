# E4 — the cache adapter

**Status:** `SPECCED` — depends on E2. Do not build before the matrix exists.

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

### Two substrates, and they are not interchangeable

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

(Prices: `results/pricing/20260910/`, on-demand, `ap-southeast-1`.)

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
