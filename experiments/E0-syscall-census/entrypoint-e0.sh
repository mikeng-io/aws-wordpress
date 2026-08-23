#!/usr/bin/env bash
# Activates the PHP profile named by $PROFILE, then hands off to the upstream
# WordPress entrypoint so normal wp-config generation still happens.
set -euo pipefail

profile="${PROFILE:-naive}"
src="/php-profiles/${profile}.ini"

if [[ ! -f "$src" ]]; then
  echo "E0: unknown PROFILE '${profile}' (no ${src})" >&2
  exit 64
fi

cp "$src" /usr/local/etc/php/conf.d/zz-e0-profile.ini
echo "E0: active PHP profile = ${profile}"

exec docker-entrypoint.sh "$@"
