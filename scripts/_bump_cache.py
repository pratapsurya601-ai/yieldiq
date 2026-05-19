"""One-shot CACHE_VERSION bump utility — Day-14.

Reads backend/services/cache_service.py, finds the literal
``CACHE_VERSION = 117`` (anywhere on line 34's long comment line),
replaces it with ``CACHE_VERSION = 118  # <day-14 comment>  # # `` and
preserves the historical inline-comment ledger that's already there.

The pattern used in past bumps: prepend the new bump's annotation,
keep the prior annotations intact, separated by `# # `.
"""
from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / "backend" / "services" / "cache_service.py"

DAY14_COMMENT = (
    "118: feat/day14-cache-bump (2026-05-19). Force recompute so the Day-7 → "
    "Day-13 fixes land in user-visible payloads. Bundled changes: "
    "(a) Day-7 yfinance current_liabilities collector — fills 4,003 NULL rows "
    "in financials, unblocks Tier 2 ROCE enrichment for INFY-shape tickers. "
    "(b) Day-8 story-DCF back-test guardrails — surfaces operator-review "
    "backlog. (c) Day-9 frontend StoryDcfBadge — surfaces narrative-valuation "
    "warning when third-rung rescue fires. (d) Day-10 engine-string fidelity "
    "fix in analysis/service.py — _fair_value_source no longer collapses "
    "all 3 safety-net rungs to 'tier2_fallback'; payload now carries the "
    "rung-specific source ('tier2_fallback_after_dcf_collapse', "
    "'platform_ps_after_dcf_collapse', 'story_dcf_after_dcf_collapse'). "
    "(e) Day-11/12 admin endpoints for story-DCF override review (read-only "
    "+ preview-simulator + audit). (f) Day-13 pharma-generic expansion — "
    "added NATCOPHARM (was producing 3.57x consensus), renamed "
    "NEULAND -> NEULANDLAB (dead-entry bug — never matched real NSE ticker), "
    "synced WACC and terminal-g sets so generics get symmetric treatment. "
    "Sector-scope: pharma generics tighten WACC floor (0.105) + terminal-g "
    "cap (0.035); platform/payments/fintech_broker/wealth_mgmt cohort "
    "tickers may flip to story_dcf_after_dcf_collapse engine on recompute. "
    "Expected directional changes: NATCOPHARM ~3,393 -> ~1,000-1,200; "
    "DRREDDY ~1,927 -> ~1,400; ZYDUSLIFE ~1,370 -> ~1,000; PAYTM / ZOMATO "
    "/ MEESHO / SWIGGY may pick up StoryDcfBadge with confidence cap 50."
)


def main() -> int:
    text = PATH.read_text(encoding="utf-8")
    old = "CACHE_VERSION = 117"
    new = f"CACHE_VERSION = 118  # {DAY14_COMMENT}  # # "
    if old not in text:
        print(f"FAIL: '{old}' not found in {PATH}")
        return 2
    # Make sure we only edit the variable declaration once.
    count = text.count(old + "  #")
    if count != 1:
        print(f"FAIL: expected exactly 1 declaration, found {count}")
        return 3
    new_text = text.replace(old + "  #", new + "#", 1)
    PATH.write_text(new_text, encoding="utf-8", newline="")
    print(f"OK: bumped CACHE_VERSION 117 -> 118 in {PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
