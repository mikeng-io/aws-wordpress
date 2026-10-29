| Tier | stat p50 | stat_enoent p50 | open_read p50 | create p50 | unlink p50 |
|---|---|---|---|---|---|
| `ec2/ebs` | 1.4 µs | 3.9 µs | 7.1 µs | 21.2 µs | 8.3 µs |
| `ec2/efs` | 870.4 µs | 936.2 µs | 753.9 µs | 7.14 ms | 2.93 ms |
| `ec2/efs_host_plain` | 785.6 µs | 879.1 µs | 621.2 µs | 6.84 ms | 2.82 ms |
| `ec2/efs_host_tls` | 864.3 µs | 1.01 ms | 820.5 µs | 7.01 ms | 2.87 ms |
| `ec2/efs_plain` | 800.6 µs | 991.0 µs | 692.5 µs | 6.68 ms | 2.82 ms |
| `ec2/instance_store` | 1.4 µs | 3.4 µs | 6.1 µs | 20.2 µs | 8.0 µs |
| `ec2/juicefs` | 104.6 µs | 95.1 µs | 413.4 µs | 29.18 ms | 498.9 µs |
| `ec2/mountpoint_s3` | — | — | — | — | — |
| `ec2/seaweedfs` | 20.2 µs | 25.9 µs | 456.8 µs | 2.28 ms | 810.7 µs |
| `fargate/efs` | 942.3 µs | 1.04 ms | 854.5 µs | 7.18 ms | 2.93 ms |
| `fargate/efs_plain` | 896.2 µs | 982.2 µs | 840.9 µs | 7.07 ms | 2.89 ms |
| `fargate/ephemeral` | 3.0 µs | 7.2 µs | 9.9 µs | 31.0 µs | 17.1 µs |

### Prediction 5 (pre-registered, graded mechanically)

**REFUTED** — 0/4 checks met.

| Op | Expected | Observed | Ratio |
|---|---|---|--:|
| `stat` | TIE | INCONCLUSIVE ⚠ | 2.2× |
| `create` | SEPARATED | INCONCLUSIVE ⚠ | 1.54× |
| `unlink` | SEPARATED | INCONCLUSIVE ⚠ | 2.14× |
| `open_read` | SEPARATED | INCONCLUSIVE ⚠ | 1.61× |

### Declared comparisons, judged against the noise floor

| Comparison | op | ratio | verdict | rep-to-rep spread | inside noise? |
|---|---|--:|---|--:|---|
| device: attached NVMe vs network block | `stat` | 1.00× | TIE | 1.06× | yes |
| device: attached NVMe vs network block | `open_read` | 1.16× | TIE | 1.33× | yes |
| device: attached NVMe vs network block | `create` | 1.05× | TIE | 1.04× | **NO** |
| device: attached NVMe vs network block | `unlink` | 1.04× | TIE | 1.06× | yes |
| TLS cost, container-direct (EC2) | `stat` | 1.09× | TIE | 1.23× | yes |
| TLS cost, container-direct (EC2) | `open_read` | 1.09× | TIE | 1.13× | yes |
| TLS cost, container-direct (EC2) | `create` | 1.07× | TIE | 1.09× | yes |
| TLS cost, container-direct (EC2) | `unlink` | 1.04× | TIE | 1.16× | yes |
| TLS cost, host mount (EC2) | `stat` | 1.10× | TIE | 1.21× | yes |
| TLS cost, host mount (EC2) | `open_read` | 1.32× | TIE | 1.13× | **NO** |
| TLS cost, host mount (EC2) | `create` | 1.02× | TIE | 1.08× | yes |
| TLS cost, host mount (EC2) | `unlink` | 1.02× | TIE | 1.12× | yes |
| TLS cost, container-direct (Fargate) | `stat` | 1.05× | TIE | 1.13× | yes |
| TLS cost, container-direct (Fargate) | `open_read` | 1.02× | TIE | 1.34× | yes |
| TLS cost, container-direct (Fargate) | `create` | 1.01× | TIE | 1.04× | yes |
| TLS cost, container-direct (Fargate) | `unlink` | 1.01× | TIE | 1.05× | yes |
| mount topology, TLS held | `stat` | 1.01× | TIE | 1.21× | yes |
| mount topology, TLS held | `open_read` | 1.09× | TIE | 1.13× | yes |
| mount topology, TLS held | `create` | 1.02× | TIE | 1.09× | yes |
| mount topology, TLS held | `unlink` | 1.02× | TIE | 1.08× | yes |
| mount topology, plain held | `stat` | 1.02× | TIE | 1.23× | yes |
| mount topology, plain held | `open_read` | 1.11× | TIE | 1.13× | yes |
| mount topology, plain held | `create` | 1.02× | TIE | 1.08× | yes |
| mount topology, plain held | `unlink` | 1.00× | TIE | 1.16× | yes |
| compute type, direct+TLS held | `stat` | 1.08× | TIE | 1.20× | yes |
| compute type, direct+TLS held | `open_read` | 1.13× | TIE | 1.23× | yes |
| compute type, direct+TLS held | `create` | 1.00× | TIE | 1.09× | yes |
| compute type, direct+TLS held | `unlink` | 1.00× | TIE | 1.08× | yes |

