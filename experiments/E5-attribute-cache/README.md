# E5 — what an NFS `stat` costs once the file is old

**Status:** `BUILT, NOT DEPLOYED` (this branch). Specified 2026-10-15; apparatus built and checked
locally on 2026-10-16, full-timing local check run the same day (see [Build record](#build-record-2026-10-16)). No AWS resource has
been created. A deploy needs an explicit go-ahead, recorded here.

**Bears on:** [H1](../../hypotheses/H1-cache-locality.md), specifically its per-op
cost factor. See the 2026-10-15 evidence note there. Also
[H4](../../hypotheses/H4-cold-start-is-the-metric.md), through the cold-client
cohort.

**Motivated by:** [docs/findings/E2-server-backed.md](../../docs/findings/E2-server-backed.md),
`results/E2/20261015T000959Z-85382cc/`.

## Why this experiment exists

Every NFS `stat` latency this study has published comes from `bench.c`. That
includes E3's 0.84 ms and both E2 runs. `bench.c` `stat`s each file a few seconds
after it creates it. E2's FSx group showed that the fast/slow split on NFS tiers is
the file's age measured against the client's ~3 s attribute-cache window, and not
anything the server does. ONTAP's 1.7 µs is a cache hit: 8 `GETATTR` RPCs for 1,000
`stat`s. Its real lookup cost has never been observed.

The finding states the consequence as `HYPOTHESIS`. Production PHP files are old.
On a busy web tier, the attribute cache may answer almost every `stat`, whatever
the storage. If so, the tier matters only through miss cost × miss rate. H1's
product, a fixed op count times a per-tier cost, would then be using the wrong
cost.

Two things are missing, and this experiment measures both:

- **(a)** the true per-`stat` miss cost on EFS, FSx OpenZFS, FSx ONTAP and FSx
  Lustre;
- **(b)** the steady-state hit rate when the same files are `stat`ed at intervals
  that look like a web tier's.

It also fixes `open_read`. About 6,000 NFS `open_read` calls in E2 produced 7 READ
RPCs, because each file was read straight after it was written.

## Question

On files that the client did not just create, what does a `stat` cost on each
server-backed tier:

1. on a miss, split into a cold client (first touch) and a revalidation (attributes
   expired);
2. on average, at steady state, when each file is `stat`ed every 0.1 s, 1 s or
   10 s?

## The mechanism this design rests on

The design depends on how the Linux NFS client decides that cached attributes have
expired. This was read from the source rather than assumed: `fs/nfs/inode.c` at
v6.1, which is the line E2's hosts ran (`6.1.188-233.386.amzn2023.aarch64`, from
`mount-facts.csv`).

- **A new inode starts at `acregmin`** (`nfsi->attrtimeo = NFS_MINATTRTIMEO`, in
  `nfs_fhget`). E2's boundary of 2.3–2.9 s is this.
- **A revalidation that finds the file unchanged doubles the timeout,** capped at
  `acregmax` (`nfsi->attrtimeo <<= 1`, in `nfs_update_inode`).
- **A change resets it to `acregmin`.**
- **A held delegation means the cache never expires** (`nfs_attribute_cache_expired`
  returns 0 when `nfs_have_delegated_attributes`).
- E2's mounts set none of these options, so the defaults applied:
  `acregmin=3`, `acregmax=60`, `acdirmin=30`, `acdirmax=60` (nfs(5)).

**This changes the brief.** "Files older than `acregmax`" is not what sets the cache
lifetime on Linux. The timeout follows the inode's revalidation history on this
client, not the file's `mtime`. A file written a year ago, looked up for the first
time, starts at 3 s like a new one. It reaches 60 s only after about five unchanged
revalidations (3 → 6 → 12 → 24 → 48 → 60, roughly 93 s of continuous use).
Production therefore has two different miss events, and this experiment measures
them separately:

| Miss event | When production pays it | NFSv4.1 RPCs | Cohort |
|---|---|---|---|
| **First touch** on a cold client | task start, scale-out, after a deploy | `LOOKUP` compound (includes attributes) | A1 |
| **Revalidation** of a cached inode whose timer expired | steady state, about once per `acregmax` per file | `GETATTR` | A3 |

The backoff conditions in `nfs_update_inode` are more involved than the summary above
(there is a `cache_revalidated` guard). So the claim "steady state saturates at
`acregmax`" is **not assumed**. Cohort B measures it, and prediction 5 can refute
it.

## Which cache-defeating options are faithful, and which are used

| Option | What it does | Faithful to production? | Used? |
|---|---|---|---|
| Files aged past `acregmax`, default mount | Server-side state is old, but the client timer still starts at 3 s | It is the production mount, so yes. Age alone does not produce a miss (see above). | **Yes**, for every A and B cohort. Files are seeded ≥120 s before measurement, from a different mount. |
| `noac` | Turns off attribute caching **and** makes writes synchronous | No. It is a different client. | **No** |
| `actimeo=0` | Sets all four timers to 0, so every path component's directory is revalidated too | No. A `stat` becomes several RPCs, so it is not a per-`stat` miss cost. | **No** |
| `acregmin=0,acregmax=0` | Every file `stat` is a `GETATTR`; directory caching stays at its defaults | No as a configuration. AWS warns that lowering attribute caching degrades EFS performance ([knowledge center](https://repost.aws/knowledge-center/efs-troubleshoot-slow-performance)). | **Only as an instrument** (A8): many forced misses, cheaply. It is used only if it agrees with A3 (prediction 4). |

The production configuration is the E2 mount, unchanged:
`nfsvers=4.1,rsize=1048576,wsize=1048576,hard,timeo=600,retrans=2`, plus
`noresvport` on EFS. Every graded number comes from it.

## Tiers

Run on EC2 `c7gd.large`, the same instance as E2, so that prediction 1 compares
client against identical client.

| Tier | Why it is in |
|---|---|
| `ebs` (host root, a plain directory) | The block-backed ruler for prediction 9. E2 showed the three block tiers tie, so one is enough. |
| `efs_host_plain` | Same client path as the FSx tiers. Carries E2's 827 µs. |
| `efs_host_tls` | Production ECS+EFS mounts with TLS through the EFS mount helper. E2 found TLS did not move `stat`, but on the cache-confounded measurement. A miss is a round trip through the local proxy, so it is re-measured here. |
| `fsx_openzfs` | Grants read delegations (E2: `DELEGRETURN` 1,000). This is the one tier where the cache can stop expiring. |
| `fsx_ontap` | Miss cost never observed. No delegations seen in E2. |
| `fsx_lustre` | Not NFS. Attributes are cached under DLM locks with no timer. E2 `stat`ed each file once, so it never measured a repeat `stat`. |

**Fargate is out of scope.** It runs the same NFS client code, and its EFS mount
options are managed rather than chosen. Excluding it removes ~$0.05/hr and an arm
that cannot answer a different question. It is listed as a threat to validity.

FSx configurations are E2's, unchanged: OpenZFS 64 GiB / 128 MBps, Lustre Scratch 2
on 2.15, ONTAP gen-1 Single-AZ 1024 GiB / 128 MBps, no snapshots, no automatic
backups, `CopyTagsToBackups`. Everything listed in E2's "Configuration cross-checked
against official AWS guidance" carries over.

## Method

### Mounts: one superblock per cohort, so the RPC counters are attributable

Each NFS tier gets five host mounts, each pointing at its own subtree of the export,
and each with `nosharecache`. Without `nosharecache`, Linux shares one superblock,
and so one attribute cache and one set of `mountstats` counters, between mounts of
the same export. A second mount with different options can also silently inherit
the first one's.

| Mount | Options | Subtree | Used by |
|---|---|---|---|
| `seed` | production | all | boot-time seeding only, then **unmounted** |
| `default` | production | `e5/a` | cohorts A1–A7 |
| `forced` | production + `acregmin=0,acregmax=0` | `e5/forced` | cohort A8 |
| `ss-0.1`, `ss-1`, `ss-10` | production | `e5/ss-<Δ>` | cohort B |

Seeding goes through `seed`, which is then unmounted. Every measurement mount
therefore meets the files as a client that has never seen them: no new-inode timer,
no dirty pages, and no delegation left over from writing them. No `drop_caches` is
needed for the NFS tiers. The negotiated options are recorded per mount in
`mount-facts.csv`, as in E2. A mount whose `nosharecache` or `ac*` values did not
take fails the run.

**Lustre** has one client per filesystem, so it gets one mount with the same
subtrees. After seeding, the host runs `lctl set_param ldlm.namespaces.*.lru_size=clear`,
which cancels the DLM locks and the pages they cover. **EBS** gets
`drop_caches=3` after seeding. Both happen in host user data before the ECS task
starts, so the benchmark container stays unprivileged, as in E2.

### The tree

The tree is the same shape as `bench.c`: 20 `plugin-NNN/includes/` directories × 50
files of 2–50 KB, sized by `bench.c`'s `file_size()` formula, one tree per subtree.
To it are added **1,000 names that do not exist** (`missing-NNN.php`, 50 per
directory). E0 found ~1,600 of the ~3,900 warm `stat`s are `ENOENT`. E2 timed only
20.

Host user data writes the tree at boot, then writes `host-facts/seed-utc`. The
entrypoint refuses to start a cohort until `now − seed-utc ≥ 120 s`, which is past
`acregmax` and `acdirmax`. The age is checked against the host's own record. It is
not read through a measurement mount, because that read would warm the cache it is
checking.

### Instrument: `agebench`

`agebench` is a new binary in the shared bench image (`infra/lib/stacks/bench/agebench.c`).
**`bench.c` is not modified.** E2 and E3's instrument stays byte-identical. The image
digest changes, and that is recorded.

The timing primitive is the same as `bench.c`: `clock_gettime(CLOCK_MONOTONIC)`
around each syscall. There are two modes:

- **`agebench pass <dir> <op> <cohort>`** is one timed pass over the tree in fixed
  order. `op` is `stat`, `enoent` or `open_read`. It writes one raw line per op:
  `cohort,op,seq,ns`.
- **`agebench serve <dir> <Δ> <warmup_s> <measure_s> <cohort>`** emulates a web tier
  after a deploy:
  1. **Compile:** `open_read` every file once. This is opcache's first request, and
     on OpenZFS it is when delegations get granted.
  2. **Requests:** at fixed-rate deadlines (`clock_nanosleep` with `TIMER_ABSTIME`,
     so the interval is Δ and not Δ plus the work), one request `stat`s all 1,000
     files and all 1,000 missing names.
  3. **Output:** per request, a log-binned latency histogram for each op (20 bins
     per decade, 100 ns – 1 s, exact counts), the request's start lateness, and its
     summed `stat` time.
  4. **Raw lines:** every op is written raw at Δ = 1 s and 10 s. At Δ = 0.1 s
     (~14 M ops per mount), one request in ten is written raw.

  Per-op timing is kept, as protocol §2.5 requires. At 12 % bin width, the
  histogram loses nothing the hit/miss split depends on.

### Cohort A: miss cost, sequential, one tier at a time, tier order shuffled

Each NFS tier runs on its `default` mount, in this order. The expected RPC signature
is checked from a `/proc/self/mountstats` snapshot taken before and after every
cohort, not once per run as in E2. N = 1,000.

| Cohort | Step | Measures | Expected signature (fail-closed) |
|---|---|---|---|
| A1 | `stat` pass | first-touch miss (cold client) | `LOOKUP` Δ ≥ 0.95 N |
| A2 | `enoent` pass | first-touch negative lookup | `LOOKUP` Δ ≥ 0.95 N |
| — | wait 75 s | > `acregmax` and `acdirmax` | — |
| A3 | `stat` pass | **revalidation miss: the production steady-state miss** | `GETATTR` Δ ≥ 0.95 N, `LOOKUP` Δ ≤ 0.05 N |
| A4 | `enoent` pass | negative-dentry revalidation | recorded; graded only by P8 |
| A5 | `stat` pass, immediately | hit | `GETATTR` + `LOOKUP` Δ ≤ 0.05 N |
| A6 | `open_read` pass | first read, cold data | `READ` Δ ≥ 0.95 N |
| — | wait 75 s | | — |
| A7 | `open_read` pass | open of cached data whose attributes have expired: production's non-opcache read | recorded: `READ` Δ, `GETATTR`/`ACCESS` Δ, `DELEGRETURN` |
| A8 | 10 × `stat` pass on `forced` | high-n forced miss | `GETATTR` Δ ≥ 0.95 × 10 N |

**A cohort whose signature does not match is `ERROR` for that tier and
replication.** It is never graded, never pooled, and never reported as a latency.
This is the check E2 lacked. It turns "this measured the cache, not the server" from
a post-hoc discovery into a gate.

**A6 and A7 are the fix for `open_read`.** A6 is the first `open_read` this mount
performs on data it has never read, and its signature requires a READ per file.
A7 is what a steady-state open costs: close-to-open revalidation, then data from the
page cache if the change attribute says the data is unchanged. In production, opcache
opens a PHP file once, at compile. Its `open_read` cost therefore belongs to cold
start (H4) and to non-PHP reads, not to the warm floor.

**Lustre** has no `mountstats`. Its signature comes from `lctl get_param mdc.*.md_stats`
and `ldlm` lock counts, snapshotted the same way. The exact counter names are
confirmed on the pilot replication, before it is graded. For Lustre, A1 is the miss
(no lock held). A3 is expected to be a hit, because locks do not expire at 75 s, and
its signature check is waived. **EBS** runs A1–A7 with no signature check. Its
numbers are the block reference.

### Cohort B: steady state, all tiers and all intervals at once

B runs after every A cohort has finished, never overlapping with one.

- 3 intervals × 6 tiers = 18 `serve` processes, each on its own mount (NFS) or its
  own subtree (Lustre, EBS).
- **Δ ∈ {0.1 s, 1 s, 10 s}** is the interval at which one client `stat`s one
  file. E0's warm floor is paid on every request, so Δ = 1 / (requests per second per
  task). The three intervals are a busy task, a modest one, and a quiet one.
- **Warm-up 300 s, excluded.** The 3 s → 60 s backoff needs ~93 s of continuous
  revalidation at its fastest, and longer at Δ = 10 s. **Measured: 600 s.**
- **The miss fraction is graded from RPC counters, not from latency.**
  `mountstats` is snapshotted at the warm-up boundary and at the end:
  - positive-`stat` miss fraction = (`GETATTR` + `LOOKUP` + `ACCESS` Δ) / `stat`s
    issued, with a binomial CI (§3.1, proportions);
  - directory revalidations fall inside that numerator. That is deliberate: they
    are part of what a production `stat` costs.
- **Latency is the cross-check.** The protocol's k-means (k = 2, log10) on each
  cell's histogram gives a slow-cluster share. If it differs from the counter
  fraction by more than 20 % relative, the cell is `ERROR`.
- **Running concurrently is a trade-off, stated here.**
  - On 2 vCPUs, B's hit latencies carry scheduler noise, so they are **not** cited
    as a hit cost. A5 is the hit cost.
  - The counters cannot be affected by contention.
  - A cell where more than 5 % of requests start later than Δ/2 is `ERROR`.
  - Running sequentially would take 18 × 15 min per replication.

`ENOENT` names are in the same requests. Their RPCs cannot be separated from the
positive `stat`s by counter. P8 is therefore graded on latency clusters alone, and
says so.

### Statistics

Per §3.1 of the protocol:

- **Latency cohorts:** median with order-statistic CI, geometric mean, percentiles,
  IQR/median, and the k = 2 bimodality test. A bimodal A cohort that passed its
  signature check is reported, not explained away.
- **Proportions:** binomial CI, with n.
- **Steady-state cost:** **summed `stat` time per request**, because a per-request
  cost is a sum. The amortised figure is (total `stat` time in the window) /
  (requests). Its median, p99 and maximum across requests are reported alongside
  it, because synchronized expiry concentrates misses into a few requests (P10).
- **Between-replication spread** for every graded figure. Three independent deploys.

All of it lives in `analysis/e5_stats.py`. The script is written and run against
synthetic runs reaching every grade before the first deploy (see blockers).

## Predictions

Pre-registered 2026-10-15, before any E5 apparatus exists. The E2 figures quoted are
from `results/E2/20261015T000959Z-85382cc/`. Each is graded per replication. A
prediction is SUPPORTED if every evaluable replication supports it, REFUTED if every
one refutes it, and INCONCLUSIVE otherwise. It is NOT EVALUABLE with fewer than 3
evaluable replications, where a replication is evaluable for a prediction if none of
the cohorts it reads is `ERROR`.

| # | Prediction | Kill condition |
|---|---|---|
| 1 | **E2's slow cluster was the real revalidation cost.** A3 median for `efs_host_plain` and `fsx_openzfs`, and A1 median for `fsx_lustre`, each within 0.5×–2× of E2's 827 / 98 / 149 µs. | Any of the three outside [0.5×, 2×]. E2's miss-cost table is then not the production miss cost, and the finding gets an appended correction. |
| 2 | **ONTAP's unobserved miss is OpenZFS-class, not EFS-class.** ONTAP A3 median within 0.5×–2× of the same replication's OpenZFS A3 median, **and** ≤ ¼ of `efs_host_plain`'s A3 median. Basis: ONTAP beat OpenZFS on `create`/`unlink` in E2 (982 vs 1,570 µs; 342 vs 561 µs), and both sit in the same AZ. | ONTAP A3 outside [0.5×, 2×] of OpenZFS, or > ¼ of EFS. |
| 3 | **First touch costs more than revalidation, but not by much.** On every NFS tier, A1 median / A3 median ∈ [1.0, 3.0]: one compound either way, with a `LOOKUP` adding server work. | Ratio < 0.9 or > 3.0 on any NFS tier. |
| 4 | **The forced-miss mount measures the same thing as a real revalidation** (an instrument check, not a hypothesis). A8 median within ±25 % of A3 median on each NFS tier. | Outside ±25 %. A8 is then reported, but not used for anything. |
| 5 | **Without delegations, the steady-state miss fraction is about Δ / `acregmax`.** For `efs_host_plain`, `efs_host_tls` and `fsx_ontap`: Δ = 0.1 s → ≤ 0.5 %; Δ = 1 s → 1.0–3.0 %; Δ = 10 s → 10–25 % (the model gives 1/7 to 1/6). | Δ = 1 s above 5 %, or Δ = 0.1 s above 2 %, on any of the three. Either means the timer does not settle at `acregmax` under a web-tier access pattern. |
| 6 | **Delegations stop the clock on OpenZFS.** After the compile step, `fsx_openzfs` miss fraction ≤ 2 % at **every** Δ, including 10 s, where P5's model gives ~15 %. | Δ = 10 s miss fraction ≥ 5 %. Delegations then do not survive, or do not cover `stat`, under this pattern, and OpenZFS behaves like P5. |
| 7 | **Lustre repeats are free.** `fsx_lustre` slow-cluster share ≤ 1 % at every Δ. DLM locks have no timer at these timescales. | > 5 % at any Δ. Then Lustre has no effective attribute cache in steady state, and pays ~149 µs per `stat` forever. |
| 8 | **Missing files are cheaper to keep missing than existing files are to keep fresh.** Negative dentries are revalidated through their directory, which is shared by 50 names. On each NFS tier, at Δ = 1 s, the `ENOENT` slow-cluster share ≤ the positive-`stat` slow-cluster share. | `ENOENT` share > 2× positive share on any NFS tier. |
| 9 | **The headline (H1).** At Δ = 1 s, amortised per-request `stat` time on `efs_host_plain` / the same on `ebs` ≤ 50×. Model estimate ~11×: 1,000 × (~2 µs + 1.7 % × 827 µs) against 1,000 × ~1.4 µs. E2's per-op ratio was 638×. | **Refuted at ≥ 200×.** Then the attribute cache does not rescue NFS at a modest request rate, and H1's tier-cost factor stands as measured. Between 50× and 200× is INCONCLUSIVE. |
| 10 | **Misses arrive together.** Files compiled together expire together. At Δ = 1 s on `efs_host_plain`, the 5 % of requests with the most misses carry ≥ 50 % of all misses. | < 20 %. Misses are then spread out, and the per-request p99 is not a stall. |

Prediction 9 grades the reframing the E2 finding proposed. Prediction 10 is the
reason the amortised mean is never quoted without the per-request tail. If 10 holds,
a deploy produces a periodic stall: a request that pays the miss cost on every file
at once, about once a minute. That is a latency finding the averages would hide.

**What changes for H1:**
- 9 SUPPORTED, with 1 and 5: H1's per-op factor becomes miss cost × miss rate, and
  the verdict is reviewed.
- 9 REFUTED: the factor stands as E3 and E2 measured it, and the 2026-10-15 caveat
  is closed in its favour.
- Either way, the verdict change cites this run's directory.

## Apparatus to build before the first deploy

Nothing below exists yet. Each item is reused from E2 where it fits, and the reuse is
named.

1. **`agebench.c`** in the shared bench image. `bench.c`, `tput.c` and
   `conformance.sh` are untouched. It is tested locally against tmpfs and ext4 in
   the image, with the output parsed by `e5_stats.py`.
2. **Stack `E5-AttributeCache-dev`** in `infra/lib/stacks/e5-attribute-cache.ts`.
   - Stack ID fixed now, per CLAUDE.md.
   - Tags: `Study=aws-wordpress`, `Experiment=E5`.
   - The FSx and EFS construction is factored out of `e2-storage-matrix.ts` into a
     shared module **only if** `cdk synth E2-StorageMatrix-dev` is byte-identical
     before and after. Otherwise it is copied, and the copy is noted in both files.
     E2's security-group dependency fix and backup settings come across either way.
   - No Fargate arm. The interface-endpoint list drops whatever only Fargate needed;
     the final list is recorded here.
3. **Host user data** adds the `seed` / `default` / `forced` / `ss-*` mounts with
   `nosharecache`, seeds the trees, unmounts `seed`, clears Lustre locks, drops EBS
   caches and writes `seed-utc`. This extends E2's user data, which already mounts
   all five server-backed tiers and records `host-facts`.
4. **Entrypoint.** E2's `entrypoint.sh` gains an `E5` mode. It reuses, unchanged:
   - the `st_dev` mount check (every `nosharecache` mount has its own `st_dev`, so a
     silently shared superblock fails it);
   - `mount-facts.csv`;
   - the shuffled tier order;
   - the S3 upload and manifest;
   - **the conformance gate**, on each tier's `default` mount in its own `conf/`
     directory, so the seeded tree is never touched before A1.

   New in this mode:
   - per-cohort `mountstats` snapshots (Lustre `md_stats`);
   - the signature checks;
   - the 120 s age gate.
5. **Lustre counters from an unprivileged container: `UNVERIFIED`.** If
   `/proc/fs/lustre` is not readable there, E2's privileged `cache-dropper` sidecar
   gains a "snapshot counters" request through the same file protocol `request-drop`
   uses.
6. **`experiments/E5-attribute-cache/scripts/collect.sh`** is derived from E2's.
   - Kept: the destroy trap installed before deploy; the scoped FSx backup sweep that
     polls to zero; AWS CLI v2 resolution that skips the broken v1; refusal on a dirty
     tree or a pre-existing stack; per-replication `meta.json` with image digests,
     FSx IDs and tool versions; task logs saved even on failure; and
     `STOP_AFTER_REP` / `RESUME_RUN_ID` / `RESUME_ALLOW_CHANGED` pause and resume.
   - Carried with it: E2's fix that resets `FSX_SOURCE_IDS` per replication.
7. **`make e5` and `make e5-container`**, using the existing `infra/runner` image.
8. **`analysis/e5_stats.py`** implements every grading rule above. Before deploy it
   is run on synthetic runs that reach SUPPORTED, REFUTED, INCONCLUSIVE and `ERROR`
   (a failed signature, a late cell, a counter/latency disagreement) for every
   prediction.

## Build record, 2026-10-16

Built against the list above. Nothing was deployed; every check below ran locally.

| Item | Where | Checked how |
|---|---|---|
| `agebench` | `infra/lib/stacks/bench/agebench.c`, built in the shared image with `-Werror` | Ran in the image, against a block layout and a local kernel NFS server (below) |
| E5 task sequence | `infra/lib/stacks/bench/e5-run.sh`, reached from E2's `entrypoint.sh` by one line (`BENCH_MODE=e5` → `exec e5-run`) | Ran end to end in the image, both layouts |
| Host seeder, Lustre counter service | `infra/lib/stacks/e5-host/seed.py`, `hostctl.sh`, shipped gzipped in user data | Seeder ran in the local check; `hostctl.sh` has not run (no Lustre locally) |
| Stack `E5-AttributeCache-dev` | `infra/lib/stacks/e5-attribute-cache.ts`, registered in `infra/bin/apparatus.ts` | `tsc --noEmit` and `cdk synth` under Node 22.17.0 (`node:22.17.0-slim`, fresh `npm ci`); rendered user data 7.8 KB of EC2's 16 KB limit; `bash -n` clean |
| E2 and E3 unchanged | — | Their synthesized templates were diffed against commit `6bb2e8f`: the **only** difference is the bench image asset hash, because the shared image gained `agebench` and `e5-run` |
| Collection | `experiments/E5-attribute-cache/scripts/collect.sh` | `bash -n`; `collect_arm` run against real task output with `aws` stubbed: complete output passes, a missing B file or snapshot exits 1 naming it |
| Grading | `analysis/e5_stats.py` | `analysis/test_e5_stats.py`: synthetic runs (`analysis/e5_synthetic.py`) reach SUPPORTED, REFUTED, INCONCLUSIVE and NOT EVALUABLE on all ten predictions, and each ERROR path blocks exactly the predictions that rest on it: a failed signature, a late cell, a counter/latency disagreement, an overrun, missing Lustre counters. 11/11 pass |
| Make targets | `make e5`, `make e5-container`, `make e5-local`, `make e5-stats` | `make help` |

### What the local NFS check showed

`scripts/local-nfs-check.sh` runs the real image and the real seeder against a
loopback NFSv4.1 server on the Docker VM's kernel (6.12), with the stack's mount
discipline. Its latencies mean nothing; its RPC counts are evidence for the gates. In
the fast mode (2 s waits), per-cohort `mountstats` deltas on the NFS tier:

| Cohort | RPCs | Gate |
|---|---|---|
| A1 cold `stat` | LOOKUP 1,040, ACCESS 40 | PASS: one LOOKUP per file, plus 40 directories |
| A2 cold `ENOENT` | LOOKUP 1,000 | PASS |
| A3 after **2 s** | none | **FAIL**, correctly: inside the 3 s window it is a hit, and the gate refused to report it as a miss. With the real 75 s wait it should be GETATTRs; that run is outstanding (below) |
| A5 hit | none | PASS |
| A6 cold read | OPEN 1,000, READ 1,000, CLOSE 1,000 | PASS: one READ per file. This is the `open_read` fix working |
| A8 forced | GETATTR 10,000, **LOOKUP 1,040** | PASS, and see amendment 2 |

`e5_stats.py` read this output without error. Every prediction graded NOT EVALUABLE,
which is right for one replication with a failed A3.

### The full-timing local run, 2026-10-15 18:46 UTC

**Output:** [`local-check/20261015T184617Z-6e7ec1f/`](local-check/20261015T184617Z-6e7ec1f/).
The raw task output is there, and `summary.json`/`summary.md` come from
`analysis/e5_stats.py`.

- **Settings:** commit `6e7ec1f`, `make e5-local` with the defaults, real 75 s waits, B
  warm-up 150 s and measurement 240 s (both shortened from 300 s and 600 s).
- **Client and server:** kernel 6.12.72 (linuxkit), loopback NFSv4.1 to Linux knfsd on a
  tmpfs export. Tiers `ebs` and one NFS tier.
- **What it is:** an apparatus check, not a result. It sits outside `results/` because
  nothing in it describes AWS. It is filed here because the README cites it.

**What it scopes to.** It tests **this branch's** apparatus. Master carries a separate
E5 implementation (`73e880e`, built in parallel from the same spec), and that one is
what the 2026-10-15 pilot attempts deployed. What carries over to both is the
behaviour of the Linux NFS client. That behaviour is what the gates and predictions
rest on.

**Cohort A: every signature matched, with the real waits.**

| Cohort | `mountstats` delta | Gate |
|---|---|---|
| A1 cold `stat` | LOOKUP 1,040, ACCESS 40, GETATTR 1 | PASS |
| A2 cold `ENOENT` | LOOKUP 1,000 | PASS |
| A3 after 75 s | **GETATTR 1,041**, LOOKUP 0 | PASS. A real revalidation: one GETATTR per file, plus a directory. The mechanism section's reading of `fs/nfs/inode.c` holds on this kernel |
| A4 `ENOENT` after 75 s | none | recorded. Negative dentries survived on unchanged directories |
| A5 immediately after A3 | none | PASS |
| A6 cold read | OPEN 1,000, READ 1,000, CLOSE 1,000 | PASS: the `open_read` fix |
| A7 warm read after 75 s | OPEN 1,000, CLOSE 1,000, GETATTR 41, **READ 0** | recorded. Close-to-open revalidation went to the server; the data came from the page cache |
| A8 forced, 10 passes | GETATTR 10,000, LOOKUP 1,040 | PASS. Pass 1 is a first touch (amendment 2) |

**Cohort B: the server granted delegations, and the latency cross-check failed
closed.**

| Interval | Stats in window | RPCs in window | Counter miss fraction | Latency miss fraction | Cell |
|---|--:|--:|--:|--:|---|
| 0.1 s | 2,360,000 | GETATTR 164 | 0.007 % | 5.75 % | ERROR |
| 1 s | 236,000 | GETATTR 164 | 0.069 % | 3.99 % | ERROR |
| 10 s | 23,000 | GETATTR 124 | 0.54 % | 2.50 % | ERROR |

Two things happened:

1. **The file attribute timers never expired.** P5's no-delegation model predicts about
   N × window / `acregmax` = 4,000 file GETATTRs at Δ = 0.1 s. There were 164, about the
   same at every interval, roughly the 40 directories revalidating every 60 s.
   - Linux knfsd grants read delegations, and the compile step opened every file.
   - Attributing this to delegations is an **inference**: the delegations were not
     counted directly.
   - On this point the local server behaves like FSx OpenZFS (P6's mechanism), not
     like EFS or ONTAP. So **P5's model was not tested here.**
2. **The latency classifier disagreed with the counters, and the grader marked every
   NFS cell ERROR.**
   - The hit/miss threshold (amendment 5) came out at 4.5 µs: the geometric midpoint of
     a 0.6 µs hit (A5) and a 32 µs loopback miss (A3).
   - With 18 serve processes on the VM's CPUs, ordinary hits drifted past 4.5 µs. EBS's
     B hits averaged 2–3.5 µs a `stat` against 1.1 µs in A5.
   - The protocol's k-means read every cell as unimodal, which agrees with the counters.
   - This is the fail-closed rule working, not a defect in it. But it is a live risk for
     the pilot.

**What this means for AWS.** The margin between hit and miss is wider there: a ~2 µs hit
against misses of 98–827 µs puts the threshold at roughly 14–40 µs. Concurrency noise
crossing that is less likely, but it is not ruled out. If the pilot's B cells come back
ERROR for this reason, the counter fraction stands as the measurement. Deciding whether
to grade on counters alone is then a change to the pre-registration, and has to be
recorded as one. This check does not make that change.

**Not tested locally:** EFS, FSx and Lustre themselves, TLS mounts, the host user data,
the Lustre counter service, and P5's no-delegation regime. Knfsd can be run with leases
off (`fs.leases-enable=0`) to cover the last one.

### Amendments to the method, made while building, before any E5 data

The original text above is left as written. These rules are what `e5_stats.py`
implements.

1. **A3's gate is GETATTR + LOOKUP ≥ 0.95 N,** not "GETATTR ≥ 0.95 N and LOOKUP ≤
   0.05 N". Whether the kernel revalidates an expired cached dentry with a GETATTR or a
   LOOKUP is a kernel detail, not the property being measured. The property is one
   server round trip per `stat`. The composition is recorded per cohort.
2. **A8 drops its first pass.** The forced mount is cold too, so pass 1 is a first
   touch: LOOKUP + GETATTR, seen locally. The A8 median uses passes 2–10, n = 9,000.
   P4 compares that with A3.
3. **A late B request is skipped, not run late.** `agebench` skips any deadline it
   has missed by more than Δ/2, rather than issuing catch-up requests that would only
   inflate the hit count. The rule "more than 5 % of requests start later than Δ/2"
   becomes "more than 5 % of deadlines skipped". It is the same intent, measured
   directly. Any request still running at a counter snapshot is also ERROR.
4. **Raw B lines are sampled for size:** every op at Δ = 10 s, every 10th request at
   1 s, every 100th at 0.1 s. All files are gzipped. The histograms (exact counts)
   are kept for every request. The spec's "1 in 10 at 0.1 s" would have committed
   ~0.5 GB per replication.
5. **B's latency hit/miss split uses a threshold from the same replication's
   cohort A:** the geometric midpoint of the tier's A5 (hit) median and its miss median
   (A3, or A1 on Lustre). The protocol's k-means is still run and reported, but it
   cannot be the classifier here. At Δ = 0.1 s the expected miss share (~0.2 %) is
   below its 2 % cluster-share gate by design. If A5 or the miss cohort is not PASS,
   the cell is ERROR.
6. **The counter/latency agreement tolerance is max(20 % relative, 0.002
   absolute).** At a 0.2 % miss fraction, 20 % relative is 0.04 percentage points,
   which a handful of directory GETATTRs exceeds. The counter fraction's numerator
   includes ENOENT and directory RPCs, so it is an upper bound on positive-`stat`
   misses, and it is what a production `stat` pays. Its denominator is positive `stat`s.
7. **P8's refutation allows 0.001 absolute,** so that two near-zero shares are not
   graded on noise: REFUTES if the ENOENT share > 2 × positive share + 0.001.
8. **Lustre counters come from a host-side service** (`hostctl.sh`, the same
   request-file protocol as E2's `request-drop`), not from `/proc` inside the
   container. This settles blocker 5 without making anything privileged. The grader
   uses MDC RPCs net of pings, `req_waittime − obd_ping`, for A1, and `ost_read` for A6.
   The counter names are still `UNVERIFIED` until the pilot.
9. **The task is polled to a 90 min deadline,** not `aws ecs wait tasks-stopped`. That
   waiter gives up after 10 minutes, and the task runs ~40. Under E2's script, the
   waiter's failure would have fired the destroy trap mid-measurement.
10. **The ASG signal timeout is 25 min, not E2's 10,** because seeding ~30,000 files
    happens before the signal. `UNVERIFIED`: the pilot measures it.

### Pilot-only unknowns

These cannot be checked without AWS. Each one fails closed, either at boot with
diagnostics kept in the retained bucket, or in the task's mount check.

- Whether the EFS mount helper passes `nosharecache` and `acregmin`/`acregmax`
  through on TLS mounts. The task requires them in the negotiated options of the
  `forced` cohort.
- Whether an ECS host volume's bind is recursive, so that the ~20 NFS mounts under
  `/mnt/e5` appear inside the task. If not, every cohort fails the `st_dev` check.
- Lustre's counter names in `mdc.*.stats` and `osc.*.stats` on 2.15.
- Whether seeding fits inside the 25 min signal.

## Cost

From snapshot `results/pricing/20260918T080950Z-c94ac10/`, the same as E2. It is
refreshed with `make pricing` on the day.

| Line item | $/hr |
|---|--:|
| `c7gd.large` | 0.1058 |
| Interface endpoints, ≤ 12 × 1 AZ × $0.013 (E2's set, an upper bound) | ≤ 0.1560 |
| FSx OpenZFS + Lustre Scratch 2 + ONTAP gen-1 (E2's arms, unchanged) | 0.6929 |
| EFS, S3, CloudWatch Logs at these volumes (~25 MB read per tier per replication; no throughput probe) | ~0 |
| **Standing total** | **≤ ~0.955** |

| | Estimate, `UNVERIFIED` until replication 1 measures it |
|---|---|
| One replication | 80–100 min. Deploy and FSx creation took ~25–35 min in E2. Seeding and the age gate overlap the task launch. Cohort A takes ~20 min (6 tiers × two 75 s waits plus the passes). Cohort B takes 15 min. Destroy and sweep take ~20 min. |
| Three replications | ~4.5–5 h × $0.955 ≈ **$4.50–5** |
| **Hard ceiling** | **$10**, including failed attempts. Past it: stop and diagnose, do not retry. |

## Teardown, and how it is verified

The same discipline as E2, because it is the same FSx trap. At ~$0.955/hr a stack
left standing costs ~$700/month, and a leaked FSx final backup bills on its own,
outside any stack.

- **Per replication:** the destroy trap is armed before `cdk deploy`. After
  `cdk destroy`, the scoped backup sweep runs: it matches by this stack's FSx IDs or
  by `Study=aws-wordpress` + `Experiment=E5`, polls until it sees zero twice 60 s
  apart, and exits 3 naming anything still billing after 40 min. The verdict is
  whether the stack still exists, not `cdk destroy`'s exit code.
- **After the run,** in every region: no stack `E5-AttributeCache-dev`, no FSx file
  systems, no FSx backups from this stack, and nothing tagged `Study=aws-wordpress`
  except inactive task definitions. SVMs are confirmed against
  `describe-storage-virtual-machines`, because the tag index lists deleted ones. The
  result is recorded here with its timestamp.
- **Backstop:** run `cdk destroy E5-AttributeCache-dev`, then the scoped sweep, by
  hand.
- **Pre-flight on the day:**
  - a clean baseline (`Study=aws-wordpress`, all regions);
  - `make doctor`;
  - Node 22.17.0, or the runner image;
  - `caffeinate -i`;
  - a launch that survives the terminal closing.

## Run order

1. **`STOP_AFTER_REP=1 make e5-container REPS=3`.** Replication 1 is the pilot. It is
   graded only if it passes step 2.
2. **Check before replications 2 and 3 count:**
   - every tier passed conformance;
   - every A cohort matched its signature;
   - `mount-facts.csv` shows `nosharecache`, and `acregmin=0,acregmax=0` only on
     `forced`;
   - the Lustre counter names are confirmed;
   - no B cell is late;
   - the seed age was ≥ 120 s;
   - the measured duration is recorded here.

   If anything is wrong, stop. A known confound is not worth two more replications.
3. Resume with `RESUME_RUN_ID=<run-id>`.

## Threats to validity, known before running

- **One kernel line (6.1, AL2023).** The timer defaults are upstream defaults, but the
  backoff code has changed across kernel versions. The result holds for this client.
- **Fargate is not measured.**
- **Synchronized seeding.** Every file is compiled within seconds, so expiries are
  synchronized. That is what a deploy does, so it is faithful at the start. A real
  site's traffic may desynchronize it over hours, and 600 s cannot show that.
- **Uniform access.** Every request `stat`s all 1,000 files. Real requests touch
  different subsets per endpoint, so a rarely touched file sees a larger Δ than its
  site's request rate implies. Δ is a per-file interval, and the conversion to a
  request rate is per task.
- **Server caches are warm.** Files are seeded minutes before measurement. That
  matches a hot production code tree, but not a server that has just restarted or
  failed over.
- **`nosharecache` is not a production option.** It is used so each cohort has its
  own counters. With one mount per export, as in production, it changes nothing about
  the caching behaviour being measured.
- **`atime`.** Mounts are `relatime`. If a server bumps the change attribute on a
  read-driven `atime` update, every read resets the timer to `acregmin`. Cohort B
  issues only `stat`s after the compile step, so this does not reach it. A7 would show
  it for open-heavy workloads.
- **The FSx minimum-size distortion, single AZ and single instance size** all carry
  over from E2 unchanged.
