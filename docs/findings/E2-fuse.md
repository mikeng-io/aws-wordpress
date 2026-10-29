# E2 — FUSE arms: JuiceFS misses the 10× bar, Mountpoint fails POSIX

**Result:** [`results/E2/20261029T070456Z-a2041d6/`](../../results/E2/20261029T070456Z-a2041d6/).
Three replications, one fresh `c7gd.large` deployment each, `ap-southeast-1a`,
image `sha256:6f6202b559e90128c3d1df5fe6d469865757d978e23f5602e7fe54bfcb2b3051`,
apparatus commit `ab9f3ba`. Every tier ran 4,020 timed operations per replication;
Mountpoint was conformance-only (see below). Statistics and the P2/P4 grades live
in the run's `summary.json` / `summary.md`, produced by `analysis/e2_stats.py`.

**Bears on:** [P2 and P4](../../experiments/E2-storage-matrix/fuse-arms.md),
[H2](../../hypotheses/H2-fargate-isolation.md), and the E4 gate.

## Graded predictions

Both rules were fixed in [`fuse-arms.md`](../../experiments/E2-storage-matrix/fuse-arms.md)
before the first mount.

| Prediction | Status | What it rests on |
|---|---|---|
| 2. JuiceFS `stat` ≤ 0.10× EFS **and** ≥ 3× local | **INCONCLUSIVE** | Pooled JuiceFS/EFS = **0.133×** (7.5× faster), local separation 76.5×. The direction held; the wide-margin half did not. |
| 4. Mountpoint for S3 fails single-node POSIX conformance | **SUPPORTED** | **8 of 11** checks fail in every replication, 0 `ERROR`: rename, in-place write, append, truncate, hardlink, symlink, directory rename, `mtime` advance. |

The formal sample is three independent deployments. The one-rep smoke
(`20261029T064046Z-0bcacd1`) was apparatus validation and is not part of the grade.

### P2, per replication

| Rep | JuiceFS `stat` p50 | EFS `stat` p50 | ratio | JuiceFS/local |
|---|--:|--:|--:|--:|
| 1 | 110.0 µs | 879.6 µs | 0.125 | 80.8× |
| 2 | 98.0 µs | 755.1 µs | 0.130 | 71.3× |
| 3 | 101.1 µs | 781.3 µs | 0.129 | 75.3× |
| **pooled** | **104.6 µs** | **785.6 µs** | **0.133** | **76.5×** |

JuiceFS's metadata engine is genuinely faster than an EFS metadata round trip, but
not by the 10× the prediction required. The second half of P2 did hold: JuiceFS is
still 76× slower than the local block tier on `stat`, and 1,450× slower on `create`.

## The P2 comparison is a cache-mode comparison, and should not be read as support

The registered estimator is a pooled `stat` p50. On EFS that p50 is not a stable
property of EFS: it is a mixture of two client-side modes, exactly the bimodality
the [server-backed finding](E2-server-backed.md) already documented.

| Tier | `stat` p25 | p50 | fast share (<10 µs) | fast median | slow median |
|---|--:|--:|--:|--:|--:|
| JuiceFS | 84.3 µs | 104.6 µs | 0.0% | — | — |
| SeaweedFS | 18.7 µs | 20.2 µs | 0.0% | — | — |
| EFS (`efs_host_plain`) | 1.9 µs | 785.6 µs | 31.8% | 1.8 µs | 839.3 µs |
| instance store | 1.3 µs | 1.4 µs | 99.9% | — | — |

So JuiceFS is 7.5× faster than EFS **when the EFS p50 lands in the cache-miss
mode**, and roughly 58× *slower* than EFS when the comparison lands in the
attribute-cache-hit mode. The registered p50 happened to fall on the slow side in
all three replications; that is why the prediction's first half almost passed, not
because JuiceFS beat EFS's fast path.

This does not change the mechanical grade — `INCONCLUSIVE` is what the fixed rule
returns at 0.133×. It changes what the study can claim: **the experiment did not
isolate the metadata mechanism it meant to test.** A v2 would compare cache-miss to
cache-miss and cache-hit to cache-hit, or force a cold attribute cache before the
`stat` pass, and would have to say so before running.

