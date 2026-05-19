"""Verify the retuned DELHIVERY override produces a positive,
in-band FV BEFORE bumping CACHE_VERSION."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.services.story_dcf_engine import (
    compute_story_dcf_fair_value,
    _load_overrides,
)

_load_overrides.cache_clear()

# Real-ish DELHIVERY anchors
result = compute_story_dcf_fair_value(
    ticker="DELHIVERY",
    sector="Internet Platform",
    financials={
        "revenue": 8930e7,       # ~₹8,930 Cr revenue
        "shares": 74.87e7,       # 74.87 Cr shares
        "current_price": 459.4,
    },
)

if result is None:
    print("FAIL: story-DCF returned None — params still produce negative EV")
    sys.exit(1)

fv = float(result["fair_value"])
cmp_ = 459.4
ratio = fv / cmp_
in_band = 0.30 <= ratio <= 3.50
print(f"DELHIVERY tuned params produce:")
print(f"  FV       = ₹{fv:.2f}")
print(f"  CMP      = ₹{cmp_:.2f}")
print(f"  FV/CMP   = {ratio:.3f}x")
print(f"  in [0.30, 3.50] safety-net band? {in_band}")
print(f"  engine confidence cap = {result.get('confidence_score')}")
print(f"  TV pct of EV = {result.get('_meta', {}).get('tv_pct_of_ev')}")
if not in_band:
    print("WARN: FV is finite but below safety-net floor — rescue would be rejected")
    sys.exit(2)
print("OK: new params produce in-band FV; safety net will pass the rescue value.")
