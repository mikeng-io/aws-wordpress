#!/usr/bin/env bash
# E5 mode of the shared bench image. entrypoint.sh execs this after its st_dev mount
# check and its mount-facts capture, which E5 reuses unchanged: every nosharecache
# mount has its own st_dev, so a superblock that was silently shared fails there.
#
# What this adds, per experiments/E5-attribute-cache/README.md:
#   - fail-closed checks that the mount options E5 depends on actually took
#   - the 120 s seed-age gate, read from the host's record, never through a mount
#   - conformance on each tier's default mount, inside conf/ only
#   - cohort A: one tier at a time, tier order shuffled, a counter snapshot before
#     and after every cohort
#   - cohort B: all tiers and intervals at once
#   - upload, with a per-tier status file the collector checks
#
# A cohort whose instrument fails is recorded as `error` in status.csv and is never
# dropped silently; the grader turns it into ERROR. The run continues, because one
# tier's failure should not throw away five others.
set -euo pipefail

: "${E5_TIERS:?}" "${E5_NFS_TIERS?}"
WAIT_S="${E5_WAIT_S:-75}"
PROBE_WAIT_S="${E5_PROBE_WAIT_S:-75}"
WARMUP_S="${E5_WARMUP_S:-300}"
MEASURE_S="${E5_MEASURE_S:-600}"
AGE_MIN_S="${E5_AGE_MIN_S:-120}"
DELTAS="${E5_DELTAS:-0.1 1 10}"
# Raw per-op lines for one request in R. Every request is kept as a per-op
# histogram regardless; see the README's 2026-10-16 amendment for why not all raw.
RAW_EVERY="${E5_RAW_EVERY:-0.1:100 1:10 10:1}"
A8_PASSES="${E5_A8_PASSES:-10}"
OUT=/tmp/e5
FACTS=/tmp/mount-facts.csv
mkdir -p "$OUT"

log() { echo "[$(date -u +%H:%M:%S)] $*"; }
is_nfs() { case " $E5_NFS_TIERS " in *" $1 "*) return 0 ;; esac; return 1; }
mount_path() {  # the BENCH_MOUNTS path for a mount name
    local pair
    for pair in $BENCH_MOUNTS; do [ "${pair%%=*}" = "$1" ] && { echo "${pair#*=}"; return 0; }; done
    echo "FATAL: no mount named $1 in BENCH_MOUNTS" >&2; exit 1
}
# The directory a cohort runs in. NFS tiers have one mount (one superblock) per
# cohort family; Lustre and EBS have one mount, so families are subtrees of it.
tier_dir() {  # tier_dir <tier> <default|forced|ss-0.1|ss-1|ss-10>
    if is_nfs "$1"; then mount_path "$1.$2"
    else
        local sub="$2"; [ "$sub" = default ] && sub=a
        echo "$(mount_path "$1")/$sub"
    fi
}
conf_dir() { if is_nfs "$1"; then echo "$(tier_dir "$1" default)/conf"; else echo "$(mount_path "$1")/conf"; fi; }

# --- the mount options E5 depends on, checked, not assumed --------------------
# nosharecache is what makes each mount's counters attributable; acregmin/acregmax
# must be 0 on `forced` and untouched everywhere else, or "production mount" is a
# label rather than a fact. The kernel prints nosharecache and any non-default ac*
# value in the mount options, so absence of ac* means the defaults (3/60/30/60).
bad_mounts=0
for tier in $E5_NFS_TIERS; do
    for m in default forced ss-0.1 ss-1 ss-10; do
        p=$(mount_path "$tier.$m")
        opts=$(findmnt -n -o OPTIONS --target "$p" || echo "")
        case ",$opts," in *,nosharecache,*) ;; *) echo "FATAL: $tier.$m is not nosharecache: $opts" >&2; bad_mounts=1 ;; esac
        if [ "$m" = forced ]; then
            case ",$opts," in *,acregmin=0,*) ;; *) echo "FATAL: $tier.forced lacks acregmin=0: $opts" >&2; bad_mounts=1 ;; esac
            case ",$opts," in *,acregmax=0,*) ;; *) echo "FATAL: $tier.forced lacks acregmax=0: $opts" >&2; bad_mounts=1 ;; esac
        else
            case ",$opts," in *,acreg*|*,acdir*|*,noac,*|*,actimeo*|*,lookupcache=*)
                echo "FATAL: $tier.$m is not the production mount: $opts" >&2; bad_mounts=1 ;; esac
        fi
    done
done
[ "$bad_mounts" -eq 0 ] || exit 1
log "E5 mount options verified: nosharecache everywhere, acregmin=acregmax=0 only on forced"

