| Tier | stat p50 | stat_enoent p50 | open_read p50 | create p50 | unlink p50 |
|---|---|---|---|---|---|
| `ec2/ebs` | 1.3 µs | 3.8 µs | 7.4 µs | 20.5 µs | 8.3 µs |
| `ec2/efs` | 840.5 µs | 918.1 µs | 682.0 µs | 6.55 ms | 2.75 ms |
| `ec2/efs_host_plain` | 758.5 µs | 850.9 µs | 583.9 µs | 6.46 ms | 2.64 ms |
| `ec2/efs_host_tls` | 812.6 µs | 876.2 µs | 709.6 µs | 6.68 ms | 2.74 ms |
| `ec2/efs_plain` | 812.9 µs | 918.8 µs | 661.9 µs | 6.52 ms | 2.72 ms |
| `ec2/fsx_lustre` | 149.4 µs | 144.3 µs | 336.7 µs | 606.8 µs | 309.1 µs |
| `ec2/fsx_ontap` | 1.7 µs | 107.0 µs | 272.5 µs | 982.1 µs | 341.6 µs |
| `ec2/fsx_openzfs` | 1.8 µs | 98.0 µs | 199.4 µs | 1.57 ms | 560.5 µs |
| `ec2/instance_store` | 1.4 µs | 3.5 µs | 7.0 µs | 19.6 µs | 8.0 µs |
| `fargate/efs` | 785.0 µs | 868.6 µs | 653.3 µs | 6.49 ms | 2.67 ms |
| `fargate/efs_plain` | 795.3 µs | 871.7 µs | 606.8 µs | 6.40 ms | 2.67 ms |
| `fargate/ephemeral` | 2.0 µs | 5.8 µs | 6.8 µs | 22.4 µs | 12.2 µs |

### Prediction 5 (pre-registered, graded mechanically)

**PARTIALLY SUPPORTED** — 1/4 checks met.

| Op | Expected | Observed | Ratio |
|---|---|---|--:|
| `stat` | TIE | TIE | 1.48× |
| `create` | SEPARATED | TIE ⚠ | 1.14× |
| `unlink` | SEPARATED | INCONCLUSIVE ⚠ | 1.53× |
| `open_read` | SEPARATED | TIE ⚠ | 1.04× |

### Declared comparisons, judged against the noise floor

