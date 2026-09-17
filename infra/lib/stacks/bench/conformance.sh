#!/usr/bin/env bash
# POSIX conformance gate. Runs BEFORE any latency number is collected, per H6:
# a filesystem that cannot hold POSIX semantics is not eligible for a latency
# comparison, and reporting its speed beside correct ones would be misleading.
#
# SCOPE. This is the SINGLE-NODE gate - the semantics one process on one host
# expects from a filesystem. It is what disqualifies object-store-backed FUSE
# mounts (no rename, no in-place write), which is the specific prediction E2
# pre-registered for Mountpoint-S3.
#
# It deliberately does NOT test cross-node consistency - two hosts, one file,
# close-to-open ordering and cross-node flock. That is a different gate needing a
# second instance, it is H6/E4's question rather than E2's, and conflating the two
# would let a tier fail here for a reason that has nothing to do with eligibility
# for a latency number.
#
# Output: one "check,status[,detail]" line per check. Exit 0 if all pass.
set -uo pipefail

ROOT="${1:?usage: conformance <mount-dir>}"
DIR="$ROOT/conformance.$$"
mkdir -p "$DIR" || { echo "setup,FAIL,cannot mkdir under $ROOT"; exit 1; }
trap 'rm -rf "$DIR" 2>/dev/null' EXIT

# PASS / FAIL / ERROR are kept distinct, and an ERROR is never counted as a PASS.
# FAIL means the filesystem lacks the capability - a real verdict about the tier.
# ERROR means this gate could not perform the check at all, usually a missing tool,
# which says nothing about the filesystem and must never be reported as though it
# did. Collapsing the two is how a broken harness gets written up as a broken
# filesystem.
fails=0
errors=0
ok()   { echo "$1,PASS"; }
bad()  { echo "$1,FAIL,${2:-}"; fails=$((fails + 1)); }
err()  { echo "$1,ERROR,${2:-}"; errors=$((errors + 1)); }

require() {  # require <tool> <check-name>; returns 1 if absent
    command -v "$1" >/dev/null 2>&1 && return 0
    err "$2" "required tool '$1' not present in image"
    return 1
}

# --- rename over an existing file --------------------------------------------
# The single most load-bearing operation for the applications this study is about:
# atomic config/plugin replacement is a write-temp-then-rename. Object stores have
# no rename at all; they copy and delete, which is neither atomic nor cheap.
printf 'old' > "$DIR/target"
printf 'new' > "$DIR/staged"
if mv "$DIR/staged" "$DIR/target" 2>/dev/null && [ "$(cat "$DIR/target")" = "new" ] \
   && [ ! -e "$DIR/staged" ]; then ok rename; else bad rename "mv did not replace"; fi

# --- in-place write at an offset ---------------------------------------------
# Object stores replace whole objects. A filesystem lets you change four bytes in
# the middle of a file without rewriting it.
printf 'AAAABBBBCCCC' > "$DIR/inplace"
if dd if=/dev/zero of="$DIR/inplace" bs=1 seek=4 count=4 conv=notrunc status=none 2>/dev/null \
   && [ "$(stat -c %s "$DIR/inplace")" = "12" ] \
   && [ "$(head -c4 "$DIR/inplace")" = "AAAA" ]; then ok in_place_write; else bad in_place_write; fi

# --- append ------------------------------------------------------------------
printf 'one' > "$DIR/append"
if printf 'two' >> "$DIR/append" && [ "$(cat "$DIR/append")" = "onetwo" ]; then
    ok append; else bad append; fi

# --- truncate ----------------------------------------------------------------
printf '0123456789' > "$DIR/trunc"
if truncate -s 4 "$DIR/trunc" 2>/dev/null && [ "$(stat -c %s "$DIR/trunc")" = "4" ]; then
    ok truncate; else bad truncate; fi

# --- fsync -------------------------------------------------------------------
if printf 'durable' > "$DIR/fsync" && sync "$DIR/fsync" 2>/dev/null; then
    ok fsync; else bad fsync; fi

# --- hard link ---------------------------------------------------------------
printf 'linked' > "$DIR/linksrc"
if ln "$DIR/linksrc" "$DIR/linkdst" 2>/dev/null \
   && [ "$(stat -c %h "$DIR/linksrc")" = "2" ]; then ok hardlink; else bad hardlink; fi

# --- symlink -----------------------------------------------------------------
if ln -s linksrc "$DIR/symdst" 2>/dev/null && [ "$(cat "$DIR/symdst")" = "linked" ]; then
    ok symlink; else bad symlink; fi

# --- directory rename --------------------------------------------------------
mkdir -p "$DIR/dir_a/nested"
if mv "$DIR/dir_a" "$DIR/dir_b" 2>/dev/null && [ -d "$DIR/dir_b/nested" ]; then
    ok dir_rename; else bad dir_rename; fi

# --- flock, and that it actually excludes ------------------------------------
# Taking a lock proves little; a lock that does not block a second holder is worse
# than no lock, because the application believes it is serialised.
printf 'lock' > "$DIR/lockfile"
if ! require flock flock_excludes; then :
elif flock -x -w 2 "$DIR/lockfile" true 2>/dev/null; then
    if flock -x "$DIR/lockfile" -c 'flock -x -n '"$DIR"'/lockfile -c true' 2>/dev/null; then
        bad flock_excludes "second holder acquired a held exclusive lock"
    else
        ok flock_excludes
    fi
else
    bad flock_excludes "could not take an exclusive lock at all"
fi

# --- mtime moves on write ----------------------------------------------------
# PHP's opcache revalidation is a stat-and-compare-mtime. A filesystem that does
# not move mtime silently serves stale bytecode.
printf 'v1' > "$DIR/mtime"
before=$(stat -c %Y "$DIR/mtime")
sleep 1.1
printf 'v2' > "$DIR/mtime"
if [ "$(stat -c %Y "$DIR/mtime")" != "$before" ]; then ok mtime_advances; else bad mtime_advances; fi

echo "TOTAL_FAILURES,$fails"
echo "TOTAL_ERRORS,$errors"
# Non-zero on either: a tier with failures is disqualified, and a run with errors
# has not actually been assessed, which is not the same thing as passing.
exit $(( fails > 0 || errors > 0 ? 1 : 0 ))
