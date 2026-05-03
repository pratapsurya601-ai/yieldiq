# YieldIQ CI Gates — author guide

This is the practical guide for working WITH the merge gates (canary-diff,
sector-isolation, CACHE_VERSION-bump, SEBI lint). All five exist because
of a previously-shipped regression. None of them are arbitrary. But they
were originally calibrated for a one-PR-at-a-time flow; the ergonomics
overhaul (PR #ci-gate-ergonomics) added per-PR exemption hatches so that
parallel PRs no longer punish each other.

## The five gates at a glance

| Gate                         | Workflow                                  | Script                                |
|------------------------------|-------------------------------------------|---------------------------------------|
| Canary diff                  | `canary_diff.yml`                         | `scripts/canary_diff.py`              |
| Sector isolation             | `sector_isolation.yml`                    | `scripts/sector_isolation_check.py`   |
| CACHE_VERSION bump           | `cache_version_check.yml`                 | `scripts/cache_version_check.py`      |
| SEBI vocabulary (frontend)   | `frontend_sebi_lint.yml`                  | `scripts/check_sebi_words.py`         |
| Sector-scope auto-suggest    | `sector_scope_suggest.yml`                | `scripts/sector_scope_suggest.py`     |

## Intentional FV deltas — the new hatch

When a PR INTENTIONALLY moves fair-value or score for one or more
tickers (e.g. a cement supercycle anchor adjustment), declare them in
the PR template:

```
intentional-fv-deltas:
  ULTRACEMCO: cement supercycle anchor adjustment
  SHREECEM: same calibration cohort
```

What this changes:

1. **canary_diff.py exempts those tickers.** Their gate violations
   appear in the report under "EXEMPTED (intentional)" and do NOT
   count toward `gate_violations`. Other tickers still gate normally.
2. **Auto-snapshot on merge.** The
   `auto_snapshot_on_intentional_deltas.yml` workflow runs
   `scripts/snapshot_50_stocks.py` against production immediately after
   the PR merges and pushes the new snapshot to `main` with `[skip ci]`.
   This means the NEXT PR opened doesn't see a stale-baseline diff for
   the intentionally-moved ticker.

If you don't list anything, behavior is identical to before — the gate
fires on every violation.

## SEBI lint diff-only mode

`scripts/check_sebi_words.py --diff-only --base origin/main` only
checks lines ADDED in the PR. Inherited debt from older code does NOT
fail your PR. The CI workflow uses this mode by default; full-tree
mode is still available locally for periodic audits.

## CACHE_VERSION-bump exemptions

The `cache_version_check.py` script no longer demands a bump when:

- All changed files are brand new (don't exist in the base branch)
- Changed files match `EXEMPT_PATTERNS` (`**/scaffolds/**`,
  `**/*_scaffold.py`)
- Changed files are entirely outside `backend/services/analysis/`

This eliminates the false-positive class where a pure-additive PR
(adding a new endpoint, a new scaffold) triggered the bump check
purely because it touched something under `backend/services/`.

## Sector-isolation auto-fix

When a PR carries the label `auto-sector-scope`, the
`sector_isolation.yml` workflow runs `sector_scope_suggest.py
--auto-commit` BEFORE the merge gate. This:

1. Computes the suggested `sector-scope:` line
2. Edits the PR body to add the line at the top via `gh pr edit`
3. Posts a comment explaining what was added

PRs WITHOUT the label still get the suggestion comment but no edit —
opt-in is the default to avoid surprise body mutations.

## When NOT to use these hatches

- Don't list a ticker as intentional-fv-delta to silence a real bug.
  The auto-snapshot will bake the bug into the baseline.
- Don't add new files purely to dodge the CACHE_VERSION bump check —
  the new-file exemption only fires when ALL files are new.
- Don't add the `auto-sector-scope` label to a PR that genuinely needs
  human judgment about scope (e.g. a refactor that touches three
  sectors but legitimately belongs as `*`).
