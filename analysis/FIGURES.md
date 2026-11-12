# The `aws-fs.summary` figure dataset

`analysis/export_figures.py` exports a JSON dataset (`aws-fs.summary.json` +
`index.json`) of every number a site article may draw as a figure. Each entry is
a named **selector**: a `value` already rounded for display, a declared `unit`,
a `definition`, and a `raw` block recording the committed artifact (path, JSON
pointer, exact leaf values, source unit) the number came from. The site renderer
does no arithmetic — every derived number and every display rounding is decided
here, once.

## Regenerate

```sh
python3 analysis/export_figures.py            # writes analysis/out/
python3 analysis/export_figures.py --out DIR  # writes DIR/
```

Before the cache-window selectors can export, the derived input must exist:

```sh
python3 analysis/e2_cache_window.py           # writes analysis/derived/
```

Everything runs offline against committed artifacts. Output is deterministic:
two runs (with or without `SOURCE_DATE_EPOCH`) produce byte-identical files —
`produced_at` is the only wall-clock field and honours `SOURCE_DATE_EPOCH`.
Validation is fail-closed: any missing or invalid input aborts the whole export
with a nonzero exit and leaves existing outputs untouched.

## Pinned runs

| Constant | Run | Role |
|---|---|---|
| `E0` | `results/E0/20260902T105746Z-f62a686` | reference |
| `E2` | `results/E2/20260910T163206Z-66dcff8` | reference |
| `E2_FSX` | `results/E2/20261015T000959Z-85382cc` | reference |
| `E4` | `results/E4/20261029T091909Z-842d596` | reference |
| `E5` | `results/E5-formal/20261028T160106Z-dd5fce0` | formal-v3 |

`E5_REPS` (the three eligible formal-v3 replications, chronological):
`20261028T103017Z-342d6b4/rep-1`, `20261028T125412Z-f6659e0/rep-1`,
`20261028T160106Z-dd5fce0/rep-1`. Run eligibility is checked against
`docs/study-runs.json`; only `reference` and `formal-v3` roles may appear in the
dataset.

## Precision and unit rules

- **latencies** (`transform="latency"`): `e2_chart.fmt` — ns → `%.1f µs` (unit
  `us`), `%.2f ms`, or bare ns. Mixed-unit arrays are rejected.
- **ratios and shares** (`present()`): below 1 → 4 significant figures; 1–10 →
  two decimals; ≥10 → one decimal. The exact quotient is recoverable from `raw`.
- **percent** (`transform="percent"`): recorded fraction × 100 via exact decimal
  conversion, then `present()`.
- **four significant figures** (`sig4`): the rule for every ladder element
  (`us_4sf`, ns/1000 then 4 s.f.) and for seconds trimmed from artifact
  precision (`sig4`). The exact ns / full-precision value stays in `raw.value`.
- **counts, bytes, exact ratios** (`identity`, `identity_exact`): artifact
  precision, no rounding.
- **derived ratios** (`divide`, `divide_pairs`): quotient of two recorded leaves
  in ns before any rounding, then `present()`. The artifact carries no ratio
  field; `derived: true` marks every computed value.
- **`uniform`**: several leaves required to be identical, emitted once
  (`e4.hydration.bytes`); disagreement fails the export.
- **`null`**: a metric that is undefined under the study's method exports `null`
  per element with `defined: false` and an `undefined_reason` — see the
  cache-window note below. A renderer must not plot nulls as zero.

## series_axis vocabulary

| Axis | Meaning |
|---|---|
| `replication` | Array elements are independent replications in chronological order (E5: the three pinned formal-v3 runs; E2 FSx: rep-1..3; E4: per_replication[0..2]). |
| `cadence` | Elements are interval/cadence variants of one measurement. |
| `percentile` | Elements are an ordered percentile ladder in one declared unit, so ladders can share an axis. `series_labels` names the elements. Orders: request ladders `[median, mean (amortised), p99, max]`; stat ladders `[p50, p95, p99]`. |

## Selectors

