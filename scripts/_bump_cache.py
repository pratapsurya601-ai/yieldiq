"""Day-20 CACHE_VERSION bump utility — 121 -> 122."""
from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / "backend" / "services" / "cache_service.py"

DAY20_COMMENT = (
    "122: fix/day20-wacc-ceiling-and-safety-net-revenue (2026-05-20). "
    "POST-validation fix. The impact_check_day14_19.py forced-warm + "
    "measurement showed only 3/24 named Day-14-19 tickers actually moved "
    "FV at cache_version=121 — 13/24 recomputed but produced near-same "
    "FV. Two root causes diagnosed via live payload inspection: "
    "(a) Day-16/Day-19 WACC FLOORS were no-ops because CAPM-derived "
    "hospital/CDMO WACCs sit at 0.098-0.128, already above the 0.085/"
    "0.095 floors. max(wacc_floor, X) returns unchanged CAPM. Switched "
    "to a POST-clip CEILING: hospitals capped at 0.095, CDMOs at 0.105 "
    "— these actually bite (e.g. AGARWALEYE 0.128 -> 0.095, ANTHEM/"
    "SAGILITY/IKS 0.128 -> 0.105). (b) Day-18 logistics rescue couldn't "
    "fire because the safety-net's _fin_sn dict at service.py:2574 was "
    "missing the 'revenue' field. compute_story_dcf_fair_value returns "
    "None at rev0<=0 guard, so DELHIVERY / PAYTM / MEESHO / ZOMATO / "
    "POLICYBZR / NYKAA / SWIGGY all failed the 3rd rescue rung — "
    "verified live for DELHIVERY (data_issues confirmed safety net "
    "fired but all 3 rungs returned None). Added 'revenue' + "
    "'latest_revenue' to the dict. Expected post-recompute: hospitals "
    "FV move +30-50% (TV uplift from tighter wacc-g spread); CDMOs +20-"
    "40%; DELHIVERY now rescues via story-DCF (engine string flips to "
    "story_dcf_after_dcf_collapse). Defers Day-16/Day-19 terminal-g "
    "lift gating bug (TG flag absent from all payloads — needs more "
    "diagnosis) and ITCHOTELS/ABLBL no-cache-row bug (pipeline short-"
    "circuit on NULL eps_basic — separate PR). Sector-scope: pharma + "
    "Internet Platform (multi-sector — same scope as Day-16/Day-18/19)."
)


def main() -> int:
    text = PATH.read_text(encoding="utf-8")
    old = "CACHE_VERSION = 121"
    new = f"CACHE_VERSION = 122  # {DAY20_COMMENT}  # # "
    if old not in text:
        print(f"FAIL: '{old}' not found in {PATH}")
        return 2
    count = text.count(old + "  #")
    if count != 1:
        print(f"FAIL: expected 1 declaration, found {count}")
        return 3
    new_text = text.replace(old + "  #", new + "#", 1)
    PATH.write_text(new_text, encoding="utf-8", newline="")
    print(f"OK: bumped CACHE_VERSION 121 -> 122 in {PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
