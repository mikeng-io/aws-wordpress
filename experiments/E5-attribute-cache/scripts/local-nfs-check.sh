#!/usr/bin/env bash
# Local apparatus check for E5: no AWS, no cost. Runs the REAL bench image
# (entrypoint.sh -> e5-run.sh, agebench) and the REAL seeder (e5-seed.py) against a
# Linux kernel NFS server inside one privileged container, with the stack's mount
# discipline reproduced:
#   - seed through a separate mount, unmount it, drop caches, write seed-utc;
#   - five nosharecache mounts of the export ROOT per NFS tier, `forced` with
#     acregmin=0,acregmax=0, each bind-mounted at /bench/<tier>.<family> from its
#     own subtree e5/<tier>/<a|forced|ss-*> - the same paths the task sees;
#   - an `ebs` tier that is a plain directory on the container root, with root-dev
#     written so entrypoint.sh's "ebs must be on the root" check is live.
#
# It tests the assumptions the RPC-signature gates and the grader rest on: that a
# cold stat is a LOOKUP, a revalidation a GETATTR, a hit nothing, that per-mount
# mountstats are attributable, and what cohort B's counters and latency classifier
# do under 18-way concurrency. It is a loopback NFSv4.1 server on the Docker VM's
# kernel, not EFS or FSx: its latencies mean nothing, only its RPC counts are
# evidence. Output is an apparatus check, never a result; it does not go in results/.
#
# Usage: local-nfs-check.sh <out-dir> [fast] [leases-off]
#   fast        shortened waits and windows, for exercising the plumbing only. The
#               default is the pre-registered timing (75 s waits, 120 s seed age,
#               300 s warm-up, 600 s measured), so the attribute timers are crossed.
#   leases-off  run knfsd with fs.leases-enable=0, so it grants no delegations: the
#               regime P5 models (EFS cannot grant them). The sysctl is VM-wide; it is
#               restored on exit.
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
OUT="${1:?usage: local-nfs-check.sh <out-dir> [fast] [leases-off]}"
shift
FAST=0; LEASES=1
for a in "$@"; do
    case "$a" in
        fast) FAST=1 ;;
        leases-off) LEASES=0 ;;
        *) echo "unknown option: $a" >&2; exit 2 ;;
    esac
done
mkdir -p "$OUT"
OUT="$(cd "$OUT" && pwd)"
if [ "$FAST" = 1 ]; then
    TIMING="E5_WAIT_S=2 E5_WARMUP_S=6 E5_MEASURE_S=10 E5_AGE_MIN_S=0"
else
    TIMING=""   # e5-run.sh's defaults are the pre-registered values
fi

docker build -q -t e5-bench-local "$REPO/infra/lib/stacks/bench" >/dev/null
{
    echo "git_commit,$(git -C "$REPO" rev-parse --short HEAD)"
    echo "git_dirty,$(git -C "$REPO" status --porcelain | grep -c . || true)"
    echo "started_utc,$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "image_id,$(docker image inspect -f '{{.Id}}' e5-bench-local)"
    echo "docker_kernel,$(docker info --format '{{.KernelVersion}}')"
    echo "mode,$([ "$FAST" = 1 ] && echo fast || echo full)"
    echo "timing,${TIMING:-pre-registered defaults}"
    echo "leases_enable,$LEASES"
} > "$OUT/local-meta.csv"

rc=0
docker run --rm --privileged --name e5-local-check \
    -v "$REPO/infra/lib/stacks/bench/e5-seed.py:/e5-seed.py:ro" -v "$OUT:/export-out" \
    -e LEASES="$LEASES" \
    --entrypoint bash e5-bench-local -c "
set -euo pipefail
T=efs_host_plain
FAMILIES='default forced ss-0.1 ss-1 ss-10'
sub() { case \$1 in default) echo a ;; *) echo \$1 ;; esac; }
OLD_LEASES=\$(cat /proc/sys/fs/leases-enable)

