# E1 — EFS mount topology on ECS

**Bears on:** [H1](../../hypotheses/H1-cache-locality.md) — decides whether its
mechanism physically exists.

**Cost:** ~$0.48/hr while up for the current five-arm apparatus — four EC2 instances
(`t4g.small`, `m7g.large`, `c7g.large`, `r7g.large`), two Fargate tasks, ten VPC
endpoints (nine interface + the free S3 gateway), EFS at near-zero usage. The first
round cost ~$0.14/hr on one instance. Torn down in the same command that runs it.
Nothing persists.

Most of that is the endpoints. Running the instances in a public subnet with public
IPs would cost less, and was the original design here. It was the wrong trade: a
workload that needs no inbound access and no internet route belongs in a private
isolated subnet, and paying to keep it there is not a real cost question.

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

`COMPLETE` — prediction refuted. See
[docs/findings/E1-mount-per-task.md](../../docs/findings/E1-mount-per-task.md).

ECS mounts EFS once **per task**, not once per host: two separate NFS4 client
mounts, two separate `efs-proxy` TLS processes, confirmed directly on the host via
SSM. Not the "one mount, bind-mounted into each task" this experiment predicted.

Result: `results/E1/20260902T060000Z-24d9bb9/`

Five real deploy bugs were found and fixed en route (CFN not waiting for the ASG,
a user-data ordering bug, a missing CloudFormation VPC endpoint, a missing package
on the AMI, and an EFS file-system policy that omitted `ClientMount`) — each
confirmed by direct evidence before being fixed, not guessed. See the git history
for `infra/lib/stacks/e1-mount-topology.ts`.

Stack torn down after data collection; nothing left running.

## Round two: does the finding generalise?

The result above was measured on one instance type. "ECS mounts EFS per task" is
being asserted as a property of ECS, but a single `t4g.small` cannot distinguish
that from a property of *that instance* — its kernel, its NIC, its size class, its
ECS agent build.

Under the numbering rule (`CLAUDE.md`), the apparatus was **replaced in place**
rather than forked into an E1b: `infra/lib/stacks/e1-mount-topology.ts` now stands
up five arms against **one** VPC and **one** EFS filesystem, so no arm's result can
be attributed to a different filesystem or a different network path:

| Arm | Why it is in the matrix |
|---|---|
| `t4g.small` | the original arm — makes round two comparable to round one |
| `m7g.large` | general purpose, the default anyone would actually pick |
| `c7g.large` | compute optimised — same Graviton generation, different size/NIC class |
| `r7g.large` | memory optimised — most page cache available to hold attributes |
| Fargate | no host to inspect at all; the arm where the question changes shape |

The Fargate arm is not a fifth data point, it is a different question. There is no
instance to run `mount` or `nfsstat -c` on, so the topology has to be inferred from
inside the task. That difference is the point: if the only way to observe your own
storage topology is to not use Fargate, that is a finding about the platform.

**Prediction, pre-registered:** per-task mounts on all four EC2 arms, with no
family-dependent variation, because the mechanism found in round one is an ECS agent
behaviour rather than a kernel or instance one.

**Kill condition:** any arm showing one host mount bind-mounted into both tasks. That
would mean round one measured an instance property and the finding does not
generalise.

**Status:** apparatus written and typechecking; `cdk list` resolves it as
`E1-MountTopology-dev`. **Not deployed.** Three replications per
[the protocol](../../docs/benchmark-protocol.md), so this is a spending decision, not
a one-command run.

> **Option flagged, not taken.** Running the three large arms as `m7gd`/`c7gd`/`r7gd`
> instead of `m7g`/`c7g`/`r7g` would attach 118 GB of NVMe instance store to each,
> at a modest price premium, and leave E2's instance-store arm already provisioned.
> Not done: E1 asks one question about mount topology, and widening its apparatus
> to serve a different experiment is how apparatus stops being attributable. If E1
> round two and E2 end up deploying together, revisit it then.
