# E5 — what an NFS `stat` costs once the file is old

**Status:** `PILOT COLLECTED; NOT READY FOR REPLICATIONS 2/3` (2026-10-27 HKT).
The single authorised AWS pilot collected six tiers and both cohorts. Four of
18 B cells fail validity gates. Lustre A1 counter-name coverage is corrected in
the separately versioned offline follow-up; original pilot grading is frozen.
All aggregate predictions remain NOT EVALUABLE at n=1. No hypothesis verdict changes.

## Current status and handoff (2026-10-26)

See the [pilot review](../../results/E5/20261026T152946Z-b1efcb2/pilot-review.md),
[unchanged-method grading](../../results/E5/20261026T152946Z-b1efcb2/summary.md) and
[final teardown evidence](../../results/E5/20261026T152946Z-b1efcb2/teardown.json).
Source was clean at `b1efcb2`. Host watchdog and direct-service inventories verify
cleanup; this validates the normal live path, not every injected failure path.

**Next work, before another paid run:**

- Attribute the ten GETATTR operations outside request phases in each EFS TLS B
  window; preserve exact reconciliation rather than subtracting background noise.
- Confirm the deployed Lustre `ldlm_ibits_enqueue` counter semantics and add a raw
  fixture regression. Keep this pilot's original grading when reanalysing.
- Diagnose Lustre's 25.7% late-request share at 0.1s and concurrent instrumentation
  overhead. Do not relax the predeclared 5% gate to fit this observation.
- Record any apparatus/method amendment, refresh budget/baseline, and obtain the
  separate go-ahead for another run. Replications 2/3 have not been launched.

The local NFS checks, phase-attributed RPC amendment, conservative expiry probes
and host watchdog remain integrated. Historical attempts and protocol decisions
below are retained as dated evidence. WordPress is the motivating workload;
filesystem cost/cache behaviour remains the research acceptance target.

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

## Method amendment — phase-attributed RPCs (2026-10-26)

Recorded before implementing this amendment or running the amended instrument.
The original method and predictions below remain the historical pre-registration.
This is a changed operationalisation, not a regrade of the existing local checks.
It follows the noise failures in `local-check/20261016T181153Z-725266b-leases-on/`
and `local-check/20261016T183547Z-725266b-leases-off/`.

1. **Separate attribution inside each request.** `serve` performs all positive
   stats, then all negative stats, rather than interleaving them. On NFS it reads
   GETATTR/LOOKUP/ACCESS counts for the exact measurement mount before the positive
   phase, between phases, and after the negative phase. Each request records both
   deltas. These snapshots and output formatting are outside syscall timing;
   their scheduler/CPU overhead still exists and is subject to the lateness gate.
   Compile, request count, intervals and warm-up/measurement windows are unchanged.
   Phase order is fixed, so shared-directory revalidation is paid first by the
   positive phase; the negative comparison is conditional on that order.
2. **Counters measure RPC-operation intensity, not a Bernoulli miss probability.**
   GETATTR + LOOKUP + ACCESS per stat includes directory work and can exceed one.
   Report the operations separately, the per-phase rate and between-replication
   spread; do not attach binomial confidence intervals to this rate. Validate
   counter presence, monotonicity, per-request attribution and agreement with the
   independent warm/end snapshots. Missing, reset or inconsistent counters fail
   the affected cell. Old files without phase attribution are ineligible for this
   amended method, not silently upgraded.
3. **Latency cross-check is diagnostic on NFS.** Preserve the original separation
   and discrepancy thresholds and report disagreement, including the EBS control's
   slow share. It is not a veto of valid phase-attributed counters or summed time.
   No noise-floor subtraction is applied. P5/P6 retain their numerical bands but
   apply to positive-phase RPC intensity; P8 retains its ratio thresholds but now
   compares negative/positive RPC intensity at 1 s. P10 retains its concentration
   thresholds but uses positive-phase RPC operations per request. Report these as
   amended operational tests, not literal file-miss fractions or delegation proof.
   P7 still has latency evidence only; it is NOT EVALUABLE when the EBS control
   has a slow share above the original 1% support limit, or its slow population
   overlaps Lustre's classifier boundary. A latency-only grade never proves locks.
