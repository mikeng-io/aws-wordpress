# H6 — Bidirectional write-back caching cannot be made correct

**Status:** `UNTESTED`

## Claim

A sidecar syncing local ephemeral storage and EFS in both directions looks like a
cache and behaves like a distributed database with no consensus. Two tasks write
locally, both flush, last writer wins, silently.

## Prediction

A conformance suite will exhibit data loss under concurrent writes for any
bidirectional design, and the periodic reverse scan needed to detect remote changes
will itself cost a full-tree metadata traversal — relocating the problem rather than
solving it.

## Kill condition

**H6 is refuted by** exhibiting a bidirectional design that passes the conformance
suite without a single-writer assumption.

## The alternative this motivates

Single-writer designs avoid the problem entirely:

- Code hydrated at task start from one tarball, never synced back
- `/wp-admin/*` and `/wp-login.php` routed at the load balancer to a small admin
  service whose code directory genuinely is on shared storage; public traffic served
  from local copies; propagation is a rolling restart

Both are pure infrastructure — ALB rules and task definitions. Whether the
propagation lag is acceptable is an empirical question, not a design opinion.

## Conformance suite (gates all performance numbers)

No variant's performance results count until it passes: cross-node `flock`
exclusion, atomic rename visibility, close-to-open consistency window, `fsync`
durability, mmap support, hardlinks, ownership persistence, concurrent same-file
writes. A filesystem that is fast but loses a plugin update is disqualified, and
that ordering is deliberate.
