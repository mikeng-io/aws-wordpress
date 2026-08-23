#!/usr/bin/env bash
# E0 - syscall census.  Local only, no AWS, no cost.
#
# SKELETON: the harness loop, provenance capture, and output layout are real.
# The trace parsing (strace -> census.json) is not yet implemented; see TODO below.
set -euo pipefail

cd "$(dirname "$0")"
REPO_ROOT="$(cd ../.. && pwd)"

PROFILES=(naive tuned max)
ENDPOINTS=(home product cart wp-admin)

# Run IDs are caller-supplied or derived from the git SHA + an incrementing counter,
# never from a wall clock alone, so a rerun is distinguishable from a re-analysis.
RUN_ID="${RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)-$(git -C "$REPO_ROOT" rev-parse --short HEAD 2>/dev/null || echo nogit)}"
OUT="${REPO_ROOT}/results/E0/${RUN_ID}"

if [[ -e "$OUT" ]]; then
  echo "E0: refusing to overwrite existing run ${RUN_ID} - results are immutable" >&2
  exit 65
fi
mkdir -p "$OUT"

# --- provenance -------------------------------------------------------------
cat > "${OUT}/meta.json" <<META
{
  "experiment": "E0-syscall-census",
  "run_id": "${RUN_ID}",
  "utc": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "host_os": "$(uname -srm)",
  "docker": "$(docker --version)",
  "git_sha": "$(git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null || echo unknown)",
  "git_dirty": $(if [[ -n "$(git -C "$REPO_ROOT" status --porcelain 2>/dev/null)" ]]; then echo true; else echo false; fi),
  "profiles": [$(printf '"%s",' "${PROFILES[@]}" | sed 's/,$//')],
  "endpoints": [$(printf '"%s",' "${ENDPOINTS[@]}" | sed 's/,$//')]
}
META

echo "E0: run ${RUN_ID} -> ${OUT}"

for profile in "${PROFILES[@]}"; do
  echo "E0: === profile ${profile} ==="
  mkdir -p "${OUT}/${profile}"

  PROFILE="$profile" docker compose up -d --build --wait

  # TODO(E0): for each endpoint, per cold/warm cohort:
  #   1. reset opcache (restart the fpm worker) for the cold case
  #   2. strace -f -e trace=file -o raw.strace the php-fpm master
  #   3. issue exactly one request via cgi-fcgi to the FastCGI socket
  #   4. stop the trace, copy raw.strace into ${OUT}/${profile}/${endpoint}.${cohort}.strace
  #
  # TODO(E0): parse traces into census.json:
  #   - counts by syscall name
  #   - unique paths touched
  #   - path-component stats vs distinct-file lookups (the realpath-miss multiplier)
  #   - ENOENT vs success ratio (failed lookups are pure waste and pure latency)
  echo "E0: TRACE CAPTURE NOT YET IMPLEMENTED for profile ${profile}" | tee "${OUT}/${profile}/STATUS"

  docker compose down -v
done

echo "E0: skeleton complete. Results dir: ${OUT}"
echo "E0: no census produced - apparatus is scaffolded, not implemented."
