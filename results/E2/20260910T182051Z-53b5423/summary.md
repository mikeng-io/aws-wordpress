| Tier | stat p50 | stat_enoent p50 | open_read p50 | create p50 | unlink p50 |
|---|---|---|---|---|---|
| `ec2/ebs` | 1.2 µs | 3.1 µs | 5.4 µs | 19.8 µs | 7.5 µs |
| `ec2/efs` | 739.7 µs | 1.09 ms | 904.1 µs | 7.08 ms | 2.94 ms |
| `ec2/efs_host_plain` | 682.8 µs | 994.8 µs | 792.2 µs | 6.97 ms | 2.89 ms |
| `ec2/efs_host_tls` | 740.6 µs | 1.04 ms | 932.5 µs | 7.16 ms | 3.03 ms |
| `ec2/efs_plain` | 742.9 µs | 872.7 µs | 875.8 µs | 7.12 ms | 2.96 ms |
| `ec2/instance_store` | 1.2 µs | 2.9 µs | 5.1 µs | 19.4 µs | 7.4 µs |
| `fargate/efs` | 785.8 µs | 882.0 µs | 837.5 µs | 7.16 ms | 2.99 ms |
| `fargate/efs_plain` | 717.1 µs | 1.01 ms | 831.2 µs | 7.01 ms | 2.91 ms |
| `fargate/ephemeral` | 1.9 µs | 4.6 µs | 6.0 µs | 22.3 µs | 11.8 µs |

### Prediction 5 (pre-registered, graded mechanically)

**PARTIALLY SUPPORTED** — 0/4 checks met.

| Op | Expected | Observed | Ratio |
|---|---|---|--:|
| `stat` | TIE | INCONCLUSIVE ⚠ | 1.53× |
| `create` | SEPARATED | TIE ⚠ | 1.15× |
| `unlink` | SEPARATED | INCONCLUSIVE ⚠ | 1.6× |
| `open_read` | SEPARATED | TIE ⚠ | 1.17× |

### Declared comparisons, judged against the noise floor

| Comparison | op | ratio | verdict | rep-to-rep spread | inside noise? |
|---|---|--:|---|--:|---|
| device: attached NVMe vs network block | `stat` | 1.00× | TIE | 1.04× | yes |
| device: attached NVMe vs network block | `open_read` | 1.06× | TIE | 1.06× | yes |
| device: attached NVMe vs network block | `create` | 1.02× | TIE | 1.02× | yes |
| device: attached NVMe vs network block | `unlink` | 1.02× | TIE | 1.02× | yes |
| TLS cost, container-direct (EC2) | `stat` | 1.00× | TIE | 1.52× | yes |
| TLS cost, container-direct (EC2) | `open_read` | 1.03× | TIE | 1.48× | yes |
| TLS cost, container-direct (EC2) | `create` | 1.00× | TIE | 1.19× | yes |
| TLS cost, container-direct (EC2) | `unlink` | 1.01× | TIE | 1.24× | yes |
| TLS cost, host mount (EC2) | `stat` | 1.08× | TIE | 1.82× | yes |
| TLS cost, host mount (EC2) | `open_read` | 1.18× | TIE | 1.48× | yes |
| TLS cost, host mount (EC2) | `create` | 1.03× | TIE | 1.23× | yes |
| TLS cost, host mount (EC2) | `unlink` | 1.05× | TIE | 1.22× | yes |
| TLS cost, container-direct (Fargate) | `stat` | 1.10× | TIE | 1.77× | yes |
| TLS cost, container-direct (Fargate) | `open_read` | 1.01× | TIE | 1.46× | yes |
| TLS cost, container-direct (Fargate) | `create` | 1.02× | TIE | 1.21× | yes |
| TLS cost, container-direct (Fargate) | `unlink` | 1.03× | TIE | 1.20× | yes |
| mount topology, TLS held | `stat` | 1.00× | TIE | 1.54× | yes |
| mount topology, TLS held | `open_read` | 1.03× | TIE | 1.48× | yes |
| mount topology, TLS held | `create` | 1.01× | TIE | 1.23× | yes |
| mount topology, TLS held | `unlink` | 1.03× | TIE | 1.24× | yes |
| mount topology, plain held | `stat` | 1.09× | TIE | 1.82× | yes |
| mount topology, plain held | `open_read` | 1.11× | TIE | 1.48× | yes |
| mount topology, plain held | `create` | 1.02× | TIE | 1.23× | yes |
| mount topology, plain held | `unlink` | 1.02× | TIE | 1.22× | yes |
| compute type, direct+TLS held | `stat` | 1.06× | TIE | 1.52× | yes |
| compute type, direct+TLS held | `open_read` | 1.08× | TIE | 1.48× | yes |
| compute type, direct+TLS held | `create` | 1.01× | TIE | 1.21× | yes |
| compute type, direct+TLS held | `unlink` | 1.02× | TIE | 1.24× | yes |