### Bimodality (1-D k-means on log10, E3's gates)

| Tier | op | fast share | fast median | slow median | separation |
|---|---|--:|--:|--:|--:|
| `ec2/efs` | `stat` | 29.5% | 1.8 µs | 928.4 µs | 531× |
| `ec2/efs_host_plain` | `stat` | 31.8% | 1.8 µs | 839.3 µs | 470× |
| `ec2/efs_host_tls` | `stat` | 31.2% | 1.8 µs | 931.4 µs | 519× |
| `ec2/efs_plain` | `stat` | 33.3% | 1.8 µs | 855.5 µs | 494× |
| `fargate/efs` | `stat` | 29.9% | 2.4 µs | 991.4 µs | 434× |
| `fargate/efs_plain` | `stat` | 30.4% | 2.4 µs | 935.3 µs | 422× |

### Between-replication agreement (median of each rep)

| Tier | op | per-rep medians | spread |
|---|---|---|--:|
| `ec2/ebs` | `stat` | 1.4 µs, 1.4 µs, 1.3 µs | 1.06× |
| `ec2/ebs` | `create` | 21.3 µs, 21.2 µs, 21.0 µs | 1.02× |
| `ec2/efs` | `stat` | 980.9 µs, 818.6 µs, 872.9 µs | 1.20× |
| `ec2/efs` | `create` | 7.00 ms, 6.95 ms, 7.55 ms | 1.09× |
| `ec2/efs_host_plain` | `stat` | 879.6 µs, 755.0 µs, 781.3 µs | 1.16× |
| `ec2/efs_host_plain` | `create` | 6.98 ms, 6.48 ms, 6.98 ms | 1.08× |
| `ec2/efs_host_tls` | `stat` | 971.6 µs, 802.3 µs, 884.0 µs | 1.21× |
| `ec2/efs_host_tls` | `create` | 7.16 ms, 7.03 ms, 6.82 ms | 1.05× |
| `ec2/efs_plain` | `stat` | 955.1 µs, 787.2 µs, 777.1 µs | 1.23× |
| `ec2/efs_plain` | `create` | 6.98 ms, 6.53 ms, 6.52 ms | 1.07× |
| `ec2/instance_store` | `stat` | 1.4 µs, 1.4 µs, 1.3 µs | 1.02× |
| `ec2/instance_store` | `create` | 19.7 µs, 20.5 µs, 20.4 µs | 1.04× |
| `ec2/juicefs` | `stat` | 110.0 µs, 98.0 µs, 101.1 µs | 1.12× |
| `ec2/juicefs` | `create` | 29.53 ms, 29.37 ms, 28.40 ms | 1.04× |
| `ec2/seaweedfs` | `stat` | 19.5 µs, 23.1 µs, 20.4 µs | 1.19× |
| `ec2/seaweedfs` | `create` | 2.39 ms, 2.23 ms, 2.24 ms | 1.07× |
| `fargate/efs` | `stat` | 954.5 µs, 895.7 µs, 1.01 ms | 1.13× |
| `fargate/efs` | `create` | 7.02 ms, 7.12 ms, 7.32 ms | 1.04× |
| `fargate/efs_plain` | `stat` | 937.3 µs, 906.1 µs, 867.7 µs | 1.08× |
| `fargate/efs_plain` | `create` | 6.98 ms, 7.17 ms, 7.07 ms | 1.03× |
| `fargate/ephemeral` | `stat` | 1.8 µs, 3.1 µs, 3.2 µs | 1.75× |
| `fargate/ephemeral` | `create` | 21.8 µs, 37.7 µs, 37.3 µs | 1.73× |

