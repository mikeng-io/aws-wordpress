# H3 — opcache tuning makes filesystem choice largely irrelevant at steady state

**Status:** `UNTESTED`

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
