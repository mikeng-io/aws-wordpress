# E2 — the device does not matter; the protocol boundary is everything

**Result:** `results/E2/20260910T163206Z-66dcff8/` (3 replications, 3 independent
deployments, 60,300 timed ops)
**Bears on:** [H1](../../hypotheses/H1-cache-locality.md),
[H2](../../hypotheses/H2-fargate-forbids-caching.md),
[E4](../../experiments/E4-cache-adapter/)

## The pre-registered prediction failed

E2's [prediction 5](../../experiments/E2-storage-matrix/README.md) was differential
and deliberately sharp: EC2 instance store and Fargate ephemeral should **tie** on
`stat` p50 (both answered by the kernel's dentry cache) and **separate** on the
device-touching ops, because instance store is physically attached NVMe and Fargate
ephemeral is a network-backed volume.

Graded mechanically against thresholds fixed before the run
(`analysis/e2_stats.py`, tie ≤1.5×, separation ≥3×):

| Op | Expected | Observed | Ratio |
|---|---|---|--:|
| `stat` | TIE | TIE | 1.43× |
| `create` | SEPARATED | **TIE** | 1.11× |
| `unlink` | SEPARATED | **INCONCLUSIVE** | 1.52× |
| `open_read` | SEPARATED | **TIE** | 1.10× |

The script reports `PARTIALLY SUPPORTED — 1/4`, which is too kind and only avoids
the "uniform result" refutation clause because `unlink` landed at 1.52× against a
1.5× threshold. **Read it as refuted.** Three of four ops tied outright and the
fourth missed by two hundredths. The one check that passed did not pass for the
reason predicted — it is part of a uniform tie, not evidence of a mechanism that
distinguishes the two tiers.

## What the data actually says

Pooled across 3 replications (p50):

| Tier | stat | stat ENOENT | open+read | create | unlink |
|---|--:|--:|--:|--:|--:|
| `ec2/instance_store` | **1.3 µs** | 2.9 µs | 5.2 µs | 19.7 µs | 7.5 µs |
| `ec2/ebs` | **1.3 µs** | 3.3 µs | 5.3 µs | 19.9 µs | 7.6 µs |
| `fargate/ephemeral` | **1.8 µs** | 4.0 µs | 5.7 µs | 21.9 µs | 11.4 µs |
| `ec2/efs` | 814.3 µs | 1.07 ms | 903.6 µs | 7.34 ms | 3.00 ms |
| `fargate/efs` | 777.7 µs | 858.1 µs | 679.3 µs | 6.99 ms | 2.93 ms |

**EBS and instance store are the same tier, empirically.** Every op, including the
tails:

| Op | instance store | EBS | ratio |
|---|--:|--:|--:|
| `stat` | 1276 ns | 1274 ns | **1.00×** |
| `open_read` | 5203 ns | 5337 ns | 1.03× |
| `create` | 19673 ns | 19937 ns | 1.01× |
| `unlink` | 7518 ns | 7633 ns | 1.02× |

118 GB of physically attached NVMe, rated 33,542 read IOPS, delivers **nothing
measurable** over a network-attached EBS gp3 root volume for this workload. Their
p99s track too (`stat` 1.8 µs both; `unlink` 131 µs vs 142 µs — and that shared
17–19× unlink tail is an XFS journal artifact both inherit, not a device property).

## The boundary that does exist

| Op | block-backed → EFS |
|---|--:|
| `stat` | **638×** |
| `unlink` | 399× |
| `create` | 373× |
| `open+read` | 174× |

The line is not fast-disk vs slow-disk. It is **whether the kernel owns the
filesystem or a server does.** Everything on one side of that line is within 1.5×
of everything else on that side; the other side is two to three orders of magnitude
away.

The asymmetry the study has argued since E0 holds and is now measured on a third
independent apparatus: metadata (`stat`, 638×) is far worse than bulk movement
(`open+read`, 174×). EFS is much less bad at moving bytes than at answering
questions about files.

## E3's bimodality replicates

E3 found EFS `stat` to be bimodal — a fast population of NFS attribute-cache hits
that never reach the wire, and a slow population that does. That was one experiment
on one task. It reproduces here on independent hardware, on **both** arms
(`analysis/e3_clusters.py`, 1-D k-means on log10, same gates):

| Tier | fast share | fast median | slow median | separation |
|---|--:|--:|--:|--:|
| `ec2/efs` `stat` | 28.6% | 1.8 µs | 1.02 ms | **555×** |
| `fargate/efs` `stat` | 30.7% | 1.6 µs | 861 µs | **537×** |

E3 measured 24.4% at 2.6 µs with 415× separation. Same structure, same order of
magnitude, different day and different hardware — this is a replication, not a
restatement.

The fast cluster's median (1.6–1.8 µs) is indistinguishable from the block-backed
tiers' `stat` p50 (1.3–1.8 µs), which is the giveaway: those calls never left the
kernel. Every block-backed tier tested unimodal, as did EFS `open_read`.

## Between-replication agreement

Block-backed tiers are essentially deterministic across independent deployments
(`stat` medians 1.00–1.03× spread). EFS varies 1.20–1.47×, which is what a network
filesystem should look like. The effects reported here are 100–600×; the variance
is not in contention.

## What this changes

**H1 is strengthened in its reframed form.** "Which storage tier is reachable"
determines performance, and the tier boundary is a protocol boundary, not a hardware
one. Placement was already refuted by E1; the device is now refuted too.

**H2's cost argument collapses in Fargate's favour.** The [cost
table](../../experiments/E2-storage-matrix/README.md) prices instance store at a
+27% instance premium. It buys nothing here. Fargate ephemeral is 1.4× slower on
`stat` than instance store in absolute terms — 1.8 µs against 1.3 µs — which is
noise beside a 638× tier gap.

**E4's substrate question is answered before E4 is built.** The cache adapter does
not need instance store, and does not need a `d`-class instance. It needs *any*
block device with a local filesystem on it — which every compute platform already
has, Fargate included. The two-substrate table in E4's README should be read as
one substrate with two price tags.

## Threats to validity

- **The working set fits in page cache.** 20 dirs × 50 files at 2–50 KB is ~50 MB
  against 4 GiB of RAM, so this measures warm-cache behaviour. That is the right
  shape for the WordPress code path E0 measured — the same files, read repeatedly —
  but it is *not* a claim that instance store and EBS are interchangeable for a
  working set exceeding RAM, or for sustained write floods where EBS gp3's 3,000
  baseline IOPS would bind and NVMe would not. The equivalence is claimed for this
  workload shape, not in general.
- **Single instance type.** `c7gd.large` only. Larger instances get more EBS
  throughput and more instance-store IOPS; whether they diverge is untested.
- **Single region and AZ**, `ap-southeast-1a`. EFS numbers are same-AZ.
- **The FSx and FUSE tiers are not in this dataset.** They are costed and specced
  but unbuilt, so nothing here speaks to them.

## Apparatus notes

The entrypoint refuses to run unless every named mount has a distinct `st_dev` and
none shares one with `/`. This is not decoration: a bind mount that silently fails
leaves an ordinary directory on the root volume, and the benchmark would have
reported the root volume's latency under another tier's name. Given that EBS and
instance store turn out to be indistinguishable, a failed instance-store mount would
have produced *exactly the numbers reported here* and been undetectable in the data.
The host was independently confirmed via SSM: `nvme1n1`, 109.9 G, XFS at
`/mnt/instance-store`, separate device from the 30 G EBS root.

Two collection bugs were found and fixed before this dataset:
stdout transport silently truncated the third tier (12,060 log lines against
GetLogEvents' 10,000 cap, task still exiting 0), and progress logging on stdout
corrupted the task-id capture. Both would have produced plausible wrong output
rather than an error. Results now go to S3 with a per-arm manifest the collector
verifies. One self-inflicted failure is worth recording too: editing `collect.sh`
while it was running corrupted the final line of the third replication, because bash
reads scripts incrementally by byte offset. The data was already collected and the
stack already destroyed; the run is complete and valid.
