# Quarterly WACC recalibration

YieldIQ's DCF engine reads three macro-sensitive knobs from
`models/industry_wacc.py`:

1. **Risk-free rate** — used implicitly via `wacc_default`; the cost-of-equity
   leg of every WACC is anchored to the 10Y Indian G-Sec.
2. **`beta_typical`** per sector — Damodaran-style equity-risk premium scaling.
3. **`terminal_growth`** per sector — the stable-stage growth used in the
   Gordon tail of every DCF.

Macro conditions move on a slow clock; refreshing these knobs once a quarter
keeps fair values honest without churning the model every week.

## Why a script and not Claude

The first version of this refresh asked Claude for "current" rates. Claude
correctly refused to fabricate a 10Y G-Sec print from its training data. The
script in this directory replaces that habit with a reproducible data-pull
the operator runs locally with internet access.

## Files

| File | Purpose |
| --- | --- |
| `scripts/fetch_recalibration_inputs.py` | Pulls fresh rf-rate, sector betas, RBI-anchored terminal growth; writes a JSON artifact under `scripts/snapshots/`. |
| `scripts/apply_recalibration.py` | Reads the artifact, prints a before/after diff, optionally rewrites `models/industry_wacc.py`. |
| `backend/tests/test_recalibration_scripts.py` | Unit tests using mocked yfinance. |
| `docs/operations/quarterly-recalibration.md` | This file. |

## Operator workflow (per quarter)

```bash
# 0. Refresh main.
git checkout main && git pull

# 1. Pull fresh inputs (writes scripts/snapshots/recalibration_q<n>_<yyyy>_<ts>.json).
python scripts/fetch_recalibration_inputs.py --dry-run     # eyeball first
python scripts/fetch_recalibration_inputs.py               # writes JSON

# 2. Review the JSON. Hand-edit any obviously-wrong sector value
#    (e.g. a sector where yfinance returned a beta of 4.0 on stale data).

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

1. Confirm Python venv has `yfinance` installed.
2. Run `python scripts/fetch_recalibration_inputs.py --dry-run` — verify
   each sector returns a sane beta and the rf-rate prints.
3. Run without `--dry-run` to write the artifact.
4. Hand-edit `terminal_growth` overlays for any sector whose RBI-anchored
   value differs by > 100 bps from the current model — those need a human
   decision, not a regex.
5. Run `scripts/apply_recalibration.py --input <artifact>` (preview).
6. Open the recalibration PR following the workflow above.
