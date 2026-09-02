# E0 aggregate

Run: `20260902T091846Z-158f9cd`

Median across repetitions, with min-max range. Counts are filesystem syscalls
per single request. E0 measures counts, not latency.

| profile | endpoint | cohort | n | total (median) | range | stat | open | ENOENT-ish fails |
|---|---|---|--:|--:|---|--:|--:|--:|
| max | cart | cold | 1 | 5371 | 5371–5371 | 4539 | 595 | 1753 |
| max | cart | warm | 1 | 5041 | 5041–5041 | 4317 | 517 | 1688 |
| max | checkout | cold | 1 | 5319 | 5319–5319 | 4496 | 586 | 1740 |
| max | checkout | warm | 1 | 4985 | 4985–4985 | 4271 | 507 | 1675 |
| max | home | cold | 1 | 15457 | 15457–15457 | 10614 | 4598 | 1693 |
| max | home | warm | 1 | 4324 | 4324–4324 | 3921 | 196 | 1616 |
| max | product | cold | 1 | 15629 | 15629–15629 | 10729 | 4652 | 1744 |
| max | product | warm | 1 | 4376 | 4376–4376 | 3972 | 194 | 1667 |
| max | wp-admin | cold | 1 | 15176 | 15176–15176 | 10346 | 4590 | 1662 |
| max | wp-admin | warm | 1 | 4250 | 4250–4250 | 3763 | 285 | 1584 |
| naive | cart | cold | 1 | 6118 | 6118–6118 | 4562 | 1313 | 1781 |
| naive | cart | warm | 1 | 5941 | 5941–5941 | 4389 | 1309 | 1760 |
| naive | cart | warm-aged | 1 | 5981 | 5981–5981 | 4418 | 1320 | 1765 |
| naive | checkout | cold | 1 | 6079 | 6079–6079 | 4535 | 1301 | 1775 |
| naive | checkout | warm | 1 | 5884 | 5884–5884 | 4343 | 1298 | 1747 |
| naive | checkout | warm-aged | 1 | 5891 | 5891–5891 | 4349 | 1299 | 1752 |
| naive | home | cold | 1 | 15755 | 15755–15755 | 10805 | 4700 | 1719 |
| naive | home | warm | 1 | 5168 | 5168–5168 | 3942 | 1008 | 1638 |
| naive | home | warm-aged | 1 | 8753 | 8753–8753 | 7526 | 1008 | 1640 |
| naive | product | cold | 1 | 15657 | 15657–15657 | 10747 | 4662 | 1744 |
| naive | product | warm | 1 | 5265 | 5265–5265 | 4044 | 975 | 1739 |
| naive | product | warm-aged | 1 | 8942 | 8942–8942 | 7720 | 975 | 1741 |
| naive | wp-admin | cold | 1 | 15226 | 15226–15226 | 10380 | 4602 | 1702 |
| naive | wp-admin | warm | 1 | 5141 | 5141–5141 | 3777 | 1155 | 1598 |
| naive | wp-admin | warm-aged | 1 | 8566 | 8566–8566 | 7201 | 1155 | 1600 |
| tuned | cart | cold | 1 | 5371 | 5371–5371 | 4539 | 595 | 1753 |
| tuned | cart | warm | 1 | 5041 | 5041–5041 | 4317 | 517 | 1688 |
| tuned | cart | warm-aged | 1 | 5125 | 5125–5125 | 4401 | 517 | 1693 |
| tuned | checkout | cold | 1 | 5319 | 5319–5319 | 4496 | 586 | 1740 |
| tuned | checkout | warm | 1 | 4985 | 4985–4985 | 4271 | 507 | 1675 |
| tuned | checkout | warm-aged | 1 | 5070 | 5070–5070 | 4356 | 507 | 1680 |
| tuned | home | cold | 1 | 15457 | 15457–15457 | 10614 | 4598 | 1693 |
| tuned | home | warm | 1 | 4324 | 4324–4324 | 3921 | 196 | 1616 |
| tuned | home | warm-aged | 1 | 8777 | 8777–8777 | 8357 | 206 | 1630 |
| tuned | product | cold | 1 | 15629 | 15629–15629 | 10729 | 4652 | 1744 |
| tuned | product | warm | 1 | 4376 | 4376–4376 | 3972 | 194 | 1667 |
| tuned | product | warm-aged | 1 | 8885 | 8885–8885 | 8464 | 204 | 1681 |
| tuned | wp-admin | cold | 1 | 15176 | 15176–15176 | 10346 | 4590 | 1662 |
| tuned | wp-admin | warm | 1 | 4250 | 4250–4250 | 3763 | 285 | 1584 |
| tuned | wp-admin | warm-aged | 1 | 8583 | 8583–8583 | 8089 | 285 | 1598 |

