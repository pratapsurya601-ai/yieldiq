# YieldIQ — Post-audit PR ladder

Generated 2026-04-19 from `reports/formula_audit_20260419.md` after the
re-audit revealed 13 MoS computation sites + 3 ROE sites + the SoT
collapse (PR1) wasn't enough on its own.

**Discipline rules** (from CLAUDE.md):
- Every PR below runs through `python scripts/canary_diff.py` as the merge gate
- Snapshot before, snapshot after — explain any FV drift > 15%
- One bug class per PR — never mix MoS + scenarios + bounds in one merge

---

## Phase 0 — Foundation (DONE before this ladder)

| | Commit | What |
|---|---|---|
| ✅ | 272613c (PR1) | SoT collapse: `public/stock-summary` reads from `analysis_cache` |
| ✅ | 201b1fa (PR2) | Canary harness + formula audit + 50-stock list |
| ✅ | bcda963 | Commit-SHA tagging in canary reports/snapshots |
| ✅ | 5952d16 | 3 harness bugs (Gate 1 shape + Gate 2/5 unit) |
| ✅ | 756df67 | Gitignore canary_report.{json,md} |

---

## Phase 1 — Rename, don't collapse (5 sites → ZERO false-duplicate count)

These 5 sites compute a DIFFERENT concept that happens to share the name `mos_pct`. Per re-audit feedback: rename to make the concept-difference explicit. Pure refactor, no math change.

### PR-A1 — Rename per-axis MoS in hex services (3 sites)

**Concept**: `axis_margin_of_safety` — value-axis-specific MoS used for the Prism radar's Value-axis score. NOT the headline FV-vs-CMP MoS.

| File | Line | Function | Rename `mos_pct` → |
|---|---|---|---|
| `backend/services/hex_service.py` | 367 | `_axis_value_general()` | `axis_value_mos_pct` |
| `backend/services/hex_history_service.py` | 465 | `_compute_value_axis()` | `axis_value_mos_pct` |
| `backend/services/hex_history_service.py` | 615 | `_compute_snapshot()` | `axis_value_mos_pct` |

Local-variable rename + 1-line comment explaining the concept. Adds zero new sites to the audit; reduces MoS count 13 → 10.

**Risk**: minimal — local rename only.
**Canary**: should pass with zero new violations (no math changed).

### PR-A2 — Rename per-scenario MoS in financial valuation (2 sites)

**Concept**: `scenario_margin_of_safety` for bear/bull DCF computations. The headline `valuation.margin_of_safety` is set elsewhere; these are intermediate scenario values.

| File | Line | Function | Rename `mos_pct` → |
|---|---|---|---|
| `backend/services/financial_valuation_service.py` | 285 | `_compute_pbv_path()` | `scenario_mos_pct` |
| `backend/services/financial_valuation_service.py` | 325 | `_compute_pe_path()` | `scenario_mos_pct` |

**Canary**: should pass.

After Phase 1: audit reports **5 MoS computation sites** instead of 13.

---

## Phase 2 — Collapse the real duplicates (8 PRs, 1 file each)

Each PR replaces an inline `(fv - cmp) / cmp` recomputation with either:
- Passthrough to canonical `analysis_service.valuation.margin_of_safety`
- OR call to a shared helper `compute_mos(fv, cmp)` that lives in ONE place

Recommended: introduce `backend/services/_mos.py` with:
```python
def compute_mos_pct(fair_value: float, current_price: float) -> float | None:
    if not (current_price and current_price > 0): return None
    if fair_value is None: return None
    return (fair_value - current_price) / current_price * 100.0
```
This is the formula source-of-truth. Every other site imports it.

### PR-B1 — Portfolio router (1 site)

| File | Line | Function | Action |
|---|---|---|---|
| `backend/routers/portfolio.py` | 159 | `_do_import()` | replace inline calc with `compute_mos_pct(fv, cmp)` |

**Canary**: 50 stocks. Zero new Gate 2 violations expected.

### PR-B2 — Screener router (1 site)

| File | Line | Function | Action |
|---|---|---|---|
| `backend/routers/screener.py` | 71 | `_query_stocks_from_db()` | helper call |

### PR-B3 — Portfolio service (1 site)

| File | Line | Function | Action |
|---|---|---|---|
| `backend/services/portfolio_service.py` | 218 | `get_holdings_with_live_data()` | helper call |

### PR-B4 — Prism service (1 site)

| File | Line | Function | Action |
|---|---|---|---|
| `backend/services/prism_service.py` | 556 | `_build_prism()` | helper call |

Note: a previous fix (99b3c78) corrected the formula here from `(fv-cmp)/fv` to `(fv-cmp)/cmp`. This PR replaces the inline formula with the helper for consistency. No math change.

### PR-B5 — analysis_service line 1584 (1 site)

| File | Line | Function | Action |
|---|---|---|---|
| `backend/services/analysis_service.py` | 1584 | `_get_full_analysis_inner()` (early init) | DELETE — redundant with line 1786 (canonical) |

The line 1786 site is the canonical FIX1 site that fires AFTER moat adjustment. Line 1584 was the pre-FIX1 site that's now overwritten. Safe to delete.

### PR-B6 — analysis_service ScenarioCase rounding (2 sites)

| File | Line | Function | Action |
|---|---|---|---|
| `backend/services/analysis_service.py` | 2293 | `_get_full_analysis_inner()` (bear) | helper call inside ScenarioCase constructor |
| `backend/services/analysis_service.py` | 2295 | `_get_full_analysis_inner()` (bull) | same |

