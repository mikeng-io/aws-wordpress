# E1 — ECS mounts EFS once per task, not once per host

**Result:** `results/E1/20260902T060000Z-24d9bb9/`
**Status:** decisive. Direct process- and mount-table-level evidence, not inference.

## What was predicted

E1's README pre-registered: "one mount per host, bind-mounted into each task,"
reasoning that the ECS agent manages EFS volumes at the instance level.

**That prediction is refuted.**

## What was observed

Two ECS tasks, same task definition, same EFS filesystem, forced onto the same
`t4g.small` container instance (desiredCount=2 against a 1-instance cluster).

On the host:

```
127.0.0.1:/ on .../ecs-...-efs-cab885c6...  type nfs4  (port=20464, ...)
127.0.0.1:/ on .../ecs-...-efs-b4baaca0...  type nfs4  (port=20572, ...)
```

Two independent NFS4 client mounts, each on its own local port. Behind them:

```
root  2710  /sbin/efs-proxy  stunnel-config....efs-cab885c6....20464  --tls
root  3131  /sbin/efs-proxy  stunnel-config....efs-b4baaca0....20572  --tls
```

**Two separate `efs-proxy` processes** — the TLS-terminating proxy ECS installs for
`transitEncryption: ENABLED` — one per task, each with its own config file, its own
local port, and its own TLS session to the EFS server.

This is unambiguous. Not two containers sharing one mount via bind mount; two fully
independent kernel NFS4 client sessions, each a distinct mount point (distinct
superblock), each with its own attribute cache, its own page cache, and its own TCP
connection — despite both tasks running on the identical host and mounting the
identical filesystem.

## What this means for H1

[H1](../../hypotheses/H1-cache-locality.md) proposed a specific mechanism: co-located
tasks share one NFS client, so task 2's `stat()` calls are served from a cache task 1
already warmed. **That mechanism does not exist** for the configuration tested here
(`transitEncryption: ENABLED`, no IAM auth, no access point, `awsvpc` network mode —
which is the standard, default configuration for ECS + EFS on EC2).

Separate mount points are separate Linux VFS superblocks. The kernel does not share
page cache or attribute cache across them, even for identical remote file content.
So the specific cache-sharing story E1 was built to validate is dead on arrival.

**This does not resolve H1 itself.** Co-located tasks might still show a locality
effect through other means the mount-per-task finding doesn't rule out — shared host
network path to the same-AZ mount target (both proxies still terminate through the
same physical NIC and the same short RTT to the mount target), shared CPU/memory
contention effects, or the EFS server side itself serving cached data faster to a
"nearby" client for unrelated reasons. E2's placement differential is still the
direct test of whether locality matters — but it is no longer testing the mechanism
E1 assumed. It would be testing a different, weaker, unnamed mechanism, and E2's
design should be revisited before it runs rather than carried forward unchanged.

## Provenance

ECS agent 1.106.1, Amazon Linux 2023 (kernel 6.1.180), `t4g.small`, ap-southeast-1a.
Full details in `meta.json`.