# --- seed age, from the host's record ------------------------------------------
seed_utc=$(cat /bench/host-facts/seed-utc 2>/dev/null || true)
if ! printf '%s' "$seed_utc" | grep -qE '^[0-9]+$'; then
    echo "FATAL: no usable /bench/host-facts/seed-utc ('$seed_utc') - cannot prove the files are old" >&2
    exit 1
fi
now=$(date +%s)
if [ "$seed_utc" -gt "$now" ]; then echo "FATAL: seed-utc is in the future" >&2; exit 1; fi
while [ $(( $(date +%s) - seed_utc )) -lt "$AGE_MIN_S" ]; do sleep 5; done
echo "seed_age_at_start_s,$(( $(date +%s) - seed_utc ))" >> "$FACTS"
log "seed age gate passed: $(( $(date +%s) - seed_utc )) s since seeding"

# --- counters ------------------------------------------------------------------
# NFS: only this mount's section of /proc/self/mountstats - a whole-file snapshot
# per cohort would be ~2 MB per tier, and analysis needs one section.
mountstats_section() {  # <mountpoint>
    awk -v mp=" mounted on $1 with fstype " '/^device /{p = index($0, mp) > 0} p' /proc/self/mountstats
}
snap() {  # snap <tier> <cohort> <pre|post> <mount-family>
    local f="$OUT/$1/$2.$3"
    if is_nfs "$1"; then
        mountstats_section "$(tier_dir "$1" "$4")" > "$f.mountstats"
        [ -s "$f.mountstats" ] || { echo "no mountstats section for $1/$4" >&2; return 1; }
    elif [ "$1" = fsx_lustre ]; then
        # Lustre keeps no mountstats; its counters are under /proc/fs/lustre or
        # debugfs, read by the privileged sidecar. A failure is an ERROR for the
        # cohort, not a missing column.
        request-lustre-stats > "$f.lustre" || { echo "lustre counters unavailable" >&2; return 1; }
    fi
}

status() { echo "$2,$3" >> "$OUT/$1/status.csv"; }

# One cohort: counters, timed pass, counters. Prints nothing on success.
cohort() {  # cohort <tier> <cohort> <op> <family> [passes]
    local tier=$1 c=$2 op=$3 fam=$4 passes=${5:-1} dir
    dir=$(tier_dir "$tier" "$fam")
    : > "$OUT/$tier/$c.err"
    if snap "$tier" "$c" pre "$fam" 2>> "$OUT/$tier/$c.err" \
       && agebench pass "$dir" "$op" "$c" "$passes" > "$OUT/$tier/$c.csv" 2>> "$OUT/$tier/$c.err" \
       && snap "$tier" "$c" post "$fam" 2>> "$OUT/$tier/$c.err"; then
        status "$tier" "$c" ok; rm -f "$OUT/$tier/$c.err"
    else
        status "$tier" "$c" error
        log "  $tier $c: ERROR - $(tail -1 "$OUT/$tier/$c.err" 2>/dev/null)"
        return 1
    fi
}

# --- conformance, on the default mount, in conf/ only --------------------------
for tier in $E5_TIERS; do
    mkdir -p "$OUT/$tier"
    : > "$OUT/$tier/status.csv"
    if conformance "$(conf_dir "$tier")" > "$OUT/$tier/conformance.csv" 2>&1; then
        log "$tier: POSIX conformance PASSED"
    else
        log "$tier: POSIX conformance FAILED - $(grep -c ',FAIL' "$OUT/$tier/conformance.csv" || true) check(s)"
    fi
done

# --- cohort A: miss cost, one tier at a time --------------------------------------
order=$(printf '%s\n' $E5_TIERS | shuf | tr '\n' ' ')
i=0; for t in $order; do i=$((i + 1)); echo "tier_order,$t,$i" >> "$FACTS"; done
log "cohort A tier order: $order"

for tier in $order; do
    log "cohort A: $tier"
    echo "a_start,$tier,$(date +%s)" >> "$FACTS"
    {
        cohort "$tier" A1 stat default &&
        cohort "$tier" A2 enoent default &&
        { log "  $tier: waiting ${WAIT_S}s for attributes to expire"; sleep "$WAIT_S"; } &&
        cohort "$tier" A3 stat default &&
        cohort "$tier" A4 enoent default &&
        cohort "$tier" A5 stat default &&
        cohort "$tier" A6 open_read default &&
        { log "  $tier: waiting ${WAIT_S}s"; sleep "$WAIT_S"; } &&
        cohort "$tier" A7 open_read default &&
        if is_nfs "$tier"; then
            # The forced mount's first pass is a first touch (LOOKUP), not a
            # revalidation, so it is recorded as A8w and excluded from A8.
            cohort "$tier" A8w stat forced &&
            cohort "$tier" A8 stat forced "$A8_PASSES"
        fi
    } || log "  $tier: cohort A stopped at the first ERROR; later cohorts not run"
