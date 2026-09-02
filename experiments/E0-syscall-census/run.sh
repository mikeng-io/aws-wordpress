#!/usr/bin/env bash
# E0 - syscall census. Local only, no AWS, no cost.
#
# Counts what a WordPress request does to the filesystem, across PHP tuning
# profiles and request cohorts. It measures OP COUNTS, not op latency - Docker
# volumes on a laptop say nothing about EFS. Latency is E1-E3's job, on real
# infrastructure. The multiplier E0 produces is what those latencies get
# multiplied by.
set -euo pipefail

cd "$(dirname "$0")"
REPO_ROOT="$(cd ../.. && pwd)"

PROFILES=(naive tuned max)
WARMUPS=5
REPS="${REPS:-1}"

# A profile with validate_timestamps=1 only re-stats once its revalidate_freq window
# has elapsed. Warm requests issued back-to-back never cross it, so `tuned` measured
# identically to `max` in the first run - the profile was never actually exercised.
# The aged cohort waits past the window. Profiles with validation off have no window
# and are skipped.
declare -A REVALIDATE_FREQ=( [naive]=2 [tuned]=60 [max]=0 )
AGED_REPS="${AGED_REPS:-3}"   # aged cohort is slow; fewer reps by design

RUN_ID="${RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)-$(git -C "$REPO_ROOT" rev-parse --short HEAD 2>/dev/null || echo nogit)}"
OUT="${REPO_ROOT}/results/E0/${RUN_ID}"

if [[ -e "$OUT" ]]; then
  echo "E0: refusing to overwrite existing run ${RUN_ID} - results are immutable" >&2
  exit 65
fi
mkdir -p "$OUT" ./out

cleanup() {
  docker compose down 2>/dev/null || true
  # An aborted run is not a result. Leaving a half-populated directory under
  # results/ would let it be mistaken for data, so drop it when no trace was
  # captured. Complete runs are never touched.
  # Depth-independent on purpose: a glob pinned to a fixed depth silently stopped
  # matching when the layout gained a rep-N level, and this guard then deleted a
  # completed run.
  if [[ -d "$OUT" ]] && [[ -z "$(find "$OUT" -name '*.strace' -print -quit 2>/dev/null)" ]]; then
    rm -rf "$OUT"
    echo "E0: aborted before any trace - removed empty ${OUT}"
  fi
}
trap cleanup EXIT

# --- bring up and seed once -------------------------------------------------
echo "E0: run ${RUN_ID}"
PROFILE=naive docker compose up -d --build --wait
docker compose exec -T wordpress /scripts/seed.sh 2>&1 | sed 's/^/  /'

cp ./out/plugins.lock "${OUT}/plugins.lock"
cp ./out/endpoints.resolved.tsv "${OUT}/endpoints.tsv"

# Used to populate a real cart session before cart/checkout traces (see below) -
# without it those pages were being traced empty, and WooCommerce short-circuits
# checkout's shipping-method/payment-gateway class loading on an empty cart.
CART_PRODUCT_ID="$(cat ./out/product_id.txt)"

# --- provenance -------------------------------------------------------------
cat > "${OUT}/meta.json" <<META
{
  "experiment": "E0-syscall-census",
  "run_id": "${RUN_ID}",
  "utc": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "measures": "syscall counts, not latency",
  "host_os": "$(uname -srm)",
  "docker": "$(docker --version)",
  "php": "$(docker compose exec -T wordpress php -r 'echo PHP_VERSION;')",
  "wordpress": "$(docker compose exec -T wordpress wp --allow-root --skip-plugins --skip-themes --path=/var/www/html core version)",
  "kernel": "$(docker compose exec -T wordpress uname -r)",
  "git_sha": "$(git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null || echo unknown)",
  "git_dirty": $(if [[ -n "$(git -C "$REPO_ROOT" status --porcelain 2>/dev/null)" ]]; then echo true; else echo false; fi),
  "profiles": [$(printf '"%s",' "${PROFILES[@]}" | sed 's/,$//')],
  "warmups_for_warm_cohort": ${WARMUPS},
  "reps": ${REPS},
  "aged_reps": ${AGED_REPS},
  "cohorts": {
    "cold": "first request after php-fpm master restart, opcache empty",
    "warm": "request after ${WARMUPS} warmups, issued immediately",
    "warm-aged": "request after ${WARMUPS} warmups plus a wait past the profile revalidate_freq window"
  }
}
META

# --- trace ------------------------------------------------------------------
for rep in $(seq 1 "$REPS"); do
for profile in "${PROFILES[@]}"; do
  echo "E0: === rep ${rep}/${REPS} profile ${profile} ==="
  mkdir -p "${OUT}/rep-${rep}/${profile}"

  while IFS=$'\t' read -r name uri; do
    [[ -z "${name:-}" || "$name" == \#* ]] && continue

    # Recreate PER ENDPOINT, not per profile. Recreating restarts the php-fpm
    # master, which clears the opcache SHM segment; restarting only a worker would
    # not, since opcache is shared across the pool.
    #
    # Doing this once per profile is wrong and was a real bug here: the first
    # endpoint traced absorbed the whole compile cost, and every later "cold" trace
    # silently inherited a warm opcache.
    PROFILE="$profile" docker compose up -d --force-recreate --wait wordpress >/dev/null 2>&1

    # cart and checkout are traced with an item already in the cart - a shopper
    # who reaches either page normally has one. Every other endpoint is traced
    # cart-free.
    cart_arg=""
    [[ "$name" == "cart" || "$name" == "checkout" ]] && cart_arg="$CART_PRODUCT_ID"

    # cold: first request this master has ever served, opcache empty
    docker compose exec -T wordpress /scripts/trace.sh "$uri" \
      "/out/${profile}.${name}.cold.strace" 0 "$cart_arg" </dev/null | sed 's/^/  /'

    # warm: opcache populated by WARMUPS prior requests, issued immediately
    docker compose exec -T wordpress /scripts/trace.sh "$uri" \
      "/out/${profile}.${name}.warm.strace" "$WARMUPS" "$cart_arg" </dev/null | sed 's/^/  /'

    mv "./out/${profile}.${name}.cold.strace" "${OUT}/rep-${rep}/${profile}/${name}.cold.strace"
    mv "./out/${profile}.${name}.warm.strace" "${OUT}/rep-${rep}/${profile}/${name}.warm.strace"

    # warm-aged: only meaningful where timestamp validation is on
    freq="${REVALIDATE_FREQ[$profile]}"
    if [[ "$freq" -gt 0 && "$rep" -le "$AGED_REPS" ]]; then
      echo "  aging ${freq}s past revalidate window (${profile})"
      sleep "$((freq + 3))"
      docker compose exec -T wordpress /scripts/trace.sh "$uri" \
        "/out/${profile}.${name}.warm-aged.strace" 0 "$cart_arg" </dev/null | sed 's/^/  /'
      mv "./out/${profile}.${name}.warm-aged.strace" \
         "${OUT}/rep-${rep}/${profile}/${name}.warm-aged.strace"
    fi
  done < "${OUT}/endpoints.tsv"
done
done

# --- census -----------------------------------------------------------------
echo "E0: parsing traces"
python3 "${REPO_ROOT}/analysis/e0_census.py" "$OUT"
python3 "${REPO_ROOT}/analysis/e0_aggregate.py" "$OUT"

echo
echo "E0: complete -> ${OUT}"
echo "E0: results are immutable. Re-running produces a new run ID."