### Bimodality (1-D k-means on log10, E3's gates)

| Tier | op | fast share | fast median | slow median | separation |
|---|---|--:|--:|--:|--:|
| `ec2/efs` | `stat` | 31.5% | 1.8 µs | 814.8 µs | 493× |
| `ec2/efs_host_plain` | `stat` | 32.8% | 1.7 µs | 809.4 µs | 512× |
| `ec2/efs_host_tls` | `stat` | 32.1% | 1.7 µs | 838.4 µs | 504× |
| `ec2/efs_plain` | `stat` | 32.3% | 1.7 µs | 821.6 µs | 509× |
| `fargate/efs` | `stat` | 30.3% | 1.7 µs | 1.01 ms | 562× |
| `fargate/efs_plain` | `stat` | 31.3% | 1.7 µs | 830.8 µs | 530× |

### Between-replication agreement (median of each rep)

| Tier | op | per-rep medians | spread |
|---|---|---|--:|
| `ec2/ebs` | `stat` | 1.3 µs, 1.2 µs, 1.3 µs | 1.05× |
| `ec2/ebs` | `create` | 19.9 µs, 19.9 µs, 19.7 µs | 1.01× |
| `ec2/efs` | `stat` | 756.9 µs, 697.8 µs, 1.06 ms | 1.52× |
| `ec2/efs` | `create` | 7.27 ms, 6.30 ms, 7.46 ms | 1.18× |
| `ec2/efs_host_plain` | `stat` | 697.9 µs, 640.3 µs, 1.16 ms | 1.82× |
| `ec2/efs_host_plain` | `create` | 7.38 ms, 5.99 ms, 7.34 ms | 1.23× |
| `ec2/efs_host_tls` | `stat` | 767.6 µs, 688.1 µs, 1.06 ms | 1.54× |
| `ec2/efs_host_tls` | `create` | 7.58 ms, 6.17 ms, 7.56 ms | 1.23× |
| `ec2/efs_plain` | `stat` | 703.4 µs, 742.6 µs, 1.06 ms | 1.51× |
| `ec2/efs_plain` | `create` | 7.26 ms, 6.42 ms, 7.47 ms | 1.16× |
| `ec2/instance_store` | `stat` | 1.3 µs, 1.2 µs, 1.2 µs | 1.03× |
| `ec2/instance_store` | `create` | 19.3 µs, 19.2 µs, 19.6 µs | 1.02× |
| `fargate/efs` | `stat` | 881.4 µs, 695.2 µs, 1.03 ms | 1.49× |
| `fargate/efs` | `create` | 7.74 ms, 6.38 ms, 7.34 ms | 1.21× |
| `fargate/efs_plain` | `stat` | 746.4 µs, 659.9 µs, 1.17 ms | 1.77× |
| `fargate/efs_plain` | `create` | 7.35 ms, 6.25 ms, 7.36 ms | 1.18× |
| `fargate/ephemeral` | `stat` | 1.8 µs, 2.0 µs, 1.9 µs | 1.09× |
| `fargate/ephemeral` | `create` | 22.1 µs, 23.0 µs, 21.7 µs | 1.06× |
