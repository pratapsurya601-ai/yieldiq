# Week-6 Canary Gate Restoration

**Date**: 2026-05-20 (Day 51)
**Trigger**: Canary nightly has been failing on `main` for 2+ days
(2026-05-19, 2026-05-20). Three PRs (#438, #439, #440) admin-merged
past it during the Week-5 monetization sprint. The gate is now a
no-op for engineering judgement, which violates CLAUDE.md rule #1
("Never ship a data fix without running canary-diff first").

**Goal**: Restore green canary on `main` so the gate provides real
signal again — without papering over genuine issues by widening
bounds blindly.

---

## What's actually failing

Latest report (PR #438 run 26148515470 against commit 5c6c84b43e50):

| Gate | Count | Nature |
|---|---|---|
| 3 — scenario_dispersion | 4 | **Real engine bug** — bear > base for cyclicals |
| 4 — canary_bounds | 112 | Mix of stale bounds + real data shifts |
| 5 — forbidden_values | 5 | Marginal premium stocks just below fv/cmp floor |

Total: **121 violations** across 333 tickers.

Fetch failures: 10 (within budget 14 — not the cause).

---

## Day 51 (P0): Fix the engine bug

### Root cause

`backend/services/analysis/service.py` cyclical handling:

1. L2058: trough anchor fires when `iv < 0.2 * price` →
   `_trough_anchor_fired = True`, `_trough_anchor_bear_iv = 0.85 * price`.
2. L2098-2105: Tier-2 cohort engine then runs and OVERWRITES `iv`
   to the cohort FV.
3. L3060: scenario block uses `_trough_anchor_bear_iv` (still pinned
   to `0.85 * price`) against the now-Tier-2 `iv`.
4. Result: bear ≈ 0.85 × price can exceed base = cohort FV.

Affected tickers in this run (all metals/cement/gas — all run the
cohort engine after the cyclical-trough triggers):
- **HINDALCO**: bear=524 base=320 bull=543 (price≈617)
- **HINDZINC**: bear=316 base=307 bull=421
- **COROMANDEL**: bear=939 base=749 bull=1068
- **GUJGASLTD**: bear=188 base=183 bull=257

All four follow the same pattern: bear ≥ base while base < bull. The
trough-anchor bear is being kept even though Tier-2 took over base.

### Fix

When Tier-2 (or any layer after the trough anchor) overrides `iv`,
invalidate the trough-anchor scenario floor. Two options:

- **A. Clear the flag** when iv is overridden — simplest, but loses
  the legitimate trough-anchor display rescue when the new iv is
  itself sub-`0.5*price`.
- **B. Re-anchor bear/bull to the new iv** when iv is overridden —
  set `_trough_anchor_bear_iv = max(_trough_anchor_bear_iv, iv * 0.85)`
  guarded by `min(_trough_anchor_bear_iv, iv * 0.95)`. Preserves
  display but guarantees bear ≤ base.

**Chosen: B** with a cleaner formulation: after the Tier-2 override,
recompute the anchor band off `iv` rather than `price`:

```python
if _trough_anchor_fired:
    # Recompute the trough-anchor scenarios off the new iv so the
    # bear floor cannot exceed the (possibly Tier-2-overridden) base.
    _trough_anchor_bear_iv = round(min(0.85 * price, iv * 0.95), 2)
    _trough_anchor_bull_iv = round(max(1.10 * price, iv * 1.05), 2)
```

This keeps the "cycle has priced in" intuition (band sits around
price) but never lets bear exceed 95% of base. Bull stays ≥ 105% of
base so the dispersion gate also holds.

### Test plan

- Unit test in `tests/regression/test_cyclical_trough_tier2_interaction.py`
  exercising: trough fires → Tier-2 overrides iv to a value below the
  raw anchor band → assert bear < base < bull.
- Run canary against the 4 known-bad tickers after the fix.

---

## Day 52 (P1): Re-baseline ROE/WACC bounds

111 gate-4 violations break down into sub-categories. Fix per
category, not blanket widening.

### Category A — Banks post-HDFC merger (5 tickers)
HDFCBANK, KOTAKBANK, INDUSINDBK, IDFCFIRSTB, BANDHANBNK

ROE 1-11% reported, bounds set at 12-20%. Post-merger HDFC ROE has
genuinely compressed; the bounds reflect pre-merger steady state.

**Action**: widen bank ROE lower bound to 0.05 (5%) across the
"banks" cohort in `canary_universe_180.json`. Document the merger
as the trigger.

### Category B — Special-situation high ROEs (5 tickers)
LICI (38%), INDIGO (77%), DIXON (36%), DEVYANI (84%), VEDL (35%)

These are correct numbers for the situation:
- LICI uses appraisal value, not book value — ROE is mechanically
  inflated.
- INDIGO had a fuel cost windfall in FY25 → spike not sustainable.
- DEVYANI is a turnaround company — small denominator effect.
- DIXON is a fast-growing manufacturer.
- VEDL has a complex restructuring.

**Action**: raise upper bounds per ticker in
`canary_universe_180.json` with a comment naming the special
situation. Do NOT blanket-widen — each justification matters.

### Category C — WACC floor at 0.098 (3 tickers)
ZOMATO, NYKAA, POLICYBZR all sit at 0.098 vs floor 0.10/0.11.

The repo's risk-free rate input has drifted. India 10y G-sec is
currently ~6.5%; with a 3% ERP and ~1.0 beta the implied WACC
floor for low-debt new-economy names lands at 0.098-0.10, not the
historical 0.11.

**Action**: lower WACC floor for "new-economy" cohort to 0.09.

### Category D — Genuine concern (1 ticker)
INDIACEM ROE=-66% (bounds -5% to 15%).

A -66% ROE indicates either a real impairment or bad data.

**Action**: investigate the source — if real, exempt with a note;
if bad data, fix the upstream feed.

### Category E — Long tail (~97 remaining)
ROEs slightly outside bounds. Treat as bound drift; widen the
relevant cohort bound by 1-2 percentage points after spot-checking
3-5 tickers per cohort to confirm the new numbers are real.

---

## Day 53 (P2): Gate-5 fv/cmp floor

5 tickers at fv/cmp 0.31-0.35 vs floor 0.35:

| Ticker | fv/cmp | Comment |
|---|---|---|
| BERGEPAINT | 0.348 | Premium paint, narrow miss |
| UNITDSPR | 0.338 | Premium spirits, narrow miss |
| SCHAEFFLER | 0.343 | Auto components premium |
| KEI | 0.313 | Cable maker run-up |
| JSWINFRA | 0.325 | Infra premium |

All are premium consumer/cap-goods names that the market has bid
above any reasonable DCF. The 0.35 floor was set as "if engine
thinks it's 65%+ overvalued, probably a data bug". These look like
genuine engine reads, not bugs.

**Action**: lower fv/cmp lower bound to 0.30 in
`canary_universe_180.json`. Keep upper bound at 2.7 — that side is
load-bearing (catches when bear becomes a "trough buy" magnet).

---

## Day 54: Verify

1. Run canary against current main locally — expect 0 violations.
2. Push a no-op PR to confirm CI canary passes.
3. Reinstate canary as a non-bypassable merge gate.
4. Restart the 7-consecutive-nightly clean-run counter (CLAUDE.md
   rule #3).

---

## Out of scope

- Sector-isolation failures: same pattern (timed out after 9-10min).
  Once the engine fix lands, the sector-isolation re-run should
  surface only true sector-shifts; re-investigate then.
- Stale bounds in non-NIFTY tickers: pruned by limiting bounds
  updates to the canary-universe-180 set.