| Selector | Unit | Dimension | series_axis | Source (path + JSON pointer) | Derived |
|---|---|---|---|---|---|
| `e0.warm.enoent` | count | metadata | — | `results/E0/20260902T105746Z-f62a686/rep-1/max/home.warm.census.json` `/errno/ENOENT` | no |
| `e0.warm.stat` | count | metadata | — | `results/E0/20260902T105746Z-f62a686/aggregate.json` `/max~1home~1warm/stat_median` | no |
| `e0.warm.syscalls` | count | metadata | — | `results/E0/20260902T105746Z-f62a686/aggregate.json` `/max~1home~1warm/total_file_syscalls/median` | no |
| `e2.block.stat.p50` | us | metadata | — | `results/E2/20260910T163206Z-66dcff8/summary.json` `/tiers/ec2~1instance_store/stat/p50_ns` | no |
| `e2.cache_window.efs.boundary_age_s` | s | metadata | replication | `analysis/derived/e2-cache-window-20261015T000959Z-85382cc.json` `/tiers/efs/replications` | yes |
| `e2.cache_window.efs.create_pass_s` | s | metadata | replication | `analysis/derived/e2-cache-window-20261015T000959Z-85382cc.json` `/tiers/efs/replications` | yes |
| `e2.cache_window.efs.fast_stat_share` | percent | metadata | replication | `analysis/derived/e2-cache-window-20261015T000959Z-85382cc.json` `/tiers/efs/replications` | yes |
| `e2.cache_window.fsx_lustre.boundary_age_s` | s | metadata | replication | `analysis/derived/e2-cache-window-20261015T000959Z-85382cc.json` `/tiers/fsx_lustre/replications` | yes |
| `e2.cache_window.fsx_lustre.create_pass_s` | s | metadata | replication | `analysis/derived/e2-cache-window-20261015T000959Z-85382cc.json` `/tiers/fsx_lustre/replications` | yes |
| `e2.cache_window.fsx_lustre.fast_stat_share` | percent | metadata | replication | `analysis/derived/e2-cache-window-20261015T000959Z-85382cc.json` `/tiers/fsx_lustre/replications` | yes |
| `e2.cache_window.fsx_ontap.boundary_age_s` | s | metadata | replication | `analysis/derived/e2-cache-window-20261015T000959Z-85382cc.json` `/tiers/fsx_ontap/replications` | yes |
| `e2.cache_window.fsx_ontap.create_pass_s` | s | metadata | replication | `analysis/derived/e2-cache-window-20261015T000959Z-85382cc.json` `/tiers/fsx_ontap/replications` | yes |
| `e2.cache_window.fsx_ontap.fast_stat_share` | percent | metadata | replication | `analysis/derived/e2-cache-window-20261015T000959Z-85382cc.json` `/tiers/fsx_ontap/replications` | yes |
| `e2.cache_window.fsx_openzfs.boundary_age_s` | s | metadata | replication | `analysis/derived/e2-cache-window-20261015T000959Z-85382cc.json` `/tiers/fsx_openzfs/replications` | yes |
| `e2.cache_window.fsx_openzfs.create_pass_s` | s | metadata | replication | `analysis/derived/e2-cache-window-20261015T000959Z-85382cc.json` `/tiers/fsx_openzfs/replications` | yes |
| `e2.cache_window.fsx_openzfs.fast_stat_share` | percent | metadata | replication | `analysis/derived/e2-cache-window-20261015T000959Z-85382cc.json` `/tiers/fsx_openzfs/replications` | yes |
| `e2.efs.stat.p50` | us | metadata | — | `results/E2/20260910T163206Z-66dcff8/summary.json` `/tiers/ec2~1efs/stat/p50_ns` | no |
| `e2.efs_over_block.open_read` | ratio | bytes | — | `results/E2/20260910T163206Z-66dcff8/summary.json` `/tiers` | yes |
| `e2.efs_over_block.stat` | ratio | metadata | — | `results/E2/20260910T163206Z-66dcff8/summary.json` `/tiers` | yes |
| `e4.efs.stat.ladder` | us | metadata | percentile | `results/E4/20261029T091909Z-842d596/summary.json` `/pooled/efs/stat` | no |
| `e4.hydrated.stat.ladder` | us | metadata | percentile | `results/E4/20261029T091909Z-842d596/summary.json` `/pooled/hydrated/stat` | no |
| `e4.hydrated.stat.p50` | us | metadata | — | `results/E4/20261029T091909Z-842d596/summary.json` `/pooled/hydrated/stat/p50_ns` | no |
| `e4.hydration.bytes` | bytes | bytes | — | `results/E4/20261029T091909Z-842d596/summary.json` `/per_replication` | no |
| `e4.hydration.seconds` | s | bytes | replication | `results/E4/20261029T091909Z-842d596/summary.json` `/per_replication` | no |
| `e5.ebs.request.ladder@1` | us | metadata | percentile | `results/E5-formal/20261028T160106Z-dd5fce0/analysis-pooled-3.json` `/predictions/9/per_replication/20261028T103017Z-342d6b4~1rep-1` | no |
| `e5.ebs.request.ladder@2` | us | metadata | percentile | `results/E5-formal/20261028T160106Z-dd5fce0/analysis-pooled-3.json` `/predictions/9/per_replication/20261028T125412Z-f6659e0~1rep-1` | no |
| `e5.ebs.request.ladder@3` | us | metadata | percentile | `results/E5-formal/20261028T160106Z-dd5fce0/analysis-pooled-3.json` `/predictions/9/per_replication/20261028T160106Z-dd5fce0~1rep-1` | no |
| `e5.ebs.request.median` | ms | metadata | replication | `results/E5-formal/20261028T160106Z-dd5fce0/analysis-pooled-3.json` `/predictions/9/per_replication` | no |
| `e5.efs.request.ladder@1` | us | metadata | percentile | `results/E5-formal/20261028T160106Z-dd5fce0/analysis-pooled-3.json` `/predictions/9/per_replication/20261028T103017Z-342d6b4~1rep-1` | no |
| `e5.efs.request.ladder@2` | us | metadata | percentile | `results/E5-formal/20261028T160106Z-dd5fce0/analysis-pooled-3.json` `/predictions/9/per_replication/20261028T125412Z-f6659e0~1rep-1` | no |
| `e5.efs.request.ladder@3` | us | metadata | percentile | `results/E5-formal/20261028T160106Z-dd5fce0/analysis-pooled-3.json` `/predictions/9/per_replication/20261028T160106Z-dd5fce0~1rep-1` | no |
| `e5.efs.request.median` | ms | metadata | replication | `results/E5-formal/20261028T160106Z-dd5fce0/analysis-pooled-3.json` `/predictions/9/per_replication` | no |
| `e5.efs.request.p99` | ms | metadata | replication | `results/E5-formal/20261028T160106Z-dd5fce0/analysis-pooled-3.json` `/predictions/9/per_replication` | no |
| `e5.efs_over_ebs.amortised` | ratio | metadata | replication | `results/E5-formal/20261028T160106Z-dd5fce0/analysis-pooled-3.json` `/predictions/9/per_replication` | no |
| `e5.efs_over_ebs.median` | ratio | metadata | replication | `results/E5-formal/20261028T160106Z-dd5fce0/analysis-pooled-3.json` `/predictions/9/per_replication` | yes |
| `e5.efs_over_ebs.p99` | ratio | metadata | replication | `results/E5-formal/20261028T160106Z-dd5fce0/analysis-pooled-3.json` `/predictions/9/per_replication` | yes |
| `e5.lustre.slow_share@0.1` | percent | metadata | replication | `results/E5-formal/20261028T160106Z-dd5fce0/analysis-pooled-3.json` `/predictions/7/per_replication` | no |
| `e5.lustre.slow_share@1` | percent | metadata | replication | `results/E5-formal/20261028T160106Z-dd5fce0/analysis-pooled-3.json` `/predictions/7/per_replication` | no |
| `e5.lustre.slow_share@10` | percent | metadata | replication | `results/E5-formal/20261028T160106Z-dd5fce0/analysis-pooled-3.json` `/predictions/7/per_replication` | no |
| `e5.rpc_per_stat.plain@0.1` | ratio | metadata | replication | `results/E5-formal/20261028T160106Z-dd5fce0/analysis-pooled-3.json` `/predictions/5/per_replication` | no |
| `e5.rpc_per_stat.plain@1` | ratio | metadata | replication | `results/E5-formal/20261028T160106Z-dd5fce0/analysis-pooled-3.json` `/predictions/5/per_replication` | no |
| `e5.rpc_per_stat.plain@10` | ratio | metadata | replication | `results/E5-formal/20261028T160106Z-dd5fce0/analysis-pooled-3.json` `/predictions/5/per_replication` | no |
| `e5.rpc_per_stat.tls@0.1` | ratio | metadata | replication | `results/E5-formal/20261028T160106Z-dd5fce0/analysis-pooled-3.json` `/predictions/5/per_replication` | no |
| `e5.rpc_per_stat.tls@1` | ratio | metadata | replication | `results/E5-formal/20261028T160106Z-dd5fce0/analysis-pooled-3.json` `/predictions/5/per_replication` | no |
| `e5.rpc_per_stat.tls@10` | ratio | metadata | replication | `results/E5-formal/20261028T160106Z-dd5fce0/analysis-pooled-3.json` `/predictions/5/per_replication` | no |

