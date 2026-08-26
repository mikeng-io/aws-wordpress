# E0 census summary

Run: `20260826T105956Z-c16d429`

Counts are filesystem syscalls per single request. E0 measures counts, not
latency — these are the multiplier that per-op latency gets multiplied by.

| profile | endpoint.cohort | total | stat | open | unique paths | component ops | failed |
|---|---|--:|--:|--:|--:|--:|--:|
| max | cart.cold | 16356 | 11127 | 4984 | 9034 | 2244 | 10.7% |
| max | cart.warm | 5023 | 4299 | 517 | 3021 | 427 | 33.4% |
| max | home.cold | 15426 | 10590 | 4591 | 8827 | 2125 | 10.9% |
| max | home.warm | 4305 | 3902 | 196 | 2836 | 321 | 37.2% |
| max | product.cold | 15603 | 10706 | 4649 | 8947 | 2138 | 11.1% |
| max | product.warm | 4354 | 3950 | 194 | 2883 | 324 | 37.9% |
| max | wp-admin.cold | 15185 | 10344 | 4601 | 8705 | 2140 | 10.9% |
| max | wp-admin.warm | 4233 | 3746 | 285 | 2651 | 357 | 37.1% |
| naive | cart.cold | 16356 | 11127 | 4984 | 9034 | 2244 | 10.7% |
| naive | cart.warm | 5905 | 4371 | 1291 | 3583 | 463 | 29.6% |
| naive | home.cold | 15426 | 10590 | 4591 | 8827 | 2125 | 10.9% |
| naive | home.warm | 5115 | 3974 | 898 | 3330 | 357 | 32.8% |
| naive | product.cold | 15603 | 10706 | 4649 | 8947 | 2138 | 11.1% |
| naive | product.warm | 5224 | 4022 | 956 | 3432 | 360 | 33.0% |
| naive | wp-admin.cold | 15185 | 10344 | 4601 | 8705 | 2140 | 10.9% |
| naive | wp-admin.warm | 5127 | 3760 | 1158 | 3440 | 364 | 30.9% |
| tuned | cart.cold | 16356 | 11127 | 4984 | 9034 | 2244 | 10.7% |
| tuned | cart.warm | 5023 | 4299 | 517 | 3021 | 427 | 33.4% |
| tuned | home.cold | 15426 | 10590 | 4591 | 8827 | 2125 | 10.9% |
| tuned | home.warm | 4305 | 3902 | 196 | 2836 | 321 | 37.2% |
| tuned | product.cold | 15603 | 10706 | 4649 | 8947 | 2138 | 11.1% |
| tuned | product.warm | 4354 | 3950 | 194 | 2883 | 324 | 37.9% |
| tuned | wp-admin.cold | 15152 | 10321 | 4591 | 8692 | 2137 | 10.9% |
| tuned | wp-admin.warm | 4233 | 3746 | 285 | 2651 | 357 | 37.1% |

