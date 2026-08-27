# E0 aggregate

Run: `20260827T185901Z-bff2d22`

Median across repetitions, with min-max range. Counts are filesystem syscalls
per single request. E0 measures counts, not latency.

| profile | endpoint | cohort | n | total (median) | range | stat | open | ENOENT-ish fails |
|---|---|---|--:|--:|---|--:|--:|--:|
| max | cart | cold | 10 | 16356 | 16356–16356 | 11127 | 4984 | 1752 |
| max | cart | warm | 10 | 5023 | 5023–5023 | 4299 | 517 | 1675 |
| max | home | cold | 10 | 15426 | 15426–15426 | 10590 | 4591 | 1680 |
| max | home | warm | 10 | 4305 | 4305–4305 | 3902 | 196 | 1603 |
| max | product | cold | 10 | 15603 | 15603–15603 | 10706 | 4649 | 1727 |
| max | product | warm | 10 | 4354 | 4354–4354 | 3950 | 194 | 1650 |
| max | wp-admin | cold | 10 | 15185 | 15152–15185 | 10344 | 4601 | 1649 |
| max | wp-admin | warm | 10 | 4233 | 4233–4233 | 3746 | 285 | 1571 |
| naive | cart | cold | 10 | 16356 | 16356–16356 | 11127 | 4984 | 1752 |
| naive | cart | warm | 10 | 5905 | 5905–5905 | 4371 | 1291 | 1747 |
| naive | cart | warm-aged | 3 | 9598 | 9598–9598 | 8063 | 1291 | 1749 |
| naive | home | cold | 10 | 15426 | 15426–15811 | 10590 | 4591 | 1680 |
| naive | home | warm | 10 | 5115 | 5115–5135 | 3974 | 898 | 1675 |
| naive | home | warm-aged | 3 | 8808 | 8784–8841 | 7666 | 908 | 1677 |
| naive | product | cold | 10 | 15603 | 15603–15636 | 10706 | 4649 | 1727 |
| naive | product | warm | 10 | 5224 | 5224–5224 | 4022 | 956 | 1722 |
| naive | product | warm-aged | 3 | 8917 | 8917–8917 | 7714 | 956 | 1724 |
| naive | wp-admin | cold | 10 | 15182 | 15152–15186 | 10342 | 4600 | 1649 |
| naive | wp-admin | warm | 10 | 5127 | 5127–5127 | 3760 | 1158 | 1585 |
| naive | wp-admin | warm-aged | 3 | 8560 | 8560–8560 | 7192 | 1158 | 1587 |
| tuned | cart | cold | 10 | 16389 | 16356–16389 | 11150 | 4994 | 1752 |
| tuned | cart | warm | 10 | 5023 | 5023–5023 | 4299 | 517 | 1675 |
| tuned | cart | warm-aged | 3 | 9541 | 9541–9541 | 8800 | 527 | 1689 |
| tuned | home | cold | 10 | 15426 | 15426–15459 | 10590 | 4591 | 1680 |
| tuned | home | warm | 10 | 4305 | 4305–4305 | 3902 | 196 | 1603 |
| tuned | home | warm-aged | 3 | 8751 | 8738–8751 | 8331 | 206 | 1617 |
| tuned | product | cold | 10 | 15603 | 15603–15603 | 10706 | 4649 | 1727 |
| tuned | product | warm | 10 | 4354 | 4354–4354 | 3950 | 194 | 1650 |
| tuned | product | warm-aged | 3 | 8860 | 8860–8860 | 8439 | 204 | 1664 |
| tuned | wp-admin | cold | 10 | 15185 | 15152–15185 | 10344 | 4601 | 1649 |
| tuned | wp-admin | warm | 10 | 4233 | 4233–4233 | 3746 | 285 | 1571 |
| tuned | wp-admin | warm-aged | 3 | 8577 | 8577–8577 | 8083 | 285 | 1585 |

