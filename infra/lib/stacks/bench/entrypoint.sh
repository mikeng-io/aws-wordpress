#!/usr/bin/env bash
# Runs the benchmark against every mount named in BENCH_MOUNTS, in sequence, inside
# one task - so the only variable between result sets is which mount served the
# request. Same CPU, same kernel, same moment in time.
#
# BENCH_MOUNTS is a space-separated list of "name=path" pairs, e.g.
#   "instance_store=/bench/instance-store ebs=/bench/ebs efs=/bench/efs"
# The name becomes the CSV block label that the collector greps for.
set -euo pipefail

: "${BENCH_MOUNTS:?BENCH_MOUNTS must be set, e.g. 'local=/local-bench efs=/efs-bench'}"

# --- fail closed on the failure mode that would look like a result ------------
#
# Every arm here is a bind mount or a volume. If one silently failed to mount, the
# path still exists - as an ordinary directory on the root filesystem - and the
# benchmark would run happily and report the root volume's latency under another
# tier's name. That is indistinguishable from a real measurement once it is in a
# CSV, so it is checked here rather than trusted: st_dev must be distinct across
# every named mount, and no mount may share st_dev with /.
declare -A seen_dev

# The HOST's root device, written by the host because the container cannot work it
# out. Inside a container `/` is an overlay mount with its own device id, so
# comparing a bind-mounted path against the CONTAINER's root never matches - for a
# real mount or a silently-failed one alike. Verified: container / = 62, bind-mounted
# plain host dir = 49. This check was therefore inert for every bind-mounted tier,
# and what actually caught failures was the st_dev collision test below, because the
# 'ebs' arm is deliberately anchored to the host root. That was luck, not design: it
# evaporates the moment 'ebs' is not in the mount list.
host_root_dev=$(cat /bench/host-facts/root-dev 2>/dev/null || true)
# Must be a non-empty integer. An empty or malformed file would otherwise compare
# equal to nothing and let every tier through - a check that passes because it is
# broken is worse than no check, and this exact case was hit while testing.
if printf '%s' "$host_root_dev" | grep -qE '^[0-9]+$'; then
    root_dev=$host_root_dev
    echo "host root device (from host): $root_dev"
else
    host_root_dev=""
    root_dev=$(stat -c %d /)
    # Fargate has no host to ask, and its tiers are the task's own writable layer
    # plus EFS - neither is a host bind mount - so the container's own root is the
    # right reference there. On EC2 this fallback means the check is weaker than it
    # looks, so it says so rather than passing quietly.
    echo "WARNING: no host root-dev provided; using container root ($root_dev)." >&2
    echo "         Bind-mounted tiers cannot be checked against the host root." >&2
fi
for pair in $BENCH_MOUNTS; do
    name="${pair%%=*}"; path="${pair#*=}"
    mkdir -p "$path"
    dev=$(stat -c %d "$path")
    case "$name" in
        ephemeral|root)
            # The task's own writable layer IS the tier measured; nothing to check.
            ;;
        ebs)
            # The EBS tier is the host's root volume ON PURPOSE: /mnt/ebs-bench is a
            # plain directory on it. So the check is inverted, not skipped - it must
            # BE on the host root. Until 2026-10-15 'ebs' was missing from the exempt
            # list above, which went unnoticed while the root-dev comparison was inert
            # and failed the first FSx replication the moment it was made live.
            if [ -n "$host_root_dev" ] && [ "$dev" != "$root_dev" ]; then
                echo "FATAL: ebs ($path) is not on the host root volume (st_dev=$dev, root=$root_dev)." >&2
                echo "       Refusing to report another device as EBS." >&2
                exit 1
            fi
            ;;
        *)
            if [ "$dev" = "$root_dev" ]; then
                echo "FATAL: $name ($path) is on the root filesystem (st_dev=$dev)." >&2
                echo "       It did not mount. Refusing to report the root volume as $name." >&2
                exit 1
            fi
            ;;
    esac
    if [ -n "${seen_dev[$dev]:-}" ]; then
        echo "FATAL: $name ($path) shares st_dev=$dev with ${seen_dev[$dev]}." >&2
        echo "       Two arms are the same device. Refusing to report them as distinct." >&2
        exit 1
    fi
    seen_dev[$dev]="$name"
done

echo "mount check passed:"
for pair in $BENCH_MOUNTS; do
    name="${pair%%=*}"; path="${pair#*=}"
    echo "  $name -> $path (st_dev=$(stat -c %d "$path"), fs=$(stat -f -c %T "$path"))"
done

