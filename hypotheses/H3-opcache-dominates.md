# H3 — opcache tuning makes filesystem choice largely irrelevant at steady state

**Status:** `INCONCLUSIVE` — first evidence contradicts the prediction

## Claim

With `opcache.validate_timestamps=0`, a large realpath cache, and preloading, a warm
PHP request barely touches the filesystem. Filesystem differences that dominate at
default settings should mostly disappear.

## Why it matters

If true, most published "EFS is slow for WordPress" results are really statements
about PHP defaults, not about EFS. A benchmark that holds PHP at defaults is
measuring the wrong thing — and this study would be making the same mistake if PHP
configuration were treated as a constant.

`php.ini` ships in the container image, so it is infrastructure and remains in scope.

## The three profiles

| Profile | Settings |
|---|---|
| `naive` | Stock defaults: `validate_timestamps=1`, `realpath_cache_size=4096k` default, no preload |
| `tuned` | `revalidate_freq` raised, realpath cache enlarged, `read_ahead_kb` raised where reachable |
| `max` | `validate_timestamps=0`, preload enabled, large realpath cache — accepting that in-place updates now need a container restart |

## Prediction

Spread across storage backends narrows sharply from `naive` to `max` on **warm**
requests, and narrows much less on **cold** ones, because a cold task must still
compile from the filesystem regardless of validation settings.

## Kill condition

**H3 is refuted if** the spread across storage backends stays wide at the `max`
profile on warm requests.

## Consequence either way

If supported, the cheapest real-world fix is a `php.ini` change, and the storage
matrix matters mainly for cold starts and writes — which promotes H4.

## Bearing experiments

- `E0-syscall-census` — measures op counts per profile directly, locally, for free
- `E2-placement-differential`

## First evidence (E0, run `20260826T105956Z-c16d429`)

Turning timestamp validation off removed ~700 `open` calls but only **1.8%** of
`stat` calls (3974 -> 3902 on a warm home request). The predicted order-of-magnitude
collapse did not occur.

Grouping surviving ops by area shows why: the storm is plugin code doing its own
`file_exists` / `is_readable` / template-hierarchy checks — wpforms-lite alone
accounts for ~1155 ops, against ~103 for all of `wp-includes`. opcache is not
involved in those and cannot remove them.

Recorded as `INCONCLUSIVE` rather than `REFUTED` only because n=1 with no
repetitions, and because the `tuned` profile was never actually exercised (its
`revalidate_freq=60` window never elapsed inside the trace). The `naive` vs `max`
comparison is clean, and the effect size is not one repetitions are likely to
reverse.

See [docs/findings/E0-first-run.md](../docs/findings/E0-first-run.md).
