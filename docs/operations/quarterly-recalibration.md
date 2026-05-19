# WACC recalibration (quarterly rf-rate, annual betas + terminal growth)

YieldIQ's DCF engine reads three macro-sensitive knobs from
`models/industry_wacc.py`:

1. **Risk-free rate** — used implicitly via `wacc_default`; the cost-of-equity
   leg of every WACC is anchored to the 10Y Indian G-Sec. **Refresh quarterly.**
2. **`beta_typical`** per sector — Damodaran emerging-markets sector betas
   (India sheet). **Refresh annually**, aligned with Damodaran's January
   data drop.
3. **`terminal_growth`** per sector — Damodaran-style stable-stage growth used
   in the Gordon tail of every DCF, capped at 6 %. **Refresh annually**
   alongside betas.

Macro conditions move on a slow clock; this two-cadence refresh
(quarterly rf, annual betas + terminal growth) keeps fair values honest
without churning the model every week.

## Why a script and not Claude

The first version of this refresh asked Claude for "current" rates. Claude
correctly refused to fabricate a 10Y G-Sec print from its training data. The
script in this directory replaces that habit with a reproducible data-pull
that reads from hardcoded tables sourced from authoritative public
datasets (RBI press releases, Damodaran's Stern dataset) which the operator
refreshes on the cadence above.

### Why not yfinance

The original implementation pulled rf-rate, sector betas, and nominal GDP
from yfinance. That path was removed in May 2026 after a recalibration run
produced unsafe values:

- yfinance dropped `^IN10Y` and `IN10YT=RR` (both 404).
- `yf.Ticker(t).info["beta"]` returned 0.13 for IT services and 0.004 for
  tech hardware — values that would balloon FVs if applied. Several
  tickers (AMBER.NS, TATAMOTORS.NS, SHREECEM.NS) returned no beta at all.
- "RBI nominal GDP − 50 bps" was the wrong heuristic for terminal growth:
  10 % current nominal ≠ 4–5 % long-run terminal. The script previously
  produced terminal growth of 10 %, which is unsupportable.

## Files

| File | Purpose |
| --- | --- |
| `scripts/fetch_recalibration_inputs.py` | Pulls fresh rf-rate, sector betas, RBI-anchored terminal growth; writes a JSON artifact under `scripts/snapshots/`. |
| `scripts/apply_recalibration.py` | Reads the artifact, prints a before/after diff, optionally rewrites `models/industry_wacc.py`. |
| `backend/tests/test_recalibration_scripts.py` | Unit tests using mocked yfinance. |
| `docs/operations/quarterly-recalibration.md` | This file. |

## Operator workflow

### Before running: refresh the hardcoded tables

The script reads from three hardcoded tables in
`scripts/fetch_recalibration_inputs.py`. Update them on this cadence:

| Table | Cadence | Source | Action |
| --- | --- | --- | --- |
| `RBI_10Y_GSEC_2026Q2` | Quarterly | RBI press releases — [BS_PressReleaseDisplay](https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx) "Government Stock - 10 Year" weighted-average yield | Edit constant; rename suffix to current quarter (e.g. `_2026Q3`). |
| `DAMODARAN_INDIA_BETAS_2026` | Annually (January) | Damodaran Stern dataset — [Betas.html](http://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/Betas.html), Emerging Markets > India sheet | Pull the spreadsheet, copy the levered-beta column into the dict; rename suffix to current year. |
| `TERMINAL_GROWTH_2026` | Annually | Damodaran recommendation for India (~4–5 % nominal, capped at 6 %) | Revise sector overlays alongside the beta refresh. |

```bash
# 0. Refresh main.
git checkout main && git pull

# 1. Pull fresh inputs (writes scripts/snapshots/recalibration_q<n>_<yyyy>_<ts>.json).
python scripts/fetch_recalibration_inputs.py --dry-run     # eyeball first
python scripts/fetch_recalibration_inputs.py               # writes JSON

# 2. Review the JSON. Verify each sector beta against the actual Damodaran
#    spreadsheet (the hardcoded values are starting points). Hand-edit any
#    sector value the operator wants to deviate from.

# 3. Preview the source diff without writing.
python scripts/apply_recalibration.py \
    --input scripts/snapshots/recalibration_q*_<year>_*.json

# 4. If diff looks reasonable, open a NEW branch and apply.
git checkout -b feat/q<n>-<year>-wacc-recalibration
python scripts/apply_recalibration.py \
    --input scripts/snapshots/recalibration_q*_<year>_*.json --apply
git diff models/industry_wacc.py    # human review here

# 5. Run the merge gate. CLAUDE.md rule #1 is non-negotiable.
python scripts/snapshot_50_stocks.py             # before-snapshot
# … bump CACHE_VERSION by 1 in the same PR …
python scripts/canary_diff.py --diff-against latest

# 6. Commit, push, open PR. Include the canary report in the PR body.
```

## Verification before merging the recalibration PR

The PR that carries the new WACC values (NOT the tooling PR) must satisfy:

- [ ] `python scripts/canary_diff.py` exits 0 (5/5 gates pass on all 50).
- [ ] No canary ticker has a fair-value swing > 15 %; flagged ones are
  explained in the PR body.
- [ ] `CACHE_VERSION` bumped by exactly 1.
- [ ] Before-snapshot committed under `scripts/snapshots/` for posterity.
- [ ] Artifact JSON also committed so anyone can re-derive the diff.

If any canary ticker moves > 15 %, the operator should *reduce scope* — apply
only the beta changes, defer the terminal-growth bump, or vice versa — rather
than ship a noisy refresh.

## Why this PR does NOT bump CACHE_VERSION

This PR ships the **tooling**. No fair value, no service file, no model
file changes. The tooling itself is dead code at runtime; only the script
and tests + this doc page land. The first quarterly refresh that actually
uses the script will land as a separate PR with the cache bump, the canary
report, and the before/after snapshot.

## First-quarter target operator checklist

1. Verify the hardcoded tables in `scripts/fetch_recalibration_inputs.py`
   are current (see the cadence table above). At minimum the rf-rate
   constant should reflect the most recent RBI publication.
2. Run `python scripts/fetch_recalibration_inputs.py --dry-run` — verify
   each sector returns a sane beta (0.4 ≤ β ≤ 2.0) and the rf-rate prints.
3. Run without `--dry-run` to write the artifact.
4. Hand-edit any sector's `terminal_growth` overlay if the operator
   disagrees with the table default — those need a human decision, not
   a regex. Remember the 6 % cap is enforced by the script.
5. Verify the artifact's `sector_betas` against the actual Damodaran
   January spreadsheet for any sector with > 0.10 beta delta vs current
   model.
6. Run `scripts/apply_recalibration.py --input <artifact>` (preview).
7. Open the recalibration PR following the workflow above.
