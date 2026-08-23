# H7 — At equal p95, the cheapest storage line item does not win

**Status:** `UNTESTED`

## Claim

Comparing configurations on monthly cost alone, without holding latency constant,
systematically favours slow storage. At an equal p95 target, the ranking inverts or
scrambles.

## Normalisations to report

| Column | Question answered |
|---|---|
| Idle floor ($/mo at zero traffic) | What you pay at 3am |
| $/1k requests at fixed tiers | Cost at 100k / 1M / 10M req/mo |
| **$/1k requests at equal p95** | Cost to hit the *same* latency target |
| $ per ms of TTFB bought | Whether faster storage is worth its premium |

The third is the headline. Comparing a 200 ms configuration against a 900 ms one on
price alone is the standard dishonest benchmark.

## Method

Cost is computed from live AWS Price List Query API rates multiplied by *measured*
utilisation from the runs — real ACU-hours, real GB transferred, real request
counts. Never hand-typed. Every table records its pricing snapshot date.

## Line items that decide outcomes and are usually missed

- EFS Elastic Throughput bills per GB read/written — a metadata storm may exceed
  the storage line. Must be measured.
- S3 request pricing under cache-backed filesystems can dwarf storage entirely.
- NAT Gateway data processing: S3-backed storage without a gateway VPC endpoint
  bleeds money silently. The model must expose this trap.
- Cross-AZ traffic on multi-AZ FSx.
- Spot's real discount is meaningless without a measured interruption rate, and an
  interruption mid-write is a correctness question, not just availability.

## Kill condition

**H7 is refuted if** ranking by raw monthly cost matches ranking by cost at equal
p95.
