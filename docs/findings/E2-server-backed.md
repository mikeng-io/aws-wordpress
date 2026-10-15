# E2 — server-backed tiers: what `stat` measured was the NFS client's attribute cache

**Result:** `results/E2/20261015T000959Z-85382cc/`. Three independent deployments,
12 tiers, 4,020 timed operations per tier per replication, and a 4 GiB throughput
probe on 7 tiers. Statistics come from `analysis/e2_stats.py` and land in
`summary.json`/`summary.md` in the run directory. The attribute-cache analysis is
the inline script recorded in the commit that adds this file.

**Bears on:** [H1](../../hypotheses/H1-cache-locality.md),
[H3](../../hypotheses/H3-opcache-dominates.md),
[E2 predictions 1, 3, 5](../../experiments/E2-storage-matrix/README.md#predictions)

## How the run went

All 12 tiers passed all 11 single-node conformance checks in every replication, with
zero `ERROR`. Every replication ran in `ap-southeast-1a` on `c7gd.large`, with the
identical bench image (`sha256:692f4fa2…`). No FSx weekly maintenance window
overlapped a benchmark: every window fell on another weekday. Teardown was verified
independently after each replication.

Replication 3 was resumed after a collection-plumbing fix. Its `meta.json` records
the exception. A pilot replication and two failed attempts preceded this run; they
are recorded in the experiment README's attempt log and are not graded.

## Graded predictions

| Prediction | Status (mechanical) | What it rests on |
|---|---|---|
| 1. Metadata and throughput rankings differ | **NOT EVALUABLE** | Lustre's read phases started 8.0%, 17.6% and 26.4% resident, against the 1% guard, in all three replications. This was even with the host page cache dropped. |
| 3. No server-backed tier within 10× of the block group on `stat` | **REFUTED**, see the caveat below | ONTAP 1.7 µs and OpenZFS 1.8 µs, against a block-group p50 of 1.4 µs (1.3× and 1.4×) |
| 5. Instance store vs Fargate ephemeral: tie on `stat`, separate on device ops | **PARTIALLY SUPPORTED**, 1 of 4 | Same shape as the 2026-09-10 runs: they tie on `stat`, and on `create`/`open_read`, where separation was predicted |

**Prediction 1, exploratory and not a verdict.** The bound was drafted before
replications 2 and 3 were seen. A phase that started r% resident delivered at least
measured × (1 − r) from storage. At both ends of that bound, ρ reads DIFFER in every
replication: −0.357 / −0.429 / −0.357 at measured throughput, and −0.357 at the floor.
Lustre ranks first or third on throughput in every case, against sixth of seven on `stat`. The
rankings disagree however the residency is accounted for. That is suggestive, but it
is not a pass of the pre-registered test, and it inherits the `stat` caveat below.

## The finding: `stat` on an NFS tier measured file age, not the server

On every NFS tier, the fast `stat`s are a **contiguous tail of the most recently
created files**. The boundary sits at a fixed age, the same on every tier and in
every replication:

| Tier | Create pass | `stat` answered fast | Age of the oldest fast file at end of create |
|---|--:|--:|--:|
| EFS (all 3 EC2 configs, Fargate), 9 tier-replications | 6.5–7.2 s | 31–38% | 2.30–2.48 s |
| FSx OpenZFS | 3.4 s | 68–70% | 2.91–2.92 s |
| FSx ONTAP | 1.0 s | **100%** | (whole pass younger than the boundary) |
| FSx Lustre (not NFS) | 0.6–0.75 s | 0% | — |

This is the Linux NFS client's attribute cache. Attributes of a recently modified
file are trusted for about 3 s (`acregmin`), and `bench.c` `stat`s each file
seconds after creating it. A tier that creates 1,000 files in under 3 s is
`stat`-ed entirely from client memory. ONTAP sent **8** `GETATTR` RPCs for 1,000
`stat` calls. Its 1.7 µs is a cache hit, not a round trip.

So the per-tier `stat` p50 for NFS tiers is mostly a function of how fast that tier
*creates* files, which sets how many are younger than the cache window when the
`stat` pass begins. It is not the server's lookup cost. This applies to the EFS
bimodality reported by E3 and by the 2026-09-10 E2 runs as well. That was already
attributed to attribute caching, and this run shows the split is a timing
artifact of the benchmark.

**Consequence for prediction 3.** Its REFUTED grade is mechanically correct and
substantively uninformative. The tiers that refute it did so because the benchmark
read their attributes from client RAM. The comparison the prediction meant, a
server round trip against local disk, was never made for ONTAP. ONTAP produced no
cache misses to measure.

## What the run *can* say cleanly

**Cache-miss cost: the slow cluster of `stat`, a real round trip.**

| Tier | Miss cost (median) |
|---|--:|
| EFS (`efs_host_plain`) | 827 µs |
| FSx Lustre (no client attribute cache; every `stat` measured) | 149 µs |
| FSx OpenZFS | 98 µs |
| FSx ONTAP | not observed: 0 misses |

**Mutating operations: no cache can answer these.**

| Tier | `create` p50 | `unlink` p50 |
|---|--:|--:|
| EFS (EC2, host, plain) | 6.46 ms | 2.64 ms |
| FSx OpenZFS | 1.57 ms | 561 µs |
| FSx ONTAP | 982 µs | 342 µs |
| FSx Lustre | 607 µs | 309 µs |
| Block group (for scale) | 20–22 µs | 8–12 µs |

Every FSx tier separates from EFS by 4–11× on `create` and `unlink`, outside the
between-replication noise floor. The block group is still 30–300× faster than any
server-backed tier on these operations.

**Delegations.** Per-mount `mountstats` attribute every delegation to FSx OpenZFS:
`DELEGRETURN` 1,000, and 0 on every EFS mount and on ONTAP. They did not change the
`stat` pattern. OpenZFS's fast/slow boundary is at the same file age as EFS's.

**Throughput** (4-stream read, median of 3; MB/s = 10⁶ B/s):

| Tier | 4-stream read | 1-stream read | 4-stream write | Note |
|---|--:|--:|--:|---|
| FSx Lustre | 1,145 | 1,067 | 271 | read phases 8–26% resident: `ERROR` under the rule |
| FSx ONTAP | 615 | 610 | 137 | 4.8× its 128 MBps provision (server cache and burst); negotiated `rsize` 64 KiB, not the 1 MiB requested |
| EFS (`efs_host_plain`) | 552 | 595 | 431 | |
| Instance store (c7gd.large) | 169 | 159 | 77 | |
| Fargate ephemeral | 135 | 136 | 138 | |
| EBS gp3 root | 132 | 131 | 135 | at gp3's 125 MiB/s baseline |
| FSx OpenZFS | 95 | 88 | 154 | below its 128 MBps provision |

Every tier except Lustre started its read phases at 0.000% resident.

## Threats to validity

- **`stat` on NFS tiers is a cache-window measurement**, as above. It applies to
  every NFS `stat` number this study has published.
- **`open_read` on NFS tiers is also served from the client page cache.** About
  6,000 NFS `open_read` calls produced 7 READ RPCs, because each file is read
  straight after it is written. What it measures is open and close-to-open
  revalidation plus a memory read.
- **Lustre's client cache could not be emptied** by `POSIX_FADV_DONTNEED` or by
  `drop_caches=1`. Its throughput is an upper bound.
- **Server caches and burst credit are inside every server-backed throughput
  number**, by the pre-registered method.
- **One instance size, one region, one AZ.** `c7gd.large` sets the instance-store
  and network ceilings.
- **FSx is bought at its documented minimums.** Lustre and ONTAP are around 1 TiB
  for a working set of a few GB.

## What it means for the study — `HYPOTHESIS`, not a finding

E0 counted ~3,900 `stat` calls per warm WordPress request. The cost model since
E3 multiplies that count by a per-tier `stat` latency, and every NFS latency in it
came from this benchmark shape: freshly created files.

In production, PHP files are old. The Linux client then extends the attribute cache
lifetime toward `acregmax` (60 s by default). With opcache `stat`-ing a file rather
than opening it, a busy web tier may revalidate each file about once a minute,
whatever the storage. If so, steady-state `stat` cost on *every* NFS tier is mostly
a ~2 µs cache hit, and the tier matters through the miss cost (98 µs to 827 µs
here) times the miss rate.

That is untested. It would reframe H1's per-op cost factor, and it needs an
experiment that `stat`s files older than the cache window, at a production-like
request rate, before anything rests on it.
