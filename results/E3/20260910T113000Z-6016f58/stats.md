# E3 distribution statistics

Run `20260910T113000Z-6016f58` · 3 reps pooled · distribution-free median CIs.

Latency is log-normal, so the geometric mean is reported rather than an
arithmetic mean, which the tail would dominate. `tail` is p99/p50: near 1.0 is
a tight, local-disk-shaped distribution; large means a heavy tail.

| op | mount | n | median (95% CI) | geo-mean | p95 | p99 | tail p99/p50 |
|---|---|--:|--:|--:|--:|--:|--:|
| create | local | 3,000 | 38.5 µs (38.1 µs–39.1 µs) | 38.8 µs | 55.6 µs | 104.1 µs | 2.7× |
| create | efs | 3,000 | 7.78 ms (7.73 ms–7.83 ms) | 8.09 ms | 11.37 ms | 15.62 ms | 2.01× |
| open_read | local | 3,000 | 11.3 µs (11.2 µs–11.3 µs) | 12.2 µs | 17.7 µs | 628.5 µs | 55.83× |
| open_read | efs | 3,000 | 1.03 ms (1.02 ms–1.04 ms) | 1.13 ms | 1.91 ms | 2.62 ms | 2.55× |
| stat | local | 3,000 | 3.1 µs (3.1 µs–3.1 µs) | 3.2 µs | 3.8 µs | 4.7 µs | 1.51× |
| stat | efs | 3,000 | 1.04 ms (1.03 ms–1.05 ms) | 256.9 µs | 1.38 ms | 1.58 ms | 1.52× |
| stat_enoent | local | 60 | 7.2 µs (7.1 µs–7.4 µs) | 7.5 µs | 19.9 µs | 20.9 µs | 2.88× |
| stat_enoent | efs | 60 | 1.24 ms (1.19 ms–1.29 ms) | 1.27 ms | 1.68 ms | 3.41 ms | 2.76× |
| unlink | local | 3,000 | 19.8 µs (19.6 µs–19.9 µs) | 19.8 µs | 24.6 µs | 30.7 µs | 1.55× |
| unlink | efs | 3,000 | 3.32 ms (3.30 ms–3.33 ms) | 3.42 ms | 4.20 ms | 7.17 ms | 2.16× |

## EFS penalty by operation

| op | median ratio | p99 ratio |
|---|--:|--:|
| create | 201.8× | 150.0× |
| open_read | 91.5× | 4.2× |
| stat | 333.6× | 334.6× |
| stat_enoent | 170.5× | 163.1× |
| unlink | 167.9× | 233.7× |

## Between-rep agreement

Three independent Fargate task runs. Spread is (max−min)/mean of the
per-rep medians - the check on whether any single run is quotable.

| op | mount | rep medians | spread |
|---|---|---|--:|
| create | local | 38.2 µs / 38.5 µs / 38.9 µs | 1.7% |
| create | efs | 7.59 ms / 8.08 ms / 7.60 ms | 6.4% |
| open_read | local | 11.3 µs / 11.5 µs / 10.9 µs | 4.9% |
| open_read | efs | 1.03 ms / 1.12 ms / 898.9 µs | 21.9% |
| stat | local | 3.1 µs / 3.1 µs / 3.1 µs | 1.8% |
| stat | efs | 1.08 ms / 1.17 ms / 954.8 µs | 20.2% |
| stat_enoent | local | 7.2 µs / 7.3 µs / 7.2 µs | 1.2% |
| stat_enoent | efs | 1.29 ms / 1.19 ms / 1.24 ms | 7.6% |
| unlink | local | 19.7 µs / 19.1 µs / 20.5 µs | 6.9% |
| unlink | efs | 3.20 ms / 3.48 ms / 3.32 ms | 8.3% |

