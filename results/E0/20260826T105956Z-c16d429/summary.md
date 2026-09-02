# E0 census summary

Run: `20260826T105956Z-c16d429`

Counts are filesystem syscalls per single request. E0 measures counts, not
latency — these are the multiplier that per-op latency gets multiplied by.

| profile | endpoint.cohort | total | stat | open | unique paths | component ops | failed |
|---|---|--:|--:|--:|--:|--:|--:|
| rep-1/max | cart.cold | 16356 | 11127 | 4984 | 9034 | 2012 | 10.7% |
| rep-1/max | cart.warm | 5023 | 4299 | 517 | 3020 | 233 | 33.4% |
| rep-1/max | home.cold | 15426 | 10590 | 4591 | 8827 | 1893 | 10.9% |
| rep-1/max | home.warm | 4305 | 3902 | 196 | 2835 | 127 | 37.2% |
| rep-1/max | product.cold | 15603 | 10706 | 4649 | 8947 | 1903 | 11.1% |
| rep-1/max | product.warm | 4354 | 3950 | 194 | 2882 | 127 | 37.9% |
| rep-1/max | wp-admin.cold | 15185 | 10344 | 4601 | 8705 | 1909 | 10.9% |
| rep-1/max | wp-admin.warm | 4233 | 3746 | 285 | 2649 | 164 | 37.1% |
| rep-1/naive | cart.cold | 16356 | 11127 | 4984 | 9034 | 2012 | 10.7% |
| rep-1/naive | cart.warm | 5905 | 4371 | 1291 | 3582 | 233 | 29.6% |
| rep-1/naive | home.cold | 15426 | 10590 | 4591 | 8827 | 1893 | 10.9% |
| rep-1/naive | home.warm | 5115 | 3974 | 898 | 3329 | 127 | 32.8% |
| rep-1/naive | product.cold | 15603 | 10706 | 4649 | 8947 | 1903 | 11.1% |
| rep-1/naive | product.warm | 5224 | 4022 | 956 | 3431 | 127 | 33.0% |
| rep-1/naive | wp-admin.cold | 15185 | 10344 | 4601 | 8705 | 1909 | 10.9% |
| rep-1/naive | wp-admin.warm | 5127 | 3760 | 1158 | 3438 | 164 | 30.9% |
| rep-1/tuned | cart.cold | 16356 | 11127 | 4984 | 9034 | 2012 | 10.7% |
| rep-1/tuned | cart.warm | 5023 | 4299 | 517 | 3020 | 233 | 33.4% |
| rep-1/tuned | home.cold | 15426 | 10590 | 4591 | 8827 | 1893 | 10.9% |
| rep-1/tuned | home.warm | 4305 | 3902 | 196 | 2835 | 127 | 37.2% |
| rep-1/tuned | product.cold | 15603 | 10706 | 4649 | 8947 | 1903 | 11.1% |
| rep-1/tuned | product.warm | 4354 | 3950 | 194 | 2882 | 127 | 37.9% |
| rep-1/tuned | wp-admin.cold | 15152 | 10321 | 4591 | 8692 | 1906 | 10.9% |
| rep-1/tuned | wp-admin.warm | 4233 | 3746 | 285 | 2649 | 164 | 37.1% |

