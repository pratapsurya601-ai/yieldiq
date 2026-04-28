# CACHE_VERSION-bump discipline

## Why this exists

On **2026-04-27** two PRs landed back-to-back:

* **PR #134** — touched `backend/services/` analysis paths.
* **PR #136** — touched `backend/services/` and `backend/routers/`.

Both required a `CACHE_VERSION` bump in
`backend/services/cache_service.py` so that previously-cached analysis
payloads would recompute against the new logic. Neither PR bumped the
constant on merge.

Result: production (Railway) kept serving stale cached values from
the pre-merge `CACHE_VERSION` for hours, until **PR #137** retroactively
bumped to flush. Users who had visited any of the affected tickers
during that window saw the old, wrong, fair-value / red-flag /
strengths output.

This document plus the
[`cache_version_check.yml`](../.github/workflows/cache_version_check.yml)
PR gate plus the
[`scripts/cache_version_check.py`](../scripts/cache_version_check.py)
helper exist so that mistake cannot recur.

## What the gate does

When a PR is opened against `main` and its diff includes any of:

* `backend/services/`
* `backend/routers/`
* `backend/validators/`
* `backend/models/`
* `models/forecaster.py`
* `models/industry_wacc.py`
* `data_pipeline/sources/`

…the PR **must** also include either:

* a `CACHE_VERSION = N` -> `CACHE_VERSION = N+1` change in
  `backend/services/cache_service.py`, **or**
* a `cache-version: skip` / `cache-version: not-needed` declaration in
  the PR body, ideally with a short rationale.

Otherwise the gate fails and posts a comment explaining how to fix.

## When to bump

Bump if the PR could change, for any existing ticker, any of:

* `fair_value`
* `margin_of_safety` (and any MoS-derived label)
* `verdict` band (PASS / AMBER / FAIL)
* composite `score` axis (Quality / Safety / Growth / Value / Moat)
* `red_flags_structured` (W- and I-rules)
* `strengths`
* any other field that a cached `AnalysisResponse` already serialises

The decision tree is in the comment block above the
`CACHE_VERSION` literal in `cache_service.py`. Read it before deciding.

## When to skip

Don't bump for changes that are surface-only or non-payload:

* logging / observability / metrics
* error message wording, sanitisation, redaction
* request-id propagation, rate-limit middleware, header tweaks
* frontend wiring (`frontend/**` is not even a trigger path)
* schema additions that don't touch existing fields (additive new
  optional fields are usually safe — but if they're computed from
  cached data, bump anyway so caches re-fill them)
* docs, tests, CI, scripts that aren't shipped
* refactors that are byte-identical at the analysis-output level

## How to declare a skip

Add a line **anywhere** in the PR body:

```
cache-version: not-needed - frontend-only
cache-version: skip - logging additions, no payload change
cache-version: not-needed - error-message rewording in 5xx handler
cache-version: skip - new admin endpoint, no analysis path touched
```

The token is parsed case-insensitively and tolerates Markdown
decorations (backticks, blockquotes, list bullets) — same lesson as
the sector-isolation parser fix
([test_sector_isolation_parser.py](../tests/test_sector_isolation_parser.py)).

A rationale after the dash is recommended but not required by the
parser. Reviewers will push back if the rationale is missing or
unconvincing.

## How to bump

1. Open `backend/services/cache_service.py`.
2. Increment the integer on the `CACHE_VERSION = N` line by 1.
3. Append (don't replace) a one-line entry to the inline comment
   describing **what cached payloads need to recompute and why**.
   Format follows existing entries — see the comment for examples.
4. If the bump might shift fair-values materially, follow the
   discipline rule from `CLAUDE.md`: run `snapshot_50_stocks.py`
   before, `canary_diff.py --diff-against latest` after, and explain
   any FV change > 15% in the PR description.

## Example bump comments from history

The comment header in `cache_service.py` accumulates these in chronological
order (newest first). Pattern: `vN=<short-id> (<PR>, <date>): <one-paragraph-rationale>`.

* `v65=fix/normalize-pct-bound-correction (2026-04-28): _normalize_pct
  heuristic window narrowed from ±5 to ±1; previously-cached
  ROE/ROCE/ROA values for low-margin stocks were double-multiplied
  (GRASIM ROE 2.35% surfaced as 235%); bump forces every v64 cached
  analysis payload to recompute against the corrected normalizer.`
* `v62=feat/analytical-notes (PR #69, 2026-04-24): analytical_notes
  field added to every analysis payload. Bump forces v61 payloads to
  recompute so every cached response carries the new field. Purely
  additive — does NOT alter FV, scoring, or any axis.`
* `v53=hotfix/piotroski-bank-mode (PR #61, 2026-04-24 PM): bank-mode
  Piotroski (4 of 9 signals) replaces classic 9-signal for bank-like
  tickers. HDFCBANK piotroski 3/9 -> 7/9; composite 42 -> 58.`

Read the full history block in `cache_service.py` for the format and
calibration of these notes.

## Local pre-push hook

To run the same check before pushing, install a `.git/hooks/pre-push`
that does:

```bash
#!/usr/bin/env bash
set -e
TMP=$(mktemp -d)
git diff origin/main...HEAD > "$TMP/pr.diff"
# Pull the PR body from somewhere — for local pushes there isn't one,
# so this hook is conservative and treats absence as "no skip".
: > "$TMP/pr_body.txt"
python scripts/cache_version_check.py \
  --diff-file "$TMP/pr.diff" \
  --pr-body-file "$TMP/pr_body.txt" \
  --require-bump
```

If you're pushing a draft branch where you intend to add the skip
declaration in the GitHub PR body later, you can `git push --no-verify`
once and let the PR gate catch any real problem.

## Maintenance

* Adding a new top-level analysis-output-affecting path? Update both
  `TRIGGER_PREFIXES` / `TRIGGER_EXACT` in
  `scripts/cache_version_check.py` AND add a test case to
  `tests/test_cache_version_check.py`.
* If the gate fires too often on genuinely safe paths, narrow the
  trigger set rather than relaxing the skip-detection — false skips
  are how we got into the 2026-04-27 incident in the first place.
