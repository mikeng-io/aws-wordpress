# E0 census summary

Run: `20260902T091846Z-158f9cd`

Counts are filesystem syscalls per single request. E0 measures counts, not
latency — these are the multiplier that per-op latency gets multiplied by.

| profile | endpoint.cohort | total | stat | open | unique paths | component ops | failed |
|---|---|--:|--:|--:|--:|--:|--:|
| rep-1/max | cart.cold | 5371 | 4539 | 595 | 3202 | 249 | 32.6% |
| rep-1/max | cart.warm | 5041 | 4317 | 517 | 3033 | 233 | 33.5% |
| rep-1/max | checkout.cold | 5319 | 4496 | 586 | 3192 | 251 | 32.7% |
| rep-1/max | checkout.warm | 4985 | 4271 | 507 | 3021 | 233 | 33.6% |
| rep-1/max | home.cold | 15457 | 10614 | 4598 | 8842 | 1891 | 10.9% |
| rep-1/max | home.warm | 4324 | 3921 | 196 | 2849 | 127 | 37.4% |
| rep-1/max | product.cold | 15629 | 10729 | 4652 | 8962 | 1901 | 11.2% |
| rep-1/max | product.warm | 4376 | 3972 | 194 | 2899 | 127 | 38.1% |
| rep-1/max | wp-admin.cold | 15176 | 10346 | 4590 | 8703 | 1904 | 10.9% |
| rep-1/max | wp-admin.warm | 4250 | 3763 | 285 | 2661 | 164 | 37.3% |
| rep-1/naive | cart.cold | 6118 | 4562 | 1313 | 3663 | 244 | 29.1% |
| rep-1/naive | cart.warm | 5941 | 4389 | 1309 | 3612 | 233 | 29.6% |
| rep-1/naive | cart.warm-aged | 5981 | 4418 | 1320 | 3630 | 236 | 29.5% |
| rep-1/naive | checkout.cold | 6079 | 4535 | 1301 | 3664 | 251 | 29.2% |
| rep-1/naive | checkout.warm | 5884 | 4343 | 1298 | 3600 | 233 | 29.7% |
| rep-1/naive | checkout.warm-aged | 5891 | 4349 | 1299 | 3605 | 233 | 29.7% |
| rep-1/naive | home.cold | 15755 | 10805 | 4700 | 8969 | 1919 | 10.9% |
| rep-1/naive | home.warm | 5168 | 3942 | 1008 | 3401 | 127 | 31.7% |
| rep-1/naive | home.warm-aged | 8753 | 7526 | 1008 | 6275 | 128 | 18.7% |
| rep-1/naive | product.cold | 15657 | 10747 | 4662 | 8978 | 1903 | 11.1% |
| rep-1/naive | product.warm | 5265 | 4044 | 975 | 3466 | 127 | 33.0% |
| rep-1/naive | product.warm-aged | 8942 | 7720 | 975 | 6432 | 128 | 19.5% |
| rep-1/naive | wp-admin.cold | 15226 | 10380 | 4602 | 8709 | 1917 | 11.2% |
| rep-1/naive | wp-admin.warm | 5141 | 3777 | 1155 | 3452 | 164 | 31.1% |
| rep-1/naive | wp-admin.warm-aged | 8566 | 7201 | 1155 | 6066 | 165 | 18.7% |
| rep-1/tuned | cart.cold | 5371 | 4539 | 595 | 3202 | 249 | 32.6% |
| rep-1/tuned | cart.warm | 5041 | 4317 | 517 | 3033 | 233 | 33.5% |
| rep-1/tuned | cart.warm-aged | 5125 | 4401 | 517 | 3110 | 233 | 33.0% |
| rep-1/tuned | checkout.cold | 5319 | 4496 | 586 | 3192 | 251 | 32.7% |
| rep-1/tuned | checkout.warm | 4985 | 4271 | 507 | 3021 | 233 | 33.6% |
| rep-1/tuned | checkout.warm-aged | 5070 | 4356 | 507 | 3098 | 233 | 33.1% |
| rep-1/tuned | home.cold | 15457 | 10614 | 4598 | 8842 | 1891 | 10.9% |
| rep-1/tuned | home.warm | 4324 | 3921 | 196 | 2849 | 127 | 37.4% |
| rep-1/tuned | home.warm-aged | 8777 | 8357 | 206 | 6283 | 131 | 18.6% |
| rep-1/tuned | product.cold | 15629 | 10729 | 4652 | 8962 | 1901 | 11.2% |
| rep-1/tuned | product.warm | 4376 | 3972 | 194 | 2899 | 127 | 38.1% |
| rep-1/tuned | product.warm-aged | 8885 | 8464 | 204 | 6385 | 131 | 18.9% |
| rep-1/tuned | wp-admin.cold | 15176 | 10346 | 4590 | 8703 | 1904 | 10.9% |
| rep-1/tuned | wp-admin.warm | 4250 | 3763 | 285 | 2661 | 164 | 37.3% |
| rep-1/tuned | wp-admin.warm-aged | 8583 | 8089 | 285 | 6074 | 165 | 18.6% |