## The cache-window derived file

`analysis/e2_cache_window.py` re-derives the E2 server-backed finding's
cache-window numbers (create-pass duration, fast-stat share, boundary age) from
the raw per-file CSVs — the finding states them as prose and no script for them
was ever committed.

The exported classification is **"answered in client memory": stat latency <
20 µs** (`CACHE_HIT_NS` in the script). It is **descriptive and post-hoc** —
declared after inspecting this run's 12,000 stat samples, not pre-registered —
and the derived file records `post_hoc: true` with the reason. It is not a
tuned value: only 4 samples lie between 10 and 60 µs (10,911 / 12,628 /
12,852 / 33,133 ns — three ONTAP rows still under 15 µs, one OpenZFS outlier
over 30 µs), so every absolute threshold in the **15–30 µs** sensitivity range
produces identical shares. 20 µs is the round midpoint of that empty gap.
Each rep record carries the recomputed shares at 15/20/25/30 µs and its count
of samples in the 10–60 µs band (`sensitivity`); the whole-run count (4) is
the document's `samples_between_10_and_60us`.

The repo's **registered** rule — `e3_clusters.kmeans2_log` with the E3 gates
(centroid separation ≥ 0.5 log10 and each cluster ≥ 2%) — is kept verbatim
per rep under `registered_rule` as diagnostics, with its gate verdict
(`bimodal`), the un-gated noise split (`ungated_lower_cluster_share`), and
its own fast/boundary fields. **The two rules disagree and both are kept:**
the registered rule's gates fail on ONTAP and Lustre (unimodal stat
populations), leaving them undefined, while the absolute rule reports ONTAP
100% and Lustre 0% — matching the finding's prose table. On EFS and OpenZFS
the two classifications happen to agree exactly.

