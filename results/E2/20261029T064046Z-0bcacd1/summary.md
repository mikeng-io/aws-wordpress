| Tier | stat p50 | stat_enoent p50 | open_read p50 | create p50 | unlink p50 |
|---|---|---|---|---|---|
| `ec2/ebs` | 1.4 µs | 3.9 µs | 6.7 µs | 20.9 µs | 8.4 µs |
| `ec2/efs` | 905.2 µs | 1.01 ms | 724.5 µs | 7.00 ms | 2.89 ms |
| `ec2/efs_host_plain` | 806.4 µs | 933.3 µs | 597.2 µs | 6.57 ms | 2.86 ms |
| `ec2/efs_host_tls` | 919.7 µs | 1.03 ms | 759.4 µs | 7.00 ms | 2.91 ms |
| `ec2/efs_plain` | 876.3 µs | 902.6 µs | 677.2 µs | 6.75 ms | 2.81 ms |
| `ec2/instance_store` | 1.4 µs | 3.7 µs | 6.5 µs | 20.1 µs | 8.1 µs |
| `ec2/juicefs` | 94.5 µs | 89.2 µs | 400.6 µs | 29.59 ms | 477.9 µs |
| `ec2/mountpoint_s3` | — | — | — | — | — |
| `ec2/seaweedfs` | 20.6 µs | 17.3 µs | 459.3 µs | 2.27 ms | 793.5 µs |
| `fargate/efs` | 945.6 µs | 1.04 ms | 829.0 µs | 7.10 ms | 2.97 ms |
| `fargate/efs_plain` | 906.3 µs | 981.8 µs | 780.2 µs | 7.00 ms | 2.84 ms |
| `fargate/ephemeral` | 2.9 µs | 5.7 µs | 9.9 µs | 37.4 µs | 17.7 µs |

### Prediction 5 (pre-registered, graded mechanically)

**REFUTED** — 0/4 checks met.

| Op | Expected | Observed | Ratio |
|---|---|---|--:|
| `stat` | TIE | INCONCLUSIVE ⚠ | 2.08× |
| `create` | SEPARATED | INCONCLUSIVE ⚠ | 1.86× |
| `unlink` | SEPARATED | INCONCLUSIVE ⚠ | 2.2× |
| `open_read` | SEPARATED | INCONCLUSIVE ⚠ | 1.52× |

### Declared comparisons, judged against the noise floor

| Comparison | op | ratio | verdict | rep-to-rep spread | inside noise? |
|---|---|--:|---|--:|---|
| device: attached NVMe vs network block | `stat` | 1.01× | TIE | 1.00× | **NO** |
| device: attached NVMe vs network block | `open_read` | 1.03× | TIE | 1.00× | **NO** |
| device: attached NVMe vs network block | `create` | 1.04× | TIE | 1.00× | **NO** |
| device: attached NVMe vs network block | `unlink` | 1.04× | TIE | 1.00× | **NO** |
| TLS cost, container-direct (EC2) | `stat` | 1.03× | TIE | 1.00× | **NO** |
| TLS cost, container-direct (EC2) | `open_read` | 1.07× | TIE | 1.00× | **NO** |
| TLS cost, container-direct (EC2) | `create` | 1.04× | TIE | 1.00× | **NO** |
| TLS cost, container-direct (EC2) | `unlink` | 1.03× | TIE | 1.00× | **NO** |
| TLS cost, host mount (EC2) | `stat` | 1.14× | TIE | 1.00× | **NO** |
| TLS cost, host mount (EC2) | `open_read` | 1.27× | TIE | 1.00× | **NO** |
| TLS cost, host mount (EC2) | `create` | 1.06× | TIE | 1.00× | **NO** |
| TLS cost, host mount (EC2) | `unlink` | 1.02× | TIE | 1.00× | **NO** |
| TLS cost, container-direct (Fargate) | `stat` | 1.04× | TIE | 1.00× | **NO** |
| TLS cost, container-direct (Fargate) | `open_read` | 1.06× | TIE | 1.00× | **NO** |
| TLS cost, container-direct (Fargate) | `create` | 1.01× | TIE | 1.00× | **NO** |
| TLS cost, container-direct (Fargate) | `unlink` | 1.04× | TIE | 1.00× | **NO** |
| mount topology, TLS held | `stat` | 1.02× | TIE | 1.00× | **NO** |
| mount topology, TLS held | `open_read` | 1.05× | TIE | 1.00× | **NO** |
| mount topology, TLS held | `create` | 1.00× | TIE | 1.00× | **NO** |
| mount topology, TLS held | `unlink` | 1.01× | TIE | 1.00× | **NO** |
| mount topology, plain held | `stat` | 1.09× | TIE | 1.00× | **NO** |
| mount topology, plain held | `open_read` | 1.13× | TIE | 1.00× | **NO** |
| mount topology, plain held | `create` | 1.03× | TIE | 1.00× | **NO** |
| mount topology, plain held | `unlink` | 1.02× | TIE | 1.00× | **NO** |
| compute type, direct+TLS held | `stat` | 1.04× | TIE | 1.00× | **NO** |
| compute type, direct+TLS held | `open_read` | 1.14× | TIE | 1.00× | **NO** |
| compute type, direct+TLS held | `create` | 1.01× | TIE | 1.00× | **NO** |
| compute type, direct+TLS held | `unlink` | 1.03× | TIE | 1.00× | **NO** |

