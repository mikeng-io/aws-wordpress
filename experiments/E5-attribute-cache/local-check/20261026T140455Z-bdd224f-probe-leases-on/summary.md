# E5 attribute cache — graded

Run: `/tmp/aws-wordpress-e5-phases-v2-probe-on`

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
| 9 | **NOT EVALUABLE** | SUPPORTED |
| 10 | **NOT EVALUABLE** | INCONCLUSIVE |

## Cohort A medians (signature-gated)

| Tier | A1 | A2 | A3 | A4 | A5 | A6 | A7 | A8 |
|---|---|---|---|---|---|---|---|---|
| rep-1/ebs | 2.9 µs | 1.6 µs | 2.7 µs | 0.8 µs | 1.2 µs | 60.8 µs | 16.1 µs | — |
| rep-1/efs_host_plain | 59.8 µs | 54.1 µs | 1.1 µs | 1.0 µs | 0.8 µs | 234.6 µs | 40.2 µs | 54.2 µs |
| rep-1/efs_host_tls | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR |
| rep-1/fsx_openzfs | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR |
| rep-1/fsx_ontap | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR |
| rep-1/fsx_lustre | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | — |

## Cohort B (phase-attributed RPC operations per stat; latency is diagnostic)

| Cell | Status | RPC ops/stat | Slow share stat | Slow share ENOENT | Amortised stat ns/request | Late |
|---|---|--:|--:|--:|--:|--:|
| rep-1/ebs@0.1s | OK | — | 0.02952 | 0.01737 | 2602184 | 0.0 |
| rep-1/ebs@1s | OK | — | 0.0213 | 0.0061 | 2407173 | 0.0 |
| rep-1/ebs@10s | OK | — | 0.018 | 0.029 | 3612699 | 0.0 |
| rep-1/efs_host_plain@0.1s | OK | 0.0 | 0.0 | 0.02188 | 3958576 | 0.0 |
| rep-1/efs_host_plain@1s | OK | 0.0 | 0.0173 | 0.0117 | 4539537 | 0.0 |
| rep-1/efs_host_plain@10s | OK | 0.0 | 0.0 | 0.003 | 2303521 | 0.0 |
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

## NFS attribution diagnostics

RPC-operation rates are not file-miss probabilities. Phase order: positive, then negative.

| Cell | RPC ops/ENOENT | Latency cross-check | Expiry probe | Counter-read ns/request |
|---|--:|---|---|--:|
| rep-1/efs_host_plain@0.1s | 0.000000 | AGREE (diagnostic) | REVALIDATION_SUPPRESSED | 2535391 |
| rep-1/efs_host_plain@1s | 0.000000 | DISAGREE (diagnostic) | REVALIDATION_SUPPRESSED | 2901187 |
| rep-1/efs_host_plain@10s | 0.000000 | AGREE (diagnostic) | REVALIDATION_SUPPRESSED | 1868374 |

Per-replication prediction details (including ineligibility reasons):

```json
{
  "1": {
    "rep-1": {
      "grade": "ERROR",
      "why": "efs_host_plain A3: signature FAIL: GETATTR \u0394=0 LOOKUP \u0394=0 READ \u0394=0 for 1000 ops; fsx_openzfs A3: instrument status absent; fsx_lustre A1: instrument status absent"
    }
  },
  "2": {
    "rep-1": {
      "grade": "ERROR",
      "why": "fsx_ontap A3: instrument status absent; fsx_openzfs A3: instrument status absent; efs_host_plain A3: signature FAIL: GETATTR \u0394=0 LOOKUP \u0394=0 READ \u0394=0 for 1000 ops"
    }
  },
  "3": {
    "rep-1": {
      "grade": "ERROR",
      "why": "efs_host_plain A3: signature FAIL: GETATTR \u0394=0 LOOKUP \u0394=0 READ \u0394=0 for 1000 ops"
    }
  },
  "4": {
    "rep-1": {
      "grade": "ERROR",
      "why": "efs_host_plain A3: signature FAIL: GETATTR \u0394=0 LOOKUP \u0394=0 READ \u0394=0 for 1000 ops"
    }
  },
  "5": {
    "rep-1": {
      "grade": "ERROR",
      "why": "efs_host_plain@0.1: timer-model precondition unproven: {'state': 'REVALIDATION_SUPPRESSED', 'idle_seconds': 75.01, 'rpc_ops': {'GETATTR': 41, 'LOOKUP': 0, 'ACCESS': 0}, 'note': 'suppression is consistent with delegations; does not prove held state'}"
    }
  },
  "6": {
    "rep-1": {
      "grade": "ERROR",
      "why": "fsx_openzfs B-0.1: instrument status absent"
    }
  },
  "7": {
    "rep-1": {
      "grade": "ERROR",
      "why": "fsx_lustre B-0.1: instrument status absent"
    }
  },
  "8": {
    "rep-1": {
      "grade": "ERROR",
      "why": "efs_host_tls B-1: instrument status absent"
    }
  },
  "9": {
    "rep-1": {
      "grade": "SUPPORTED",
      "efs_over_ebs": 1.89,
      "efs_per_request_ns": {
        "amortised": 4539536.9,
        "median": 4177907,
        "p99": 11529890,
        "max": 11529890
      },
      "ebs_per_request_ns": {
        "amortised": 2407173.4,
        "median": 2268588,
        "p99": 3702393,
        "max": 3702393
      }
    }
  },
  "10": {
    "rep-1": {
      "grade": "INCONCLUSIVE",
      "why": "no positive-phase RPC operations observed in the measured window"
    }
  }
}
```

## Cohort A ERRORs

- `rep-1/efs_host_plain/A3`: signature FAIL: GETATTR Δ=0 LOOKUP Δ=0 READ Δ=0 for 1000 ops
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