# Teardown order matters: unmount every client mount BEFORE the server stops. A
# client holding read delegations against a server that has gone away cannot return
# them, the unmount blocks in D state, and the container (and the Docker VM's NFS
# client) wedges until Docker is restarted. Seen on the first run of this harness.
teardown() {
    set +e
    [ -n "\${SAMPLER:-}" ] && kill \$SAMPLER 2>/dev/null
    for f in \$FAMILIES; do umount /bench/\$T.\$f 2>/dev/null; umount /mnt/e5/\$T/\$f 2>/dev/null; done
    umount /seed 2>/dev/null
    exportfs -ua; rpc.nfsd 0
    echo \$OLD_LEASES > /proc/sys/fs/leases-enable
    echo \"teardown: leases-enable restored to \$(cat /proc/sys/fs/leases-enable)\"
}
trap teardown EXIT

# --- server ----------------------------------------------------------------------
echo \$LEASES > /proc/sys/fs/leases-enable   # before nfsd starts, so no delegation is ever granted
mount -t nfsd nfsd /proc/fs/nfsd
mkdir -p /export && mount -t tmpfs -o size=512m tmpfs /export
echo '/export *(rw,no_root_squash,no_subtree_check,fsid=0)' > /etc/exports
rpcbind; exportfs -ra; rpc.nfsd 8 2>/dev/null || true; rpc.mountd
OPTS=nfsvers=4.1,rsize=1048576,wsize=1048576,hard,timeo=600,retrans=2

# --- seed, through a mount that is then unmounted (as the host user data does) -----
mkdir -p /seed /bench/host-facts /bench/ebs
mount -t nfs -o \$OPTS 127.0.0.1:/ /seed
python3 /e5-seed.py \$(for f in \$FAMILIES; do echo /seed/e5/\$T/\$(sub \$f); done) > /export-out/seed.log
python3 /e5-seed.py /bench/ebs/a /bench/ebs/ss-0.1 /bench/ebs/ss-1 /bench/ebs/ss-10 >> /export-out/seed.log
mkdir -p /bench/ebs/conf
sync
date +%s > /bench/host-facts/seed-utc
umount /seed
sync; echo 3 > /proc/sys/vm/drop_caches
stat -c %d / > /bench/host-facts/root-dev   # the container root stands in for the host root

# --- measurement mounts: export root per family, its subtree bound at /bench -------
for f in \$FAMILIES; do
    o=\$OPTS,nosharecache; [ \$f = forced ] && o=\$o,acregmin=0,acregmax=0
    mkdir -p /mnt/e5/\$T/\$f /bench/\$T.\$f
    mount -t nfs -o \$o 127.0.0.1:/ /mnt/e5/\$T/\$f
    mount --bind /mnt/e5/\$T/\$f/e5/\$T/\$(sub \$f) /bench/\$T.\$f
done

# --- server-side delegation count, the direct check the client cannot make --------
# /proc/fs/nfsd/clients/*/states lists every open/lock/delegation stateid the
# server holds. Sampled every 15 s for the whole run.
bash -c '
    echo utc,delegations,opens > /export-out/server-delegations.csv
    while :; do
        d=\$(cat /proc/fs/nfsd/clients/*/states 2>/dev/null | grep -c \"type: deleg\" || true)
        o=\$(cat /proc/fs/nfsd/clients/*/states 2>/dev/null | grep -c \"type: open\" || true)
        echo \$(date +%s),\$d,\$o >> /export-out/server-delegations.csv
        sleep 15
    done' &
SAMPLER=\$!

# --- the real task, as the stack runs it --------------------------------------------
export BENCH_MODE=e5 BENCH_SHUFFLE=0 E5_TIERS=\"ebs \$T\" E5_NFS_TIERS=\$T
export BENCH_MOUNTS=\"ebs=/bench/ebs \$(for f in \$FAMILIES; do printf '%s ' \$T.\$f=/bench/\$T.\$f; done)\"
rc=0
env $TIMING /usr/local/bin/entrypoint.sh > /export-out/task.log 2>&1 || rc=\$?
echo \"task exit: \$rc\" | tee -a /export-out/task.log
mkdir -p /export-out/rep-1/ec2
cp -r /tmp/e5/. /export-out/rep-1/ec2/
cp /tmp/mount-facts.csv /export-out/rep-1/ec2/mount-facts.csv 2>/dev/null || true
exit \$rc
" || rc=$?
echo "finished_utc,$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$OUT/local-meta.csv"
python3 "$REPO/analysis/e5_stats.py" "$OUT" > /dev/null
echo "local check output: $OUT (summary.md)"
exit $rc
