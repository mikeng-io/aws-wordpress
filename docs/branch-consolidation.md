# Branch consolidation, 2026-10-27

Recorded so the topology decision is auditable rather than inferred from reflog.
No file under `results/` was modified. This document makes no performance or cost
claim.

## Starting state

`master` was at `4e0aef1`, 18 commits ahead of `origin/master` (`8806f8b`,
2026-09-19), and stopped at E5 attempt 2. The E5 work of 2026-10-26/27 was on
`chore/e5-pilot-preflight`, a straight descendant of that commit 24 commits long.
Nothing from E5 had been pushed.

## What became master

`chore/e5-pilot-preflight` (`804e13e`) was fast-forwarded onto `master`. The E5
specification line and every experiment result from the pilot, diagnostic,
isolation candidate and formal v3 runs entered `master` with it.

## Branches absorbed

| Branch | Tip | How it entered `master` |
|---|---|---|
| `chore/e5-pilot-preflight` | `804e13e` | fast-forward |
| `chore/e5-context-alignment` | `7c5a239` | already an ancestor of the pilot line |
| `fix/e5-measurement-gates` | `0116a84` | already an ancestor of the pilot line |
| `fix/e5-host-watchdog` | `71ece42` | already an ancestor of the pilot line |
| `claude/recursing-agnesi-775636` | `3516151` | already an ancestor of the pilot line |
| `claude/laughing-haibt-e5f411` | `4e0aef1` | already an ancestor (equal to the old `master`) |
| `claude/e5-local-check-port` | `6c654c5` | merge `6f8a664`, `-s ours` |
| `claude/e5-attribute-cache-spec` | `5c98c8a` | merge `bf30b99`, `-s ours` |

## Why the last two use `-s ours`

Both branches were built against `master` before the E5 specification merge, so
their trees would have replaced current apparatus with an earlier design. Deleting
them without a merge would have made their commits unreachable. `-s ours` records
the ancestry and keeps the current tree, which preserves both properties: nothing
is lost, and nothing is reverted.

**`claude/e5-local-check-port`.** Its two local-check runs,
`20261016T181153Z-725266b-leases-on` and `...-leases-off`, are byte-identical to
the copies already in `master`; the pilot line adds the 2026-10-26 probe runs. The
branch's grader and Makefile edits are superseded by later amendments.

**`claude/e5-attribute-cache-spec`.** A parallel apparatus that seeded from the
host (`e5-host/hostctl.sh`), superseded in place by the `e5-run.sh` design. Its
unique evidence is the local full-timing check at
`experiments/E5-attribute-cache/local-check/20261015T184617Z-6e7ec1f/`, which was
never deployed and is not an AWS result. It remains readable from commit
`6e7ec1f` / `5c98c8a` and is a second parent of `bf30b99`.

## Cleanup

- Two linked worktrees under `.claude/worktrees/` were removed; they had no
  uncommitted or untracked changes.
- All seven non-`master` branches were deleted after the merges. `master` is the
  only local branch; their tips remain reachable through the merge parents.
- No stashes existed.
- Three `analysis/__pycache__/*.pyc` files were tracked; removed, and
  `__pycache__/` plus `*.pyc` added to `.gitignore`.
- `docs/README.md` pointed at the 2026-10-26 E5 handoff anchor and still said no
  gradable AWS run existed. Both corrected.
