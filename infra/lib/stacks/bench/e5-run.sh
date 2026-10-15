#!/usr/bin/env bash
# E5 task sequence: what an NFS stat costs on a tree this client did not create.
# Design, predictions and the reasons for every step: experiments/E5-attribute-cache.
#
# Layout, made by the host at boot (infra/lib/stacks/e5-attribute-cache.ts):
#   /e5/<tier>/<cohort>    cohort = default | forced | ss-0.1 | ss-1 | ss-10
#     NFS tiers: every cohort is its OWN mount (nosharecache), so each has its own
#                attribute cache and its own /proc/self/mountstats counters.
#     fsx_lustre: one Lustre client; cohorts are subdirectories (no forced).
#     ebs:        plain directories on the host root volume (no forced).
#   /bench/host-facts      root-dev, seed-epoch, seed-manifest, lustre-params
#   /e5-ctl                request files for the host's lctl snapshot service
#
# Order: mount check -> facts -> age gate -> conformance -> cohort A (one tier at a
# time, shuffled) -> cohort B (every tier and interval at once) -> upload.
# Every cohort is bracketed by counter snapshots; whether a cohort measured what it
# claims is decided in analysis/e5_stats.py from those counters, not assumed here.
set -euo pipefail

: "${E5_TIERS:?E5_TIERS must name the tiers}"
E5_ROOT="${E5_ROOT:-/e5}"
CTL="${E5_CTL_DIR:-/e5-ctl}"
FACTS="${E5_HOST_FACTS:-/bench/host-facts}"
INTERVALS="${E5_INTERVALS:-0.1 1 10}"
WAIT_S="${E5_WAIT_S:-75}"            # > acregmax (60) and acdirmax (60)
MIN_AGE_S="${E5_MIN_AGE_S:-120}"
WARMUP_S="${E5_WARMUP_S:-300}"
MEASURE_S="${E5_MEASURE_S:-600}"
GUARD_S="${E5_GUARD_S:-2}"
COMPILE_ALLOWANCE_S="${E5_COMPILE_ALLOWANCE_S:-120}"
FORCED_PASSES="${E5_FORCED_PASSES:-10}"
OUT=/tmp/out
mkdir -p "$OUT/ms" "$OUT/lustre"

log() { echo "[$(date -u +%H:%M:%S)] $*"; }
kind() { case "$1" in ebs) echo block ;; fsx_lustre) echo lustre ;; *) echo nfs ;; esac; }
cohorts() { [ "$(kind "$1")" = nfs ] && echo "default forced ss-${INTERVALS// / ss-}" || echo "default ss-${INTERVALS// / ss-}"; }
raw_every() { case "$1" in 0.1) echo 100 ;; 1) echo 10 ;; *) echo 1 ;; esac; }
has_lustre=0; for t in $E5_TIERS; do [ "$(kind "$t")" = lustre ] && has_lustre=1; done

