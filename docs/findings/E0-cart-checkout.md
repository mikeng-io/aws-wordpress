# E0 — cart and checkout added, and a catalog bug that made them meaningless

**Result:** `results/E0/20260902T091846Z-158f9cd/`
**n:** 1 (this run verifies the fix works end-to-end; not yet at statistical
confidence — needs the same n=10 treatment E0's other endpoints already got)

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

**Clean apparatus run** (this result, reproducible, committed): on the standard
seeded catalog, `naive`/warm:

| Endpoint | Total syscalls | vs. home |
|---|--:|---|
| home | 5,168 | — |
| product | 5,265 | +2% |
| wp-admin | 5,141 | flat |
| cart (populated) | 5,941 | +15% |
| checkout (populated) | 5,884 | +14% |

Both real WooCommerce pages now sit meaningfully above the content pages, which
they never did while traced empty.

## Status and next step

n=1. Needs the same n=10 + `warm-aged` treatment as the other four endpoints
before these numbers can be quoted with confidence intervals. The mechanism is
established; the statistics are not yet.
