# E0 aggregate

Run: `20260902T105746Z-f62a686`

Median across repetitions, with min-max range. Counts are filesystem syscalls
per single request. E0 measures counts, not latency.

| profile | endpoint | cohort | n | total (median) | range | stat | open | ENOENT-ish fails |
|---|---|---|--:|--:|---|--:|--:|--:|
| max | cart | cold | 10 | 5371 | 5371–5371 | 4539 | 595 | 1753 |
| max | cart | warm | 10 | 5041 | 5041–5074 | 4317 | 517 | 1688 |
| max | checkout | cold | 10 | 5319 | 5319–5319 | 4496 | 586 | 1740 |
| max | checkout | warm | 10 | 4985 | 4985–4985 | 4271 | 507 | 1675 |
| max | home | cold | 10 | 15457 | 15457–15490 | 10614 | 4598 | 1693 |
| max | home | warm | 10 | 4324 | 4324–4324 | 3921 | 196 | 1616 |
| max | product | cold | 10 | 15629 | 15629–15629 | 10729 | 4652 | 1744 |
| max | product | warm | 10 | 4376 | 4376–4409 | 3972 | 194 | 1667 |
| max | wp-admin | cold | 10 | 15176 | 15143–15176 | 10346 | 4590 | 1662 |
| max | wp-admin | warm | 10 | 4250 | 4250–4259 | 3763 | 285 | 1584 |
| naive | cart | cold | 10 | 6104 | 6104–6132 | 4551 | 1310 | 1765 |
| naive | cart | warm | 10 | 5941 | 5941–5941 | 4389 | 1309 | 1760 |
| naive | cart | warm-aged | 3 | 5948 | 5948–5948 | 4395 | 1310 | 1765 |
| naive | checkout | cold | 10 | 6050 | 6050–6082 | 4508 | 1299 | 1752 |
| naive | checkout | warm | 10 | 5884 | 5884–5884 | 4343 | 1298 | 1747 |
| naive | checkout | warm-aged | 3 | 5891 | 5891–5891 | 4349 | 1299 | 1752 |
| naive | home | cold | 10 | 15457 | 15457–15490 | 10614 | 4598 | 1693 |
| naive | home | warm | 10 | 5157 | 5157–5157 | 3993 | 921 | 1688 |
| naive | home | warm-aged | 3 | 8834 | 8834–8867 | 7669 | 921 | 1690 |
| naive | product | cold | 10 | 15629 | 15629–15924 | 10729 | 4652 | 1744 |
| naive | product | warm | 10 | 5265 | 5265–5265 | 4044 | 975 | 1739 |
| naive | product | warm-aged | 3 | 8942 | 8942–8942 | 7720 | 975 | 1741 |
| naive | wp-admin | cold | 10 | 15174 | 15143–15176 | 10345 | 4590 | 1662 |
| naive | wp-admin | warm | 10 | 5140 | 5140–5140 | 3777 | 1154 | 1598 |
| naive | wp-admin | warm-aged | 3 | 8566 | 8566–8566 | 7202 | 1154 | 1600 |
| tuned | cart | cold | 10 | 5371 | 5371–5371 | 4539 | 595 | 1753 |
| tuned | cart | warm | 10 | 5041 | 5041–5041 | 4317 | 517 | 1688 |
| tuned | cart | warm-aged | 3 | 5125 | 5125–5125 | 4401 | 517 | 1693 |
| tuned | checkout | cold | 10 | 5319 | 5319–5352 | 4496 | 586 | 1740 |
| tuned | checkout | warm | 10 | 4985 | 4985–4985 | 4271 | 507 | 1675 |
| tuned | checkout | warm-aged | 3 | 5070 | 5070–5070 | 4356 | 507 | 1680 |
| tuned | home | cold | 10 | 15457 | 15457–15490 | 10614 | 4598 | 1693 |
| tuned | home | warm | 10 | 4324 | 4324–4324 | 3921 | 196 | 1616 |
| tuned | home | warm-aged | 3 | 8777 | 8777–8777 | 8357 | 206 | 1630 |
| tuned | product | cold | 10 | 15629 | 15629–15662 | 10729 | 4652 | 1744 |
| tuned | product | warm | 10 | 4376 | 4376–4376 | 3972 | 194 | 1667 |
| tuned | product | warm-aged | 3 | 8885 | 8885–8885 | 8464 | 204 | 1681 |
| tuned | wp-admin | cold | 10 | 15176 | 15143–15176 | 10346 | 4590 | 1662 |
| tuned | wp-admin | warm | 10 | 4250 | 4250–4250 | 3763 | 285 | 1584 |
| tuned | wp-admin | warm-aged | 3 | 8583 | 8583–8583 | 8089 | 285 | 1598 |

