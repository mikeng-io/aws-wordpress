# E0 — Syscall census

**Bears on:** [H3](../../hypotheses/H3-opcache-dominates.md), and supplies the
op-count multiplier that [H1](../../hypotheses/H1-cache-locality.md) scales by.

**Cost:** none. Runs locally in Docker. No AWS account, no billable resources.

## Question

How many filesystem syscalls does a single heavy WordPress request actually issue,
across how many unique paths, and how does that change with PHP tuning?

Every later result is a function of this number. If a request issues 300 metadata
ops, a 1 ms round trip costs 300 ms. If it issues 30, storage barely matters. Nobody
appears to have published the figure for a realistic plugin-heavy install.

## Prediction

Pre-registered before running:

- The `naive` profile issues an order of magnitude more `stat`/`lstat`/`newfstatat`
  calls than `max`, because `opcache.validate_timestamps=1` re-stats every cached
  file on every request.
- A large share of `naive` calls are **path-component** stats caused by realpath
  cache misses, not distinct file lookups — meaning the effective multiplier is
  higher than file count alone suggests.
- `max` still issues a large burst on the *first* request of a worker's life
  (compilation), which is why cold starts stay expensive regardless of tuning.

## Method

Determinism matters more than realism in the trace itself, so:

- `pm = static`, `pm.max_children = 1` — exactly one worker handles the request, so
  the trace is attributable.
- Requests issued via `cgi-fcgi` directly to the FastCGI socket, bypassing the web
  server, so nginx does not contribute syscalls.
- `strace -f -e trace=file` against the php-fpm master, following forks.
- Container needs `cap_add: SYS_PTRACE` and `seccomp:unconfined`.

Each profile is traced for two request classes:

1. **Cold** — first request after an opcache reset
2. **Warm** — Nth request, opcache populated

Endpoints traced: home, a product page, cart, `wp-admin` dashboard.

## Output

`results/E0/<run-id>/` containing per-profile, per-endpoint:

- `raw.strace` — unmodified trace
- `census.json` — counts by syscall, unique paths, path-component vs distinct-file
  breakdown, and result (hit/miss) distribution
- `meta.json` — provenance

## Status

`SKELETON` — apparatus scaffolded, not yet implemented. See `run.sh`.
