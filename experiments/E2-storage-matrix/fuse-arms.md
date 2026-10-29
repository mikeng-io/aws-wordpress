# E2 FUSE arms — build and collection plan (2026-10-29)

**Status:** `COMPLETE` — three replications collected and graded. **P2
INCONCLUSIVE**, **P4 SUPPORTED**. Result:
[`results/E2/20261029T070456Z-a2041d6/`](../../results/E2/20261029T070456Z-a2041d6/);
finding: [docs/findings/E2-fuse.md](../../docs/findings/E2-fuse.md). Ceiling
**US$12**, approved 2026-10-29; actual standing cost about **US$0.30**.

This was the missing half of E2. The block-backed group, EFS and the three FSx arms
were already complete; the three FUSE tiers are now mounted and graded.

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

- EC2 `c7g.large` (arm64), one fresh deployment per campaign, as E2's
  `collect.sh` already does; the three replications are three sequential task runs
  inside that deployment. The stack is destroyed once, after the third.
- FUSE clients run on the **EC2 host**, where the container has `CAP_SYS_ADMIN`.
  The unprivileged bench container bind-mounts the resulting host directories, so
  the per-syscall path and seccomp profile stay identical to the other tiers. The
  earlier idea of a privileged FUSE task was rejected: it would have changed the
  thing being measured.
- One image with the three clients pinned by version and the existing `bench`
  binary. The host script mounts all three arms and fail-closes if any mount or
  `st_dev` check fails; the task entrypoint then runs conformance, latency and the
  throughput probe against the bind-mounted paths.
- JuiceFS metadata runs in a local Redis in the same task, so the comparison is
  "metadata engine on the same host" not "ElastiCache network hop". That is the
  strongest case for JuiceFS and is recorded as such; a network Redis would be a
  separate arm, not this one.
- S3 buckets are stack-owned and destroyed with the stack. No FSx in this
  campaign: `includeFsx=false`, so a FUSE-only deployment is ~$0.25/hr rather than
  ~$0.96/hr and has no final-backup teardown risk.
- Teardown uses E2's existing `collect.sh` trap and scoped sweep; the FUSE task has
  no FSx backups. A stack still standing is the failure case, as today.

## Grading rules, fixed before the first mount

P2 (JuiceFS vs EFS) uses the pooled `stat` p50 over the three replications, the same
estimator E3/E5 use. **SUPPORTED** requires both halves of the prediction: JuiceFS is
at least **10x faster than EFS** (ratio <= 0.10) *and* still at least **3x slower than
instance store** (ratio >= 3.0, the study's separation threshold). **REFUTED** if it is
not faster than EFS at all (ratio >= 1.0). Between 0.10 and 1.0, or a local tier that
does not separate, is **INCONCLUSIVE** — the direction held but "wide margin" did not.
SeaweedFS is reported without a verdict; it is a second design point, not a second
chance at the same prediction.

P4 (Mountpoint for S3) is graded on the conformance CSV, not latency: **SUPPORTED**
if any of the eleven checks is `FAIL`; **REFUTED** if all eleven `PASS`; **ERROR** if
the suite could not run and produced no verdict. This is the pre-registered reading:
the prediction is that an object-store-backed FUSE mount cannot hold POSIX rename /
in-place-write semantics, and one failure is enough.

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
4. **Replications 2 and 3.** Only if step 3 is clean; sequential task runs in the
   same deployment, matching E2's existing replication shape.
5. **Grade and publish.** Extend `analysis/e2_stats.py` for P2/P4 and the FUSE rows
   in P1's ranking; write `docs/findings/E2-fuse.md`; update H1/H2 and the E2
   status. Then decide E4.

## Outcome (2026-10-29)

The formal run was three independent deployments, 4,020 timed operations per tier
per replication, identical image digest `sha256:6f6202…`, `ap-southeast-1a`,
`c7gd.large`. P2 came out at **0.133× EFS** pooled (per rep 0.125, 0.130, 0.129)
and **76.5× local**: direction held, the 10× half did not, so the registered rule
returns **INCONCLUSIVE**. P4 returned **SUPPORTED**: the same eight checks failed in
all three replications, with zero `ERROR`.

The P2 number has a construct caveat that the finding spells out: EFS's `stat` p50
is a cache-mode mixture (31.8% of calls hit the client attribute cache at ~1.8 µs;
the rest miss at ~839 µs), while JuiceFS has one mode at ~100 µs. The p50 comparison
therefore landed in the miss mode by accident of the benchmark, not because JuiceFS
beat EFS's fast path. Do not read the 7.5× as mechanism support.

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

## Apparatus notes from the smoke

The final smoke (`results/E2/20261029T064046Z-0bcacd1`, one rep, not the formal
sample) mounted JuiceFS, SeaweedFS and Mountpoint on the host, bound all three into
the unprivileged task, and uploaded both arms. It also exposed three apparatus
facts now pinned in code:

- AL2023 already supplies `curl-minimal`; adding `curl` during host setup fails the
  whole boot with a package conflict.
- Mountpoint requires `--prefix` to end in `/`; `mountpoint` alone never mounts.
- Mountpoint's `unlink` path aborts `bench`'s create/unlink loop. P4 is therefore
  conformance-only: it writes a `skipped,0` latency marker and is excluded from the
  throughput set, rather than turning a semantic failure into a task failure.
- CDK's ECR `docker login` cannot write the macOS keychain here; the FUSE target
  seeds a file-based `DOCKER_CONFIG` and uses a `CDK_DOCKER` wrapper that skips the
  login, because `docker push` reads the same token from the file.

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
