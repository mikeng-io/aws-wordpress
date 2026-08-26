#!/usr/bin/env bash
# Runs INSIDE the wordpress container.
#   trace.sh <request-uri> <output-file> [warmup-count]
#
# Attaches strace to the php-fpm master (following forks, so the single static
# worker is covered), issues exactly one request through the FastCGI socket, and
# detaches. nginx is not involved, so nothing but PHP contributes syscalls.
set -euo pipefail

URI="${1:?usage: trace.sh <uri> <out> [warmups]}"
OUTFILE="${2:?usage: trace.sh <uri> <out> [warmups]}"
WARMUPS="${3:-0}"

DOCROOT=/var/www/html
COOKIE_FILE=/out/auth.cookie
[[ -f "$COOKIE_FILE" ]] && HTTP_COOKIE="$(cat "$COOKIE_FILE")" || HTTP_COOKIE=""

# wp-admin has its own front controller; everything else routes through index.php.
case "$URI" in
  /wp-admin/*|/wp-admin) SCRIPT_REL="wp-admin/index.php" ;;
  *)                     SCRIPT_REL="index.php" ;;
esac

QUERY_STRING="${URI#*\?}"
[[ "$QUERY_STRING" == "$URI" ]] && QUERY_STRING=""

request() {
  SCRIPT_FILENAME="${DOCROOT}/${SCRIPT_REL}" \
  SCRIPT_NAME="/${SCRIPT_REL}" \
  DOCUMENT_ROOT="$DOCROOT" \
  REQUEST_METHOD=GET \
  REQUEST_URI="$URI" \
  QUERY_STRING="$QUERY_STRING" \
  SERVER_PROTOCOL=HTTP/1.1 \
  GATEWAY_INTERFACE=CGI/1.1 \
  SERVER_SOFTWARE=e0 \
  REMOTE_ADDR=127.0.0.1 \
  HTTP_HOST=localhost \
  HTTP_COOKIE="$HTTP_COOKIE" \
    cgi-fcgi -bind -connect 127.0.0.1:9000
}

for ((i = 0; i < WARMUPS; i++)); do
  request > /dev/null 2>&1 || true
done

# Attach to the WORKER, not the master.  php-fpm workers are forked child
# processes, and `strace -f` only follows forks created after it attaches - the
# worker already exists by then, so tracing the master captures nothing at all
# (the master just sits in epoll while the worker serves the request).
# pm=static with max_children=1 means there is exactly one worker, with a PID that
# is stable for the life of the container.
FPM_WORKER="$(pgrep -f 'php-fpm: pool www' | head -1)"
if [[ -z "$FPM_WORKER" ]]; then
  echo "trace: no php-fpm worker found" >&2
  exit 69
fi

# -qq suppresses attach/detach chatter. -s 512 is required: strace's default string
# limit is 32 chars, which truncates the deep plugin paths this experiment exists to
# count. Do not lower it.
strace -f -qq -s 512 -e trace=file -o "$OUTFILE" -p "$FPM_WORKER" &
STRACE_PID=$!

# Wait for the attach to actually land. TracerPid in the worker's status file flips
# from 0 the moment strace is on it - polling the output file would race, because a
# quiet worker writes nothing.
attached=0
for _ in $(seq 1 100); do
  if [[ "$(awk '/^TracerPid:/{print $2}' "/proc/${FPM_WORKER}/status" 2>/dev/null)" != "0" ]]; then
    attached=1
    break
  fi
  sleep 0.05
done
if [[ "$attached" != "1" ]]; then
  echo "trace: strace failed to attach to worker ${FPM_WORKER}" >&2
  kill -KILL "$STRACE_PID" 2>/dev/null || true
  exit 69
fi

request > /dev/null 2>&1 || true

# INT lets strace flush and detach cleanly; escalate if it will not go, so a stuck
# tracer cannot hang the whole run.
kill -INT "$STRACE_PID" 2>/dev/null || true
for _ in $(seq 1 40); do
  kill -0 "$STRACE_PID" 2>/dev/null || break
  sleep 0.1
done
kill -KILL "$STRACE_PID" 2>/dev/null || true
wait "$STRACE_PID" 2>/dev/null || true

echo "trace: ${URI} -> ${OUTFILE} ($(wc -l < "$OUTFILE") lines)"
