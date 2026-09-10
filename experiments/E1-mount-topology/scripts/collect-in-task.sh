#!/usr/bin/env bash
# Runs INSIDE a task container. Used for the Fargate arm, where the underlying
# host is not reachable by any means - no SSM, no SSH, no host filesystem. What a
# task can see about its own mounts is the only evidence available there, which is
# itself part of the finding.
#
# Also run inside EC2-launch-type tasks so the two platforms are compared on
# identical evidence rather than on whatever each one happens to expose.
set -euo pipefail

# The task's own view of its EFS mount. On EC2 this is a bind mount of a host
# mount; on Fargate the task is the only consumer that exists.
mnt="$(grep -c ' nfs4 ' /proc/self/mountinfo 2>/dev/null || echo 0)"

# Mount peer group + propagation for the EFS mount point. If a host mount were
# shared into several tasks, the peer group would show it.
peer="$(grep ' nfs4 ' /proc/self/mountinfo 2>/dev/null | head -1 | grep -o 'shared:[0-9]*' || echo 'none')"

# The server side of the mount as this task sees it. A per-task stunnel shows as
# 127.0.0.1 with a task-unique port.
src="$(grep ' nfs4 ' /proc/self/mountinfo 2>/dev/null | head -1 | awk '{print $(NF-2)}' || echo none)"

cat <<JSON
{
  "task_visible_nfs4_mounts": ${mnt:-0},
  "mount_peer_group": "${peer}",
  "mount_source": "${src}",
  "kernel": "$(uname -r)"
}
JSON