`boundary_age_s` is the create time strictly after the oldest locally answered
file's index — its age when the create pass ended. **Lustre answered nothing
locally**, so its `oldest_local_index`, `boundary_age_s` and `slow_in_tail`
are `null` with a recorded `undefined_reason` — the only truly undefined
export. ONTAP's boundary is defined and is essentially the whole create pass
(every stat answered locally from index 0). `answered_local_share` itself is
always defined, including 0.0 for Lustre. See
`docs/findings/E2-server-backed.md`.

The exporter verifies the derived file's `inputs` manifest — a sha256 per raw
CSV — before reading any value; a stale derived file or a changed artifact fails
the export.

## Known limits

- **Three replications** in every series; a point estimate per deployment, not a
  distribution. No confidence intervals are exported.
- **`boundary_age_s` is an age proxy**, built from summed create latencies in
  file order — the create timestamps themselves are not recorded. Per-rep
  `slow_in_tail` counts violations of the contiguous-tail structure (currently
  one: OpenZFS rep-1).
- **The cache-window rule is post-hoc.** The 20 µs threshold was chosen after
  looking at the data; it is safe only because the 10–60 µs band is empty in
  this run. Re-running against a different run could put samples inside the
  band and make the threshold matter — the per-rep `sensitivity` shares are
  there to show exactly that.
- **Lustre's boundary is null** — no stat was answered locally, so there is
  no oldest-local file. `fast_stat_share` for Lustre is a defined 0%, not a
  null.
- **EFS cache-window is one arm** (`ec2/efs_host_plain`), chosen as the same
  client path as the FSx mounts; the prose range covers nine EFS
  tier-replications.
- **Rounding is for display.** Anything needing more precision must read
  `raw.value`, which is unrounded and resolves to the artifact.

## What the dataset deliberately does not contain

- **Statistics the study did not commit.** No means beyond what the artifacts
  carry, no recomputed percentiles, no fitted parameters.
- **Confidence intervals and hypothesis grades.** Gradings live in the run
  summaries; the dataset exports measurements, not verdicts.
- **The un-gated cluster split.** A k-means split on a unimodal population is
  noise; it appears only as diagnostic `ungated_lower_cluster_share` inside
  the derived file's `registered_rule` blocks, never as a selector value.
  The registered rule's gated fast share is not exported either — where it is
  defined (EFS, OpenZFS) it agrees with the absolute rule, and where it is
  not (ONTAP, Lustre) the exported rule already covers it.
- **Every tier.** Cache-window selectors cover `efs` (= `ec2/efs_host_plain`)
  and the three FSx tiers only — the four tiers the finding's table states.
- **Prose-only numbers.** Values that cannot be traced to a committed artifact
  are absent rather than transcribed.