| Comparison | op | ratio | verdict | rep-to-rep spread | inside noise? |
|---|---|--:|---|--:|---|
| device: attached NVMe vs network block | `stat` | 1.00× | TIE | 1.08× | yes |
| device: attached NVMe vs network block | `open_read` | 1.05× | TIE | 1.16× | yes |
| device: attached NVMe vs network block | `create` | 1.04× | TIE | 1.02× | **NO** |
| device: attached NVMe vs network block | `unlink` | 1.04× | TIE | 1.04× | yes |
| TLS cost, container-direct (EC2) | `stat` | 1.03× | TIE | 1.10× | yes |
| TLS cost, container-direct (EC2) | `open_read` | 1.03× | TIE | 1.03× | yes |
| TLS cost, container-direct (EC2) | `create` | 1.00× | TIE | 1.03× | yes |
| TLS cost, container-direct (EC2) | `unlink` | 1.01× | TIE | 1.04× | yes |
| TLS cost, host mount (EC2) | `stat` | 1.07× | TIE | 1.26× | yes |
| TLS cost, host mount (EC2) | `open_read` | 1.22× | TIE | 1.12× | **NO** |
| TLS cost, host mount (EC2) | `create` | 1.03× | TIE | 1.10× | yes |
| TLS cost, host mount (EC2) | `unlink` | 1.04× | TIE | 1.07× | yes |
| TLS cost, container-direct (Fargate) | `stat` | 1.01× | TIE | 1.11× | yes |
| TLS cost, container-direct (Fargate) | `open_read` | 1.08× | TIE | 1.15× | yes |
| TLS cost, container-direct (Fargate) | `create` | 1.01× | TIE | 1.03× | yes |
| TLS cost, container-direct (Fargate) | `unlink` | 1.00× | TIE | 1.02× | yes |
| mount topology, TLS held | `stat` | 1.03× | TIE | 1.10× | yes |
| mount topology, TLS held | `open_read` | 1.04× | TIE | 1.09× | yes |
| mount topology, TLS held | `create` | 1.02× | TIE | 1.06× | yes |
| mount topology, TLS held | `unlink` | 1.00× | TIE | 1.06× | yes |
| mount topology, plain held | `stat` | 1.07× | TIE | 1.26× | yes |
| mount topology, plain held | `open_read` | 1.13× | TIE | 1.12× | **NO** |
| mount topology, plain held | `create` | 1.01× | TIE | 1.10× | yes |
| mount topology, plain held | `unlink` | 1.03× | TIE | 1.07× | yes |
| compute type, direct+TLS held | `stat` | 1.07× | TIE | 1.11× | yes |
| compute type, direct+TLS held | `open_read` | 1.04× | TIE | 1.15× | yes |
| compute type, direct+TLS held | `create` | 1.01× | TIE | 1.03× | yes |
| compute type, direct+TLS held | `unlink` | 1.03× | TIE | 1.04× | yes |
| server: FSx OpenZFS vs EFS | `stat` | 411.34× | SEPARATED | 1.26× | **NO** |
| server: FSx OpenZFS vs EFS | `open_read` | 2.93× | INCONCLUSIVE | 1.21× | **NO** |
| server: FSx OpenZFS vs EFS | `create` | 4.11× | SEPARATED | 1.10× | **NO** |
| server: FSx OpenZFS vs EFS | `unlink` | 4.71× | SEPARATED | 1.07× | **NO** |
| server: FSx ONTAP vs EFS | `stat` | 444.09× | SEPARATED | 1.26× | **NO** |
| server: FSx ONTAP vs EFS | `open_read` | 2.14× | INCONCLUSIVE | 1.12× | **NO** |
| server: FSx ONTAP vs EFS | `create` | 6.57× | SEPARATED | 1.10× | **NO** |
| server: FSx ONTAP vs EFS | `unlink` | 7.74× | SEPARATED | 1.07× | **NO** |
| server: FSx Lustre vs EFS | `stat` | 5.08× | SEPARATED | 1.26× | **NO** |
| server: FSx Lustre vs EFS | `open_read` | 1.73× | INCONCLUSIVE | 1.12× | **NO** |
| server: FSx Lustre vs EFS | `create` | 10.64× | SEPARATED | 1.18× | **NO** |
| server: FSx Lustre vs EFS | `unlink` | 8.55× | SEPARATED | 1.94× | **NO** |
| NFS server, OpenZFS vs ONTAP | `stat` | 1.08× | TIE | 1.03× | **NO** |
| NFS server, OpenZFS vs ONTAP | `open_read` | 1.37× | TIE | 1.21× | **NO** |
| NFS server, OpenZFS vs ONTAP | `create` | 1.60× | INCONCLUSIVE | 1.02× | **NO** |
| NFS server, OpenZFS vs ONTAP | `unlink` | 1.64× | INCONCLUSIVE | 1.05× | **NO** |

### Bimodality (1-D k-means on log10, E3's gates)

| Tier | op | fast share | fast median | slow median | separation |
|---|---|--:|--:|--:|--:|
| `ec2/efs` | `stat` | 35.1% | 1.8 µs | 880.0 µs | 480× |
| `ec2/efs_host_plain` | `stat` | 34.1% | 1.8 µs | 827.4 µs | 465× |
| `ec2/efs_host_tls` | `stat` | 33.4% | 1.8 µs | 854.3 µs | 478× |
| `ec2/efs_plain` | `stat` | 34.8% | 1.8 µs | 865.6 µs | 494× |
| `ec2/fsx_openzfs` | `stat` | 68.8% | 1.8 µs | 97.6 µs | 53× |
| `fargate/efs` | `stat` | 34.5% | 1.7 µs | 827.7 µs | 501× |
| `fargate/efs_plain` | `stat` | 36.0% | 1.7 µs | 834.1 µs | 501× |

### Between-replication agreement (median of each rep)