4. **Post-B expiry probe on each NFS steady-state mount.** After all B processes
   exit, leave the mounts idle for at least 75 s, then snapshot counters around one
   positive stat pass. Record elapsed monotonic idle time and verify N operations.
   GETATTR >= 0.95 N and LOOKUP <= 0.05 N means REVALIDATION_OBSERVED; GETATTR +
   LOOKUP + ACCESS <= 0.05 N means REVALIDATION_SUPPRESSED; otherwise UNKNOWN.
   Missing/bad evidence or <=60 s idle is UNKNOWN. Suppression is consistent with
   held delegations, not proof of them. P5 requires REVALIDATION_OBSERVED on each
   contributing mount; suppression/unknown makes that replication NOT EVALUABLE,
   not a refutation of the timer model. P6 reports the probe alongside its rate
   grade and makes no causal delegation verdict.
5. **Limits and cost.** The probe adds at least 75 s of task time, plus passes;
   additional counter reads add unmeasured overhead. No new AWS service is added.
   The historical standing estimate and $10 ceiling remain; actual runtime and
   remaining budget must be checked before a pilot. This amendment authorises no
   deployment. The Docker-external teardown watchdog remains a separate blocker.

The 60 s bound is the default regular-file maximum in
[nfs(5)](https://man7.org/linux/man-pages/man5/nfs.5.html); existing mount-option
checks must still establish the intended configuration. Delegation caching
semantics are specified in [RFC 8881](https://www.rfc-editor.org/rfc/rfc8881.html).
The probe classifications are this study's conservative inference, not a direct
observation of NFS delegation state. Direct server-side state in a local check
can independently test that inference, but is not assumed available on AWS.

## Predictions

The table retains the original predictions. For new runs, apply the dated
phase-attribution amendment above to P5–P8 and P10; numerical thresholds remain
unchanged. In particular, amended RPC rates are not literal miss probabilities.

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

## Apparatus as built (2026-10-16)

Built after the predictions above and before any E5 data exists. Nothing has been
deployed.

| Item in the list above | File | State |
|---|---|---|
| 1. `agebench` | `infra/lib/stacks/bench/agebench.c` | Built into the shared image. `bench.c`, `tput.c` and `conformance.sh` are untouched. |
| 2. Stack `E5-AttributeCache-dev` | `infra/lib/stacks/e5-attribute-cache.ts`, registered in `infra/bin/apparatus.ts` | **Copied** from `e2-storage-matrix.ts`, not factored: a copy cannot move E2's template, and E2 is complete. The header comment says what was carried over and what differs. Synthesizes in the pinned runner (Node 22.17.0). |
| 3. Host user data | same file | Seeds through `seed` mounts, then unmounts them; clears Lustre DLM locks; drops caches; mounts 5 × 4 NFS measurement mounts; writes `seed-utc`. The seeder is `infra/lib/stacks/bench/e5-seed.py`, embedded into the user data at synth. |
| 4. Entrypoint E5 mode | `entrypoint.sh` execs `e5-run.sh` when `BENCH_MODE=e5`, after its unchanged st_dev check and mount-facts capture | E2 and E3 never set `BENCH_MODE`; their path is unchanged. |
| 5. Lustre counters | `cache-dropper` gains an `lreq-*` request; client `request-lustre-stats` | Read by the privileged sidecar from the start, rather than trying the unprivileged container first. |
| 6. `collect.sh` | `experiments/E5-attribute-cache/scripts/collect.sh` | Derived from E2's; differences listed in its header. |
| 7. `make e5`, `make e5-container` | `Makefile` | Also `make e5-stats` and `make e5-selftest`. |
| 8. `analysis/e5_stats.py` | plus `analysis/e5_selftest.py` | Self-test: **59 of 59 cases** reach their intended grade. That covers every prediction at SUPPORTED, REFUTED, INCONCLUSIVE (mixed and, where a band exists, per replication) and NOT EVALUABLE, plus the named ERROR paths: a failed signature, a late cell, a counter/latency disagreement, an unknown Lustre counter name, and a debugfs duplicate that must not double-count. |

**Interface endpoints:** E2's twelve, unchanged. None was there only for Fargate.

**Host layout.** Each NFS measurement mount mounts the export **root** with
`nosharecache`, and the task bind-mounts that mount's own subtree
(`/mnt/e5/<tier>/<family>/e5/<tier>/<subtree>`). The spec said "pointing at its own
subtree"; the caching is identical, because each mount only ever walks into its own
subtree, and it reuses E2's exact, already-working mount commands instead of
introducing subdirectory mounts. The two EFS tiers share one file system, with
separate subtrees and separate mounts.

### Verified before deploy, and not

| Verified | How |
|---|---|
| `agebench` builds `-Werror`, runs both modes, and verifies every size against `bench.c`'s formula | Local image build; a smoke run of `e5-run.sh` in E5 mode on a bind mount and an ext4 volume with short timings |
| The ERROR path for an instrument or counter failure | The same smoke run, with Lustre counters unreachable: `A1,error` recorded, the tier's later A cohorts skipped, B still run |
| The grader parses real `agebench`/`e5-run.sh` output | `e5_stats.py` over the smoke run's files |
| The grading rules reach every grade | `make e5-selftest`, 59/59 |
| The stack synthesizes; user data is valid shell and ~12 KB of the 16 KB limit | `cdk synth` in the runner; `bash -n` on the rendered user data |

**Not verifiable before a deploy.** The pilot replication (run order, step 2) is where
each of these is checked:
- that `nosharecache` and `acregmin=0,acregmax=0` pass through the EFS mount helper
  (`mount -t efs -o tls,...`). `e5-run.sh` refuses to start if they did not take.
- every NFS signature on real mounts, including the A1-A8 RPC shapes.
- Lustre's counter location and names (`LUSTRE_MISS_COUNTERS` in `e5_stats.py`).
- seeding time against the 25-minute boot signal.
- the 24-volume task definition on a real ECS agent.

### Amendments to the method, 2026-10-16, before any data

Each was found while building, not by looking at results; none changes a prediction
or a threshold in "Predictions".

1. **A8 gets an unscored first pass, `A8w`.** The `forced` mount has never looked
   the files up, so its first pass is a first touch (`LOOKUP`), not a revalidation.
   The spec's A8 signature (`GETATTR` ≥ 0.95 × 10 N) would have failed by one pass
   on every tier. `A8w` is recorded; the 10 graded passes follow it.
2. **Raw per-op sampling is thinner than specified:** every request at Δ = 10 s, one in
   10 at 1 s, one in 100 at 0.1 s. The spec's rate would commit ~100 MB of raw data
   per run, against a repository of ~10 MB. Every op of every request is still in the
   per-request histograms, which are what the grader reads, so no graded figure
   depends on the raw sample.
3. **The counter/latency cross-check tolerance is max(20 % relative, 0.2 percentage
   points).** A purely relative rule makes a cell at a 0.17 % miss fraction (the
   expected Δ = 0.1 s value) an ERROR over a handful of directory revalidations, which
   the counter includes by design and the latency of file `stat`s does not.
4. **The slow-cluster split is a weighted k-means on the histogram, initialised at the
   extremes,** with E3's 0.5-decade separation gate and **without** E3's 2 % share
   gate. Misses at ~1.7 % are the quantity being measured, so a 2 % floor would erase
   them. Without a slow cluster at least 0.5 decades above the fast one, the slow
   share is 0.
5. **Prediction 9 sums positive `stat`s only,** as its own model estimate does
   (1,000 × …). `ENOENT` time is reported alongside it.
6. **The task is polled, not waited on.** `aws ecs wait tasks-stopped` gives up after
   10 minutes; this task runs ~35.
7. **The retained diagnostics bucket is copied into the replication and deleted** after
   teardown. E2 never deleted its own: seven `e2-storagematrix-dev-diagnosticsbucket*`
   buckets (2026-10-14 and 15) are still in the account, near-zero cost, outside any
   stack.

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

### Go-ahead (2026-10-16, local; 2026-10-15T17:06Z)

Deploy approved by the study owner for the pilot replication only:
`STOP_AFTER_REP=1 make e5-container REPS=3`, stopping after replication 1 for the
step-2 checks. Replications 2 and 3 need a second go-ahead.

Pre-flight:
- **Baseline clean**, all regions, `Study=aws-wordpress`: no stacks, file systems,
  backups, SVMs or instances. The tag index still lists deleted E2 clusters, SVMs and
  one backup (`describe-backups` confirms `BackupNotFound`); the only live items are
  E2's seven retained diagnostics buckets.
- **Pricing re-read:** `results/pricing/20261015T170607Z-73e880e/`. Every line used
  above is identical to the 2026-09-18 snapshot (c7gd.large $0.1058, OpenZFS $0.0608,
  Lustre Scratch $0.2762, ONTAP $0.3559, PrivateLink endpoint $0.013), so the
  standing total stays **~$0.955/hr**.

### Pilot go-ahead (2026-10-26)

The study owner said "go" after reviewing the 2026-10-26 conditional preflight.
Approved scope: **replication 1 only**, via
`STOP_AFTER_REP=1 make e5-container REPS=3`; collect and inspect the result and
verify teardown, then stop. Replications 2 and 3 are not authorised by this step.

The preflight's planning basis is retained: historical spend estimated at $1.55,
a $2 pilot target plus $1 reserve, and the unchanged $10 total ceiling. Actual
historical billing attribution remains unverified because allocation tags are
inactive. No billing/IAM settings are changed for this run. The host watchdog
and in-run gates remain active; a failed pilot is diagnosed before any retry.

### Pre-launch toolchain correction (2026-10-26)

Two launcher invocations stopped before creating a runner or CloudFormation stack:
`shutil.which("aws")` selected the first executable bit on PATH, an unusable x86
binary (OS errno 86), while PATH-based subprocess execution found a later working
v2. The generic error had also conflated execution failure with timeout. The host
launcher/recovery now validate every PATH candidate for a working AWS CLI v2, as
the collector already does, and report execution errors separately. Regression
checks cover wrong-architecture/v1 candidates and timeout diagnostics. These were
pre-deployment failures, not AWS replications; the single-pilot approval remains.

### Unexecuted change-set attempt (2026-10-26)

`results/E5/20261026T152151Z-feeba20/` stopped before benchmark resources were created. CDK's default
change-set deployment creates a `REVIEW_IN_PROGRESS` placeholder with no root
stack tags. The strict host watchdog rejected that placeholder and killed the
runner before its AVAILABLE change set was executed. Asset publication had
completed; any asset storage/request cost is unmeasured.

Ownership was independently verified from the change set's exact Stack ARN and
matching run/study/experiment tags. The unexecuted placeholder was deleted by
that exact ARN; direct checks confirmed no stack, FSx filesystem or backup.
`failure.json` records that the old watchdog's empty-owned-scope success was
insufficient. No benchmark data exists and this does not count as replication 1.

The collector now uses `cdk deploy --method direct` to avoid that untagged
intermediate state. Ownership validation remains strict, and a same-name unowned
stack now prevents cleanup success. Regression coverage includes that case.
The deployment method changes collection plumbing, not the measurement design.
Sources: [CreateChangeSet](https://docs.aws.amazon.com/AWSCloudFormation/latest/APIReference/API_CreateChangeSet.html)
and [CDK deployment methods](https://docs.aws.amazon.com/cdk/v2/guide/ref-cli-cmd-deploy.html).

### Isolated CDK output correction (2026-10-26)

`results/E5/20261026T152700Z-bf451df/` failed before deployment because the killed container left a PID lock
in shared `infra/cdk.out`; a new container reused that PID namespace. The original
collector teardown and the host watchdog both verified no stack or FSx backups.
No benchmark resources or data were created. Each replication now allocates a
unique `/tmp` CDK output directory, used by both deploy and destroy; the existing
shared output directory is left untouched. This is collection isolation only.

### Guarded pilot collected (2026-10-26 UTC)

Run [`20261026T152946Z-b1efcb2`](../../results/E5/20261026T152946Z-b1efcb2/pilot-review.md)
completed collection and normal teardown under the host watchdog. B: 14 OK,
three EFS TLS phase/window mismatch errors, one Lustre 0.1s lateness error.
Lustre A1 also fails the current counter signature. The unchanged grader reports
all aggregate predictions NOT EVALUABLE (one replication). Raw data, logs,
provenance, grading and direct-service teardown inventories are frozen in that run.
No retry or replications 2/3 are authorised by this receipt.

### Attempt log

**Attempt 1, `results/E5/20261015T170718Z-8f2db3b/` (failed, not graded).**
- Deploy: 23 min. The host's boot steps all succeeded: every mount, seeding, Lustre
  lock clear, and cfn-signal.
- The task's gates passed: all 22 mounts distinct by st_dev; `nosharecache` on all 20
  NFS mounts and `acregmin=0,acregmax=0` only on `forced`. The EFS mount helper
  passes both through, which was one of the open questions. Seed age was 121 s and
  conformance passed on all 6 tiers.
- Cohort A ran on every tier with no ERROR line. That includes Lustre's counter
  requests, which returned something non-empty; the names are still unconfirmed.
  Cohort B ran its full 15 minutes.
- **The upload failed** after 33 min: `s3:ListBucket` AccessDenied. `e5-run.sh`
  uploaded with `aws s3 sync`, which lists the destination, and the task role is
  granted write only, as in E2. The task exited 1, and the stack, bucket included,
  was destroyed with the data in it.
- **Not caught locally** because the smoke run had no bucket. Fixed by uploading with
  `aws s3 cp --recursive`, which needs only PutObject.
- **Kept:** the task log, host and FSx provenance, and the boot diagnostics.
- **Teardown verified:** the stack is gone, the two FSx final backups were swept
  (matched by id and tag), and the diagnostics bucket was copied and deleted.
- **Cost:** ~1.3 h × $0.955 ≈ **$1.25**, against the $10 ceiling.

**Attempt 2, run `20261015T183102Z-6272b44` (aborted during deploy, no data).**
- Launched 18:31Z from `6272b44`, with the upload fix.
- At about 18:40Z the workstation's Docker daemon stopped while CloudFormation was
  still creating the stack. That killed the runner container, so `collect.sh`'s
  destroy trap never ran. The stack was orphaned in `CREATE_IN_PROGRESS`, with
  OpenZFS and Lustre available and ONTAP still creating.
- **Torn down by hand** without Docker: `aws cloudformation delete-stack` at 18:42Z,
  and the stack was gone by 18:49Z. The scoped sweep found one OpenZFS final backup
  (`backup-0ba7475c959692c00`, matched by source id and `Experiment=E5`), which was
  deleted. The retained diagnostics bucket was empty, since the host never booted far
  enough to write to it, and was deleted.
- **Verified 18:50Z, directly rather than through the lagging tag index:** no stack,
  FSx file system, SVM, backup, VPC, endpoint, volume, ECS cluster or log group from
  E5. The only E5 instance is attempt 1's, terminated.
- **Lesson:** the destroy trap lives inside the runner container, so anything that
  kills Docker defeats it. Before attempt 3, the run needs an out-of-container
  watchdog that deletes the stack if the runner dies.
- **Cost:** ~20 min of standing FSx + endpoints ≈ **$0.30**. Running total for E5:
  ~$1.55 of $10.

## Phase-attribution validation (2026-10-26)

[Validation receipt](local-check/20261026-phase-attribution.md): 59 synthetic
grading cases, 25 regression checks and two sequential kernel-NFS `fast-probe`
runs with real 75 s idle probes. With leases enabled the probes report
REVALIDATION_SUPPRESSED; with leases disabled they report REVALIDATION_OBSERVED,
matching independently sampled local server state. Both runs produce complete
JSON/Markdown with phase/window counters reconciled. Short A/B timing, one NFS
family and six serve processes limit this to apparatus validation; AWS behaviour,
steady-state bands and 18-process overhead remain unverified.

## Local NFS apparatus checks (2026-10-16 UTC)

**These are apparatus checks, not results.** They sit in `local-check/`, outside
`results/`, because nothing in them describes AWS. The client is Linux 6.12.72
(linuxkit, Docker Desktop's VM). The server is loopback NFSv4.1 to Linux knfsd on a
tmpfs export. Only the RPC counts are evidence. The latencies describe a loopback,
not EFS or FSx.

**Harness:** `scripts/local-nfs-check.sh`, `make e5-local [MODE="fast leases-off"]`.
It was ported from the parallel build on `claude/e5-attribute-cache-spec` (`6e7ec1f`,
`5c98c8a`) and adapted to this apparatus. It runs this repository's bench image
unchanged (`entrypoint.sh` → `e5-run.sh` → `agebench`) and `e5-seed.py`, and it
reproduces the stack's layout:
- seeding goes through a mount that is then unmounted, followed by `drop_caches` and
  `seed-utc`;
- each family mounts the export root with `nosharecache`, and each subtree is
  bind-mounted at `/bench/<tier>.<family>`;
- `ebs` is a plain directory on the container root, and `root-dev` is written so the
  "ebs must be on the root" check is live.

The harness also samples `/proc/fs/nfsd/clients/*/states` every 15 s to count the
delegations the server holds. A client cannot see that number, and on AWS nobody can.
Teardown unmounts every client mount before it stops nfsd: a client holding
delegations against a server that has gone away wedges the Docker VM.

Both runs used commit `725266b` with the pre-registered timing: 120 s seed age, 75 s
waits, 300 s warm-up and 600 s measured. The tiers were `ebs` and `efs_host_plain`.
`git_dirty` in `local-meta.csv` counts the grader edit below and the first run's
output directory. The image and harness were unchanged between the runs. Both
`summary.*` files were regenerated with the grader as committed here.

| | [`…181153Z-725266b-leases-on`](local-check/20261016T181153Z-725266b-leases-on/) | [`…183547Z-725266b-leases-off`](local-check/20261016T183547Z-725266b-leases-off/) |
|---|---|---|
| `fs.leases-enable` | 1 (default) | 0 (restored to 1 on exit) |
| Delegations the server held during B | 3,000–4,000 | **0** in every sample |
| A1 / A2 | LOOKUP 1,040 / 1,000: PASS | same |
| A3 after 75 s | GETATTR 1,041, LOOKUP 0: PASS | same |
| A5 | 0 RPCs: PASS | same |
| A6 / A7 | READ 1,000 / READ 0, GETATTR 41 | same |
| **A8w** (unscored) | LOOKUP 1,040 + GETATTR 1,000 + ACCESS 41 | same |
| A8 (10 passes) | GETATTR 10,000, LOOKUP 0: PASS | same |
| B counter miss fraction, Δ = 0.1 / 1 / 10 s | 0.007 % / 0.07 % / 0.62 % | **0.17 % / 1.74 % / 15.6 %** |
| B-1 RPCs in the 600 s window | GETATTR 410 | GETATTR 10,410 |
| B latency slow share, Δ = 0.1 / 1 / 10 s | 0.89 % / 0.97 % / 1.10 % | 1.05 % / 2.36 % / 10.5 % |
| B cells (`efs_host_plain`) | all ERROR (cross-check) | all ERROR (cross-check) |
| `ebs` B slow share (no NFS, so all noise) | 0.83–1.10 % | 0.77–0.92 % |

What these runs show about the apparatus:
1. **Every cohort A signature holds on this kernel,** with the real waits, under
   master's own `e5-run.sh`.
2. **No-delegation steady state matches P5's model.** With leases off, the counter
   fractions fall inside all three P5 bands (≤ 0.5 %, 1–3 %, 10–25 %). B-1's 10,410
   GETATTRs are 1,000 files × 600 s / 60 s `acregmax` plus 410 directory
   revalidations. This is one loopback replication of one tier, so it is not a P5
   verdict. It does show that the timer model and the counter arithmetic the grader
   uses agree on a real Linux client.
3. **Delegations stop the clock, now measured directly.** With leases on, the server
   held a delegation on every compile-opened file, and file GETATTRs dropped to about
   zero. The branch's check had inferred this. Here the server counts it.
4. **The latency cross-check cannot pass here, and may not pass on AWS** (grader
   difference 2 below).

### Grader differences from the parallel build, and their status

The parallel build's local check raised three points about grading. Master's grader
(`analysis/e5_stats.py`) was checked against each one, and the port found a fourth.
**No grading rule was changed.**

1. **The forced mount's first pass is a cold first touch.** *Already handled.*
   Amendment 1 (2026-10-16) records it as `A8w`, and the grader reads only `A8`.
   Confirmed above: A8w is LOOKUP + GETATTR, and A8 is pure GETATTR.
2. **The latency classifier disagrees with the counters under 18-way concurrency.**
   *Flagged, not fixed: fixing it is a change to the pre-registration.* Master
   classifies by per-cell k-means; the branch used a threshold taken from cohort A.
   Both fail the same way:
   - On `ebs`, which has no misses at all, k-means finds a "slow cluster" at ~25–30 µs
     holding 0.8–1.1 % of stats. That is scheduler noise, and it is a floor under every
     cell's slow share.
   - The cross-check's tolerance is max(20 %, 0.2 pp). Against that floor, a
     no-delegation cell at Δ = 0.1 s (expected ≤ 0.5 %) cannot pass. A cell at Δ = 1 s
     (1–3 %) passes only if the noise happens to be small.
   - Locally, the misses (30–110 µs) also overlap that noise, which is a loopback
     artefact. On AWS the split sits near 30–40 µs, and whether 18 processes on 2 vCPUs
     put ≥ 0.2 % of hits above it is unknown until the pilot.
   - **Risk:** P5, P6 and P9–P10 can grade ERROR on every replication with correct
     counters.
   - A remedy needs a dated amendment, recorded before the pilot is graded. Two
     candidates: grade B's miss fraction on counters alone and report the
     cross-check; or subtract the same-Δ `ebs` slow share as a measured noise floor.
   - To diagnose, the grader now reports each cell's k-means centroids and split as
     `stat_split`. It is reported only and changes no grade.
3. **A delegating server keeps attributes valid indefinitely.** *Flagged.* P5's model
   assumes no delegations. The grader cannot see delegations on AWS: the client has
   no counter for delegations it holds, and `DELEGRETURN` only counts returns.
   - EFS cannot grant delegations, so P5's EFS tiers are safe. P6 covers OpenZFS by
     design.
   - **ONTAP is the exposure.** If it grants delegations, its counter fraction falls
     to ~0 (above: 0.07 % at Δ = 1 s). P5 then grades INCONCLUSIVE, which reads as "the
     timer model is wrong" when the cause is a capability.
   - A cheap discriminator, not added because it changes the deployed run: after B,
     wait 75 s and `stat` each `ss-*` mount once. GETATTR ≈ N means no delegation;
     ≈ 0 means a delegation is held.
4. **`e5_stats.py` crashed on every real run.** *Fixed in `725266b`; not a rule
   change.* `main()` serialized `constants`, which picked up `PREDICTIONS`, a dict of
   functions, so `json.dumps` raised before `summary.json` was written. The self-test
   called `analyse()` only. It now serializes and renders as well, and still reaches
   every intended grade.

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

## Host backstop (2026-10-26)

`make e5-container` now starts a detached host watchdog before the runner. Every
replication requires its fresh lease and stack-absence preflight. Watchdog cleanup
uses per-launch tags and captured Stack ARNs/source IDs, including rollback events
and final backups. The existing collector trap remains, with token-scoped backup
selection. Direct `make e5` requires that host lease.

See [operation, recovery and limits](../../docs/e5-watchdog.md). This closes the
implementation gap noted after attempt 2; it is not live AWS teardown proof or a
new pilot approval. Pricing, remaining budget and the baseline must be reconciled
on the pilot day. Replications 2 and 3 retain their recorded second-go-ahead gate.

## Pilot-day preflight (2026-10-26)

[Read-only preflight receipt](preflight/20261026T145822Z-55d483a/README.md): clean E5 baseline
across 18 enabled regions; 12 watchdog actions allowed in IAM simulation; selected
standing subtotal unchanged at ~$0.955/hr from
`results/pricing/20261026T144948Z-71ece42/`. No new AWS experiment ran.

Readiness is **CONDITIONAL_PILOT_READY**: `Study` and `Experiment` billing tags are
inactive, so actual historical spend and remaining budget cannot be verified from
the zero tag-filtered Cost Explorer response. Planning retains the historical
$1.55 estimate and $10 ceiling; one pilot has a $2 target plus $1 reserve. These
are estimates, not an invoice balance or an automatic spending cap. Recheck the
transient baseline and credentials at launch; do not count later replications
without their recorded gate.

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

## Pilot follow-up (2026-10-27)

The [2026-10-27 offline follow-up](pilot-followup/20261027/README.md) corrects
Lustre A1 counter-name coverage and records scheduling diagnostics plus a concrete
TLS helper-interference candidate. Original pilot grading remains frozen;
TLS attribution and Lustre scheduling still block another paid run.
