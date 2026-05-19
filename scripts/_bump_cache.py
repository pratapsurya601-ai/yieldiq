"""Day-17 CACHE_VERSION bump utility — 119 -> 120."""
from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / "backend" / "services" / "cache_service.py"

DAY17_COMMENT = (
    "120: feat/day17-recent-ipo-routing (2026-05-20). Tier-2 outlier "
    "reduction PR #2 (after Day-16 hospital chain). Routes 5 under-valued "
    "recent-IPO tickers to their proper peer cohorts. Sector overrides: "
    "ITCHOTELS + ABLBL pinned to Retail (was 'Hotels'/'Hospitality' -> "
    "no cohort -> plain DCF). Bank-like classifier: FIVESTAR + AADHARHFC "
    "+ CANHLIFE added to _NBFC_INSURANCE_BANKLIKE and FINANCIAL_COMPANIES "
    "(was producing FV ~7% of consensus by routing through generic DCF). "
    "Financial peer groups: FIVESTAR -> lending_nbfc, AADHARHFC -> "
    "premium_hfc, CANHLIFE -> life_insurance. Tier-2 sector resolution: "
    "Hospitality / Hotels / Lodging now map to the retail peer cohort "
    "(consumer-brand + store-expansion economics). IPO window: retail + "
    "consumer cyclical lifted 36 -> 48 months to cover the 4y QSR "
    "franchise ramp (WESTLIFE/DEVYANI/SAPPHIRE/ITCHOTELS/ABLBL all in "
    "the 0-48mo bucket). Sector-scope: financial-services + retail + "
    "consumer-cyclical (multi-sector by design — 3 separate sub-sectors "
    "share the recent-IPO routing path). Expected directional shifts: "
    "FIVESTAR ~Rs45 -> Rs500+, AADHARHFC ~Rs45 -> Rs500+, CANHLIFE "
    "~Rs14 -> Rs160+, ITCHOTELS ~Rs16 -> Rs180+, ABLBL ~Rs10 -> Rs140+."
)


def main() -> int:
    text = PATH.read_text(encoding="utf-8")
    old = "CACHE_VERSION = 119"
    new = f"CACHE_VERSION = 120  # {DAY17_COMMENT}  # # "
    if old not in text:
        print(f"FAIL: '{old}' not found in {PATH}")
        return 2
    count = text.count(old + "  #")
    if count != 1:
        print(f"FAIL: expected 1 declaration, found {count}")
        return 3
    new_text = text.replace(old + "  #", new + "#", 1)
    PATH.write_text(new_text, encoding="utf-8", newline="")
    print(f"OK: bumped CACHE_VERSION 119 -> 120 in {PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
