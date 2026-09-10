# Scope audit

Written when the study's framing changed: WordPress stopped being the subject and
became the instrument. What follows is what survives that change, what is retired,
and why.

**Numbering rule.** Experiments are `E0`–`En`, one number each, forever. No `v2`,
no `E2a`. When an experiment's apparatus improves, the apparatus is replaced in
place and the number keeps its meaning. When an experiment's *question* dies, the
number is retired and may be redefined **only** if it produced no committed
results — otherwise it stays retired and the next question takes the next number.

---

## The reframing

WordPress is not the subject. It is a **measuring instrument**: a widely-deployed,
unmodifiable, filesystem-bound application that produces a realistic and
reproducible metadata workload on demand.

The subject is the class of applications that are filesystem-bound by construction
and cannot be refactored out of it. Bolting on object storage, a CDN, and cache
plugins does not remove that dependency — it relocates some traffic and leaves the
code path on the filesystem untouched.

That makes the central question **which storage tier can serve a metadata-heavy
workload, and at what cost** — so the filesystem matrix is the core of the study,
not an appendix to it.

---

## Experiments

| | Verdict | Reason |
|---|---|---|
| **E0** — syscall census | **Keep, unchanged** | Measures the *demand* side: how many filesystem ops the workload issues. Every latency number in the matrix is meaningless without it, and it defines the workload shape each filesystem gets tested against. Complete at n=10. |
| **E1** — mount topology | **Keep, deprioritised** | Its original job was gating E2's old premise, which no longer exists. Its remaining value is characterising how each compute platform mounts, which informs the cache adapter. Worth running once across arms; not urgent. |
| **E2** — placement differential | **RETIRED, number redefined** | Premise died with E1's finding: there is no shared NFS client, so there is no placement effect to detect. It produced no committed results, so under the numbering rule the number is free. **E2 is now the storage matrix.** |
| **E3** — ephemeral latency | **Keep, promoted** | Establishes that Fargate's local tier is genuinely fast (~271× EFS on `stat`, local-disk-shaped tail). That is precisely the finding the cache adapter is built on. Complete. |
| **E4** — cache adapter | **New** | The experimental design: ephemeral storage as a cache tier in front of a durable mountable backend. |

---

## Hypotheses

| | Verdict |
|---|---|
| **H1** — cache locality | **Rewritten.** Its mechanism (shared NFS client across co-located tasks) was refuted by E1. The surviving claim is stronger and simpler: performance is set by *which tier is reachable*, not by which filesystem is mounted. |
| **H2** — Fargate forbids caching | **Keep, reframed.** E3 showed Fargate is not missing a fast local tier — it has one. What it cannot do is *share* it. That is exactly what motivates E4. |
| **H3** — opcache dominates | **Keep, marked peripheral.** `INCONCLUSIVE`. Under the new framing this is a WordPress-tuning question, not a storage question. It stays because E0's data already bears on it; it is not a priority. |
| **H4** — cold start is the metric | **Keep, promoted.** More central now, not less: a cache tier's warming cost *is* the cold-start cost. E4 cannot be evaluated without it. |
| **H5** — DB is the same shape | **Parked, explicitly.** A different axis from storage. Real, but out of the current line of enquiry. Left `UNTESTED` and marked parked rather than quietly ignored. |
| **H6** — write-back cannot be correct | **Keep, promoted to central.** A cache in front of a shared filesystem has exactly the write-back correctness problem this hypothesis describes. E4 either solves it or is disqualified by it. |
| **H7** — cheapest storage loses at equal performance | **Keep.** The matrix is what finally makes it testable. |

---

## What was removed

- The `v2` stack file. The E1 apparatus was replaced in place under the numbering
  rule; there is no `e1-mount-topology-v2.ts`.
- E2's placement-differential design. Recorded here rather than deleted silently,
  because "we built an experiment whose mechanism turned out not to exist" is
  itself a result worth keeping visible.

## What was deliberately kept despite being superseded

- `docs/findings/E0-first-run.md`. Superseded twice by later analysis, retained
  because the protocol requires corrections to be appended and auditable rather
  than overwritten.
