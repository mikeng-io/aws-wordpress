# E2 FUSE arms — build and collection plan (2026-10-29)

**Status:** `PLANNED` — no apparatus exists yet; no AWS spend authorised by this
document alone.

This is the missing half of E2. The block-backed group, EFS and the three FSx arms
are complete; the three FUSE tiers in the matrix have never been mounted, so P2
(JuiceFS metadata) and P4 (Mountpoint correctness) are still ungraded.

## What must be measured

| Arm | What it is | Why | Pre-registered outcome |
|---|---|---|---|
| `juicefs` | JuiceFS FUSE mount; Redis metadata engine, S3 data | P2: metadata lookup is a DB query, not an NFS round trip | beats EFS on `stat`, still loses to block-backed |
| `seaweedfs` | SeaweedFS filer + volume servers, FUSE mount | P2 generality: a second FUSE design, not one vendor | same direction as JuiceFS, no claim of equality |
| `mountpoint_s3` | Mountpoint for S3, FUSE over S3 | P4: POSIX completeness, not latency | fails conformance before latency is graded |

For each arm, collect the same artefacts as the existing tiers: `stat`, `create`,
`unlink`, `open_read`, `readdir`, `ENOENT stat`; the ten-check conformance CSV; the
throughput probe; `mount-facts.csv` (kernel, MTU, negotiated mount options, `st_dev`);
and the image digest / instance identity in `meta.json`.

## Apparatus shape

- EC2 `c7g.large` (arm64), one fresh deployment per replication, as E2 does today.
- A privileged ECS container with `/dev/fuse` and `CAP_SYS_ADMIN`; the existing
  bench container deliberately is **not** privileged, so FUSE gets its own task
  definition rather than weakening the latency measurement's seccomp profile.
- One image with the three clients pinned by version and the existing `bench`
  binary. The entrypoint mounts exactly one arm, seeds the same tree, runs
  conformance first, then latency, then the throughput probe, and uploads.
- JuiceFS metadata runs in a local Redis in the same task, so the comparison is
  "metadata engine on the same host" not "ElastiCache network hop". That is the
  strongest case for JuiceFS and is recorded as such; a network Redis would be a
  separate arm, not this one.
- S3 buckets are stack-owned and destroyed with the stack. No FSx in this
  campaign: `includeFsx=false`, so a FUSE-only deployment is ~$0.25/hr rather than
  ~$0.96/hr and has no final-backup teardown risk.
- Teardown uses E2's existing `collect.sh` trap and scoped sweep; the FUSE task has
  no FSx backups. A stack still standing is the failure case, as today.

## Run plan

1. **Offline build.** Add `includeFuse` to the stack, the FUSE image/entrypoint,
   the collect path and the E2 analysis tiers. Local: image build, `cdk synth`,
   unit fixtures. No AWS.
2. **Smoke, one arm.** JuiceFS only, one deployment, stop after the task. Check
   mount, conformance, one latency CSV, teardown. This is apparatus validation, not
   a replication.
3. **Replication 1, all three arms.** Stop and review before 2 and 3. Check
   `mount-facts.csv` (FUSE `st_dev`, mount options), conformance verdicts and
   throughput residency.
4. **Replications 2 and 3.** Only if step 3 is clean. Three independent deployments.
5. **Grade and publish.** Extend `analysis/e2_stats.py` for P2/P4 and the FUSE rows
   in P1's ranking; write `docs/findings/E2-fuse.md`; update H1/H2 and the E2
   status. Then decide E4.

## E4 gate

E4 is deliberately **not** in this plan's first phase. Its README says: do not
build before the matrix exists, because JuiceFS or SeaweedFS may already deliver
the cache tier E4 would build. After E2-FUSE:

- If a FUSE tier already provides a correct read cache with acceptable hydration,
  E4's answer is "use it", with the measured numbers, and no bespoke adapter is
  built.
- If not, E4 builds the read-only cache first (zero write-back correctness cost),
  then the write-through / single-writer / multi-writer variants only if H6 is
  still open. That is a separate apparatus and a separate approval.

## Cost and stop conditions

- FUSE-only standing cost: `c7g.large` $0.1058/hr + interface endpoints ~$0.156/hr
  + S3/EFS at benchmark volume ≈ **$0.27/hr**. A 30-minute replication is ~$0.14.
- Three arms × three replications, plus smoke and iteration: planning envelope
  **US$10** for E2-FUSE. Hard stop at **US$12**, including failed attempts.
- No FSx, no NAT gateway, no ElastiCache. No idle stack: teardown after every
  replication, `cleanup_verified` required.
- E4 is not costed here; it gets its own ceiling if the gate says build.

## Approval

This plan needs an explicit new ceiling because E5's US$30 is closed and fully
allocated. Proposed: **US$12 for E2-FUSE**, with a stop after the smoke and again
after replication 1. No deployment starts until that ceiling is recorded.
