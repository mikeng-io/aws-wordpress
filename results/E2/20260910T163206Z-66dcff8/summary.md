| Tier | stat p50 | stat_enoent p50 | open_read p50 | create p50 | unlink p50 |
|---|---|---|---|---|---|
| `ec2/ebs` | 1.3 µs | 3.3 µs | 5.3 µs | 19.9 µs | 7.6 µs |
| `ec2/efs` | 814.3 µs | 1.07 ms | 903.6 µs | 7.34 ms | 3.00 ms |
| `ec2/instance_store` | 1.3 µs | 2.9 µs | 5.2 µs | 19.7 µs | 7.5 µs |
| `fargate/efs` | 777.7 µs | 858.1 µs | 679.3 µs | 6.99 ms | 2.93 ms |
| `fargate/ephemeral` | 1.8 µs | 4.0 µs | 5.7 µs | 21.9 µs | 11.4 µs |

### Prediction 5 (pre-registered, graded mechanically)

**PARTIALLY SUPPORTED** — 1/4 checks met.

| Op | Expected | Observed | Ratio |
|---|---|---|--:|
| `stat` | TIE | TIE | 1.43× |
| `create` | SEPARATED | TIE ⚠ | 1.11× |
| `unlink` | SEPARATED | INCONCLUSIVE ⚠ | 1.52× |
| `open_read` | SEPARATED | TIE ⚠ | 1.1× |

### Between-replication agreement (median of each rep)

| Tier | op | per-rep medians | spread |
|---|---|---|--:|
| `ec2/ebs` | `stat` | 1.3 µs, 1.3 µs, 1.3 µs | 1.01× |
| `ec2/ebs` | `create` | 20.0 µs, 19.9 µs, 19.8 µs | 1.01× |
| `ec2/efs` | `stat` | 707.3 µs, 957.6 µs, 1.04 ms | 1.47× |
| `ec2/efs` | `create` | 6.46 ms, 8.67 ms, 7.48 ms | 1.34× |
| `ec2/instance_store` | `stat` | 1.3 µs, 1.3 µs, 1.3 µs | 1.00× |
| `ec2/instance_store` | `create` | 19.3 µs, 19.9 µs, 19.7 µs | 1.03× |
| `fargate/efs` | `stat` | 737.4 µs, 797.1 µs, 888.2 µs | 1.20× |
| `fargate/efs` | `create` | 6.59 ms, 8.06 ms, 7.02 ms | 1.22× |
| `fargate/ephemeral` | `stat` | 1.8 µs, 1.9 µs, 1.8 µs | 1.03× |
| `fargate/ephemeral` | `create` | 21.9 µs, 22.1 µs, 21.7 µs | 1.02× |
