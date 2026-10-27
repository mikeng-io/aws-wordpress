# First full formal isolation v3 validation — 2026-10-27

**Protocol ELIGIBLE; full-method cell validity PASS; P7 attribution ERROR; n=1.**
All ten aggregate predictions remain **NOT EVALUABLE**. This is one authorised
fresh deployment, not approval to launch further independent replications.

Launch source: `b5b480fe0f2882bf89cca56561ff435cf7b35517`, after the
[predeclared method amendment](../../../experiments/E5-attribute-cache/method-amendments/20261027-formal-v3/README.md)
and [fresh baseline/budget clearance](../../../experiments/E5-attribute-cache/preflight/20261027T092947Z-32410a7/formal-budget.md).
The total study ceiling is US$20. No retry, parameter tuning, gate relaxation,
background-RPC subtraction or regrade was performed.

## What the full run validated

- All **46 evaluated cohort-A cells**, **18 B target cells** and **3 matched EBS
  reference cells** are valid. Four A8 warm-pass files remain separate from A8.
- Complete A1-A7, NFS A8w/A8 and twelve post-B expiry probes are retained. All
  actual A waits span at least 75 seconds, fit inside cohort A and do not overlap.
- B uses the registered **300s warmup /600s requested measurement grid**. Per
  interval, this gives 6000 /600 /60 measured requests. The last 10s request starts
  before the grid's unused final interval tail, so process lifetime need not equal
  900 seconds. No window parameter was shortened.
- All twelve measured NFS cells reconcile their positive/negative phase RPCs
  exactly with independent GETATTR/LOOKUP/ACCESS window counters.
- The worst target lateness is **1/6000 (0.0167%)**, Lustre at 0.1s. Other target
  cells and all matched controls have zero requests later than delta/2. The
  predeclared maximum remains 5% per cell.
- Quiet idle spans **360.013169466 actual monotonic seconds** on five TLS roots,
  with no GETATTR/LOOKUP/ACCESS change and no traced helper root stat call. The
  tracer liveness control, quiet profile and lifecycle watchdog checks pass.
- Effective TLS readahead and watchdog PID remain unchanged. Original config
  fields and complete original bytes are restored. All six conformance tiers pass.
- Exact batch identities, fresh EBS reference subtrees, child commands, observed
  reap ordering and raw/export bindings pass. Runtime image and packaged artifact
  hashes are retained; the source matches the committed apparatus.

These facts validate the apparatus inputs for this full method. They do not make
all latency attribution claims evaluable: the separate P7 noise rule still applies.

## Per-run prediction grades

These are **one-deployment observations**, not aggregate verdicts or H1 conclusions.

| Prediction | Per-run grade | Evidence |
| --- | --- | --- |
| P1 | REFUTED | EFS plain /E2 miss estimate 0.328; OpenZFS 1.000; Lustre 2.067. |
| P2 | REFUTED | ONTAP/OpenZFS 1.153, ONTAP/EFS 0.416; the specified EFS-relative condition fails. |
| P3 | REFUTED | A1/A3 ratios: plain 3.976, TLS 3.275, OpenZFS 0.735, ONTAP 1.052. |
| P4 | SUPPORTED | A8/A3 ratios within the original tolerance on all four NFS tiers. |
| P5 | SUPPORTED | EFS/ONTAP positive-phase RPC rates fit all declared interval bands. |
| P6 | SUPPORTED | OpenZFS RPC rates fit the amended rate test; post-idle revalidation observed. No causal delegation claim. |
| P7 | ERROR | 10s matched EBS control crosses Lustre's slow-cluster attribution boundary. |
| P8 | SUPPORTED | Negative-phase RPC rate test passes; positive phase precedes ENOENT. |
| P9 | SUPPORTED | EFS plain /non-Lustre EBS amortised stat-sum ratio at 1s is 4.31. |
| P10 | SUPPORTED | Top 5% of 1s EFS plain requests contain 78.86% of positive-phase RPCs. |

The grader returns **NOT EVALUABLE for P1-P10 aggregates** because fewer than
three independent evaluable formal-v3 deployments exist. Earlier methods are not
pooled with this run.

## Why P7 remains ERROR

The matched EBS slow shares at 0.1s, 1s and 10s are 0.2099%, 0.2918% and 0.1100%:
none trips the 1% share check. At **10s**, however, the EBS slow centroid is
**14601ns**, above the Lustre classification threshold **14208ns**, with nonzero
EBS slow share. This trips the second predeclared P7 noise check. At 0.1s and 1s
that centroid/boundary check does not trip. The exact original ERROR is preserved.

The Lustre slow shares themselves are 0.1396%, 0.5912% and 0.8817%; the noise gate
prevents treating them as attributable filesystem/DLM evidence. No fixed lock-cache
capacity, CPU-only cause or DLM-state conclusion follows.

A separate [read-only raw-tail review](p7-noise-review.json), reproducible with
[p7-noise-review.py](p7-noise-review.py), examines every positive stat in the 60
measured 10s EBS requests: 30 of 60000 calls meet/exceed the Lustre boundary,
spread over 28 requests; **27 of those 30 calls are the first stat in a request**.
This suggests a first-operation effect worth investigating, without identifying
its cause. It does not replace the registered histogram rule or change P7's grade.

The next decision is a bounded review of this control-noise attribution and
replication readiness, with the existing gates preserved. Do not automatically
launch replications 2/3 or silently remove the first operation from a request.

## Evidence and teardown

[Formal analysis](analysis-v3.json), [grader provenance](analysis-provenance.json),
[actual runtime image](image-provenance.json), and `rep-1/formal/` retain the complete
raw protocol, A/D snapshots, four batches, matched references, canonical exports
and restoration evidence. The 501 downloaded raw formal files were hashed before
analysis. All 819 prior frozen files remain untouched.

Benchmark and collector both exited **0**, with no deadline handover. The stack
reached DELETE_COMPLETE; two owned FSx final backups were removed, the diagnostics
bucket was downloaded and deleted, and the host guard completed sustained-empty
verification. [Independent teardown](teardown.json) confirms 18 regions × 11
service inventories (198 checks), zero API errors and no E5 workload matches or
retained diagnostics bucket. [Guard summary](guard-summary.json),
[execution](execution.json), [runtime/source verification](apparatus-source-verification.json)
and [validation](validation.json) retain the evidence boundaries. Shared CDK/ECR
assets and provider log archives are outside this workload inventory.

[Cost review](cost-review.json): stack lifetime 124.8446 minutes; standing
engineering envelope US$2.0969, plus US$0.50 ancillary reserve. The study
ceiling stays US$20; the conservative launch proxy was US$19.255544. Actual E5
billing/allocation and remaining balance are still unverified; CE remains estimated.
The postrun proxy deliberately retains the prior double-counting reserves.

[Manifest](manifest.json) lists sizes and SHA-256 hashes for every preserved file,
excluding itself. The raw-tail script is read-only and prints its reproducible
result; the audit script refuses an existing output and is fenced to this exact
guard/deployment. Neither script authorises a deployment.
