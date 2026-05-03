<!--
  YieldIQ PR template.

  The first line below is REQUIRED. Replace `*` with a comma-separated list of
  sectors (e.g. `Cement, Banks`) or leave as `*` for an intentionally-global
  change. The sector-isolation merge gate parses this directive and will FAIL
  the build if it is missing.

  Quick auto-detect:
      python scripts/sector_scope_suggest.py
  Paste its output as the `sector-scope:` line.

  Sector taxonomy lives in scripts/sector_snapshot.json.
-->

sector-scope: *

## Summary

<!-- 1-3 sentences. The "why", not the "what". -->

## Scope

<!--
  Which paths/services are touched? If the change is sector-specific, list
  the sectors above. If `sector-scope: *`, justify why a global change is
  required (rare — most legitimate changes are sector-scoped).
-->

## Test Plan

- [ ] Unit tests pass locally
- [ ] `python scripts/test_dcf.py` (if scoring touched)
- [ ] `python scripts/canary_diff.py` exits 0 (if backend/services|routers|validators|models touched)
- [ ] Manual smoke check (describe)

## CACHE_VERSION impact

- [ ] CACHE_VERSION needed? **(Y / N)**

<!--
  If Y: explain WHY (what cached payload shape changed) AND attach a
  before/after snapshot per docs/CACHE_VERSION_DISCIPLINE.md. Never bump
  CACHE_VERSION casually — it invalidates every cached analysis.
-->

## Intentional FV deltas

If this PR intentionally changes fair-value or score for specific tickers, list them here. The canary gate will treat listed tickers as expected-to-move and only fail on UNlisted ticker movements. The post-merge auto-snapshot job will rebaseline these tickers on merge.

```
intentional-fv-deltas:
  TICKER: brief reason (e.g. "cement supercycle anchor adjustment")
```

Leave empty if no intentional deltas.

## Discipline checklist

- [ ] `sector-scope:` declared at top of this body (REQUIRED)
- [ ] CACHE_VERSION needed? (Y / N) — if Y, before/after snapshot attached
- [ ] Canary required? (touches `backend/services/`, `backend/routers/`,
      `backend/validators/`, `backend/models/`, or `models/`) — **(Y / N)**
- [ ] If canary required: was canary green? (link the workflow run)
- [ ] If `sector-scope: *`: justified above
- [ ] Sector-isolation gate green (or shifted sectors all declared)