### PR-B7 — Add `compute_mos_pct` helper + tests

| File | Action |
|---|---|
| `backend/services/_mos.py` (NEW) | the helper |
| `tests/test_mos_helper.py` (NEW) | unit tests covering edge cases (cmp=0, fv=None, negative fv, etc.) |

Ship FIRST in this phase. Then PR-B1..B6 can land independently and reach for the helper.

### PR-B8 — Formula audit hard-fail in CI

| File | Action |
|---|---|
| `.github/workflows/canary_diff.yml` | add `python -m backend.audits.formula_audit` step. Must exit 0. |

After Phase 2: audit reports **1 MoS computation site** (the canonical `analysis_service.py:1786` one). Discipline rule structurally enforced.

---

## Phase 3 — ROE same treatment (3 PRs)

### PR-C1 — `compute_roe_pct(net_income, shareholders_equity)` helper

`backend/services/_ratios.py` (NEW) — also future home for ROCE, EV/EBITDA, debt/EBITDA helpers when those need collapsing.

### PR-C2 — Collapse 3 ROE computation sites

Per audit: `roe` has 3 computation sites (analysis_service line ~X, financial_valuation_service line ~Y, possibly local_data_service).

While in each file, also check ROCE — same pattern usually.

### PR-C3 — Audit gate covers `roe` + `roce`

Same pattern as PR-B8 but for ratio fields.

---

## Phase 4 — Validator follow-ups (2 PRs)

### PR-D1 — Bank/NBFC Safety axis branch

User-facing bug: HDFCBANK + BAJFINANCE show Safety n/a (5/6 lit). FIX1 + POL1 added IT-sector branch but not bank/NBFC.

| File | Line | Action |
|---|---|---|
| `backend/services/hex_service.py` | `_axis_safety` general branch | add `if sector in BANKS_NBFC: ...` branch using CAR proxy + provision coverage instead of D/E + interest coverage |

**Canary**: should reduce Gate 4 violations on banks (bank ROE bound was hitting because Safety axis n/a → no contribution).

### PR-D2 — `analysis_service.py:2051` ROCE rounding fix

FIX2 noted: ROCE fallback rounds tiny positive EBIT/TA values to 0.0%. Should return None instead.

| File | Line | Action |
|---|---|---|
| `backend/services/analysis_service.py` | 2051 | `_roce_val = round(_ebit_val / _total_assets * 100, 1)` → return None when value rounds to 0 (use the same forbidden-value pattern) |

---

## Phase 5 — Stability + observability (3 PRs, post-launch)

### PR-E1 — Bank/NBFC Safety canary bounds tuned

Once PR-D1 ships, the canary `wacc` and `roe` bounds for HDFCBANK / ICICIBANK / KOTAKBANK / BAJFINANCE / SHRIRAMFIN need re-tuning to actual observed values.

### PR-E2 — IT WACC bound widened

TCS WACC 0.098 currently fails canary bound `[0.10, 0.14]`. Real value is correct (G-Sec dropped). Loosen to `[0.085, 0.14]` for IT large-caps. Done as canary_stocks_50.json edit.

### PR-E3 — Add `formula_audit` to nightly cron

Currently formula_audit runs once and writes `reports/formula_audit_YYYYMMDD.md`. Run nightly to catch any new computation site that snuck in via a non-canary-gated PR.

---

## Execution order

```
Day 1 (post first clean canary):
  PR-A1, PR-A2          (renames — zero risk)
  PR-B7                 (helper module + tests, no live integration yet)

Day 2:
  PR-B1, PR-B2, PR-B3   (3 routers/services — independent, ship parallel)

Day 3:
  PR-B4, PR-B5, PR-B6   (analysis_service + prism — single-file changes)

Day 4:
  PR-B8                 (CI gate flips — formula audit becomes blocking)
  PR-C1, PR-C2          (ROE helper + collapse)

Day 5:
  PR-D1                 (Bank Safety branch)
  PR-D2                 (ROCE rounding)
  PR-C3                 (audit covers ratios)

Days 6–14:
  Watch nightly canary. Each clean day = +1 toward the 7-day gate.
  Any failure = stop, diagnose, fix in a single-class PR.

Day 14 (or first 7 consecutive clean days, whichever later):
  Launch.
```

---

## Per-PR template

Every PR in Phase 1–5 ships with:

```markdown
## Snapshot (run before merge)
python scripts/snapshot_50_stocks.py
→ saved scripts/snapshots/snapshot_<ts>_<sha>.json

## Canary (must exit 0)
python scripts/canary_diff.py
→ all 5 gates pass on all 50 stocks

## Diff vs snapshot
python scripts/canary_diff.py --diff-against scripts/snapshots/<latest>.json
→ report any FV drift > 15% with explanation

## Files changed
- ...

## Risk
- (low/medium/high — explain)
```

---

## What's intentionally NOT in this ladder

- **`/screener` page actually built** — we put a redirect in PR4 (commit c2370d8 era). Not a data fix; can ship anytime.
- **9s SSR investigation** — already shipped in PR1 (Option C).
- **`computation_inputs` snapshot in cache** — already shipped in 320e5d3.
- **Cache warmup workflow** — already runs 3× daily; user just needs to trigger first run.

These are done. The ladder above is exclusively the cleanup that turns whack-a-mole into compounding progress.
