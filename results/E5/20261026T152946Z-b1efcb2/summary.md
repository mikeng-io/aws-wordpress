# E5 attribute cache — graded

Run: `results/E5/20261026T152946Z-b1efcb2`

| Prediction | Status | Per replication |
|---|---|---|
| 1 | **NOT EVALUABLE** | ERROR |
| 2 | **NOT EVALUABLE** | REFUTED |
| 3 | **NOT EVALUABLE** | REFUTED |
| 4 | **NOT EVALUABLE** | REFUTED |
| 5 | **NOT EVALUABLE** | ERROR |
| 6 | **NOT EVALUABLE** | SUPPORTED |
| 7 | **NOT EVALUABLE** | ERROR |
| 8 | **NOT EVALUABLE** | ERROR |
| 9 | **NOT EVALUABLE** | SUPPORTED |
| 10 | **NOT EVALUABLE** | SUPPORTED |

## Cohort A medians (signature-gated)

| Tier | A1 | A2 | A3 | A4 | A5 | A6 | A7 | A8 |
|---|---|---|---|---|---|---|---|---|
| rep-1/ebs | 3.9 µs | 2.0 µs | 1.3 µs | 1.0 µs | 1.3 µs | 637.0 µs | 5.8 µs | — |
| rep-1/efs_host_plain | 1.14 ms | 897.2 µs | 264.8 µs | 1.1 µs | 1.5 µs | 2.06 ms | 572.9 µs | 242.5 µs |
| rep-1/efs_host_tls | 1.16 ms | 901.7 µs | 352.2 µs | 1.1 µs | 1.5 µs | 2.27 ms | 793.9 µs | 336.7 µs |
| rep-1/fsx_openzfs | 98.2 µs | 98.2 µs | 98.0 µs | 1.1 µs | 1.4 µs | 322.8 µs | 196.3 µs | 69.9 µs |
| rep-1/fsx_ontap | 116.0 µs | 104.0 µs | 111.7 µs | 1.1 µs | 1.4 µs | 568.3 µs | 286.6 µs | 109.3 µs |
| rep-1/fsx_lustre | 283.7 µs | 135.0 µs | 6.7 µs | 1.6 µs | 6.8 µs | 771.8 µs | 386.8 µs | — |

## Cohort B (phase-attributed RPC operations per stat; latency is diagnostic)

| Cell | Status | RPC ops/stat | Slow share stat | Slow share ENOENT | Amortised stat ns/request | Late |
|---|---|--:|--:|--:|--:|--:|
| rep-1/ebs@0.1s | OK | — | 0.013006 | 0.008029 | 1761691 | 0.0 |
| rep-1/ebs@1s | OK | — | 0.022017 | 0.01441 | 1943529 | 0.0 |
| rep-1/ebs@10s | OK | — | 0.016683 | 0.012383 | 1825213 | 0.0 |
| rep-1/efs_host_plain@0.1s | OK | 0.001735 | 0.013183 | 0.008118 | 2608277 | 0.0 |
| rep-1/efs_host_plain@1s | OK | 0.01735 | 0.018147 | 0.010067 | 7905468 | 0.0 |
| rep-1/efs_host_plain@10s | OK | 0.1649 | 0.162283 | 0.009233 | 56903103 | 0.0 |
| rep-1/efs_host_tls@0.1s | ERROR: phase RPC totals disagree with independent window counters | | | | | |
| rep-1/efs_host_tls@1s | ERROR: phase RPC totals disagree with independent window counters | | | | | |
| rep-1/efs_host_tls@10s | ERROR: phase RPC totals disagree with independent window counters | | | | | |
| rep-1/fsx_openzfs@0.1s | OK | 6.833333333333333e-05 | 0.01316 | 0.008205 | 2144778 | 0.0 |
| rep-1/fsx_openzfs@1s | OK | 0.0005033333333333333 | 0.023602 | 0.014405 | 2358866 | 0.0 |
| rep-1/fsx_openzfs@10s | OK | 0.006833333333333334 | 0.024717 | 0.01555 | 3648717 | 0.0 |
| rep-1/fsx_ontap@0.1s | OK | 0.001722 | 0.00273 | 0.002665 | 2266511 | 0.0 |
| rep-1/fsx_ontap@1s | OK | 0.017346666666666666 | 0.018588 | 0.003497 | 4880824 | 0.0 |
| rep-1/fsx_ontap@10s | OK | 0.16798333333333335 | 0.163183 | 0.003783 | 24489105 | 0.0 |
| rep-1/fsx_lustre@0.1s | ERROR: 25.7% of requests later than delta/2 | | | | | |
| rep-1/fsx_lustre@1s | OK | — | 0.015583 | 0.02147 | 413377761 | 0.0 |
| rep-1/fsx_lustre@10s | OK | — | 0.010783 | 0.022967 | 466345528 | 0.0 |

## NFS attribution diagnostics

RPC-operation rates are not file-miss probabilities. Phase order: positive, then negative.

