# Canary Diff — Post-Recalibration
Branch: `audit/dcf-terminal-growth-wacc-recalibration`
Date: 2026-04-27

## Pre-change snapshot
`scripts/snapshots/snapshot_20260428_013802_33e11c61d2cc.json`
Captured on clean main (commit `33e11c61d2cc`) immediately after `git status` confirmed no staged changes.

## Diff command
```
C:/ProgramData/miniconda3/python.exe scripts/canary_diff.py \
    --diff-against scripts/snapshots/snapshot_20260428_013802_33e11c61d2cc.json
```

## Result — ⚠️ HARNESS LIMITATION, NOT A PASS

```
Gate violations: 0
Fetch failures: 49 (budget 2)
  ok   single_source_of_truth: 0
  ok   mos_math_consistency: 0
  ok   scenario_dispersion: 0
  ok   canary_bounds: 0
  ok   forbidden_values: 0
FAIL: 49 fetch failure(s) > budget of 2 — API likely unhealthy.
Snapshot drift notes (advisory): 1
```

### Why this is not a usable signal for this branch

`scripts/canary_diff.py:167`:
```python
API_BASE = os.environ.get("CANARY_API_BASE", "https://api.yieldiq.in")
```

The canary harness fetches from the **deployed Railway production API**, not from local source. Local edits to `models/forecaster.py` and `models/industry_wacc.py` cannot influence this run. Even if the API had been reachable, the diff would have shown ~0 drift because both snapshot and live fetch route through the same prod codebase.

Compounding that, **49 of 50 fetches failed** in the diff run (only 1 ticker came back), so even a same-vs-same baseline check is not actionable — the production API itself appears to be unhealthy / unreachable from this machine right now.

## What is required before this branch is merge-eligible

Per CLAUDE.md rules #1 and #2, the canary gates must pass on production-equivalent inputs **with the new code**. That means at minimum one of:

1. **Local-mode canary**: extend `scripts/canary_diff.py` to support `CANARY_API_BASE=http://localhost:8000` and run a local FastAPI process from this branch. Then snapshot → recalibrate → diff against the snapshot. (Cleanest; recommended.)
2. **Pre-deploy canary**: deploy this branch to a Railway preview environment, set `CANARY_API_BASE` to that URL, snapshot the preview before-merge, push the recalibration, snapshot the preview after-merge, diff. (Mirrors GH Actions canary workflow.)
3. **Fix prod fetch first**: the 49/50 failure rate is itself a P1 worth investigating before any canary-gated merge.

This branch leaves the recalibration committed locally so the next iteration can pick it up; it does **not** propose to merge until a real diff is available.

## What I can validate without the API
The recalibration was applied as five literal `wacc_default` field bumps in `models/industry_wacc.py` plus one constant change in `models/forecaster.py`. Direction-of-effect is unambiguous from the closed-form DCF:
- Higher WACC → lower IV → lower MoS (correct direction for the 7 outliers).
- Lower `LONG_RUN_TARGET` → lower compound growth in years 1–10 → lower IV (correct direction).

Magnitude estimate (from the terminal-multiplier sensitivity in `audit_dcf_terminal_growth_wacc.md` §4 + the year-1–10 growth blend at `0.6 × actual + 0.4 × LONG_RUN`):
- TCS / IT-services bucket: expected FV reduction ~8–12% → MoS 44% → ~25–30%.
- Pharma bucket (NATCO/SANOFI/ZYDUS): expected FV reduction ~10–15% → MoS 66–76% → ~45–55%.
- FMCG bucket (EMAMI): expected FV reduction ~6–9% → MoS 82% → ~70%.

**These are still too high for TCS** — confirming the audit conclusion that this branch alone is necessary-but-not-sufficient. The remaining over-FV is in `fcf_base` selection + projection-period growth, which the sibling `wip/forecaster-margin-reversion-needs-canary` branch addresses.

## Status
- **Pre-change snapshot**: ✅ captured.
- **Canary-diff vs that snapshot**: ❌ unable to produce a meaningful result (harness points at unhealthy prod API).
- **Per CLAUDE.md gating**: this branch must NOT be merged until a real diff (5/5 gates clean on 50 stocks, then 7 nightly runs) is achieved.
