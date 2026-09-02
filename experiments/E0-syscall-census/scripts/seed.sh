#!/usr/bin/env bash
# Runs INSIDE the wordpress container. Installs WordPress, the heavy plugin set,
# and enough content that the traced endpoints are real pages rather than 404s.
# Idempotent: safe to re-run, does nothing if already seeded.
set -euo pipefail

WP="wp --allow-root --path=/var/www/html"
# Management commands run with no plugins loaded. Several plugins in the heavy set
# (Elementor among them) fatal during wp-cli bootstrap because they expect an admin
# request context; letting them load would break every later command. Core functions
# are all these commands need.
WPQ="$WP --skip-plugins --skip-themes"
OUT=/out

if $WPQ core is-installed 2>/dev/null; then
  echo "seed: WordPress already installed, skipping"
else
  echo "seed: installing WordPress core"
  $WPQ core install \
    --url=http://localhost \
    --title="E0 census" \
    --admin_user=e0 \
    --admin_password=e0-local-only \
    --admin_email=e0@example.invalid \
    --skip-email
fi

# Forced unconditionally, not just on fresh install. trace.sh sends
# HTTP_HOST=localhost (no port); a mismatch here makes WordPress's own
# redirect_canonical() 301/302 every request before it renders anything, and the
# resulting trace silently measures a redirect instead of a real page - it still
# "succeeds" and produces a number, just the wrong one. This has happened for real:
# the docker-compose.browse.yml overlay repoints siteurl to include :8088 so a
# human can look at the install in a browser, and that change persists on the
# shared wpdata volume across container recreates. A run kicked off after a
# browsing session without remembering to revert it silently corrupted an entire
# n=10 result (never committed - caught by every non-wp-admin endpoint reporting
# byte-identical syscall counts, which a real page render cannot do). Do not make
# this conditional on whether the option already looks right; the whole point is
# not to depend on what a human left on the volume.
$WPQ option update siteurl "http://localhost"
$WPQ option update home "http://localhost"

