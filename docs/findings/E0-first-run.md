# E0, first run — the stat storm is plugins, not opcache

**Result:** `results/E0/20260826T105956Z-c16d429/`
**Status:** provisional. One run, no repetitions.

## What was predicted

[H3](../../hypotheses/H3-opcache-dominates.md) pre-registered that the `naive`
profile would issue "an order of magnitude more `stat`-family calls than `max`",
because `opcache.validate_timestamps=1` re-stats every cached file on every request.

## What was observed

On a warm home-page request:

| profile | total | stat | open | ENOENT |
|---|--:|--:|--:|--:|
| naive | 5115 | 3974 | 898 | 1638 |
| max | 4305 | 3902 | 196 | 1566 |

Turning timestamp validation off removed roughly 700 `open` calls and **1.8% of
`stat` calls**. The predicted order-of-magnitude collapse did not happen.

## Why, apparently

Grouping the surviving ops in `max/home.warm` by area:

| ops | area |
|--:|---|
| 1155 | wpforms-lite |
| 590 | elementor |
| 528 | woocommerce |
| 309 | broken-link-checker |
| 214 | themes |
| 137 | advanced-custom-fields |
| 103 | wp-includes |

WordPress core accounts for about a hundred ops. The storm is **plugin code running
its own `file_exists` / `is_readable` / template-hierarchy checks**, which opcache
has no involvement in and therefore cannot eliminate.

Two further observations from the same traces:

- **~1,566 of ~4,300 ops on a fully tuned warm request are ENOENT** — roughly a
  third of all filesystem syscalls are lookups for files that do not exist. Pure
  waste, and on a network filesystem, pure latency.
- `/var/www/html` itself is stat'd ~193 times in a single request.

Cold requests are ~15,400–16,400 ops and **identical across all three profiles**,
which is expected: with an empty opcache every profile must compile from disk. This
part of the prediction held.

## What it means for the study

If ~4,000 metadata ops survive maximum PHP tuning, then `php.ini` is not an escape
route from the metadata storm, and the multiplier that per-op latency gets applied to
stays in the thousands regardless of tuning.

That weakens H3 and correspondingly strengthens the motivation for
[H1](../../hypotheses/H1-cache-locality.md): if the op count cannot be reduced from
inside the application — which the governing constraint forbids anyway — then the
only remaining lever is where those ops are served from. Which is infrastructure.

**This is not yet a finding.** It needs repetitions before it earns that word.

## Known limitations of this run

1. **n=1.** No repetitions, no confidence intervals.
2. **`tuned` and `max` are indistinguishable here**, because `tuned` sets
   `opcache.revalidate_freq=60` and every warm request in the trace window happens
   well inside that window. Revalidation never fires. A `warm-aged` cohort that
   waits past the window is needed before `tuned` means anything.
3. **Generated content.** `wp post generate` products are not real product pages
   with real media, so the template and image paths exercised are thinner than a
   production catalog.
4. **Counts, not latency.** Nothing here says anything about EFS. That is E1–E3.
