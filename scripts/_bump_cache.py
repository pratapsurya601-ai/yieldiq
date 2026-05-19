"""Day-18+19 CACHE_VERSION bump utility — 120 -> 121."""
from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / "backend" / "services" / "cache_service.py"

DAY18_19_COMMENT = (
    "121: feat/day18-19-logistics-cdmo (2026-05-20). Tier-2 outlier reduction "
    "PR #3 (after Day-16 hospital + Day-17 recent-IPO routing). TWO additive "
    "engine changes: (a) Day-18 logistics platforms (DELHIVERY/MAHLOG/ALLCARGO) "
    "added to TICKER_SECTOR_OVERRIDES->Internet Platform, routing them through "
    "the existing Story-DCF rescue rung when generic DCF collapses. DELHIVERY "
    "also gets a per-ticker override in config/story_dcf_overrides.json "
    "(initial_growth=0.22, target_op_margin=0.08, reinvestment_rate=0.70, "
    "wacc=0.135) calibrated to actual analyst guidance. Live scan showed "
    "DELHIVERY FV Rs64 vs 22-analyst consensus Rs528 (0.12x). (b) Day-19 "
    "pharma CDMO/contract-services sub-bucket. New _PHARMA_CDMO_TICKERS "
    "frozenset (DIVISLAB/SYNGENE/COHANCE/ANTHEM/SAGILITY/IKS, 6 names). "
    "WACC floor 0.095 (midpoint between hospitals 0.085 and generic-pharma "
    "0.105) + TG cap 0.045 (midpoint between hospitals 0.055 and generic "
    "0.035). WACC-g spread = 0.050 (well above Gordon-model 0.030 threshold). "
    "Justification: multi-year contracts (5-10y CDMO MSAs) + sticky "
    "enterprise BPM contracts give revenue durability between generic "
    "pharma and hospitals. Sector-scope: pharma + Internet Platform "
    "(multi-sector by design). Expected: DELHIVERY ~Rs64 -> Rs450+, "
    "COHANCE ~Rs92 -> Rs250+, ANTHEM ~Rs134 -> Rs450+, SAGILITY ~Rs35 "
    "-> Rs55+, IKS ~Rs672 -> Rs1500+. SYNGENE/DIVISLAB already inside "
    "rescue band — should tighten further toward consensus."
)


def main() -> int:
    text = PATH.read_text(encoding="utf-8")
    old = "CACHE_VERSION = 120"
    new = f"CACHE_VERSION = 121  # {DAY18_19_COMMENT}  # # "
    if old not in text:
        print(f"FAIL: '{old}' not found in {PATH}")
        return 2
    count = text.count(old + "  #")
    if count != 1:
        print(f"FAIL: expected 1 declaration, found {count}")
        return 3
    new_text = text.replace(old + "  #", new + "#", 1)
    PATH.write_text(new_text, encoding="utf-8", newline="")
    print(f"OK: bumped CACHE_VERSION 120 -> 121 in {PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