# If an eviction hook is configured, prove it works once, now, before any timing.
# A hook that cannot drop the cache would make every EC2 throughput phase an ERROR;
# better to fail the task here than to spend a replication finding that out.
if [ -n "${BENCH_THROUGHPUT:-}" ] && [ -n "${TPUT_EVICT_HOOK:-}" ]; then
    if ! "$TPUT_EVICT_HOOK"; then
        echo "FATAL: eviction hook $TPUT_EVICT_HOOK does not work - refusing to run throughput" >&2
        exit 1
    fi
    echo "eviction hook $TPUT_EVICT_HOOK: verified"
fi
# --- conformance gate, before any timing -------------------------------------
#
# H6: a tier that cannot hold POSIX semantics is not eligible for a latency
# number. Running this first means a disqualified tier is recorded as such rather
# than showing up in a chart as merely fast.
#
# A failure does NOT abort the run. The result IS the finding - E2 pre-registered
# that Mountpoint-S3 fails here rather than on latency - so the gate records the
# verdict and the benchmark still runs, letting the writeup say both what it
# scored and why the score does not count.
# --- run order -----------------------------------------------------------------
#
# Tiers were previously benchmarked in a fixed order, with the FSx arms always last.
# That makes tier identity perfectly collinear with sequence position: any monotonic
# drift over the run - CPU frequency settling, interrupt coalescing, thermals - lands
# entirely on whichever tiers run late and never on the ones that run early. With a
# 600x effect that does not matter; the FSx-vs-EFS comparisons are expected to be
# much closer, where a systematic few percent could change a conclusion.
#
# So the order is shuffled per task and the ACTUAL order is recorded. Across the
# protocol's three independent replications that decorrelates position from tier.
if [ "${BENCH_SHUFFLE:-1}" = "1" ]; then
    BENCH_MOUNTS=$(printf '%s\n' $BENCH_MOUNTS | shuf | tr '\n' ' ')
fi
echo "run order: $BENCH_MOUNTS"
i=0
for pair in $BENCH_MOUNTS; do
    i=$((i + 1)); echo "order,${pair%%=*},$i" >> /tmp/mount-facts.csv
done

