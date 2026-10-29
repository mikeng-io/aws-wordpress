#!/usr/bin/env bash
# E2 FUSE arms, mounted on the EC2 host so the bench container stays unprivileged.
#
# Why the host: FUSE needs CAP_SYS_ADMIN. Making the bench container privileged
# would also remove its seccomp filter, changing the per-syscall cost this study
# measures. Mounting here and bind-mounting /mnt/<arm>/bench into the container
# keeps the measured path identical to EFS/FSx/block.
#
# Versions are pinned. The image is not used for these clients; they are downloaded
# at boot because the FUSE campaign is the only mode with a NAT gateway.
set -euxo pipefail

: "${FUSE_BUCKET:?FUSE_BUCKET must name the data bucket}"
: "${AWS_REGION:?AWS_REGION must be set}"

TOOLS=/opt/e2-fuse
mkdir -p "$TOOLS" /mnt/juicefs /mnt/seaweedfs /mnt/mountpoint \
  /mnt/juicefs-cache /mnt/seaweed-data /mnt/seaweed-cache

dnf install -y fuse3 redis6 curl tar gzip

# --- clients ---------------------------------------------------------------
curl -fsSL https://github.com/juicedata/juicefs/releases/download/v1.4.2/juicefs-1.4.2-linux-arm64.tar.gz \
  -o /tmp/juicefs.tgz
tar -xzf /tmp/juicefs.tgz -C "$TOOLS"
install -m 0755 "$TOOLS/juicefs" /usr/local/bin/juicefs

curl -fsSL https://github.com/seaweedfs/seaweedfs/releases/download/4.51/linux_arm64.tar.gz \
  -o /tmp/seaweedfs.tgz
tar -xzf /tmp/seaweedfs.tgz -C "$TOOLS"
install -m 0755 "$TOOLS/weed" /usr/local/bin/weed

# Mountpoint publishes a tarball as well as the RPM; the tarball needs no rpm
# tooling on the host.
curl -fsSL https://s3.amazonaws.com/mountpoint-s3-release/latest/arm64/mount-s3.tar.gz \
  -o /tmp/mount-s3.tgz
tar -xzf /tmp/mount-s3.tgz -C "$TOOLS"
install -m 0755 "$TOOLS/bin/mount-s3" /usr/local/bin/mount-s3

# --- JuiceFS: Redis metadata, S3 data --------------------------------------
redis6-server --daemonize yes --save '' --appendonly no --bind 127.0.0.1
for i in $(seq 1 30); do redis6-cli ping >/dev/null 2>&1 && break || sleep 1; done

juicefs format \
  --storage s3 \
  --bucket "https://s3.${AWS_REGION}.amazonaws.com/${FUSE_BUCKET}" \
  --trash-days 0 \
  redis://127.0.0.1:6379/1 bench
juicefs mount -d --cache-dir /mnt/juicefs-cache --cache-size 4096 \
  redis://127.0.0.1:6379/1 /mnt/juicefs
for i in $(seq 1 60); do mountpoint -q /mnt/juicefs && break || sleep 1; done

# --- SeaweedFS: its own master/volume/filer, no external object store ------
nohup weed server -dir=/mnt/seaweed-data -filer -s3 \
  -ip=127.0.0.1 -master.port=9333 -volume.port=8080 \
  -filer.port=8888 -s3.port=8333 \
  >/var/log/seaweed-server.log 2>&1 &
for i in $(seq 1 60); do
  curl -fsS http://127.0.0.1:8888/ >/dev/null 2>&1 && break || sleep 1
done
nohup weed mount -filer=127.0.0.1:8888 -dir=/mnt/seaweedfs \
  -cacheDir=/mnt/seaweed-cache >/var/log/seaweed-mount.log 2>&1 &
for i in $(seq 1 60); do mountpoint -q /mnt/seaweedfs && break || sleep 1; done

# --- Mountpoint for S3 -----------------------------------------------------
nohup mount-s3 "$FUSE_BUCKET" /mnt/mountpoint --prefix mountpoint \
  --allow-other >/var/log/mountpoint.log 2>&1 &
for i in $(seq 1 60); do mountpoint -q /mnt/mountpoint && break || sleep 1; done

# --- fail closed -----------------------------------------------------------
for d in /mnt/juicefs /mnt/seaweedfs /mnt/mountpoint; do
  mountpoint -q "$d" || { echo "FATAL: $d is not a mount" >&2; exit 1; }
  test "$(stat -c %d "$d")" != "$(stat -c %d /)" \
    || { echo "FATAL: $d is on the root device" >&2; exit 1; }
done
[ "$(stat -c %d /mnt/juicefs)" != "$(stat -c %d /mnt/seaweedfs)" ] \
  || { echo "FATAL: JuiceFS and SeaweedFS share st_dev" >&2; exit 1; }
[ "$(stat -c %d /mnt/juicefs)" != "$(stat -c %d /mnt/mountpoint)" ] \
  || { echo "FATAL: JuiceFS and Mountpoint share st_dev" >&2; exit 1; }

mkdir -p /mnt/juicefs/bench /mnt/seaweedfs/bench /mnt/mountpoint/bench
chmod 777 /mnt/juicefs/bench /mnt/seaweedfs/bench /mnt/mountpoint/bench

findmnt -t fuse -o TARGET,SOURCE,FSTYPE,OPTIONS || true
