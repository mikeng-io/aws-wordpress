# E0 — cart and checkout added, and a catalog bug that made them meaningless

**Result:** `results/E0/20260902T105746Z-f62a686/` (n=10, `warm-aged` n=3)
**Superseded:** `results/E0/20260902T091846Z-158f9cd/` (n=1, verified the fix works
end-to-end before committing to a full run)

## The bug this run fixes

The generated product catalog (`wp post generate --post_type=product`) has never
had a price. `wc_get_product($id)->is_purchasable()` returned `false` for every
one of the 200 generated products, since the beginning of E0. WooCommerce silently
refuses `add-to-cart` against a non-purchasable product, so **every prior cart and
checkout trace — including the committed n=10 baseline — measured an empty cart**,
never once a real one.

This was found by accident, browsing the seeded install with a real browser and
noticing add-to-cart simply did nothing.

## The fix

1. `seed.sh` now sets `_price`, `_regular_price`, `_stock_status=instock`, and the
   `simple` product-type term on every generated product.
2. `trace.sh` takes an optional cart-product-id argument. When given, it issues an
   untraced `?add-to-cart=` request first to obtain a real
   `wp_woocommerce_session_*` cookie, which then rides along on the traced
   request (warmups included).
3. `run.sh` passes this only for `cart` and `checkout` — every other endpoint is
   still traced cart-free, since that is the realistic state for a shopper who has
   not added anything yet.

## What changed, verified two ways

**Same-content before/after** (exploratory session, non-reproducible content
state, not committed as a result — see prior commit): checkout jumped from 4,095
to 6,493 syscalls (+59%) once the cart held a real item; cart itself moved from
4,896 to 6,465 (+32%). Checkout's larger relative jump is consistent with it
loading strictly more than cart — every enabled shipping-method and
payment-gateway class on top of what cart already renders.

**Clean apparatus run, n=10, `naive`/warm** (median; every cell in this table has
zero-width range across all 10 reps — deterministic, not noisy):

| Endpoint | Total syscalls | vs. home |
|---|--:|---|
| home | 5,157 | — |
| product | 5,265 | +2% |
| wp-admin | 5,140 | flat |
| cart (populated) | 5,941 | +15% |
| checkout (populated) | 5,884 | +14% |

Both real WooCommerce pages sit meaningfully above the content pages, which they
never did while traced empty. These numbers match the n=1 spot-check almost
exactly (cart 5,941 both times, checkout 5,884 both times, home within 11 of
5,168) — the effect is real and reproducible, not an artifact of one run.

## A near-miss worth recording

The first attempt at this n=10 run was silently corrupted: `siteurl` had been
repointed to `localhost:8088` for browsing (see the browse-overlay commit) and was
never reverted before the formal run started. `trace.sh` sends
`HTTP_HOST=localhost` with no port, so every request 301/302-redirected before
rendering anything — the trace still "succeeds" and produces a plausible number,
just the wrong one. Caught only because home/product/cart/checkout came back
byte-identical across all 10 reps, which no real page render does. Root-caused
and fixed in `seed.sh` (forces `siteurl`/`home` back unconditionally, every run)
and `run.sh` (preflight check aborts loudly on a redirect). See that commit for
the full account, including that some of the corrupted run's partial data briefly
made it into a commit by accident before being removed.

## Status

Done. Both endpoints are now at the same n=10 + `warm-aged` statistical bar as
the other three.
