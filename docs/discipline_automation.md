# Discipline-rule automation

`CLAUDE.md` defines three data-fix discipline rules. This document
maps each rule to the automation that enforces it, explains how to
satisfy the workflow checks, and describes what to do when something
breaks.

> CLAUDE.md is the source of truth. Do not edit it to work around a
> failing automation check — fix the underlying issue, or escalate.

## Rule -> workflow map

| Rule | What it requires | Enforcement |
|------|------------------|-------------|
| #1 — Run canary-diff before shipping a data fix | `canary_diff.py` must exit 0 on PRs touching `backend/services`, `backend/routers`, `backend/validators`, `backend/models`, or `scripts/canary_stocks_50.json` | [`.github/workflows/canary_diff.yml`](../.github/workflows/canary_diff.yml) (pre-existing) |
| #2 — Snapshot before bumping `CACHE_VERSION` | PR must declare a `snapshot-id:` in the PR body and the file must exist under `scripts/snapshots/` | [`.github/workflows/discipline_rule_2.yml`](../.github/workflows/discipline_rule_2.yml) |
| #3 — 7 consecutive clean nightly canary runs before declaring "fixed" | Nightly canary against prod, append to `docs/canary_history.jsonl`, surface streak in README badge, declare fixes via `scripts/declare_fix_status.py` | [`.github/workflows/discipline_rule_3.yml`](../.github/workflows/discipline_rule_3.yml) plus [`scripts/declare_fix_status.py`](../scripts/declare_fix_status.py) |

## Rule #2 — how to land a CACHE_VERSION bump

1. **Take a snapshot first.** From a prod-ready environment:

   ```bash
   python scripts/snapshot_50_stocks.py
   ```

   The script writes a file like
   `scripts/snapshots/snapshot_20260427_120000_<sha>.json`.
   Commit it on the same branch as the bump.

2. **Apply the bump.** Edit `backend/services/cache_service.py` and
   bump `CACHE_VERSION = N` to `N+1`, with a comment on the same
   line summarising the invalidation rationale (existing convention).

3. **Declare the snapshot in the PR body.** Add this line verbatim
   somewhere in the PR description:

   ```
   snapshot-id: snapshot_20260427_120000_<sha>.json
   ```

   The workflow's regex is case-insensitive (`Snapshot-Id:` works too)
   but the filename portion must match the file you committed.

4. **Run the after-snapshot diff.** Locally:

   ```bash
   python scripts/canary_diff.py --diff-against latest
   ```

   Any FV change >15% on any of the 50 canary stocks must be
   explained in the PR description.

The workflow fails with an actionable error message if any of these
steps is skipped. PR #126 (the 64 -> 65 bump on 2026-04-27) shipped
without a snapshot precisely because no automation existed; that gap
is now closed.

## Rule #3 — how to read the canary streak badge

The README carries a Shields.io badge:

> ![Canary streak](https://img.shields.io/badge/canary%20streak-0%2F7%20nights-red)

- **Red** — streak is 0. The most recent nightly canary failed.
- **Amber** — streak is 1..6. Progressing toward green; do not yet
  declare any pending fix as "fixed".
- **Green** — streak >= 7. Open issues/PRs labelled
  `fix-pending-validation` whose merge has been on `main` for at
  least 7 days are eligible to be declared FIXED.

The badge is updated automatically by
`.github/workflows/discipline_rule_3.yml` after each nightly run.
The append-only history lives at
[`docs/canary_history.jsonl`](./canary_history.jsonl) — one JSON
object per night.

### Declaring a fix

Run the helper (typically from a scheduled job or by hand on demand):

```bash
GH_TOKEN=... python scripts/declare_fix_status.py
```

It enumerates every open issue / PR labelled
`fix-pending-validation`, checks the current streak and the
days-on-main, and either:

- comments `Per rule #3, this fix is now declared FIXED.` (when
  streak >= 7 AND days-on-main >= 7), or
- comments `Streak: X/7 nights` as a progress update.

Use `--dry-run` to preview without writing.

## Escalation — what to do when the streak resets

A streak reset means the most recent nightly canary detected a gate
violation or a fetch failure. **Do not bypass the rule.**

1. Pull the failing run's artifacts (`canary_report.json`,
   `canary_report.md`) from the workflow run page.
2. Identify whether the regression is a real fix-the-code issue or a
   data-source flake (yfinance throttling, Neon unavailable, etc.).
3. For real regressions: open a `fix-pending-validation` issue,
   ship the fix, and let the streak rebuild from 0. Do **not**
   declare any in-flight fix as resolved while the streak is
   below 7.
4. For confirmed flakes: re-run the workflow manually
   (`workflow_dispatch`). The history line for the flake stays in
   the log (append-only) but a successful re-run extends the streak
   from the previous clean baseline.
5. If a flake recurs more than twice in a week, treat it as a real
   problem in the canary harness or data layer and triage
   accordingly — don't keep papering over it with manual re-runs.