# --- mount check: fail closed on anything that would look like a result -------
root_dev=$(cat "$FACTS/root-dev" 2>/dev/null || true)
printf '%s' "$root_dev" | grep -qE '^[0-9]+$' || { echo "FATAL: no host root-dev in $FACTS" >&2; exit 1; }
declare -A seen_dev
fail=0
for t in $E5_TIERS; do
    for c in $(cohorts "$t"); do
        p="$E5_ROOT/$t/$c"
        [ -d "$p" ] || { echo "FATAL: $p missing" >&2; fail=1; continue; }
        dev=$(stat -c %d "$p"); fs=$(stat -f -c %T "$p")
        opts=$(findmnt -n -o OPTIONS --target "$p" 2>/dev/null || echo "-")
        case "$(kind "$t")" in
            block)
                [ "$dev" = "$root_dev" ] || { echo "FATAL: $p is not on the host root volume" >&2; fail=1; } ;;
            lustre)
                [ "$fs" = lustre ] || { echo "FATAL: $p is $fs, not lustre" >&2; fail=1; }
                [ "$dev" != "$root_dev" ] || { echo "FATAL: $p is on the root volume" >&2; fail=1; } ;;
            nfs)
                [ "$fs" = nfs ] || { echo "FATAL: $p is $fs, not nfs" >&2; fail=1; }
                [ "$dev" != "$root_dev" ] || { echo "FATAL: $p did not mount" >&2; fail=1; }
                # One superblock per cohort is what makes the counters attributable.
                # nosharecache is the means; a distinct st_dev is the property.
                if [ -n "${seen_dev[$dev]:-}" ]; then
                    echo "FATAL: $p shares st_dev=$dev with ${seen_dev[$dev]} - one cache, not two" >&2; fail=1
                fi
                seen_dev[$dev]="$p"
                # forced, and only forced, zeroes the file attribute timers. No cohort
                # may zero the directory timers: that is actimeo=0, rejected in the README.
                has_ac=0; [[ ",$opts," == *",acregmin=0,"* && ",$opts," == *",acregmax=0,"* ]] && has_ac=1
                if [ "$c" = forced ] && [ "$has_ac" = 0 ]; then
                    echo "FATAL: $p is forced but its options lack acregmin=0,acregmax=0: $opts" >&2; fail=1
                elif [ "$c" != forced ] && [[ ",$opts," == *",acreg"* ]]; then
                    echo "FATAL: $p is a production cohort but sets acreg*: $opts" >&2; fail=1
                fi
                if [[ ",$opts," == *",noac,"* || ",$opts," == *",acdir"* || ",$opts," == *",actimeo"* ]]; then
                    echo "FATAL: $p touches directory/attribute caching beyond the design: $opts" >&2; fail=1
                fi ;;
        esac
    done
done
[ "$fail" = 0 ] || exit 1
log "mount check passed"

