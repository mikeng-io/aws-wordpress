# Benchmark protocol

The standard every experiment in this study must meet. It exists because the
alternative — deciding per experiment what to measure and how to report it — is how
benchmarks become anecdotes.

This codifies established practice from performance-evaluation research rather than
inventing a house style: pre-registration (against HARKing — hypothesising after
results are known), the repetition-vs-replication distinction and confidence
intervals over central tendency (Georges et al., *Statistically Rigorous Java
Performance Evaluation*, OOPSLA 2007; Kalibera & Jones, *Rigorous Benchmarking in
Reasonable Time*, ISMM 2013), and artifact-availability norms from ACM's badging
scheme (data and the code that produced it ship together, and a third party can
recompute the result).

---

## 1. Design — before any code runs

**1.1 Pre-register.** A hypothesis file (`hypotheses/H<n>-<slug>.md`) exists before
the apparatus, and states:

- the **claim**, in falsifiable form
- the **proposed mechanism** — *why* the claim would be true
- the **prediction** — what the measurement should show, with direction and
  ideally magnitude
- the **kill condition** — the specific outcome that refutes it

A prediction written after seeing results is not a prediction. If a hypothesis is
revised mid-study, the revision is dated and the original left visible.

**1.2 Distinguish the claim from its mechanism.** They fail independently. E1
refuted H1's *mechanism* (shared NFS client) without settling H1's *claim* (cache
locality matters). Status vocabulary is therefore four-valued, not binary:
`UNTESTED` · `SUPPORTED` · `REFUTED` · `INCONCLUSIVE`, with `MECHANISM REFUTED,
CLAIM OPEN` available when they diverge.

**1.3 Identify the controlled variable.** State explicitly what differs between
arms and what is held constant. The strongest design measures both arms in the
*same* run on the *same* hardware (E3 measures local and EFS inside one task) so
that no environmental difference can explain the result.

**1.4 Declare cost and teardown** before deploying anything billable.

---

## 2. Execution — collecting the data

**2.1 Repetition ≠ replication.** Repeating an operation inside one process
measures that process. Running the whole experiment again, in a fresh environment,
measures the *system*. **Replication is required; repetition alone is not
sufficient.** E3 runs 3 independent Fargate tasks, not 3 loops in one task.

**2.2 Report between-replication agreement.** If independent runs disagree, no
single run's numbers are quotable. Publish the spread across replications
alongside the pooled figure. Disagreement is a finding, not something to average
away.

**2.3 Choose n against the variance, not by habit.** Deterministic measurements
(syscall counts) need few replications and no confidence intervals — E0's counts
have zero-width ranges at n=10, which is itself the justification for reporting
medians bare. Variable measurements (latency) need enough replications to
distinguish effect from noise, and must report dispersion.

**2.4 Separate warm-up from steady state,** and report which is being measured.
Cold-start and warm behaviour are different phenomena; blending them into one
average describes neither. Where a cache has a time-based window, a cohort that
crosses it is required — otherwise the tuned configuration is never exercised.

**2.5 Isolate the instrument.** Measure the narrowest thing that answers the
question. Bypass layers that would contribute noise (E0 talks to php-fpm directly
rather than through nginx). Time individual operations, not batches — a batch
average destroys the tail, which is usually the interesting part.

**2.6 Pre-flight the apparatus.** Before collecting, assert that the system is in
the state the experiment assumes, and **fail loudly if not**. A misconfigured run
that still produces plausible numbers is worse than a crash. This rule exists
because it happened: a stale `siteurl` made every request 301-redirect, and an
entire n=10 run silently measured redirects instead of pages.

**2.7 Sanity-check for impossible agreement.** Independent conditions producing
byte-identical results is evidence of a broken harness, not a real finding.

---

## 3. Statistics — what to compute, and when

**3.1 Decision table.** The data's character picks the treatment:

| Data character | Central tendency | Dispersion | Notes |
|---|---|---|---|
| **Deterministic** (counts) | median | observed range | No CI — there is no sampling variability to estimate. State this explicitly rather than omitting silently. |
| **Right-skewed continuous** (latency) | **median** + geometric mean | percentiles, IQR/median, p99/p50 | Never an arithmetic mean: the tail dominates it and it describes no typical operation. |
| **Proportions** (cache hit rate) | proportion | binomial CI | Report n alongside. |
| **Ratios between arms** | ratio of medians | both arms' CIs | A bare ratio without both distributions is not reportable. |

**3.2 Latency is log-normal.** Treat it multiplicatively: geometric mean, log-space
clustering, ratios rather than differences. A geometric mean that diverges sharply
from the median is diagnostic — it is what exposed E3's bimodality.

