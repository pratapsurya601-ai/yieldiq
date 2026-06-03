# TCS anonymous analysis page renders error while cohort-mates render working pages

**Status:** filed 2026-06-03. Tracker only — NOT dispatched. **Verify-first framing per operator: do not propose a fix until the premise has been verified against live state.**
**Workstream:** valuation / data-path
**Priority:** MEDIUM — affects SEO landing on one high-search ticker; the other 4 ADR cohort-mates are unaffected (see Phase 0 premise-check, P0.1).

---

## The falsifiable claim (verify this BEFORE proposing any cause)

> Anonymous `/analysis/TCS` renders H1 = "Couldn't load analysis for TCS" with no verdict, no JSON-LD post-CSR, and the error-boundary body copy. Anonymous `/analysis/INFY`, `/analysis/WIPRO`, `/analysis/HCLTECH`, `/analysis/TECHM` — same ADR cohort per `AdrCohortBanner.tsx` allowlist — render H1 + ticker + JSON-LD count=2 + Data-Limited banner. So **TCS is the only one of five rendering an error.**

This is the falsifiable observation. Confirmed on 2026-06-03 against `origin/main = d71e783`. The reason TCS specifically errors is NOT YET KNOWN.

## What this tracker is NOT

It is NOT a proposal to "fix TCS." It is a request to verify the cause against live state before anyone writes code. The verify-first framing exists because three diagnoses cracked under verification earlier this session (the ON CONFLICT writer fix, the "5 zero-row tickers" claim, the 64-corrupt-tickers count) — each had been confidently proposed against an unverified premise, and each turned out to be wrong-direction by ≥3x. TCS-only-errors is exactly the shape of premise that has burnt this discipline before.

## The three possibilities the diagnosis must distinguish

Whichever agent or operator picks this up, the deliverable is verification of WHICH of these is true, not implementation of a fix for any of them:

1. **TCS-specific data state.** Something about TCS's specific cached row, financials shape, or computation path errors in a way the other 4 don't. Cheap to fix (one-ticker data correction).
2. **ADR-subpath edge case.** TCS happens to exercise a code path that the other 4 don't (e.g. TCS has US ADR ratio metadata the others lack; TCS's earliest filing date is different; TCS's auditor change history is different). The other 4 are one data-refresh or one new filing away from hitting the same. Not cheap.
3. **Visible edge of a wider issue.** The error is the first detection of a class of bug that is silently degrading the other 4 already (e.g. their FV is being clamped or substituted but not erroring; TCS's same degradation crosses a different threshold and errors). Most expensive to fix.

## Hard rules for whoever picks this up

- READ-ONLY on prod data until the cause is verified. No `UPDATE` on `company_financials`, no engine recompute, no `CACHE_VERSION` bump, no manifest entry.
- Compare live prod state on TCS to its 4 cohort-mates. Specifically: what does each return from `/api/analysis/<TICKER>` (or whatever the analysis service endpoint is)? At what step does TCS's response diverge?
- If the diagnosis surfaces a multi-ticker issue, STOP and flag — that's a different scope.
- If the diagnosis surfaces a TCS-only data fix that's safe (e.g. one corrupt row), propose the fix with the canary-diff + snapshot discipline per root `CLAUDE.md` rules 1+2.

## Cross-references

- Phase 0 premise-check P0.1: confirmed only TCS errors among the 5-ticker ADR cohort
- `AdrCohortBanner.tsx` allowlist: 16 tickers, includes TCS+INFY+WIPRO+HCLTECH+TECHM, excludes DRREDDY (intentional — see `drreddy-adr-allowlist-resolved.md`)
- `redesign/audits/funnel-2026-06-03/FINAL-32-STOCK-ANALYSIS.md` — original audit that flagged the 5-ticker pattern (incorrectly, before Phase 0 narrowed it to TCS-only)
- `redesign/audits/funnel-2026-06-03/AUDIT.md` — original visual confirmation of TCS "Couldn't load" runtime