### Bimodality (1-D k-means on log10, E3's gates)

| Tier | op | fast share | fast median | slow median | separation |
|---|---|--:|--:|--:|--:|
| `ec2/efs` | `stat` | 31.4% | 1.8 µs | 942.8 µs | 516× |
| `ec2/efs_host_plain` | `stat` | 34.9% | 1.8 µs | 856.5 µs | 470× |
| `ec2/efs_host_tls` | `stat` | 30.1% | 1.8 µs | 959.8 µs | 511× |
| `ec2/efs_plain` | `stat` | 33.4% | 1.8 µs | 916.9 µs | 512× |
| `fargate/efs` | `stat` | 30.6% | 2.6 µs | 974.8 µs | 367× |
| `fargate/efs_plain` | `stat` | 32.2% | 2.6 µs | 936.9 µs | 357× |

### Between-replication agreement (median of each rep)

| Tier | op | per-rep medians | spread |
|---|---|---|--:|

### Prediction 1 (pre-registered 2026-10-15, graded mechanically)

**NOT EVALUABLE** — 0 evaluable replication(s); Lustre clause **NOT EVALUABLE**.

- `rep-1`: not evaluable — ec2/fsx_openzfs: no stat data; ec2/fsx_openzfs: throughput ERROR (missing); ec2/fsx_lustre: no stat data; ec2/fsx_lustre: throughput ERROR (missing); ec2/fsx_ontap: no stat data; ec2/fsx_ontap: throughput ERROR (missing)

#### Prediction 1, exploratory residency bound (not a verdict)

- `rep-1`: unusable — ec2/fsx_openzfs: no stat data; ec2/fsx_lustre: no stat data; ec2/fsx_ontap: no stat data

### Prediction 3 (graded mechanically)

**SUPPORTED**

Block-group stat p50 1.4 µs; bar is 10× = 13.7 µs. FSx tiers present: none.

| Server tier | stat p50 | × block group |
|---|--:|--:|
| `ec2/efs` | 905.2 µs | 660.3× |
| `ec2/efs_host_plain` | 806.4 µs | 588.2× |
| `ec2/efs_host_tls` | 919.7 µs | 670.9× |
| `ec2/efs_plain` | 876.3 µs | 639.2× |
| `ec2/juicefs` | 94.5 µs | 68.9× |
| `fargate/efs` | 945.6 µs | 689.7× |
| `fargate/efs_plain` | 906.3 µs | 661.0× |

## Predictions 2 and 4 (FUSE arms)

- **P2 JuiceFS vs EFS:** `INCONCLUSIVE` — direction held but the wide-margin / local-separation test did not
  - JuiceFS/EFS stat p50: 0.117x; JuiceFS/local: 68.94x
- **P4 Mountpoint conformance:** `SUPPORTED` — 8 conformance check(s) failed
  - FAIL `rename` mv did not replace
  - FAIL `in_place_write`
  - FAIL `append`
  - FAIL `truncate`
  - FAIL `hardlink`
  - FAIL `symlink`
  - FAIL `dir_rename`
  - FAIL `mtime_advances`