**3.3 Confidence intervals must be distribution-free** unless normality is
established. Use order-statistic intervals for medians, not t-intervals.

**3.4 Test for multiple populations before reporting a single centre.** A
distribution spanning orders of magnitude may be two mechanisms, not one spread.

**Standard method for this study:** 1-D k-means (k=2) on `log10(value)`,
deterministically initialised at the 10th and 90th percentiles (not random seeds —
the result must be reproducible).

**Bimodality is only declared when both gates pass:**
- centroid separation ≥ 0.5 in log10 (≥ 3.2×), **and**
- each cluster holds ≥ 2% of the sample.

The share gate is what prevents calling a handful of outliers a "population" —
E3's `open_read`/local showed 64× separation and was correctly reported unimodal.

**When bimodal, report per-cluster statistics and name the mechanism.** A cluster
without a physical explanation is a curve-fitting artifact. E3's fast cluster is
attributable: 2.6 µs is indistinguishable from local disk, so those calls never
left the kernel.

**3.5 Effect size, with the composition made explicit.** Where a headline number
weights clusters, show the weighting. E3's defensible ratio is ~271× (cache-aware),
not ~335× (naive pooled median); both are published, with the difference explained.

---

## 4. Storage — the canonical schema

```
results/E<n>/<run-id>/
├── meta.json           # provenance — required, schema below
├── rep-<k>/            # one directory per REPLICATION
│   └── <arm>.<ext>     # raw, unprocessed instrument output
├── <analysis>.json     # machine-readable derived statistics
└── <analysis>.md       # human-readable rendering of the same
```

**Run ID:** `<UTC timestamp>-<git sha>`. Timestamp orders runs; SHA binds the run
to the apparatus that produced it.

**4.1 Raw output is immutable.** Never edited, never regenerated. Derived analysis
*may* be regenerated when an analysis bug is fixed — that is not a violation,
because the ground truth is untouched and the recomputation is re-derivable. This
distinction has been exercised: a parsing bug was fixed and every run's derived
files recomputed, with zero raw files modified.

**4.2 `meta.json` required fields:**

| Field | Why |
|---|---|
| `experiment`, `run_id`, `utc` | identity |
| `measures` | what the numbers *are* (e.g. "syscall counts, not latency") — prevents citation out of context |
| region, AZ, instance/platform type, CPU architecture, kernel | environment |
| service configuration under test | e.g. EFS throughput mode, encryption, access-point use |
| `reps`, sample sizes | the basis of every statistic |
| workload shape | what was actually exercised |
| `git_sha`, `git_dirty` | apparatus version; a dirty tree is recorded, not hidden |
| `pricing_snapshot_date` | required for any cost figure, `null` otherwise |

**4.3 Analysis is code, in-repo, and re-runnable.** Every published statistic must
be recomputable by running a committed script against committed raw data. No
hand-transcribed numbers.

---

## 5. Reporting

**5.1 No claim without a result file.** Any performance or cost assertion cites a
path under `results/`. Anything else is marked `HYPOTHESIS` or `UNVERIFIED`.

**5.2 Label bounds as bounds.** A figure derived by composing measurements from
different experiments is an estimate with assumptions, not a measurement. Say
which, and state the assumptions.

**5.3 Report the shape, not just the centre.** Two percentiles are not a
distribution. Publish the percentile set, the dispersion, and the cluster structure
where it exists.

**5.4 Negative and null results ship** with the same prominence as positive ones.

**5.5 Corrections are appended, not overwritten.** When a result is superseded, the
finding records what changed and why, so the correction is auditable. Precedent:
E0's first-run interpretation was corrected twice, and both corrections remain
visible in the document.

**5.6 State threats to validity explicitly** — single region, single instance size,
workload divergence from production, anything else a reader would need to discount.

---

## 6. Per-experiment checklist

Before an experiment is called complete:

- [ ] Hypothesis pre-registered with prediction and kill condition
- [ ] Controlled variable stated; both arms measured under identical conditions
- [ ] Cost and teardown declared before deploying
- [ ] Pre-flight assertion that the system is in the assumed state
- [ ] ≥3 independent **replications** (not repetitions) for variable measurements
- [ ] Between-replication spread reported
- [ ] Warm-up / steady-state cohorts separated
- [ ] Statistics chosen per §3.1; dispersion reported; CIs distribution-free
- [ ] Multi-population test run; clusters reported with a named mechanism, or
      unimodality stated
- [ ] Raw output committed immutably under the §4 schema
- [ ] `meta.json` complete per §4.2
- [ ] Every published figure recomputable from committed scripts + data
- [ ] Threats to validity stated
- [ ] Hypothesis status updated with the four-valued vocabulary
- [ ] Billable resources destroyed and verified destroyed
