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

**`cart` and `checkout` are traced with a real item in the cart.** Exploratory
browsing found `cart`/`checkout` running far heavier than a naive empty-cart trace
suggested, traced to two compounding gaps: the generated catalog had no price set
(`wp post generate` produces a bare post shell — `seed.sh` now sets `_price`,
`_regular_price`, `_stock_status`, and the `simple` product-type term on every
generated product, since WooCommerce treats a priceless product as not
purchasable and silently no-ops any add-to-cart against it), and both pages were
being traced empty regardless, which matters because WooCommerce short-circuits
checkout before loading any shipping-method or payment-gateway class when the
cart has nothing in it — exactly the code path these endpoints exist to observe.

`trace.sh` now takes an optional cart-product-id argument: an untraced
`?add-to-cart=` request establishes a real `wp_woocommerce_session_*` cookie
first, which then rides along on the traced request. `run.sh` passes this for
`cart` and `checkout` only — every other endpoint is still traced cart-free, since
that's the realistic state for a shopper who hasn't added anything yet.

The mechanism that motivated this fix — checkout jumping ~59% once the cart held a
real item, versus cart's own ~32% — came from an exploratory browsing session on a
mutated, non-reproducible content state and is **not a committed result**; see
[docs/findings/E0-cart-checkout.md](../../docs/findings/E0-cart-checkout.md) for why
it doesn't count as one. The committed, reproducible number, from a clean apparatus
run on the standard seeded catalog (`results/E0/20260902T091846Z-158f9cd/`, n=1):
cart and checkout both land 14–15% above home/product/wp-admin. Directionally the
same finding, smaller magnitude, and this is the number to cite until the n=10 run
needed for confidence intervals lands.

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