| Cell | RPC ops/ENOENT | Latency cross-check | Expiry probe | Counter-read ns/request |
|---|--:|---|---|--:|
| rep-1/efs_host_plain@0.1s | 0.000000 | DISAGREE (diagnostic) | REVALIDATION_OBSERVED | 2345732 |
| rep-1/efs_host_plain@1s | 0.000000 | AGREE (diagnostic) | REVALIDATION_OBSERVED | 2379394 |
| rep-1/efs_host_plain@10s | 0.000333 | AGREE (diagnostic) | REVALIDATION_OBSERVED | 2571444 |
| rep-1/fsx_openzfs@0.1s | 0.000000 | DISAGREE (diagnostic) | REVALIDATION_OBSERVED | 2378642 |
| rep-1/fsx_openzfs@1s | 0.000180 | DISAGREE (diagnostic) | REVALIDATION_OBSERVED | 2441574 |
| rep-1/fsx_openzfs@10s | 0.000000 | DISAGREE (diagnostic) | REVALIDATION_OBSERVED | 2560366 |
| rep-1/fsx_ontap@0.1s | 0.000013 | AGREE (diagnostic) | REVALIDATION_OBSERVED | 2328533 |
| rep-1/fsx_ontap@1s | 0.000003 | AGREE (diagnostic) | REVALIDATION_OBSERVED | 2355424 |
| rep-1/fsx_ontap@10s | 0.000217 | AGREE (diagnostic) | REVALIDATION_OBSERVED | 2238570 |

Per-replication prediction details (including ineligibility reasons):

```json
{
  "1": {
    "rep-1": {
      "grade": "ERROR",
      "why": "fsx_lustre A1: signature FAIL: mdc miss RPCs \u0394=0 for 1000 ops"
    }
  },
  "2": {
    "rep-1": {
      "grade": "REFUTED",
      "ontap_over_openzfs": 1.14,
      "ontap_over_efs": 0.422
    }
  },
  "3": {
    "rep-1": {
      "grade": "REFUTED",
      "a1_over_a3": {
        "efs_host_plain": 4.293,
        "efs_host_tls": 3.282,
        "fsx_openzfs": 1.002,
        "fsx_ontap": 1.038
      }
    }
  },
  "4": {
    "rep-1": {
      "grade": "REFUTED",
      "a8_over_a3": {
        "efs_host_plain": 0.916,
        "efs_host_tls": 0.956,
        "fsx_openzfs": 0.713,
        "fsx_ontap": 0.978
      }
    }
  },
  "5": {
    "rep-1": {
      "grade": "ERROR",
      "why": "efs_host_tls B-0.1: phase RPC totals disagree with independent window counters"
    }
  },
  "6": {
    "rep-1": {
      "grade": "SUPPORTED",
      "rpc_ops_per_stat": {
        "0.1": 6.833333333333333e-05,
        "1": 0.0005033333333333333,
        "10": 0.006833333333333334
      },
      "expiry_probes": {
        "0.1": {
          "state": "REVALIDATION_OBSERVED",
          "idle_seconds": 75.01,
          "rpc_ops": {
            "GETATTR": 1041,
            "LOOKUP": 0,
            "ACCESS": 0
          },
          "note": "suppression is consistent with delegations; does not prove held state"
        },
        "1": {
          "state": "REVALIDATION_OBSERVED",
          "idle_seconds": 75.01,
          "rpc_ops": {
            "GETATTR": 1041,
            "LOOKUP": 0,
            "ACCESS": 0
          },
          "note": "suppression is consistent with delegations; does not prove held state"
        },
        "10": {
          "state": "REVALIDATION_OBSERVED",
          "idle_seconds": 75.01,
          "rpc_ops": {
            "GETATTR": 1041,
            "LOOKUP": 0,
            "ACCESS": 0
          },
          "note": "suppression is consistent with delegations; does not prove held state"
        }
      },
      "note": "amended rate test; no causal delegation verdict"
    }
  },
  "7": {
    "rep-1": {
      "grade": "ERROR",
      "why": "fsx_lustre B-0.1: 25.7% of requests later than delta/2"
    }
  },
  "8": {
    "rep-1": {
      "grade": "ERROR",
      "why": "efs_host_tls B-1: phase RPC totals disagree with independent window counters"
    }
  },
  "9": {
    "rep-1": {
      "grade": "SUPPORTED",
      "efs_over_ebs": 4.07,
      "efs_per_request_ns": {
        "amortised": 7905467.5,
        "median": 2077094,
        "p99": 212808622,
        "max": 320923748
      },
      "ebs_per_request_ns": {
        "amortised": 1943529.2,
        "median": 1899026,
        "p99": 2688367,
        "max": 3367182
      }
    }
  },
  "10": {
    "rep-1": {
      "grade": "SUPPORTED",
      "top5pct_share_of_rpc_ops": 0.8515,
      "requests": 600,
      "rpc_ops": 10410
    }
  }
}
```

## Cohort A ERRORs

- `rep-1/fsx_lustre/A1`: signature FAIL: mdc miss RPCs Δ=0 for 1000 ops
