#!/usr/bin/env bash
# Runs ON the container instance via SSM. Emits one JSON object describing the
# EFS mount topology as the kernel and process table actually see it.
#
# v1 of E1 read this off human-eyeballed SSM output. That is fine for discovering
# a result and not fine for replicating one: it cannot be diffed across runs and
# it invites reading what you expect. This emits structured data instead.
set -euo pipefail

FS_ID="${1:?usage: collect.sh <efs-fs-id>}"

# NFS4 mounts the ECS agent created for EFS volumes. Each is a distinct kernel
# mount with its own superblock - separate mounts do not share page or attribute
# cache, which is the entire question E1 asks.
mounts="$(mount -t nfs4 2>/dev/null | grep -c '/var/lib/ecs/volumes' || true)"

# Local stunnel/TLS terminators, one per EFS volume mount when transit encryption
# is on. Counting these independently of the mount table guards against a mount
# being reused behind the scenes.
proxies="$(pgrep -fc "efs-proxy.*${FS_ID}" 2>/dev/null || echo 0)"

# Distinct local ports each proxy listens on. If two tasks shared one client,
# these would collapse to a single port.
ports="$(mount -t nfs4 2>/dev/null | grep -o 'port=[0-9]*' | sort -u | wc -l | tr -d ' ')"

# Distinct mount target IPs actually connected to.
targets="$(mount -t nfs4 2>/dev/null | grep -o 'addr=[0-9.]*' | sort -u | wc -l | tr -d ' ')"

running_tasks="$(curl -s --max-time 5 http://localhost:51678/v1/tasks 2>/dev/null \
  | grep -o '"KnownStatus":"RUNNING"' | wc -l | tr -d ' ' || echo -1)"

cat <<JSON
{
  "nfs4_mounts_for_ecs_volumes": ${mounts:-0},
  "efs_proxy_processes": ${proxies:-0},
  "distinct_local_ports": ${ports:-0},
  "distinct_mount_target_ips": ${targets:-0},
  "running_tasks_per_agent": ${running_tasks:-0},
  "kernel": "$(uname -r)",
  "instance_id": "$(curl -s --max-time 5 -H "X-aws-ec2-metadata-token: $(curl -s --max-time 5 -X PUT http://169.254.169.254/latest/api/token -H 'X-aws-ec2-metadata-token-ttl-seconds: 60')" http://169.254.169.254/latest/meta-data/instance-id 2>/dev/null || echo unknown)"
}
JSON