# --- install plugins --------------------------------------------------------
if [[ -f /e0/plugins.lock ]]; then
  echo "seed: installing from plugins.lock"
  while IFS='=' read -r slug version; do
    [[ -z "$slug" || "$slug" == \#* ]] && continue
    $WPQ plugin is-installed "$slug" 2>/dev/null && continue
    $WPQ plugin install "$slug" --version="$version" \
      || echo "seed: WARN could not install ${slug}=${version}"
  done < /e0/plugins.lock
else
  echo "seed: no lock, installing latest"
  grep -v '^\s*#' /e0/plugins.txt | grep -v '^\s*$' | while read -r slug; do
    $WPQ plugin is-installed "$slug" 2>/dev/null && continue
    $WPQ plugin install "$slug" || echo "seed: WARN could not install ${slug}"
  done
fi

# --- content, before the rest of the plugin set is live ---------------------
# WooCommerce is activated alone so its post types and CLI commands exist while the
# catalog is generated. Doing this with the full set active is what broke the first
# run: one plugin fatalling during bootstrap takes down every command after it.
if [[ "$($WPQ post list --post_type=product --format=count 2>/dev/null || echo 0)" -lt 100 ]]; then
  echo "seed: activating WooCommerce alone to seed the catalog"
  # Deactivate first, so this step behaves identically on a fresh volume and on one
  # left dirty by a failed run.
  $WPQ plugin deactivate --all >/dev/null 2>&1 || true
  $WP plugin activate woocommerce

  echo "seed: creating WooCommerce pages"
  $WP wc tool run install_pages --user=1

  echo "seed: generating catalog"
  $WP post generate --post_type=product --count=200
  $WP post generate --post_type=post --count=100

  # wp post generate produces a bare post shell - no price, no stock status, no
  # product-type term. WooCommerce treats a priceless product as not purchasable
  # (wc_get_product()->is_purchasable() === false), which silently no-ops any
  # add-to-cart attempt. Every generated product needs real product meta before
  # this catalog is anything more than decoration.
  echo "seed: making the generated catalog purchasable"
  $WP eval '
    $ids = get_posts(["post_type" => "product", "numberposts" => -1, "fields" => "ids"]);
    foreach ($ids as $id) {
      wp_set_object_terms($id, "simple", "product_type");
      update_post_meta($id, "_price", "19.99");
      update_post_meta($id, "_regular_price", "19.99");
      update_post_meta($id, "_stock_status", "instock");
      update_post_meta($id, "_manage_stock", "no");
      update_post_meta($id, "_visibility", "visible");
    }
    echo count($ids) . " products made purchasable\n";
  '
else
  echo "seed: catalog already present, skipping"
fi

# --- activate the rest ------------------------------------------------------
# One at a time: a plugin that refuses to activate is itself a data point, and
# --all would hide which one failed.
echo "seed: activating remaining plugins"
grep -v '^\s*#' /e0/plugins.txt | grep -v '^\s*$' | while read -r slug; do
  $WPQ plugin is-active "$slug" 2>/dev/null && continue
  $WPQ plugin activate "$slug" >/dev/null 2>&1 \
    && echo "  activated ${slug}" \
    || echo "  seed: WARN ${slug} failed to activate"
done

$WPQ plugin list --field=name --status=active | while read -r slug; do
  echo "${slug}=$($WPQ plugin get "$slug" --field=version)"
done > "${OUT}/plugins.lock"
echo "seed: ${OUT}/plugins.lock records $(wc -l < "${OUT}/plugins.lock") active plugins"

# --- resolve endpoint IDs ---------------------------------------------------
PRODUCT_ID=$($WPQ post list --post_type=product --field=ID --posts_per_page=1 | head -1)
CART_ID=$($WPQ option get woocommerce_cart_page_id 2>/dev/null || echo "")
echo -n "$PRODUCT_ID" > "${OUT}/product_id.txt"
CHECKOUT_ID=$($WPQ option get woocommerce_checkout_page_id 2>/dev/null || echo "")

if [[ -z "$PRODUCT_ID" ]]; then
  echo "seed: FATAL no products - a WooCommerce-less census misses the point of E0" >&2
  exit 70
fi

{
  echo -e "home\t/"
  echo -e "wp-admin\t/wp-admin/"
  echo -e "product\t/?post_type=product&p=${PRODUCT_ID}"
  [[ -n "$CART_ID" && "$CART_ID" != "0" ]] && echo -e "cart\t/?page_id=${CART_ID}"
  # Traced with an EMPTY cart. WooCommerce short-circuits checkout on an empty
  # cart before loading shipping-method and payment-gateway classes - the exact
  # code path this endpoint exists to capture. Populating a real cart session
  # first needs an add-to-cart HTTP round-trip to obtain a wp_woocommerce_session_*
  # cookie, which trace.sh does not yet perform. Known limitation until that
  # exists; do not read this endpoint's numbers as the full checkout cost.
  [[ -n "$CHECKOUT_ID" && "$CHECKOUT_ID" != "0" ]] && echo -e "checkout\t/?page_id=${CHECKOUT_ID}"
} > "${OUT}/endpoints.resolved.tsv"

echo "seed: resolved endpoints:"
sed 's/^/  /' "${OUT}/endpoints.resolved.tsv"

# --- auth cookie for admin traces -------------------------------------------
# wp-admin unauthenticated only traces the login redirect, which is not the path of
# interest. wp_generate_auth_cookie is core, so it works with plugins skipped.
COOKIEHASH=$($WPQ eval 'echo COOKIEHASH;')
COOKIE=$($WPQ eval 'echo wp_generate_auth_cookie(1, time()+86400, "logged_in");')
echo "wordpress_logged_in_${COOKIEHASH}=${COOKIE}" > "${OUT}/auth.cookie"
echo "seed: wrote auth cookie"