# --- client-side facts that were previously assumed equal across tiers ----------
# Kernel: the EC2 host records its own, but nothing recorded Fargate's, so the claim
# that every arm shares attribute-cache timer defaults was unverified there.
# MTU: FSx ENIs default to 9001. A 50 KB read is ~34 frames at 1500 against ~6 at
# 9001, so a mismatch is not negligible for open+read even though stat moves no
# payload. Capability is documented; the configured value is not, so it is read.
{
  echo "kernel,$(uname -r)"
  for nic in /sys/class/net/*/mtu; do
      [ -e "$nic" ] || continue
      echo "mtu,$(basename "$(dirname "$nic")"),$(cat "$nic" 2>/dev/null || echo '?')"
  done
} >> /tmp/mount-facts.csv

# What the mount ACTUALLY negotiated, not what was requested. A client can ask for
# rsize=1048576 and be silently given 262144 by a server with less memory; the
# request is in the CDK, the negotiated value is only here. Recorded per tier so any
# claim about transfer size can be checked against the run rather than the intent.
for pair in $BENCH_MOUNTS; do
    name="${pair%%=*}"; path="${pair#*=}"
    src=$(findmnt -n -o SOURCE --target "$path" 2>/dev/null || echo "-")
    opts=$(findmnt -n -o OPTIONS --target "$path" 2>/dev/null || echo "-")
    fstype=$(stat -f -c %T "$path" 2>/dev/null || echo "-")
    echo "mount,$name,$fstype,$src,$opts" >> /tmp/mount-facts.csv
done
# NFSv4 read delegations are a capability difference between tiers, not a speed
# difference, and they are easy to mistake for one. EFS documents that OPEN always
# returns OPEN_DELEGATE_NONE - it cannot grant a delegation at all - while FSx for
# OpenZFS documents that it can. Under a delegation a client may answer stat/open
# locally with no wire round trip AND without waiting on an attribute-cache timer,
# which is exactly the "fast cluster" this study reports. If one tier can do that and
# another cannot, a difference in fast-cluster share is a protocol capability, and
# the writeup has to say so rather than let it read as "this filesystem is faster".
#
# Counters are recorded before and after the benchmark so the delta is attributable.
# https://docs.aws.amazon.com/efs/latest/ug/limits.html
# https://docs.aws.amazon.com/fsx/latest/OpenZFSGuide/performance.html
snapshot_nfs_counters() {
    { echo "=== nfs counters ($1) ==="
      nfsstat -c 2>/dev/null || echo "(nfsstat unavailable)"
      # The whole file, per mount. The first FSx replication recorded DELEGRETURN
      # 0 -> 1002 in nfsstat's aggregate but could not say which tier granted the
      # delegations: this line used to grep "deleg" case-sensitively (the per-op
      # rows say DELEGRETURN) and cut the output at 80 lines. Per-mount op counts
      # are the attribution, so nothing is filtered here; analysis filters.
      cat /proc/self/mountstats 2>/dev/null
    } >> /tmp/nfs-counters.txt 2>&1 || true
}
snapshot_nfs_counters before

echo "negotiated mount facts:"; cat /tmp/mount-facts.csv

# E5 reuses everything above - the st_dev check, which is what proves each
# nosharecache mount is its own superblock, and the negotiated-mount record - and
# replaces everything below. E2 and E3 never set BENCH_MODE, so their path is unchanged.
if [ "${BENCH_MODE:-}" = "e5-formal" ]; then
    exec python3 /usr/local/bin/e5-formal.py
fi
if [ "${BENCH_MODE:-}" = "e5-diagnostic" ]; then
    exec python3 /usr/local/bin/e5-diagnostic.py
fi
if [ "${BENCH_MODE:-}" = "e5" ]; then
    export BENCH_MOUNTS
    exec /usr/local/bin/e5-run
fi

# E4 hydration: copy the read-only tree onto the task's local storage and time the
# download+extract. This runs BEFORE conformance and benchmarking, so both see the
# hydrated tree. The EFS arm does not set this and is a fresh task, not a warmed one.
if [ -n "${BENCH_HYDRATE_FROM:-}" ]; then
    : "${BENCH_HYDRATE_TO:?BENCH_HYDRATE_TO must name the local tree directory}"
    [ -f "$BENCH_HYDRATE_FROM" ] || {
        echo "FATAL: hydration source $BENCH_HYDRATE_FROM is not a file" >&2
        exit 1
    }
    bytes=$(stat -c %s "$BENCH_HYDRATE_FROM")
    mkdir -p "$BENCH_HYDRATE_TO"
    t0=$(date +%s%N)
    tar -xf "$BENCH_HYDRATE_FROM" -C "$BENCH_HYDRATE_TO"
    t1=$(date +%s%N)
    printf 'hydrate,%s,%s\n' "$((t1 - t0))" "$bytes" > /tmp/hydration.csv
    echo "hydrated $bytes bytes into $BENCH_HYDRATE_TO in $(( (t1 - t0) / 1000000 )) ms"
fi

for pair in $BENCH_MOUNTS; do
    name="${pair%%=*}"; path="${pair#*=}"
    echo "conformance: $name"
    if conformance "$path" > "/tmp/$name.conformance.csv" 2>&1; then
        echo "  $name: POSIX conformance PASSED"
    else
        echo "  $name: POSIX conformance FAILED - $(grep -c ',FAIL' "/tmp/$name.conformance.csv" || true) check(s)"
        grep ',FAIL' "/tmp/$name.conformance.csv" || true
    fi
done

# A tier can be conformance-only. Mountpoint for S3 is the case: E2's prediction 4
# is about POSIX semantics, and its unlink path fails the benchmark's create/unlink
# loop before a latency number exists. Forcing a latency CSV would either crash the
# task or record a number from a different operation; a marker keeps the tier in
# the manifest without pretending it was benchmarked.
is_conformance_only() {
    case " ${BENCH_CONFORMANCE_ONLY:-} " in *" $1 "*) return 0 ;; *) return 1 ;; esac
}

for pair in $BENCH_MOUNTS; do
    name="${pair%%=*}"; path="${pair#*=}"
    if is_conformance_only "$name"; then
        printf 'skipped,0\n' > "/tmp/$name.csv"
        echo "$name: conformance-only; latency benchmark skipped"
        continue
    fi
    echo "benchmarking $name at $path"
    mkdir -p "$path/tree"
    bench "$path/tree" > "/tmp/$name.csv"
    echo "$name done, $(wc -l < "/tmp/$name.csv") ops"
done

# E4 seed: leave the built tree on the origin and tar it for the hydrated arm. The
# seed task's own latency CSV is not a result; it measured a tree it just created.
if [ -n "${BENCH_SEED_ONLY:-}" ]; then
    : "${BENCH_SEED_TAR:?BENCH_SEED_TAR must name the tarball path}"
    pair=${BENCH_MOUNTS%% *}
    path=${pair#*=}
    tar -C "$path/tree" -cf "$BENCH_SEED_TAR" .
    echo "seed tar written: $BENCH_SEED_TAR ($(stat -c %s "$BENCH_SEED_TAR") bytes)"
fi

snapshot_nfs_counters after

# --- throughput, for the tiers prediction 1 ranks ------------------------------
#
# After every latency run, never interleaved with one: 4 GiB of streaming through a
# tier would otherwise sit in the page cache and the server caches while another
# tier's stat() is being timed. Opt-in per task through BENCH_THROUGHPUT, so E3's
# use of this image is unchanged.
#
# Read-phase order is shuffled per tier, for the same reason the tier order is: a
# fixed order would make "1-stream" and "ran first" the same variable. tput prints
# its phases in the order it ran them, so the CSV records the order itself.
#
# A probe that fails is recorded as an error row and the run continues. Failing the
# task here would throw away every tier's latency data over one tier's throughput,
# and the collector and grader both treat the error row as ERROR, never as a number.
for name in ${BENCH_THROUGHPUT:-}; do
    if is_conformance_only "$name"; then continue; fi
    path=""
    for pair in $BENCH_MOUNTS; do [ "${pair%%=*}" = "$name" ] && path="${pair#*=}"; done
    if [ -z "$path" ]; then
        echo "FATAL: BENCH_THROUGHPUT names '$name', which is not in BENCH_MOUNTS" >&2
        exit 1
    fi
    order=$(shuf -n1 -e 1,4 4,1)
    echo "throughput: $name (read order $order)"
    if ! throughput "$path/tput" "$order" > "/tmp/$name.tput.csv" 2> "/tmp/$name.tput.err"; then
        echo "error,0,0,0,-1" >> "/tmp/$name.tput.csv"
        rm -rf "${path:?}/tput"
        echo "  $name: throughput probe FAILED: $(cat "/tmp/$name.tput.err")" >&2
    fi
    cat "/tmp/$name.tput.csv"
done

# Results go to S3, not stdout.
#
# stdout was the original transport and it does not scale: the awslogs driver emits
# one CloudWatch event per line, three tiers is ~12,000 events, and a single
# GetLogEvents call returns at most 10,000 - so the last tier silently vanished
# from the collected output while the task still exited 0. A truncated result that
# looks complete is the exact failure mode this apparatus is supposed to refuse.
if [ -n "${BENCH_S3_BUCKET:-}" ]; then
    arm="${BENCH_ARM:-unknown}"
    for pair in $BENCH_MOUNTS; do
        name="${pair%%=*}"
        aws s3 cp "/tmp/$name.csv" "s3://$BENCH_S3_BUCKET/$arm/$name.csv" --only-show-errors
        aws s3 cp "/tmp/$name.conformance.csv" \
            "s3://$BENCH_S3_BUCKET/$arm/$name.conformance.csv" --only-show-errors
        echo "uploaded $name.csv + conformance -> s3://$BENCH_S3_BUCKET/$arm/"
    done
    for name in ${BENCH_THROUGHPUT:-}; do
        aws s3 cp "/tmp/$name.tput.csv" "s3://$BENCH_S3_BUCKET/$arm/$name.tput.csv" --only-show-errors
    done
    # The collector checks this list the way it checks the manifest: a tier that was
    # supposed to have a throughput result and does not is a collection failure.
    printf '%s\n' ${BENCH_THROUGHPUT:-} \
        | aws s3 cp - "s3://$BENCH_S3_BUCKET/$arm/throughput-manifest.txt" --only-show-errors
    # A manifest the collector checks against, so a missing tier is caught at
    # collection time rather than discovered during analysis.
    aws s3 cp /tmp/mount-facts.csv "s3://$BENCH_S3_BUCKET/$arm/mount-facts.csv" --only-show-errors
    aws s3 cp /tmp/nfs-counters.txt "s3://$BENCH_S3_BUCKET/$arm/nfs-counters.txt" --only-show-errors || true
    for pair in $BENCH_MOUNTS; do echo "${pair%%=*}"; done \
        | aws s3 cp - "s3://$BENCH_S3_BUCKET/$arm/manifest.txt" --only-show-errors
    echo "all tiers uploaded"
else
    echo "BENCH_S3_BUCKET unset - printing to stdout (only safe for small runs)"
    for pair in $BENCH_MOUNTS; do
        name="${pair%%=*}"
        echo "===CSV_START:$name==="; cat "/tmp/$name.csv"; echo "===CSV_END:$name==="
    done
fi
