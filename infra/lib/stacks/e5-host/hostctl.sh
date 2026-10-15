#!/usr/bin/env bash
# E5 host-side counter service. Runs on the HOST (systemd-run from user data), not
# in the task: lctl and Lustre's client counters live on the host, and the
# benchmark container stays unprivileged, as in E2.
#
# Same file protocol as E2's request-drop/cache-dropper: the task writes
# req-<id> (containing a tag) via rename, this answers with out-<id> (the counter
# dump) and then done-<id>. Answering out before done means a reader that sees done
# always finds a complete dump.
#
# What is dumped: mdc.*.stats and osc.*.stats are per-RPC-opcode counts (the
# evidence of a server round trip); md_stats and llite stats are client-side call
# counts; lock_count is how many DLM locks the client holds. Which of these the
# grading reads is fixed in analysis/e5_stats.py, and confirmed on the pilot.
set -uo pipefail
d="${1:-/mnt/e5-ctl}"
mkdir -p "$d"
while :; do
    for r in "$d"/req-*; do
        [ -e "$r" ] || continue
        case "$r" in *.tmp) continue ;; esac
        id="${r##*/req-}"
        tag=$(cat "$r" 2>/dev/null); rm -f "$r"
        {
            echo "tag $tag"
            echo "epoch $(date +%s.%N)"
            lctl get_param mdc.*.stats mdc.*.md_stats osc.*.stats llite.*.stats \
                ldlm.namespaces.*.lock_count 2>&1
        } > "$d/out-$id.tmp"
        mv "$d/out-$id.tmp" "$d/out-$id"
        echo ok > "$d/done-$id"
    done
    sleep 0.05
done
