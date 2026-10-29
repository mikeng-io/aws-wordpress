# Evidence index

Observation set: 2026-10-29. 34 experimental run directories.

A run directory is not automatically a completed campaign or independent replication.
This index classifies frozen evidence; it does not pool unlike methods or regrade failures.
See [study closeout](study-status.md) for current claims, limits and deferred work.

## Reference collections

| Question | Evidence | What is eligible |
|---|---|---|
| E0 count demand | [corrected census](../results/E0/20260902T105746Z-f62a686/) | n=10, aged n=3; counts only |
| E1 mount topology | [host inspection](../results/E1/20260902T060000Z-24d9bb9/) | one direct inspection, not a latency replication |
| E2 block/mount matrix | [block](../results/E2/20260910T163206Z-66dcff8/), [mount](../results/E2/20260910T182051Z-53b5423/) | three deployments each; campaign-specific grades |
| E2 FSx | [formal collection](../results/E2/20261015T000959Z-85382cc/) | three deployments; P1 NOT EVALUABLE; recorded resume exception |
| E2 FUSE | [formal collection](../results/E2/20261029T070456Z-a2041d6/) | three deployments; P2 INCONCLUSIVE, P4 SUPPORTED; dirty-provenance note |
| E3 local substrate | [Fargate collection](../results/E3/20260910T113000Z-6016f58/) | three independent tasks |
| E4 read-only hydration | [formal collection](../results/E4/20261029T091909Z-842d596/) | three clean independent deployments; smoke/failed campaigns excluded |
| E5 old-file/repeat cost | [run 1](../results/E5-formal/20261028T103017Z-342d6b4/), [run 2](../results/E5-formal/20261028T125412Z-f6659e0/), [run 3](../results/E5-formal/20261028T160106Z-dd5fce0/) | three eligible formal-v3 deployments only |

## Every retained run

