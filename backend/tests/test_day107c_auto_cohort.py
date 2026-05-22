"""Day-107c: Indian auto OEM sector cohort overrides.

Ships three coordinated engine knobs scoped to a 12-ticker Indian
auto OEM + ancillary cohort:

  1. Segment-differentiated terminal-g lift
       2W (BAJAJ-AUTO, HEROMOTOCO, EICHERMOT, TVSMOTOR)  → 5.0%
       4W passenger (MARUTI, TATAMOTORS, M&M)            → 4.5%
       CV (ASHOKLEY)                                     → 4.0%
       ancillary/tires (MOTHERSON, BOSCHLTD, MRF,
                        APOLLOTYRE)                       → 4.0%

  2. ASHOKLEY CV WACC floor at 0.11 (commodity-linked CV-cycle beta
     understated by default CAPM landing). 2W / 4W OEMs intentionally
     get NO WACC floor — their betas land in the 1.0-1.2 band.

  3. Cycle-stage detection from `enriched.ebitda_margin` vs
     `enriched.ebitda_margin_5y_median`:
       - ratio > 1.5 → "peak" flag (data-issue surfaced)
       - ratio < 0.5 → "trough" flag + bear-floor `min(0.6*fv,
                                                     0.4*price)`
         per the Day-51 cyclical-trough bear-floor pattern.

Precedents followed:
  - Day-84 pharma FRANCHISE cohort: inline set + TG lift block at
    the SSOT finalisation site immediately before DCFEngine.
  - Day-76 reverse-DCF cyclical normalization: cycle peak/trough
    detection from margin vs 5y-median ratio.
  - Day-51 cyclical-trough bear-floor: `min(0.6*fv, 0.4*price)`
    re-clamp when the cycle is below floor.

These tests are source-text + manifest guards — they don't spin
up the engine. The behavioural canary will exercise the engine.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SERVICE_PATH = REPO_ROOT / "backend" / "services" / "analysis" / "service.py"
MANIFEST_PATH = (
    REPO_ROOT / "backend" / "services" / "cache_invalidation_manifest.py"
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ─── Test 1: 2W cohort members present in source ──────────────────
def test_auto_2w_cohort_members_in_service():
    src = _read(SERVICE_PATH)
    m = re.search(r"_AUTO_2W_TICKERS_INLINE\s*=\s*\{([^}]+)\}", src)
    assert m, "2W cohort set missing from service.py"
    members = m.group(1)
    for sym in ("BAJAJ-AUTO", "HEROMOTOCO", "EICHERMOT", "TVSMOTOR"):
        assert sym in members, f"{sym} missing from 2W cohort"


# ─── Test 2: 4W and CV cohort members present in source ───────────
def test_auto_4w_cv_cohort_members_in_service():
    src = _read(SERVICE_PATH)
    m4 = re.search(r"_AUTO_4W_TICKERS_INLINE\s*=\s*\{([^}]+)\}", src)
    assert m4, "4W cohort set missing"
    members4 = m4.group(1)
    for sym in ("MARUTI", "TATAMOTORS", "M&M"):
        assert sym in members4, f"{sym} missing from 4W cohort"
    mcv = re.search(r"_AUTO_CV_TICKERS_INLINE\s*=\s*\{([^}]+)\}", src)
    assert mcv, "CV cohort set missing"
    assert "ASHOKLEY" in mcv.group(1)


# ─── Test 3: Non-auto names NOT in cohort (no false positives) ────
def test_non_auto_tickers_not_in_cohort():
    src = _read(SERVICE_PATH)
    m = re.search(
        r"_AUTO_COHORT_ALL_INLINE\s*=\s*\{([^}]+)\}", src,
    )
    assert m, "_AUTO_COHORT_ALL_INLINE missing"
    members = m.group(1)
    # Banks + IT should NOT trigger the auto cohort
    for non_auto in ("HDFCBANK", "TCS", "RELIANCE", "INFY", "ICICIBANK"):
        # Word-boundary check so MMTC etc. don't false-match M&M
        assert not re.search(rf"\"{non_auto}\"", members), (
            f"{non_auto} should NOT be in auto cohort"
        )


# ─── Test 4: Segment TG values are differentiated (2W > 4W > CV) ──
def test_auto_segment_tg_differentiated():
    src = _read(SERVICE_PATH)
    # 2W block lifts to 0.050
    assert re.search(
        r"_AUTO_2W_TICKERS_INLINE.*?terminal_g\s*<\s*0\.050",
        src, re.DOTALL,
    ), "2W TG target should be 0.050"
    # 4W block lifts to 0.045
    assert re.search(
        r"_AUTO_4W_TICKERS_INLINE.*?terminal_g\s*<\s*0\.045",
        src, re.DOTALL,
    ), "4W TG target should be 0.045"
    # CV block lifts to 0.040
    assert re.search(
        r"_AUTO_CV_TICKERS_INLINE.*?terminal_g\s*<\s*0\.040",
        src, re.DOTALL,
    ), "CV TG target should be 0.040"


# ─── Test 5: ASHOKLEY WACC floor at 11% ───────────────────────────
def test_ashokley_wacc_floor_11pct():
    src = _read(SERVICE_PATH)
    assert "_AUTO_CV_WACC_FLOOR = 0.11" in src, (
        "ASHOKLEY CV WACC floor should be 0.11"
    )
    assert re.search(
        r'clean_ticker\s*==\s*"ASHOKLEY".*?_AUTO_CV_WACC_FLOOR',
        src, re.DOTALL,
    ), "ASHOKLEY WACC floor gate missing"


# ─── Test 6: Cycle peak detection threshold = 1.5x ────────────────
def test_cycle_peak_detection_threshold():
    src = _read(SERVICE_PATH)
    # Peak threshold ratio > 1.5
    assert re.search(
        r"_ratio\s*>\s*1\.5.*?_auto_cycle_stage\s*=\s*\"peak\"",
        src, re.DOTALL,
    ), "Cycle peak threshold should be 1.5x 5y median"


# ─── Test 7: Cycle trough detection threshold = 0.5x ──────────────
def test_cycle_trough_detection_threshold():
    src = _read(SERVICE_PATH)
    assert re.search(
        r"_ratio\s*<\s*0\.5.*?_auto_cycle_stage\s*=\s*\"trough\"",
        src, re.DOTALL,
    ), "Cycle trough threshold should be 0.5x 5y median"


# ─── Test 8: Bear-floor formula matches Day-51 pattern ────────────
def test_bear_floor_min_06fv_04price():
    src = _read(SERVICE_PATH)
    # The auto bear floor is min(0.6*iv, 0.4*price)
    assert re.search(
        r"_auto_cycle_stage\s*==\s*\"trough\".*?"
        r"min\(\s*0\.6\s*\*\s*iv,\s*0\.4\s*\*\s*price",
        src, re.DOTALL,
    ), "Auto trough bear-floor formula must be min(0.6*iv, 0.4*price)"


# ─── Test 9: Manifest entry with correct applied_at + scope ───────
def test_manifest_entry_present():
    from backend.services.cache_invalidation_manifest import MANIFEST

    entry = next(
        (
            e for e in MANIFEST
            if e["version_id"] == "v_day107c_auto_cohort_2026_05_23"
        ),
        None,
    )
    assert entry is not None, "Day-107c manifest entry missing"
    assert entry["applied_at"] == datetime(
        2026, 5, 23, 10, 10, 0, tzinfo=timezone.utc,
    ), "applied_at must be 2026-05-23 10:10 UTC"
    tickers = entry["scope"]["tickers"]
    for required in (
        "MARUTI", "TATAMOTORS", "M&M", "BAJAJ-AUTO",
        "HEROMOTOCO", "EICHERMOT", "ASHOKLEY", "TVSMOTOR",
        "MOTHERSON", "BOSCHLTD", "MRF", "APOLLOTYRE",
    ):
        assert required in tickers, (
            f"{required} missing from manifest scope.tickers"
        )
    assert entry["scope"]["fields"] == "*"


# ─── Test 10: Ancillary/tire cohort lifts TG to 4.0% ──────────────
def test_auto_ancillary_cohort_tg_lift():
    src = _read(SERVICE_PATH)
    m = re.search(
        r"_AUTO_ANCILLARY_TICKERS_INLINE\s*=\s*\{([^}]+)\}", src,
    )
    assert m, "Ancillary cohort set missing"
    members = m.group(1)
    for sym in ("MOTHERSON", "BOSCHLTD", "MRF", "APOLLOTYRE"):
        assert sym in members, f"{sym} missing from ancillary cohort"
    assert re.search(
        r"_AUTO_ANCILLARY_TICKERS_INLINE.*?terminal_g\s*<\s*0\.040",
        src, re.DOTALL,
    ), "Ancillary TG target should be 0.040"