| Tier | op | per-rep medians | spread |
|---|---|---|--:|
| `ec2/ebs` | `stat` | 1.4 µs, 1.3 µs, 1.3 µs | 1.01× |
| `ec2/ebs` | `create` | 20.5 µs, 20.8 µs, 20.3 µs | 1.03× |
| `ec2/efs` | `stat` | 833.0 µs, 824.2 µs, 876.8 µs | 1.06× |
| `ec2/efs` | `create` | 6.52 ms, 6.47 ms, 6.65 ms | 1.03× |
| `ec2/efs_host_plain` | `stat` | 790.1 µs, 699.7 µs, 883.5 µs | 1.26× |
| `ec2/efs_host_plain` | `create` | 6.66 ms, 6.07 ms, 6.60 ms | 1.10× |
| `ec2/efs_host_tls` | `stat` | 808.5 µs, 787.2 µs, 865.5 µs | 1.10× |
| `ec2/efs_host_tls` | `create` | 6.89 ms, 6.47 ms, 6.72 ms | 1.07× |
| `ec2/efs_plain` | `stat` | 852.0 µs, 849.6 µs, 771.5 µs | 1.10× |
| `ec2/efs_plain` | `create` | 6.53 ms, 6.45 ms, 6.57 ms | 1.02× |
| `ec2/fsx_lustre` | `stat` | 151.0 µs, 142.9 µs, 154.6 µs | 1.08× |
| `ec2/fsx_lustre` | `create` | 553.3 µs, 609.2 µs, 654.7 µs | 1.18× |
| `ec2/fsx_ontap` | `stat` | 1.7 µs, 1.7 µs, 1.7 µs | 1.01× |
| `ec2/fsx_ontap` | `create` | 994.3 µs, 970.8 µs, 985.4 µs | 1.02× |
| `ec2/fsx_openzfs` | `stat` | 1.8 µs, 1.8 µs, 1.9 µs | 1.03× |
| `ec2/fsx_openzfs` | `create` | 1.59 ms, 1.56 ms, 1.55 ms | 1.02× |
| `ec2/instance_store` | `stat` | 1.3 µs, 1.4 µs, 1.3 µs | 1.08× |
| `ec2/instance_store` | `create` | 19.8 µs, 19.5 µs, 19.6 µs | 1.02× |
| `fargate/efs` | `stat` | 836.1 µs, 752.9 µs, 791.9 µs | 1.11× |
| `fargate/efs` | `create` | 6.52 ms, 6.51 ms, 6.47 ms | 1.01× |
| `fargate/efs_plain` | `stat` | 797.0 µs, 804.6 µs, 781.3 µs | 1.03× |
| `fargate/efs_plain` | `create` | 6.52 ms, 6.37 ms, 6.33 ms | 1.03× |
| `fargate/ephemeral` | `stat` | 1.9 µs, 2.0 µs, 2.1 µs | 1.09× |
| `fargate/ephemeral` | `create` | 22.3 µs, 22.0 µs, 23.0 µs | 1.04× |

### Prediction 1 (pre-registered 2026-10-15, graded mechanically)

**NOT EVALUABLE** — 0 evaluable replication(s); Lustre clause **NOT EVALUABLE**.

- `rep-1`: not evaluable — ec2/fsx_lustre: throughput ERROR (read started 8.046% resident)
- `rep-2`: not evaluable — ec2/fsx_lustre: throughput ERROR (read started 17.582% resident)
- `rep-3`: not evaluable — ec2/fsx_lustre: throughput ERROR (read started 26.367% resident)

#### Prediction 1, exploratory residency bound (not a verdict)

- `rep-1`: ρ -0.357 (DIFFER) at measured, -0.357 (DIFFER) at the residency floor; Lustre throughput rank 1.0 / 1.0; robust: True
- `rep-2`: ρ -0.429 (DIFFER) at measured, -0.357 (DIFFER) at the residency floor; Lustre throughput rank 1.0 / 3.0; robust: True
- `rep-3`: ρ -0.357 (DIFFER) at measured, -0.357 (DIFFER) at the residency floor; Lustre throughput rank 1.0 / 1.0; robust: True

### Prediction 3 (graded mechanically)

**REFUTED**

Block-group stat p50 1.4 µs; bar is 10× = 13.5 µs. FSx tiers present: ec2/fsx_lustre, ec2/fsx_ontap, ec2/fsx_openzfs.

| Server tier | stat p50 | × block group |
|---|--:|--:|
| `ec2/efs` | 840.5 µs | 622.1× |
| `ec2/efs_host_plain` | 758.5 µs | 561.4× |
| `ec2/efs_host_tls` | 812.6 µs | 601.5× |
| `ec2/efs_plain` | 812.9 µs | 601.7× |
| `ec2/fsx_lustre` | 149.4 µs | 110.6× |
| `ec2/fsx_ontap` | 1.7 µs | 1.3× |
| `ec2/fsx_openzfs` | 1.8 µs | 1.4× |
| `fargate/efs` | 785.0 µs | 581.1× |
| `fargate/efs_plain` | 795.3 µs | 588.7× |
