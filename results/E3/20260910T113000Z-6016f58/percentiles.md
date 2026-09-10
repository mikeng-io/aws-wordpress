# E3 latency percentiles: local ephemeral vs EFS

Same task, same benchmark, same tree shape - only the mount differs.

| op | mount | n | p50 | p95 | p99 | max | p99 ratio (EFS/local) |
|---|---|--:|--:|--:|--:|--:|--:|
| create | local | 1000 | 38,211 | 55,220 | 98,854 | 2,760,254 |  |
| create | efs | 1000 | 7,586,680 | 10,652,507 | 14,833,909 | 173,080,566 | 150.1x |
| open_read | local | 1000 | 11,299 | 18,748 | 710,607 | 20,057,689 |  |
| open_read | efs | 1000 | 1,028,331 | 1,857,665 | 2,096,432 | 5,373,736 | 3.0x |
| stat | local | 1000 | 3,085 | 3,676 | 4,635 | 14,391 |  |
| stat | efs | 1000 | 1,077,800 | 1,384,619 | 1,521,226 | 2,683,750 | 328.2x |
| stat_enoent | local | 20 | 7,245 | 20,898 | 20,898 | 20,898 |  |
| stat_enoent | efs | 20 | 1,286,109 | 1,793,764 | 1,793,764 | 1,793,764 | 85.8x |
| unlink | local | 1000 | 19,725 | 24,041 | 27,963 | 68,217 |  |
| unlink | efs | 1000 | 3,203,294 | 3,870,570 | 4,968,144 | 12,116,887 | 177.7x |

