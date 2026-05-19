"""Day-20 part-2 CACHE_VERSION bump utility — 122 -> 123."""
from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / "backend" / "services" / "cache_service.py"

DAY20_PART2_COMMENT = (
    "123: fix/day20-part2-delhivery-override-retune (2026-05-20). "
    "DELHIVERY's Day-18 story-DCF override params (22% growth / 8% op "
    "margin / 70% reinvestment / 13.5% WACC) produced NEGATIVE enterprise "
    "value at the synthetic anchors — FCFFs stayed negative through year "
    "7 and the PV of explicit period (-₹612 Cr) overwhelmed PV of TV "
    "(+₹292 Cr). Story-DCF returned None at the EV<=0 guard, so the "
    "Day-20 PR-#410 revenue-field fix had no observable effect for "
    "DELHIVERY — the rescue chain returned None and the safety-net "
    "logged the data_limited caveat. Retuned to v3: 22% growth / 15% "
    "target op margin (mature 3PL benchmark; BlueDart pre-COVID 14-16%) "
    "/ 40% reinvestment (asset-light pivot priced) / 3y margin "
    "convergence / 12.5% WACC. With these params FV computes ₹205 vs "
    "CMP ₹459 (0.45x — comfortably inside [0.30, 3.50] safety-net band). "
    "FV still well below 22-analyst consensus ₹528 because this is a "
    "narrative model with conservative assumptions (confidence cap = 50 "
    "= 'story, not fact'). To match consensus would require terminal "
    "margin 18-20% which is a growth-investor scenario this engine "
    "intentionally does not model. Sector-scope: Internet Platform "
    "(single-ticker override). Expected post-recompute: DELHIVERY FV "
    "₹64 -> ₹205, engine string flips to story_dcf_after_dcf_collapse, "
    "StoryDcfBadge fires on the frontend, confidence_score = 43-50."
)


def main() -> int:
    text = PATH.read_text(encoding="utf-8")
    old = "CACHE_VERSION = 122"
    new = f"CACHE_VERSION = 123  # {DAY20_PART2_COMMENT}  # # "
    if old not in text:
        print(f"FAIL: '{old}' not found in {PATH}")
        return 2
    count = text.count(old + "  #")
    if count != 1:
        print(f"FAIL: expected 1 declaration, found {count}")
        return 3
    new_text = text.replace(old + "  #", new + "#", 1)
    PATH.write_text(new_text, encoding="utf-8", newline="")
    print(f"OK: bumped CACHE_VERSION 122 -> 123 in {PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
