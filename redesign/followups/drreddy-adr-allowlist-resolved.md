# DRREDDY ADR-allowlist absence — RESOLVED, verified negative

**Status:** RESOLVED 2026-06-03. Closing the suspicion so it doesn't resurface in a future audit.

## What was suspected

The 32-stock funnel audit (`redesign/audits/funnel-2026-06-03/FINAL-32-STOCK-ANALYSIS.md` §1 Tier C) flagged that DRREDDY is cross-listed (US ADR) but did NOT carry the Data-Limited / ADR-cohort banner in SSR HTML, unlike its peers (TCS, INFY, WIPRO, HCLTECH, TECHM). The audit framed this as: *"Either deliberate (NSE primary listing path works) or accidentally omitted from the cohort allowlist."*

## What Phase 0 verified

DRREDDY is **intentionally absent** from the 16-ticker allowlist in `frontend/src/components/analysis/AdrCohortBanner.tsx`. Confirmed by direct grep of the allowlist constant on `origin/main = d71e783`. The exclusion is by design — DRREDDY's NSE data path is reliable enough that it doesn't carry the cohort warning.

## Disposition

- **No code change needed.**
- **No future audit should re-suspect this.** When the same observation surfaces again — "DRREDDY is cross-listed but doesn't carry the banner" — the answer is in this tracker.

## Cross-references

- Phase 0 premise-check P0.1
- `AdrCohortBanner.tsx` — the canonical 16-ticker allowlist
- `redesign/audits/funnel-2026-06-03/FINAL-32-STOCK-ANALYSIS.md` §1 Tier C — original framing (now superseded by this resolution)
