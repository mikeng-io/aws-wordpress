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

## What this measures, and what it does not

E0 measures **op counts, not op latency.** Docker volumes on a laptop say nothing
about EFS, and no timing from this experiment should ever be quoted.

Latency is E1–E3's job, on real infrastructure. E0 produces the multiplier that
those measured latencies get multiplied by. Keeping the two separate is deliberate:
counts are cheap, portable, and reproducible anywhere; latencies are none of those
things.

## Prediction

Pre-registered before running:

- The `naive` profile issues an order of magnitude more `stat`-family calls than
  `max`, because `opcache.validate_timestamps=1` re-stats every cached file on every
  request.
- A large share of `naive` calls are **path-component** stats caused by realpath
  cache misses, not distinct file lookups — so the effective multiplier is higher
  than file count alone suggests.
- `max` still issues a large burst on the *first* request of a worker's life
  (compilation), which is why cold starts stay expensive regardless of tuning.

## Method

Determinism in the trace matters more than realism of the traffic, so:

- `pm = static`, `pm.max_children = 1` — exactly one worker handles the request, so
  the trace is attributable.
- Requests issued via `cgi-fcgi` straight to the FastCGI socket, so no web server
  contributes syscalls.
- `strace -f -qq -s 512 -e trace=file` attached to the php-fpm master, following
  forks. `-s 512` is required: strace's 32-char default truncates the deep plugin
  paths this experiment exists to count.
- Container needs `cap_add: SYS_PTRACE` and `seccomp:unconfined`.

**Cohorts.** *Cold* is the first request after the php-fpm master restarts. The
master, not a worker — opcache lives in shared memory across the pool, so restarting
a worker leaves it warm. *Warm* is the request after five warmups.

**Endpoints** are resolved at seed time into `endpoints.resolved.tsv`, because
product, cart, and checkout URLs depend on generated/WooCommerce-assigned IDs.
`wp-admin` is traced with a real logged-in cookie generated via
`wp_generate_auth_cookie`; unauthenticated it would only ever trace the login
redirect, which is not the path of interest.

**`checkout` is traced with an empty cart.** WooCommerce short-circuits checkout
before loading shipping-method and payment-gateway classes when the cart has
nothing in it — which is the exact mechanism this endpoint exists to observe
(exploratory browsing found the cart endpoint disproportionately heavy, traced to
WooCommerce conditionally `include`-ing a class file per enabled gateway and
shipping method). Populating a real cart session needs an add-to-cart HTTP
round-trip first, to obtain a `wp_woocommerce_session_*` cookie, which `trace.sh`
does not yet perform. Until it does, `checkout`'s numbers are a floor, not the full
cost — do not quote them as the complete checkout path.

## The install

`plugins.txt` lists 26 wordpress.org slugs, weighted toward the popular and the
bulky. Page caches, object caches, S3-offload and DB-abstraction plugins are
deliberately excluded — they solve at the application layer what this study exists
to measure at the infrastructure layer, and are out of scope per `CLAUDE.md`.

Versions resolve at seed time and are written to `plugins.lock`, which is copied
into the run's results directory. A rerun installs from the lock when present, so a
run is reproducible even though the manifest is not hand-pinned.

## Output

`results/E0/<run-id>/` containing:

- `<profile>/<endpoint>.<cohort>.strace` — unmodified trace
- `<profile>/<endpoint>.<cohort>.census.json` — counts by syscall and family, unique
  paths, path-component vs distinct-file split, and errno distribution
- `summary.json`, `summary.md` — the cross-profile table
- `plugins.lock`, `endpoints.tsv`, `meta.json` — provenance

Runs are immutable. `run.sh` refuses to write into an existing run ID.

## Running

```bash
make e0
```
