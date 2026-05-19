"""Day-21 CACHE_VERSION bump utility — 123 -> 124."""
from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / "backend" / "services" / "cache_service.py"

DAY21_COMMENT = (
    "124: fix/day21-tg-lift-propagation (2026-05-20). Bug B fix. The "
    "Day-16/Day-19 terminal-g lift blocks inside FCFForecaster.predict() "
    "were structurally orphaned: they mutated a LOCAL _g_terminal_eff "
    "variable that never propagated to DCFEngine(terminal_growth=...) at "
    "service.py:1898. So the lift had ZERO effect on TV math despite the "
    "code paths existing — verified by absence of _hospital_chain_terminal_"
    "g_lifted and _pharma_cdmo_terminal_g_lifted flags across all 13 live "
    "payloads at cache_version=122. Moved the lift to service.py:~L1294 "
    "(immediately after the ticker_overrides terminal_g_override block and "
    "BEFORE DCFEngine construction). Mirrors the canonical sets in "
    "models/forecaster.py (test_tg_lift_set_membership_matches_forecaster "
    "locks in the parity). Hospitals: TG 0.040 -> 0.055. CDMOs: TG 0.040 "
    "-> 0.045. Combined with Day-20 WACC ceiling (hospitals capped at "
    "0.095, CDMOs at 0.105), the wacc-g spread tightens to 0.040 / 0.060 "
    "respectively — both above the 0.020 Gordon-model safety floor. "
    "Expected: now-LIVE TG lift adds another +20-40% on top of the Day-20 "
    "WACC ceiling's +5-17% — bringing hospital FVs from current 0.16-0.64x "
    "consensus toward 0.40-0.85x. Sector-scope: pharma (same as Day-16/19)."
)


def main() -> int:
    text = PATH.read_text(encoding="utf-8")
    old = "CACHE_VERSION = 123"
    new = f"CACHE_VERSION = 124  # {DAY21_COMMENT}  # # "
    if old not in text:
        print(f"FAIL: '{old}' not found in {PATH}")
        return 2
    count = text.count(old + "  #")
    if count != 1:
        print(f"FAIL: expected 1 declaration, found {count}")
        return 3
    new_text = text.replace(old + "  #", new + "#", 1)
    PATH.write_text(new_text, encoding="utf-8", newline="")
    print(f"OK: bumped CACHE_VERSION 123 -> 124 in {PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
