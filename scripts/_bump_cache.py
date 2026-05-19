"""Day-16 CACHE_VERSION bump utility — 118 -> 119."""
from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / "backend" / "services" / "cache_service.py"

DAY16_COMMENT = (
    "119: feat/day16-hospital-chain (2026-05-19). New _HOSPITAL_CHAIN_TICKERS "
    "sub-bucket in models/forecaster.py for 10 listed hospital + single-"
    "specialty chains (MAXHEALTH/FORTIS/MEDANTA/KIMS/NH/APOLLOHOSP/ASTERDM/"
    "RAINBOW/VIJAYA/AGARWALEYE). Lower WACC floor (0.085 vs default 0.09) + "
    "raise terminal-g cap to 0.055 (vs default 0.04). Day-13 outlier scan "
    "showed these systematically under-valued by 50-85% (MAXHEALTH 0.16x, "
    "VIJAYA 0.15x, MEDANTA 0.26x, FORTIS 0.32x, KIMS 0.36x, APOLLOHOSP "
    "0.39x). Root cause: standard CAPM ≈0.11 + default TG ≈0.04 misprice "
    "this sub-sector because hospital service contracts are quasi-recurring "
    "and Indian healthcare nominal spend has compounded 12-15% per decade "
    "(Ayushman Bharat + insurance penetration + demographic aging). Both "
    "_HOSPITAL_CHAIN_TICKERS and _HOSPITAL_CHAIN_TICKERS_TG sets stay synced "
    "(Day-13 lesson — asymmetric WACC/TG sets produce mis-pricing). Wacc-g "
    "spread = 0.030 — at Gordon-model safety threshold (exact equality). "
    "Sector-scope: Pharma (sub-sector). Expected: MAXHEALTH ~₹197 -> ₹600+, "
    "FORTIS ~₹353 -> ₹700+, MEDANTA ~₹342 -> ₹800+, KIMS ~₹290 -> ₹500+. "
    "Diagnostics (LALPATHLAB/METROPOLIS) intentionally NOT included — "
    "commodity pricing pressure makes them riskier than full-service "
    "hospital chains."
)


def main() -> int:
    text = PATH.read_text(encoding="utf-8")
    old = "CACHE_VERSION = 118"
    new = f"CACHE_VERSION = 119  # {DAY16_COMMENT}  # # "
    if old not in text:
        print(f"FAIL: '{old}' not found in {PATH}")
        return 2
    count = text.count(old + "  #")
    if count != 1:
        print(f"FAIL: expected 1 declaration, found {count}")
        return 3
    new_text = text.replace(old + "  #", new + "#", 1)
    PATH.write_text(new_text, encoding="utf-8", newline="")
    print(f"OK: bumped CACHE_VERSION 118 -> 119 in {PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
