# Offline publication verification

This is not an additional experiment replication and makes no AWS request.

- Initial pass: 14/19 checks passed; five E5 replays failed to import an omitted
  pinned statistics helper. See initial-verification.json and the sanitised error.
- Final pass: 19/19 checks PASS. Two expensive E0 checks reuse the initial PASS
  after all frozen input hashes and the census/aggregate source hashes match;
  the other 17 checks execute again. The prior receipt hash binds the reuse.
- 5,082 existing Git-tracked result files hash identically before/after.
- inputs.sha256.json covers those original inputs, not these newly added receipts.
- Current diagnostics may add fields; every recorded JSON field must agree.
  The published E2 HTML chart reproduces byte-for-byte.
- Historical E5 algorithm files are matched to recorded hashes. Transitive E2/E3
  helpers are restored from the matching revision and their hashes are recorded;
  those helper hashes were not present in the original E5 report.
- source_head is the prior data/repository head. This offline utility was being
  added during closeout; analysis_sha256 identifies its actual source. This is
  not a claim of a new clean-apparatus AWS measurement.
- Verbose output is retained locally, excluded from publication to avoid temporary
  host paths. Full fresh replay is available through make study-verify with a new
  OUT directory; no cached E0 result is required by the default command.
