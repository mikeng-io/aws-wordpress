# Isolation candidate v1 — live validation

**PASS_CANDIDATE_ONLY; n=1; no formal study verdict.**

The single candidate launched from `647a81139a60fa5564055207d1ca68d8020b8ec2`
after Mike explicitly raised the total E5 study ceiling to US$20. The protocol
and unchanged acceptance gates were declared before launch in the
[method amendment](../../../experiments/E5-attribute-cache/method-amendments/20261027-isolation-v1/README.md).
No automatic retry or formal replication is included.

## Measured findings

- All **21 diagnostic cells** have valid inputs and meet the candidate gates.
- Quiet idle lasted **360.037708844 seconds**. All five EFS TLS roots have zero
  GETATTR, LOOKUP and ACCESS increments; path-filtered helper statx/newfstatat
  root calls are also zero. This does not imply every NFS protocol message is absent.
- All 12 measured NFS cells have exact phase/window RPC reconciliation, with
  zero residual GETATTR/LOOKUP/ACCESS. No residual subtraction was used.
- Lustre 0.1s, 1s and 10s cells each have **0%** late requests. Their mean
  request service wall times are 8.905ms, 9.759ms and 10.339ms respectively.
- TLS 0.1s has **2/3600** requests later than delta/2 (**0.0556%**); every
  other cell has zero such late requests. The hard limit remains 5%.
- The 15-cell non-Lustre batch completed before the three sequential Lustre/EBS
  pairs. Exact cell identities, warmups, measured windows and observed child-reap
  ordering all pass. Same-time EBS controls use separate fresh subtrees.
- Effective readahead remained 15360kB on all five TLS roots, and the lifecycle
  watchdog retained its PID. Both temporary helper settings and the full original
  configuration bytes were restored successfully.

The runtime used c7gd.large, AL2023 with efs-utils 3.3.2-1 and Lustre client
2.15.6-32. [Image provenance](image-provenance.json) records the actual ECS digest,
verified while this run's task was running under the owned stack.

## Meaning and limits

This supports the **candidate measurement isolation** under the tested quiet
profile and schedule. It does not establish a fixed Lustre lock-cache capacity,
a CPU-only cause, a general performance ranking or an EFS production default.
The profile explicitly disables readahead verification and periodic stunnel
health probing while retaining lifecycle supervision.

Windows are short (360s non-Lustre and 180s Lustre, each after 60s warmup), with
one deployment. Different batches have different background loads, so their wall
times are not a fair cross-filesystem comparison. The formal cohort-A expiry/
first-touch method, registered 300s/600s windows and formal P7 matched-reference
binding have not been validated or amended by this candidate result.

Next work is an explicit versioned formal-method amendment and grader/reference
binding, verified offline before deciding any separately authorised paid
replications. The original pilot and diagnostic stay frozen.

## Evidence and cleanup

[Analysis](analysis-v1.json) and [analysis provenance](analysis-provenance.json)
retain the strict checker output and source hashes. Raw protocol and request data
are under `rep-1/diagnostic/`. Benchmark and collector both exited 0. The stack reached DELETE_COMPLETE; two
owned FSx final backups and the diagnostics bucket were removed. The host guard
completed its sustained-empty verification without deadline handover. The independent [teardown inventory](teardown.json) checks 18 regions × 11
service inventories (198 checks), with zero API errors, zero E5 matches and no
retained diagnostics bucket. [Validation](validation.json) records unchanged raw
bytes, 642 unchanged prior frozen files, byte-identical analysis reproduction and
all six conformance receipts (11 checks per tier).

[Cost review](cost-review.json): total ceiling US$20; prelaunch conservative
planning proxy US$11.4827. Stack lifetime was 64.7943 minutes. The candidate
standing envelope including rounded endpoint hours is US$1.1415 (plus $0.50 ancillary
reserve). This is not actual E5 billing or a verified remaining balance; Cost
Explorer remains estimated and allocation is unverified.

[Manifest](manifest.json) preserves file sizes and SHA-256 hashes, excluding itself.
