# E1 — EFS mount topology on ECS

**Bears on:** [H1](../../hypotheses/H1-cache-locality.md) — decides whether its
mechanism physically exists.

**Cost:** ~$0.30/hr while up (2 × t4g.small + EFS). Torn down in the same command
that runs it. Nothing persists.

## Question

When two ECS tasks land on the same EC2 instance and both mount the same EFS
filesystem, does the ECS agent mount it **once per host** and bind-mount into each
task, or **once per task**?

## Why this gates everything

H1 claims co-located tasks share an NFS attribute cache and page cache, so task 2's
`stat()` is served from what task 1 warmed. That is only true if they share one NFS
client.

If ECS mounts per task, they do not share, the predicted effect largely disappears,
and E2 would measure noise. Establishing this costs an hour and a few cents;
discovering it after building E2 costs a great deal more.

## Prediction

Pre-registered: **one mount per host, bind-mounted into each task.** Reasoning is
that the ECS agent manages EFS volumes at the instance level and containers receive
bind mounts, which is what makes the shared-cache mechanism available.

Stated plainly so it can be wrong.

## Method

Two tasks, same task definition, same EFS filesystem, forced onto **one** instance
via a placement constraint. Then from the instance (via SSM Session Manager, no SSH,
no inbound ports):

1. `mount | grep nfs` on the host — how many NFS mounts exist for the filesystem
2. `findmnt -o TARGET,SOURCE,FSTYPE` — whether task mount points are bind mounts of
   a single host mount
3. `cat /proc/<pid>/mountinfo` for each task's PHP process — the mount peer group
   and shared/private propagation of each
4. `nfsstat -c` before and after issuing identical `stat()` storms from each task —
   whether the second task's ops reach the server at all

Step 4 is the one that actually answers the question. Steps 1–3 explain the
mechanism behind whatever step 4 shows.

## Output

`results/E1/<run-id>/` with the raw command output, `mountinfo` dumps, `nfsstat`
deltas, and `meta.json` carrying instance type, AMI, kernel, ECS agent version,
region and AZ.

## Teardown

`make e1` deploys, runs, collects, and destroys in one command. The stack is tagged
`Experiment=E1` and declares its hourly rate, per `CLAUDE.md`.

## Status

`SPECCED` — apparatus not yet written. Blocked on AWS account access.
