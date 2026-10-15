#!/usr/bin/env bash
# Local apparatus check for E5: no AWS, no cost. Runs the REAL bench image and the
# REAL host seeder against a kernel NFS server inside one privileged container,
# with the same mount discipline the stack uses (seed mount -> unmount -> one
# nosharecache mount per cohort, forced = acregmin=0,acregmax=0).
#
# It exists to test, before paying for a deploy, the assumptions the RPC-signature
# gates rest on: that a cold stat is a LOOKUP, a revalidation a GETATTR, a hit
# nothing, and that per-cohort mountstats are attributable. It is a loopback NFSv4.1
# server on the Docker VM's kernel, not EFS or FSx: its latencies mean nothing, and
# only its RPC counts are evidence. Output goes to $1 (default: a scratch dir).
#
# Usage: local-nfs-check.sh <out-dir> [fast]
#   fast: shortened waits and windows, for exercising the plumbing only. The
#         default uses the real 75 s waits, so the attribute timers are crossed.
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
OUT="${1:?usage: local-nfs-check.sh <out-dir> [fast]}"
mkdir -p "$OUT"
if [ "${2:-}" = fast ]; then
    TIMING="E5_WAIT_S=2 E5_WARMUP_S=6 E5_MEASURE_S=10 E5_GUARD_S=1 E5_COMPILE_ALLOWANCE_S=10 E5_MIN_AGE_S=0"
else
    TIMING="E5_WARMUP_S=150 E5_MEASURE_S=240 E5_COMPILE_ALLOWANCE_S=20 E5_MIN_AGE_S=0"
fi
docker build -q -t e5-bench-local "$REPO/infra/lib/stacks/bench" >/dev/null
docker run --rm --privileged \
    -v "$REPO/infra/lib/stacks/e5-host:/host:ro" -v "$OUT:/export-out" \
    --entrypoint bash e5-bench-local -c "
set -euo pipefail
mount -t nfsd nfsd /proc/fs/nfsd
mkdir -p /export && mount -t tmpfs -o size=512m tmpfs /export
echo '/export *(rw,no_root_squash,no_subtree_check,fsid=0)' > /etc/exports
rpcbind; exportfs -ra; rpc.nfsd 8 2>/dev/null || true; rpc.mountd
OPTS=nfsvers=4.1,rsize=1048576,wsize=1048576,hard,timeo=600,retrans=2
T=efs_host_plain
mkdir -p /seed /bench/host-facts /e5-ctl
mount -t nfs -o \$OPTS 127.0.0.1:/ /seed
for c in default forced ss-0.1 ss-1 ss-10; do python3 /host/seed.py \$([ \$c = default ] && echo --conf) /seed/\$c; done > /bench/host-facts/seed-manifest
for c in default ss-0.1 ss-1 ss-10; do python3 /host/seed.py \$([ \$c = default ] && echo --conf) /e5/ebs/\$c; done >> /bench/host-facts/seed-manifest
umount /seed
sync; echo 3 > /proc/sys/vm/drop_caches
date +%s > /bench/host-facts/seed-epoch
stat -c %d / > /bench/host-facts/root-dev
for c in default forced ss-0.1 ss-1 ss-10; do
    mkdir -p /e5/\$T/\$c
    o=\$OPTS,nosharecache; [ \$c = forced ] && o=\$o,acregmin=0,acregmax=0
    mount -t nfs -o \$o 127.0.0.1:/\$c /e5/\$T/\$c
done
env E5_TIERS=\"ebs \$T\" $TIMING BENCH_MODE=e5 /usr/local/bin/entrypoint.sh
cp -r /tmp/out/. /export-out/
# Unmount BEFORE the server goes away. Read delegations are held on these files;
# if the container exits with the mounts still up, the client's DELEGRETURN waits on
# a server whose network namespace no longer exists, and the container cannot be
# killed (seen on the first run of this script: rpc.mountd stuck in D state).
for c in default forced ss-0.1 ss-1 ss-10; do umount /e5/\$T/\$c; done
exportfs -ua; rpc.nfsd 0
"
echo "local check output: $OUT"
