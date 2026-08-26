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
  if [[ -d "$OUT" ]] && ! compgen -G "${OUT}/*/*.strace" >/dev/null; then
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
  "warmups_for_warm_cohort": ${WARMUPS}
}
META

# --- trace ------------------------------------------------------------------
for profile in "${PROFILES[@]}"; do
  echo "E0: === profile ${profile} ==="
  mkdir -p "${OUT}/${profile}"

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

    # cold: first request this master has ever served, opcache empty
    docker compose exec -T wordpress /scripts/trace.sh "$uri" \
      "/out/${profile}.${name}.cold.strace" 0 </dev/null | sed 's/^/  /'

    # warm: opcache populated by WARMUPS prior requests
    docker compose exec -T wordpress /scripts/trace.sh "$uri" \
      "/out/${profile}.${name}.warm.strace" "$WARMUPS" </dev/null | sed 's/^/  /'

    mv "./out/${profile}.${name}.cold.strace" "${OUT}/${profile}/${name}.cold.strace"
    mv "./out/${profile}.${name}.warm.strace" "${OUT}/${profile}/${name}.warm.strace"
  done < "${OUT}/endpoints.tsv"
done

# --- census -----------------------------------------------------------------
echo "E0: parsing traces"
python3 "${REPO_ROOT}/analysis/e0_census.py" "$OUT"

echo
echo "E0: complete -> ${OUT}"
echo "E0: results are immutable. Re-running produces a new run ID."
