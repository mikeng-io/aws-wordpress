# E2 — the device does not matter, and neither does the mount; the protocol boundary is everything

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

**Figures:** [docs/charts/e2-storage-matrix.html](../charts/e2-storage-matrix.html),
generated from the committed raw CSVs by `analysis/e2_chart.py` — a shared log-10
axis across every operation, so the two-cluster structure is a spatial fact rather
than something the reader has to assemble from a table.

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

---

# Follow-up: the mount-topology matrix

**Result:** `results/E2/20260910T182051Z-53b5423/` (3 replications, 9 arms, 108,540 ops)

The first run measured EFS only as the ECS-managed volume — `efsVolumeConfiguration`,
one mount per task, transit encryption on. That is one cell of a 2×2, and the other
three mattered for two reasons. Every EFS number published above carried the
`efs-proxy` TLS hop with nothing isolating it, and the host-mount topology is the
shared NFS client that [H1](../../hypotheses/H1-cache-locality.md)'s original
mechanism assumed — [E1](E1-mount-per-task.md) refuted *"ECS mounts per host for
you"* but never tested *"mount it yourself"*.

Both host mounts were verified on a live instance before spending replications, and
the two paths are visibly different in `/proc/mounts` rather than assumed:

```
/mnt/efs-host-tls    127.0.0.1:/ port=20559   <- local efs-proxy hop
/mnt/efs-host-plain  10.44.0.145              <- straight to the mount target
```

## Every comparison is a tie

| Comparison | `stat` | `create` |
|---|--:|--:|
| TLS vs plain — container-direct, EC2 | 1.00× | 1.00× |
| TLS vs plain — host mount, EC2 | 1.08× | 1.03× |
| TLS vs plain — container-direct, Fargate | 1.10× | 1.02× |
| container-direct vs host mount — TLS held | 1.00× | 1.01× |
| container-direct vs host mount — plain held | 1.09× | 1.02× |
| EC2 vs Fargate — direct + TLS held | 1.06× | 1.01× |

**The noise floor makes this rigorous rather than merely suggestive.** EFS's own
between-replication variance on `stat` is **1.49× to 1.82×** across independent
deployments. Every difference above is 1.00–1.10× — comfortably inside it. These
are not small effects; they are no effect.

## All six EFS configurations are one tier

| Op | 6 EFS configs | spread | 3 block-backed | gap |
|---|--:|--:|--:|--:|
| `stat` | 683–786 µs | **1.15×** | 1.2–1.9 µs | 357–630× |
| `open+read` | 792–933 µs | 1.18× | 5.1–6.0 µs | 131–182× |
| `create` | 6.97–7.16 ms | 1.03× | 19.4–22.3 µs | 313–370× |
| `unlink` | 2.89–3.03 ms | 1.05× | 7.4–11.8 µs | 244–411× |

## What this settles

**The TLS proxy is not where the time goes.** The concern that published EFS numbers
were partly measuring stunnel was reasonable and is now refuted: turning transit
encryption off changes nothing measurable. The ~700 µs is the NFS round trip itself.
Encrypt in transit; it is free at this workload's shape.

**Mount topology is not a lever.** Host-mounting EFS and bind-mounting it in performs
identically to the ECS-managed per-task mount. E1 showed ECS *will not* share a
client for you; this shows that making it share one *by hand* buys nothing for a
single task. The remaining untested claim is narrower than before — whether two
concurrent tasks sharing one host mount warm each other's attribute cache — and that
needs a bench mode that reads a tree it did not create. Recorded as the open piece;
it is no longer a gap in the topology axis, only in the sharing axis.

**Two of the three axes collapse.** Compute type and mount topology both make no
difference to EFS. What is left is the filesystem itself — which is exactly where
the remaining matrix cells are, and why they are worth the money.

## Threats to validity

- **Single task per arm.** This measures topology, not sharing. Two tasks against one
  host mount is a different question and is not answered here.
- **Same-AZ, warm mount.** Every arm mounts a One Zone filesystem in its own AZ, and
  the mount is established before the benchmark runs, so nothing here includes mount
  establishment cost.
- The block-backed caveats from the first run carry over unchanged.
