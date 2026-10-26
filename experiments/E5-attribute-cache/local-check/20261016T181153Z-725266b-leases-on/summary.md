# E5 attribute cache — graded

Run: `experiments/E5-attribute-cache/local-check/20261016T181153Z-725266b-leases-on`

| Prediction | Status | Per replication |
|---|---|---|
| 1 | **NOT EVALUABLE** | ERROR |
| 2 | **NOT EVALUABLE** | ERROR |
| 3 | **NOT EVALUABLE** | ERROR |
| 4 | **NOT EVALUABLE** | ERROR |
| 5 | **NOT EVALUABLE** | ERROR |
| 6 | **NOT EVALUABLE** | ERROR |
| 7 | **NOT EVALUABLE** | ERROR |
| 8 | **NOT EVALUABLE** | ERROR |
| 9 | **NOT EVALUABLE** | ERROR |
| 10 | **NOT EVALUABLE** | ERROR |

## Cohort A medians (signature-gated)

| Tier | A1 | A2 | A3 | A4 | A5 | A6 | A7 | A8 |
|---|---|---|---|---|---|---|---|---|
| rep-1/ebs | 1.9 µs | 1.0 µs | 2.8 µs | 0.9 µs | 1.3 µs | 55.8 µs | 9.2 µs | — |
| rep-1/efs_host_plain | 62.5 µs | 59.2 µs | 44.9 µs | 0.6 µs | 0.7 µs | 44.2 µs | 152.1 µs | 48.8 µs |
| rep-1/efs_host_tls | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR |
| rep-1/fsx_openzfs | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR |
| rep-1/fsx_ontap | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR |
| rep-1/fsx_lustre | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | — |

## Cohort B (miss fraction from counters; slow share from latency)

| Cell | Status | Miss fraction | Slow share stat | Slow share ENOENT | Amortised stat ns/request | Late |
|---|---|--:|--:|--:|--:|--:|
| rep-1/ebs@0.1s | OK | — | 0.008254 | 0.005536 | 2501046 | 0.0 |
| rep-1/ebs@1s | OK | — | 0.008448 | 0.00575 | 2635764 | 0.0 |
| rep-1/ebs@10s | OK | — | 0.010983 | 0.007867 | 3111328 | 0.0 |
| rep-1/efs_host_plain@0.1s | ERROR: counter miss fraction 0.0001 vs latency slow share 0.0089 (tolerance 0.0020) | | | | | |
| rep-1/efs_host_plain@1s | ERROR: counter miss fraction 0.0007 vs latency slow share 0.0097 (tolerance 0.0020) | | | | | |
| rep-1/efs_host_plain@10s | ERROR: counter miss fraction 0.0062 vs latency slow share 0.0110 (tolerance 0.0020) | | | | | |
| rep-1/efs_host_tls@0.1s | ERROR: instrument status absent | | | | | |
| rep-1/efs_host_tls@1s | ERROR: instrument status absent | | | | | |
| rep-1/efs_host_tls@10s | ERROR: instrument status absent | | | | | |
| rep-1/fsx_openzfs@0.1s | ERROR: instrument status absent | | | | | |
| rep-1/fsx_openzfs@1s | ERROR: instrument status absent | | | | | |
| rep-1/fsx_openzfs@10s | ERROR: instrument status absent | | | | | |
| rep-1/fsx_ontap@0.1s | ERROR: instrument status absent | | | | | |
| rep-1/fsx_ontap@1s | ERROR: instrument status absent | | | | | |
| rep-1/fsx_ontap@10s | ERROR: instrument status absent | | | | | |
| rep-1/fsx_lustre@0.1s | ERROR: instrument status absent | | | | | |
| rep-1/fsx_lustre@1s | ERROR: instrument status absent | | | | | |
| rep-1/fsx_lustre@10s | ERROR: instrument status absent | | | | | |

## Cohort A ERRORs

- `rep-1/efs_host_tls/A1`: instrument status absent
- `rep-1/efs_host_tls/A2`: instrument status absent
- `rep-1/efs_host_tls/A3`: instrument status absent
- `rep-1/efs_host_tls/A4`: instrument status absent
- `rep-1/efs_host_tls/A5`: instrument status absent
- `rep-1/efs_host_tls/A6`: instrument status absent
- `rep-1/efs_host_tls/A7`: instrument status absent
- `rep-1/efs_host_tls/A8`: instrument status absent
- `rep-1/fsx_openzfs/A1`: instrument status absent
- `rep-1/fsx_openzfs/A2`: instrument status absent
- `rep-1/fsx_openzfs/A3`: instrument status absent
- `rep-1/fsx_openzfs/A4`: instrument status absent
- `rep-1/fsx_openzfs/A5`: instrument status absent
- `rep-1/fsx_openzfs/A6`: instrument status absent
- `rep-1/fsx_openzfs/A7`: instrument status absent
- `rep-1/fsx_openzfs/A8`: instrument status absent
- `rep-1/fsx_ontap/A1`: instrument status absent
- `rep-1/fsx_ontap/A2`: instrument status absent
- `rep-1/fsx_ontap/A3`: instrument status absent
- `rep-1/fsx_ontap/A4`: instrument status absent
- `rep-1/fsx_ontap/A5`: instrument status absent
- `rep-1/fsx_ontap/A6`: instrument status absent
- `rep-1/fsx_ontap/A7`: instrument status absent
- `rep-1/fsx_ontap/A8`: instrument status absent
- `rep-1/fsx_lustre/A1`: instrument status absent
- `rep-1/fsx_lustre/A2`: instrument status absent
- `rep-1/fsx_lustre/A3`: instrument status absent
- `rep-1/fsx_lustre/A4`: instrument status absent
- `rep-1/fsx_lustre/A5`: instrument status absent
- `rep-1/fsx_lustre/A6`: instrument status absent
- `rep-1/fsx_lustre/A7`: instrument status absent