done

# --- cohort B: steady state, everything at once ----------------------------------
log "cohort B: $(echo $E5_TIERS | wc -w) tiers x intervals {$DELTAS}, warm-up ${WARMUP_S}s, measured ${MEASURE_S}s"
echo "b_start,$(date +%s)" >> "$FACTS"
pids=()
labels=()
for tier in $E5_TIERS; do
    for d in $DELTAS; do
        raw=1
        for r in $RAW_EVERY; do [ "${r%%:*}" = "$d" ] && raw="${r#*:}"; done
        rpc_args=()
        if is_nfs "$tier"; then rpc_args=("$(tier_dir "$tier" "ss-$d")"); fi
        agebench serve "$(tier_dir "$tier" "ss-$d")" "$d" "$WARMUP_S" "$MEASURE_S" "B-$d" \
            "$OUT/$tier/B-$d" "$raw" "${rpc_args[@]}" 2> "$OUT/$tier/B-$d.err" &
        pids+=($!); labels+=("$tier B-$d")
    done
done
for k in "${!pids[@]}"; do
    set -- ${labels[$k]}
    if wait "${pids[$k]}"; then status "$1" "$2" ok; rm -f "$OUT/$1/$2.err"
    else status "$1" "$2" error; log "  $1 $2: ERROR - $(tail -1 "$OUT/$1/$2.err" 2>/dev/null)"; fi
done
echo "b_end,$(date +%s)" >> "$FACTS"

# Trim each serve process's whole-file snapshots to its own mount's section, and
# compress the per-request and raw files.
for tier in $E5_TIERS; do
    for d in $DELTAS; do
        for when in warm end; do
            f="$OUT/$tier/B-$d.mountstats.$when"
            [ -f "$f" ] || continue
            if is_nfs "$tier"; then
                awk -v mp=" mounted on $(tier_dir "$tier" "ss-$d") with fstype " \
                    '/^device /{p = index($0, mp) > 0} p' "$f" > "$f.tmp" && mv "$f.tmp" "$f"
            else
                rm -f "$f"
            fi
        done
        for k in req raw; do [ -f "$OUT/$tier/B-$d.$k.csv" ] && gzip -9 "$OUT/$tier/B-$d.$k.csv"; done
    done
done

# --- expiry probe: all B readers are stopped; do not touch ss mounts while idle ---
# /proc/uptime is monotonic and does not access any measurement mount.
log "expiry probes: idle ${PROBE_WAIT_S}s after all B readers stop"
idle_start=$(awk '{print $1}' /proc/uptime)
sleep "$PROBE_WAIT_S"
idle_s=$(awk -v start="$idle_start" '{printf "%.2f", $1-start}' /proc/uptime)
for tier in $E5_NFS_TIERS; do
    for d in $DELTAS; do
        echo "$idle_s" > "$OUT/$tier/D-$d.idle-seconds"
        cohort "$tier" "D-$d" stat "ss-$d" || log "  $tier D-$d: probe unavailable"
    done
done

# --- upload --------------------------------------------------------------------
if [ -n "${BENCH_S3_BUCKET:-}" ]; then
    arm="${BENCH_ARM:-ec2}"
    # cp --recursive, not sync: sync lists the destination first, and the task role
    # is granted write only (as in E2). The first E5 pilot,
    # results/E5/20261015T170718Z-8f2db3b, ran every cohort and then lost all of it
    # here to s3:ListBucket AccessDenied. A local upload needs only PutObject.
    aws s3 cp "$OUT/" "s3://$BENCH_S3_BUCKET/$arm/" --recursive --only-show-errors
    aws s3 cp "$FACTS" "s3://$BENCH_S3_BUCKET/$arm/mount-facts.csv" --only-show-errors
    # Last: the collector treats the manifest's presence as "upload finished".
    printf '%s\n' $E5_TIERS | aws s3 cp - "s3://$BENCH_S3_BUCKET/$arm/manifest.txt" --only-show-errors
    log "all tiers uploaded"
else
    cp "$FACTS" "$OUT/mount-facts.csv"
    printf '%s\n' $E5_TIERS > "$OUT/manifest.txt"
    log "BENCH_S3_BUCKET unset - results left in $OUT"
fi
