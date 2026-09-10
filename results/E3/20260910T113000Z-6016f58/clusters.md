# E3 cluster analysis — is the distribution one population or two?

Run `20260910T113000Z-6016f58`. Method: 1-D k-means (k=2) on log10(latency),
deterministically initialised at the 10th/90th percentiles. A split counts as
bimodal only if the centroids differ by ≥0.5 in log10
(≥3.2×) and each cluster holds ≥2% of the sample.

| op | mount | n | verdict | separation | fast cluster | slow cluster |
|---|---|--:|---|--:|---|---|
| stat | local | 3,000 | unimodal | 1.5× | — | — |
| stat | efs | 3,000 | bimodal | 415.4× | 24.4% @ 2.6 µs | 75.6% @ 1.11 ms |
| stat_enoent | local | 60 | unimodal | 2.9× | — | — |
| stat_enoent | efs | 60 | unimodal | 1.4× | — | — |
| open_read | local | 3,000 | unimodal | 64.3× | — | — |
| open_read | efs | 3,000 | unimodal | 1.8× | — | — |
| create | local | 3,000 | unimodal | 1.6× | — | — |
| create | efs | 3,000 | unimodal | 1.5× | — | — |
| unlink | local | 3,000 | unimodal | 1.3× | — | — |
| unlink | efs | 3,000 | unimodal | 1.9× | — | — |