| Group / run | Role | Rep directories | Metadata files | Recorded interpretation |
|---|---|--:|--:|---|
| [E0/20260826T105956Z-c16d429](../results/E0/20260826T105956Z-c16d429/) | superseded | 0 | 1 | First census; interpretation superseded by aged cohorts and later cart correction. |
| [E0/20260827T185901Z-bff2d22](../results/E0/20260827T185901Z-bff2d22/) | historical-baseline | 10 | 1 | n=10 (aged n=3); count baseline. Cart/checkout were empty and are superseded for those endpoints. |
| [E0/20260902T091846Z-158f9cd](../results/E0/20260902T091846Z-158f9cd/) | spot-check | 1 | 1 | n=1 populated-cart apparatus check; excluded from final n=10 aggregate. |
| [E0/20260902T105746Z-f62a686](../results/E0/20260902T105746Z-f62a686/) | reference | 10 | 1 | Corrected catalog/cart n=10 census (aged n=3); counts, not latency. |
| [E1/20260902T060000Z-24d9bb9](../results/E1/20260902T060000Z-24d9bb9/) | reference | 0 | 1 | One direct host inspection: two tasks, two NFS mounts and two TLS proxies. |
| [E2/20260910T163206Z-66dcff8](../results/E2/20260910T163206Z-66dcff8/) | reference | 3 | 3 | Three deployments, block group. Mechanical P5 PARTIALLY SUPPORTED (1/4), not predicted device separation. |
| [E2/20260910T182051Z-53b5423](../results/E2/20260910T182051Z-53b5423/) | reference | 3 | 3 | Three deployments, EFS mount/TLS matrix; mechanical P5 PARTIALLY SUPPORTED. |
| [E2/20261014T193521Z-7551243](../results/E2/20261014T193521Z-7551243/) | failed | 1 | 0 | Failed FSx mount check; no meta.json; no grade. |
| [E2/20261014T202700Z-47e2c95](../results/E2/20261014T202700Z-47e2c95/) | pilot | 1 | 1 | FSx pilot; residency/delegation attribution gaps; not a graded result. |
| [E2/20261015T000959Z-85382cc](../results/E2/20261015T000959Z-85382cc/) | reference | 3 | 3 | Three FSx deployments. P1 NOT EVALUABLE; P3 mechanically REFUTED with cache confound; P5 PARTIALLY SUPPORTED. |
| [E2/20261029T054218Z-df8928b](../results/E2/20261029T054218Z-df8928b/) | failed | 1 | 0 | FUSE apparatus iteration; no meta; excluded. |
| [E2/20261029T055727Z-f3b9485](../results/E2/20261029T055727Z-f3b9485/) | failed | 1 | 0 | FUSE apparatus iteration; no meta; excluded. |
| [E2/20261029T062951Z-9877550](../results/E2/20261029T062951Z-9877550/) | failed | 1 | 0 | FUSE apparatus iteration; no meta; excluded. |
| [E2/20261029T063514Z-965f894](../results/E2/20261029T063514Z-965f894/) | failed | 1 | 0 | FUSE apparatus iteration; no meta; excluded. |
| [E2/20261029T064046Z-0bcacd1](../results/E2/20261029T064046Z-0bcacd1/) | smoke | 1 | 1 | One-rep FUSE apparatus smoke; excluded from formal pool. |
| [E2/20261029T070456Z-a2041d6](../results/E2/20261029T070456Z-a2041d6/) | reference | 3 | 3 | Three FUSE deployments: P2 INCONCLUSIVE, P4 SUPPORTED; git_dirty provenance caveat retained. |
| [E3/20260910T113000Z-6016f58](../results/E3/20260910T113000Z-6016f58/) | reference | 3 | 1 | Three Fargate tasks, both mounts inside each task; fresh-file/cache mixture, not production request speedup. |
| [E4/20261029T083342Z-fe5f631](../results/E4/20261029T083342Z-fe5f631/) | failed-smoke | 1 | 0 | Failed to upload hydration.csv; no formal grade. |
| [E4/20261029T084344Z-ec1e5b2](../results/E4/20261029T084344Z-ec1e5b2/) | smoke | 1 | 1 | One-rep apparatus smoke; P1/P3 SUPPORTED, P2 REFUTED; excluded from formal pool. |
| [E4/20261029T085327Z-31e9fa2](../results/E4/20261029T085327Z-31e9fa2/) | interrupted | 1 | 0 | Interrupted after rep-1 EFS, before hydrated arm/meta; no grade. |
| [E4/20261029T090427Z-3b8faf3](../results/E4/20261029T090427Z-3b8faf3/) | failed | 2 | 1 | Rep-1 complete, rep-2 seed EFS DNS initialization failed; entire campaign excluded; cost proxy only. |
| [E4/20261029T091909Z-842d596](../results/E4/20261029T091909Z-842d596/) | reference | 3 | 3 | Three independent clean deployments: P1/P3 SUPPORTED, P2 REFUTED; read-only H2 proxy MET. |
| [E5/20261015T170718Z-8f2db3b](../results/E5/20261015T170718Z-8f2db3b/) | incomplete | 1 | 0 | Early E5 attempt without meta; excluded. |
| [E5/20261015T183102Z-6272b44](../results/E5/20261015T183102Z-6272b44/) | incomplete | 1 | 0 | Early E5 attempt without meta; excluded. |
| [E5/20261026T152151Z-feeba20](../results/E5/20261026T152151Z-feeba20/) | incomplete | 1 | 0 | Early E5 attempt without meta; excluded. |
| [E5/20261026T152700Z-bf451df](../results/E5/20261026T152700Z-bf451df/) | incomplete | 1 | 0 | Early E5 attempt without meta; excluded. |
| [E5/20261026T152946Z-b1efcb2](../results/E5/20261026T152946Z-b1efcb2/) | pilot | 1 | 1 | Frozen pilot: 14/18 valid B cells; original analysis retained; not a formal replication. |
| [E5/20261028T090923Z-d39d4d5](../results/E5/20261028T090923Z-d39d4d5/) | off-protocol | 1 | 1 | Accidentally launched legacy method; retained, ungraded, not pooled. |
| [E5-diagnostic/20261027T042037Z-7d9be14](../results/E5-diagnostic/20261027T042037Z-7d9be14/) | diagnostic | 1 | 1 | Frozen helper/concurrency diagnostic; not formal collection. |
| [E5-formal/20261027T093314Z-b5b480f](../results/E5-formal/20261027T093314Z-b5b480f/) | frozen-method-validation | 1 | 1 | Frozen full-method validation n=1: P7 ERROR under original centroid rule; NOT EVALUABLE aggregate; never pooled. |
| [E5-formal/20261028T103017Z-342d6b4](../results/E5-formal/20261028T103017Z-342d6b4/) | formal-v3 | 1 | 1 | Eligible formal-v3 deployment 1/3 (historical study rep 2); P4/P7 SUPPORTED. |
| [E5-formal/20261028T125412Z-f6659e0](../results/E5-formal/20261028T125412Z-f6659e0/) | formal-v3 | 1 | 1 | Eligible formal-v3 deployment 2/3 (historical study rep 3); P4/P7 SUPPORTED. |
| [E5-formal/20261028T160106Z-dd5fce0](../results/E5-formal/20261028T160106Z-dd5fce0/) | formal-v3 | 1 | 1 | Eligible formal-v3 deployment 3/3 (historical study rep 4); P4 REFUTED, P7 SUPPORTED; pooled P4 INCONCLUSIVE. |
| [E5-isolation-validation/20261027T073803Z-647a811](../results/E5-isolation-validation/20261027T073803Z-647a811/) | short-validation | 1 | 1 | Accepted short isolation candidate; does not replace full-window formal replication. |

## Reading the provenance

- E0 repetitions are requests on local Docker, not independent AWS deployments.
- E5 formal-v3 has one rep-1 directory in each of three run IDs; historical study labels rep 2/3/4 refer to those deployments.
- Missing metadata/arms are an eligibility limitation, not a zero latency or a negative performance grade.
- E2 FSx rep-3 records a collector-only resume exception; E2 FUSE records git_dirty=true. Neither is rewritten here.
- H2 whole-claim and H4/H5/H6/H7 unanswered questions remain deferred, not silently passed.
- Frozen snapshots remain authoritative for their original rules; the old E5 P7 ERROR is not in the newer pool.
- Archived smoke/diagnostic output may have incomplete Git timing logs; the closeout replay only claims checks named in its receipt.
- Offline replay receipts under results/closeout are validation artifacts, not additional experiment replications.

## Reproduce this index

```sh
make study-index
```

Classification is reviewed data in study-runs.json. The renderer refuses a missing or duplicated run.
