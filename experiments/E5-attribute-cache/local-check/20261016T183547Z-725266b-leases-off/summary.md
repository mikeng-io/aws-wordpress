# E5 attribute cache — graded

Run: `experiments/E5-attribute-cache/local-check/20261016T183547Z-725266b-leases-off`

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
| rep-1/ebs | 3.8 µs | 2.1 µs | 1.0 µs | 0.8 µs | 1.0 µs | 365.3 µs | 5.0 µs | — |
| rep-1/efs_host_plain | 65.3 µs | 43.6 µs | 112.9 µs | 0.8 µs | 0.8 µs | 426.2 µs | 171.5 µs | 51.1 µs |
| rep-1/efs_host_tls | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR |
| rep-1/fsx_openzfs | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR |
| rep-1/fsx_ontap | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR |
| rep-1/fsx_lustre | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | — |

## Cohort B (miss fraction from counters; slow share from latency)

| Cell | Status | Miss fraction | Slow share stat | Slow share ENOENT | Amortised stat ns/request | Late |
|---|---|--:|--:|--:|--:|--:|
| rep-1/ebs@0.1s | OK | — | 0.008533 | 0.005769 | 2337828 | 0.0002 |
| rep-1/ebs@1s | OK | — | 0.007727 | 0.005685 | 2343750 | 0.0 |
| rep-1/ebs@10s | OK | — | 0.009217 | 0.006067 | 2897030 | 0.0 |
| rep-1/efs_host_plain@0.1s | ERROR: counter miss fraction 0.0017 vs latency slow share 0.0105 (tolerance 0.0020) | | | | | |
| rep-1/efs_host_plain@1s | ERROR: counter miss fraction 0.0174 vs latency slow share 0.0236 (tolerance 0.0035) | | | | | |
| rep-1/efs_host_plain@10s | ERROR: counter miss fraction 0.1559 vs latency slow share 0.1048 (tolerance 0.0312) | | | | | |
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