# --- facts --------------------------------------------------------------------
{
    echo "kernel,$(uname -r)"
    for nic in /sys/class/net/*/mtu; do [ -e "$nic" ] && echo "mtu,$(basename "$(dirname "$nic")"),$(cat "$nic")"; done
    for p in /sys/module/nfs/parameters/*; do [ -r "$p" ] && echo "nfs_param,$(basename "$p"),$(cat "$p" 2>/dev/null)"; done
    echo "seed_epoch,$(cat "$FACTS/seed-epoch")"
    for t in $E5_TIERS; do for c in $(cohorts "$t"); do
        p="$E5_ROOT/$t/$c"
        echo "mount,$t,$c,$(stat -f -c %T "$p"),$(stat -c %d "$p"),$(findmnt -n -o SOURCE --target "$p"),$(findmnt -n -o OPTIONS --target "$p")"
    done; done
} > "$OUT/mount-facts.csv"
cp "$FACTS/seed-manifest" "$OUT/seed-manifest.csv" 2>/dev/null || { echo "FATAL: no seed manifest" >&2; exit 1; }
cp "$FACTS/lustre-params" "$OUT/lustre-params.txt" 2>/dev/null || true

# --- counter snapshots --------------------------------------------------------
# Only the /e5 mounts' blocks of mountstats, whole: per-op counts are the evidence.
lustre_snap() {
    local tag="$1" id
    id="$(date +%s%N)-$$"
    echo "$tag" > "$CTL/req-$id.tmp" && mv "$CTL/req-$id.tmp" "$CTL/req-$id"
    for _ in $(seq 1 300); do
        if [ -e "$CTL/done-$id" ]; then
            mv "$CTL/out-$id" "$OUT/lustre/$tag.txt" 2>/dev/null || echo ERROR > "$OUT/lustre/$tag.txt"
            rm -f "$CTL/done-$id"; return 0
        fi
        sleep 0.1
    done
    # Never fails the task: Lustre's checks then grade ERROR, which is what they are.
    echo "ERROR no answer from host lctl service" > "$OUT/lustre/$tag.txt"
}
snap() {
    awk -v pfx=" mounted on $E5_ROOT/" '/^device /{keep=index($0,pfx)>0} keep' /proc/self/mountstats \
        > "$OUT/ms/$1.txt"
    [ "$has_lustre" = 1 ] && lustre_snap "$1"
    return 0
}

# --- age gate -------------------------------------------------------------------
# The host's own record, not a stat through a measurement mount: that read would
# warm the very cache this experiment needs cold.
seed_epoch=$(cat "$FACTS/seed-epoch")
age=$(( $(date +%s) - seed_epoch ))
if [ "$age" -lt "$MIN_AGE_S" ]; then
    log "seed is ${age}s old; waiting $((MIN_AGE_S - age))s"
    sleep $((MIN_AGE_S - age))
fi
echo "seed_age_at_start_s,$(( $(date +%s) - seed_epoch ))" >> "$OUT/mount-facts.csv"

# --- conformance gate, in default/conf: never inside the measured tree ---------
for t in $E5_TIERS; do
    if conformance "$E5_ROOT/$t/default/conf" > "$OUT/$t.conformance.csv" 2>&1; then
        log "$t: conformance PASSED"
    else
        log "$t: conformance FAILED: $(grep -c ',FAIL' "$OUT/$t.conformance.csv" || true) check(s)"
    fi
done

# --- cohort A: miss cost, one tier at a time --------------------------------------
cohort() {  # cohort <tier> <name> <op> <dir>
    snap "A.$1.$2.pre"
    agebench pass "$4" "$3" "$2" >> "$OUT/A.$1.csv"
    snap "A.$1.$2.post"
}
order=$(printf '%s\n' $E5_TIERS | shuf | tr '\n' ' ')
i=0; for t in $order; do i=$((i + 1)); echo "order,$t,$i" >> "$OUT/mount-facts.csv"; done
log "cohort A order: $order"
for t in $order; do
    d="$E5_ROOT/$t/default"
    log "A: $t"
    echo "a_start,$t,$(date +%s.%N)" >> "$OUT/mount-facts.csv"
    cohort "$t" A1 stat "$d"
    cohort "$t" A2 enoent "$d"
    sleep "$WAIT_S"
    cohort "$t" A3 stat "$d"
    cohort "$t" A4 enoent "$d"
    cohort "$t" A5 stat "$d"
    cohort "$t" A6 open_read "$d"
    sleep "$WAIT_S"
    cohort "$t" A7 open_read "$d"
    if [ "$(kind "$t")" = nfs ]; then
        snap "A.$t.A8.pre"
        for _ in $(seq 1 "$FORCED_PASSES"); do
            agebench pass "$E5_ROOT/$t/forced" stat A8 >> "$OUT/A.$t.csv"
        done
        snap "A.$t.A8.post"
    fi
done

# --- cohort B: steady state, all tiers and intervals at once ----------------------
start=$(( $(date +%s) + COMPILE_ALLOWANCE_S ))
warm=$((start + WARMUP_S)); end=$((warm + MEASURE_S))
echo "b_timeline,$start,$warm,$end" >> "$OUT/mount-facts.csv"
log "B: start $start, warm-up ends $warm, measurement ends $end"
pids=()
for t in $E5_TIERS; do
    for iv in $INTERVALS; do
        agebench serve "$E5_ROOT/$t/ss-$iv" "$iv" "$start" "$WARMUP_S" "$MEASURE_S" "$GUARD_S" \
            "$(raw_every "$iv")" "B.$t.$iv" > "$OUT/B.$t.$iv.csv" 2> "$OUT/B.$t.$iv.err" &
        pids+=("$!")
    done
done
sleep_until() { sleep "$(awk -v t="$1" -v n="$(date +%s.%N)" 'BEGIN{d=t-n; print (d>0?d:0)}')"; }
sleep_until "$start"; snap B.start
sleep_until "$warm";  snap B.warm
sleep_until "$end";   snap B.end
bfail=0
for pid in "${pids[@]}"; do wait "$pid" || bfail=1; done
if [ "$bfail" != 0 ]; then
    echo "FATAL: a serve process failed:" >&2; cat "$OUT"/B.*.err >&2; exit 1
fi
log "B done"

# --- upload -------------------------------------------------------------------
gzip -9 "$OUT"/A.*.csv "$OUT"/B.*.csv
printf '%s\n' $E5_TIERS > "$OUT/manifest.txt"
echo "$INTERVALS" | tr ' ' '\n' > "$OUT/intervals.txt"
if [ -n "${BENCH_S3_BUCKET:-}" ]; then
    aws s3 cp "$OUT" "s3://$BENCH_S3_BUCKET/${BENCH_ARM:-ec2}/" --recursive --only-show-errors
    log "uploaded to s3://$BENCH_S3_BUCKET/${BENCH_ARM:-ec2}/"
else
    log "BENCH_S3_BUCKET unset - results left in $OUT"
fi
