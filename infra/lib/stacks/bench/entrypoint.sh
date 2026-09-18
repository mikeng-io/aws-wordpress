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
root_dev=$(stat -c %d /)
for pair in $BENCH_MOUNTS; do
    name="${pair%%=*}"; path="${pair#*=}"
    mkdir -p "$path"
    dev=$(stat -c %d "$path")
    if [ "$dev" = "$root_dev" ] && [ "$name" != "ephemeral" ] && [ "$name" != "root" ]; then
        echo "FATAL: $name ($path) is on the root filesystem (st_dev=$dev)." >&2
        echo "       It did not mount. Refusing to report the root volume as $name." >&2
        exit 1
    fi
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
echo "negotiated mount facts:"; cat /tmp/mount-facts.csv

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

for pair in $BENCH_MOUNTS; do
    name="${pair%%=*}"; path="${pair#*=}"
    echo "benchmarking $name at $path"
    mkdir -p "$path/tree"
    bench "$path/tree" > "/tmp/$name.csv"
    echo "$name done, $(wc -l < "/tmp/$name.csv") ops"
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
    # A manifest the collector checks against, so a missing tier is caught at
    # collection time rather than discovered during analysis.
    aws s3 cp /tmp/mount-facts.csv "s3://$BENCH_S3_BUCKET/$arm/mount-facts.csv" --only-show-errors
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