SeaweedFS, a second design point rather than a second P2 chance, put `stat` at
**20.2 µs** (39× faster than the EFS p50, 14.8× slower than local, 5.2× faster than
JuiceFS) and passed all 11 conformance checks. Its `create` was 2.28 ms against
JuiceFS's 29.2 ms: JuiceFS's `create` is dominated by writing the file body to S3,
not by its metadata engine. Neither FUSE tier is a substitute for local storage on
mutating operations.

## P4: the object-store mount is not a transparent filesystem

Mountpoint for S3 failed the same eight checks in all three replications:

| Check | Result | What it means for a WordPress tree |
|---|---|---|
| `rename` | FAIL — `mv` did not replace | Plugin/theme updates and atomic file replacement are unsafe. |
| `in_place_write` | FAIL | No write at an offset; config and log edits fail. |
| `append` | FAIL | No append; logs and some plugin writes fail. |
| `truncate` | FAIL | Cannot truncate in place. |
| `hardlink` | FAIL | Hardlink-dependent layouts fail. |
| `symlink` | FAIL | Symlinks are not represented. |
| `dir_rename` | FAIL | Atomic directory replacement fails. |
| `mtime_advances` | FAIL | Opcache stat-and-compare-mtime cannot see a write. |
| `fsync` | PASS | — |
| `flock_excludes` | PASS | — |
| `root_not_squashed` | PASS | — |

The `unlink` path also aborts `bench`'s create/unlink loop, so Mountpoint has no
latency CSV: the marker `skipped,0` is deliberate, and the tier is excluded from
the throughput set. A semantic failure should not be converted into a task failure
and should not be averaged into a latency table.

This is the strongest result of the FUSE campaign. The tier is not merely slower;
it cannot host the application's write path. That is a correctness boundary, not a
tuning problem, and it is the outcome P4 was written to detect.

## What this does and does not settle

- **P4 is settled for this study's use of Mountpoint**: it is unusable as a
  transparent WordPress filesystem. Object-store FUSE remains an option only for
  read-only content with a different write path, which is outside the governing
  constraint.
- **P2 is not settled in the direction of support.** JuiceFS's metadata path is
  ~100 µs, better than an EFS cache miss and worse than an EFS cache hit; the
  registered 10× bar missed. The result is a negative/near-miss on the "metadata
  engine changes the tier" claim, with a measurement caveat attached.
- **E4 is not answered by this run.** All three FUSE tiers require `CAP_SYS_ADMIN`, so
  neither is reachable from Fargate. The E4 gate asked whether a FUSE tier makes a
  bespoke cache unnecessary; the answer for the Fargate branch is no, because the
  platform cannot mount them. E4 still needs a Fargate-reachable cache, or a
  decision that H2's amortisation argument is the real constraint.

## Provenance caveat

All three `meta.json` files record `git_dirty: true`. At run start the tree was
clean; the dirty path was the regenerated summary of the earlier one-rep smoke
(`results/E2/20261029T064046Z-0bcacd1/summary.*`), not a measurement or collection
file. The image digest is identical in all three replications and the apparatus
commit is `ab9f3ba`; no file under `infra/` or `experiments/E2-storage-matrix/scripts/`
differed from that commit. This is a collector-scope bug (it should ignore
`results/` and `docs/` when deciding dirtiness), recorded rather than hidden; the
collector is being narrowed for future runs.

Cost: the three deployments stood for roughly 57 minutes of `c7gd.large` plus
interface endpoints and benchmark I/O, about **US$0.30** at the run's pricing
snapshot, well inside the approved **US$12** FUSE ceiling. No FSx was created and
no NAT gateway was used.

## Reproduce

```sh
REPS=3 make e2-fuse
python3 analysis/e2_stats.py results/E2/20261029T070456Z-a2041d6
```

The FUSE host setup is `infra/lib/stacks/e2-fuse-setup.sh`; the unprivileged
benchmark entrypoint is `infra/lib/stacks/bench/entrypoint.sh`. Mountpoint's
conformance-only marker is set by the stack's `BENCH_CONFORMANCE_ONLY`.