### Prediction 1 (pre-registered 2026-10-15, graded mechanically)

**NOT EVALUABLE** — 0 evaluable replication(s); Lustre clause **NOT EVALUABLE**.

- `rep-1`: not evaluable — ec2/fsx_openzfs: no stat data; ec2/fsx_openzfs: throughput ERROR (missing); ec2/fsx_lustre: no stat data; ec2/fsx_lustre: throughput ERROR (missing); ec2/fsx_ontap: no stat data; ec2/fsx_ontap: throughput ERROR (missing)
- `rep-2`: not evaluable — ec2/fsx_openzfs: no stat data; ec2/fsx_openzfs: throughput ERROR (missing); ec2/fsx_lustre: no stat data; ec2/fsx_lustre: throughput ERROR (missing); ec2/fsx_ontap: no stat data; ec2/fsx_ontap: throughput ERROR (missing)
- `rep-3`: not evaluable — ec2/fsx_openzfs: no stat data; ec2/fsx_openzfs: throughput ERROR (missing); ec2/fsx_lustre: no stat data; ec2/fsx_lustre: throughput ERROR (missing); ec2/fsx_ontap: no stat data; ec2/fsx_ontap: throughput ERROR (missing)

#### Prediction 1, exploratory residency bound (not a verdict)

- `rep-1`: unusable — ec2/fsx_openzfs: no stat data; ec2/fsx_lustre: no stat data; ec2/fsx_ontap: no stat data
- `rep-2`: unusable — ec2/fsx_openzfs: no stat data; ec2/fsx_lustre: no stat data; ec2/fsx_ontap: no stat data
- `rep-3`: unusable — ec2/fsx_openzfs: no stat data; ec2/fsx_lustre: no stat data; ec2/fsx_ontap: no stat data

### Prediction 3 (graded mechanically)

**SUPPORTED**

Block-group stat p50 1.4 µs; bar is 10× = 13.7 µs. FSx tiers present: none.

| Server tier | stat p50 | × block group |
|---|--:|--:|
| `ec2/efs` | 870.4 µs | 637.2× |
| `ec2/efs_host_plain` | 785.6 µs | 575.1× |
| `ec2/efs_host_tls` | 864.3 µs | 632.7× |
| `ec2/efs_plain` | 800.6 µs | 586.1× |
| `ec2/juicefs` | 104.6 µs | 76.5× |
| `fargate/efs` | 942.3 µs | 689.8× |
| `fargate/efs_plain` | 896.2 µs | 656.1× |

## Predictions 2 and 4 (FUSE arms)

- **P2 JuiceFS vs EFS:** `INCONCLUSIVE` — direction held but the wide-margin / local-separation test did not
  - JuiceFS/EFS stat p50: 0.133x; JuiceFS/local: 76.54x
- **P4 Mountpoint conformance:** `SUPPORTED` — 8 distinct conformance check(s) failed
  - FAIL `rename` mv did not replace
  - FAIL `in_place_write`
  - FAIL `append`
  - FAIL `truncate`
  - FAIL `hardlink`
  - FAIL `symlink`
  - FAIL `dir_rename`
  - FAIL `mtime_advances`

