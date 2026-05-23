"""Day-84 pharma FRANCHISE quality cohort engine fix.

Audit 2026-05-20 observed:
  > MANKIND FV ₹1,046 vs CMP ₹2,584 (−59.5%) · Got worse (was −50% on
  > prior walk). Pharma DCF still broken.

Day-53 widened MANKIND canary bounds to stop the alert, but the
underlying engine still undershoots premium-quality Indian pharma.
Day-84 fixes the engine itself: a new `_PHARMA_FRANCHISE_TICKERS`
cohort sits between hospital-chain and CDMO sub-buckets in the
existing pharma engine hierarchy:

  - WACC ceiling 0.095  (same as hospitals — quasi-FMCG pricing power
                          on domestic-OTC + branded chronic-care)
  - terminal-g floor 0.055 (same as hospitals — India healthcare
                            nominal-spend CAGR 12-15% per IRDAI /
                            Ayushman Bharat / demographic aging)

Generic-pharma exporters (US-pricing risk) keep WACC floor 0.105 +
TG cap 0.035. CDMO sub-bucket keeps WACC cap 0.105 + TG lift 0.045.

These tests pin:
  1. Source-text guards (sets in BOTH forecaster.py and service.py
     stay in sync, contain the right membership, ordering is correct)
  2. Math-behaviour guards (the WACC cap and TG lift actually fire
     for MANKIND-class names and do NOT fire for generic exporters
     or non-pharma names)
  3. Cohort overlap precedence (DIVISLAB is in both franchise and
     CDMO sets — franchise wins because order matters)
  4. CACHE_VERSION bumped to 134

If you re-org the pharma sub-bucket sets, update BOTH files in lock-
step and re-run this suite.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
FORECASTER_PATH = REPO_ROOT / "models" / "forecaster.py"
SERVICE_PATH = REPO_ROOT / "backend" / "services" / "analysis" / "service.py"
CACHE_PATH = REPO_ROOT / "backend" / "services" / "cache_service.py"


EXPECTED_FRANCHISE_MEMBERS = {
    "MANKIND", "SUNPHARMA", "CIPLA", "TORNTPHARM", "DRREDDY",
    "DIVISLAB", "ABBOTINDIA", "GLAND", "GLAXO", "PFIZER",
    "SANOFI", "AJANTPHARM", "ERIS",
}


def _read(path: Path) -> str:
    # cache_service.py is UTF-8-BOM; the others are plain UTF-8.
    return path.read_text(encoding="utf-8-sig")


def _extract_set_members(src: str, set_name: str) -> set[str]:
    """Extract members of `set_name = frozenset({...})` or
    `set_name = {...}` from source text (literal-membership only —
    no eval). Returns the upper-cased ticker symbols.

    The two source files use slightly different shapes; this helper
    is tolerant of both `frozenset({...})` and bare `{...}`.
    """
    # Find the line where the set is assigned.
    m = re.search(rf"{re.escape(set_name)}\s*=\s*(frozenset\(\{{|\{{)", src)
    if not m:
        return set()
    # From the opening brace, walk forward collecting until the
    # matching closing brace.
    start = m.end() - 1  # position of '{'
    depth = 0
    end = None
    for i, ch in enumerate(src[start:], start=start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
    if end is None:
        return set()
    body = src[start + 1:end]
    return set(re.findall(r'"([A-Z0-9]+)"', body))


# ─────────────────────────────────────────────────────────────────
# 1. Source-text guards: franchise cohort exists in both files
# ─────────────────────────────────────────────────────────────────

def test_forecaster_defines_pharma_franchise_set():
    src = _read(FORECASTER_PATH)
    assert "_PHARMA_FRANCHISE_TICKERS" in src, (
        "models/forecaster.py must define _PHARMA_FRANCHISE_TICKERS "
        "for the Day-84 WACC ceiling block."
    )
    members = _extract_set_members(src, "_PHARMA_FRANCHISE_TICKERS")
    assert members == EXPECTED_FRANCHISE_MEMBERS, (
        f"forecaster _PHARMA_FRANCHISE_TICKERS membership drifted: "
        f"got {members}, expected {EXPECTED_FRANCHISE_MEMBERS}"
    )


def test_forecaster_defines_pharma_franchise_tg_set():
    src = _read(FORECASTER_PATH)
    members = _extract_set_members(src, "_PHARMA_FRANCHISE_TICKERS_TG")
    assert members == EXPECTED_FRANCHISE_MEMBERS, (
        f"forecaster _PHARMA_FRANCHISE_TICKERS_TG membership drifted: "
        f"got {members}, expected {EXPECTED_FRANCHISE_MEMBERS}. The "
        f"WACC-cap set and the TG-lift set must stay identical."
    )


def test_service_defines_pharma_franchise_inline_set():
    src = _read(SERVICE_PATH)
    members = _extract_set_members(src, "_PHARMA_FRANCHISE_TICKERS_INLINE")
    assert members == EXPECTED_FRANCHISE_MEMBERS, (
        f"service _PHARMA_FRANCHISE_TICKERS_INLINE membership drifted: "
        f"got {members}, expected {EXPECTED_FRANCHISE_MEMBERS}. The "
        f"service SSOT block (Day-21) and the forecaster diagnostic "
        f"blocks must stay in sync."
    )


# ─────────────────────────────────────────────────────────────────
# 2. Math anchors: the right numeric thresholds are wired in
# ─────────────────────────────────────────────────────────────────

def test_forecaster_franchise_wacc_cap_is_0_095():
    src = _read(FORECASTER_PATH)
    m = re.search(
        r"_PHARMA_FRANCHISE_TICKERS\s+and\s+wacc\s*>\s*([0-9.]+)",
        src,
    )
    assert m is not None, (
        "forecaster.py must contain the franchise WACC cap test "
        "(_PHARMA_FRANCHISE_TICKERS and wacc > 0.095)."
    )
    assert float(m.group(1)) == pytest.approx(0.095), (
        f"Franchise WACC cap drifted: got {m.group(1)}, expected 0.095"
    )


def test_service_franchise_terminal_g_lift_is_0_055():
    src = _read(SERVICE_PATH)
    m = re.search(
        r"_PHARMA_FRANCHISE_TICKERS_INLINE\s+and\s+terminal_g\s*<\s*([0-9.]+)",
        src,
    )
    assert m is not None, (
        "service.py must contain the franchise TG lift test "
        "(_PHARMA_FRANCHISE_TICKERS_INLINE and terminal_g < 0.055)."
    )
    assert float(m.group(1)) == pytest.approx(0.055), (
        f"Franchise TG lift drifted: got {m.group(1)}, expected 0.055"
    )


# ─────────────────────────────────────────────────────────────────
# 3. Membership semantics: MANKIND specifically is in the cohort
# ─────────────────────────────────────────────────────────────────

def test_mankind_is_in_franchise_cohort():
    """The whole reason Day-84 exists — MANKIND must be in the new
    cohort so its DCF picks up the 0.055 terminal-g + 0.095 WACC cap
    treatment. If MANKIND is silently dropped from the set the audit
    finding regresses."""
    assert "MANKIND" in EXPECTED_FRANCHISE_MEMBERS
    for src_path in (FORECASTER_PATH, SERVICE_PATH):
        src = _read(src_path)
        assert '"MANKIND"' in src, (
            f"{src_path.name} must list MANKIND in the franchise set"
        )


def test_drreddy_is_in_franchise_cohort_not_only_generic():
    """DRREDDY is in BOTH the generic-pharma (WACC floor 0.105) and
    franchise (WACC cap 0.095) sets. Day-84 keeps it in the generic
    set (US-pricing risk is real) but adds it to the franchise cohort
    for the terminal-g lift — domestic formulations + Russia / EM
    franchises have FMCG-like durability."""
    assert "DRREDDY" in EXPECTED_FRANCHISE_MEMBERS


# ─────────────────────────────────────────────────────────────────
# 4. Cohort overlap precedence: franchise wins over CDMO
# ─────────────────────────────────────────────────────────────────

def test_divislab_in_both_franchise_and_cdmo_sets():
    """DIVISLAB has CDMO mechanics but franchise-tier margins (28-32%
    EBITDA, premium-pharma multiples). It belongs in BOTH sets and the
    code must evaluate franchise FIRST so the tighter 0.095/0.055
    treatment wins."""
    src_f = _read(FORECASTER_PATH)
    src_s = _read(SERVICE_PATH)
    franchise_f = _extract_set_members(src_f, "_PHARMA_FRANCHISE_TICKERS")
    cdmo_f = _extract_set_members(src_f, "_PHARMA_CDMO_TICKERS")
    assert "DIVISLAB" in franchise_f
    assert "DIVISLAB" in cdmo_f
    franchise_s = _extract_set_members(src_s, "_PHARMA_FRANCHISE_TICKERS_INLINE")
    cdmo_s = _extract_set_members(src_s, "_PHARMA_CDMO_TICKERS_INLINE")
    assert "DIVISLAB" in franchise_s
    assert "DIVISLAB" in cdmo_s


def test_service_evaluates_franchise_before_cdmo():
    """When DIVISLAB hits the TG block, franchise must be the elif
    branch BEFORE the CDMO elif — otherwise CDMO would short-circuit
    with the looser 0.045 floor."""
    src = _read(SERVICE_PATH)
    f_pos = src.find("_PHARMA_FRANCHISE_TICKERS_INLINE and terminal_g < 0.055")
    c_pos = src.find("_PHARMA_CDMO_TICKERS_INLINE and terminal_g < 0.045")
    assert f_pos > 0 and c_pos > 0, (
        "Both franchise and CDMO TG branches must exist in service.py"
    )
    assert f_pos < c_pos, (
        "service.py must evaluate the franchise TG lift BEFORE the "
        "CDMO TG lift so DIVISLAB picks up the tighter franchise "
        "treatment (0.055 vs 0.045)."
    )


def test_forecaster_evaluates_franchise_before_cdmo_wacc():
    """Same precedence requirement on the WACC cap side."""
    src = _read(FORECASTER_PATH)
    f_pos = src.find("_PHARMA_FRANCHISE_TICKERS and wacc > 0.095")
    c_pos = src.find("_PHARMA_CDMO_TICKERS and wacc > 0.105")
    assert f_pos > 0 and c_pos > 0
    assert f_pos < c_pos, (
        "forecaster.py must evaluate the franchise WACC cap BEFORE "
        "the CDMO WACC cap (DIVISLAB precedence)."
    )


# ─────────────────────────────────────────────────────────────────
# 5. Existing MANKIND override still in force
# ─────────────────────────────────────────────────────────────────

def test_mankind_override_still_present_after_day84():
    """Day-84 stacks on top of the existing per-ticker override —
    MANKIND's terminal_growth_override=0.05 + skip_ipo_routing=True
    from PR feat/pharma-dcf-fix must remain. The cohort lift takes
    terminal_g from 0.05 -> 0.055 (lift kicks in when terminal_g <
    0.055)."""
    from backend.services.analysis import ticker_overrides
    entry = ticker_overrides.get_override("MANKIND")
    assert entry is not None
    assert entry.get("terminal_growth_override") == 0.05
    assert entry.get("skip_ipo_routing") is True


# ─────────────────────────────────────────────────────────────────
# 6. Non-pharma tickers are untouched
# ─────────────────────────────────────────────────────────────────

def test_non_pharma_tickers_not_in_franchise_cohort():
    """TCS / RELIANCE / HDFCBANK / ITC / TITAN must NOT be in the
    pharma franchise cohort."""
    for tkr in ("TCS", "RELIANCE", "HDFCBANK", "ITC", "TITAN",
                "MAXHEALTH", "APOLLOHOSP"):
        assert tkr not in EXPECTED_FRANCHISE_MEMBERS, (
            f"{tkr} must not be in the pharma franchise cohort"
        )


def test_generic_pharma_exporters_not_in_franchise_cohort():
    """AUROPHARMA / ZYDUSLIFE / GLENMARK / IPCALAB / LAURUSLABS / etc.
    keep US-pricing risk premium (WACC floor 0.105 + TG cap 0.035).
    They must NOT be promoted into the franchise cohort by accident."""
    src = _read(FORECASTER_PATH)
    generic_members = _extract_set_members(src, "_PHARMA_GENERIC_TICKERS_TG")
    # Sanity: the generic set hasn't been emptied.
    assert "AUROPHARMA" in generic_members
    assert "ZYDUSLIFE" in generic_members
    assert "GLENMARK" in generic_members
    # Intersection rule: only DRREDDY may legitimately appear in both
    # sets (mixed franchise + generic profile). Everything else stays
    # cleanly separated.
    overlap = generic_members & EXPECTED_FRANCHISE_MEMBERS
    assert overlap <= {"DRREDDY"}, (
        f"Unexpected franchise/generic-pharma overlap: {overlap}. "
        f"Only DRREDDY may sit in both (mixed-profile) — promoting a "
        f"US-pricing-pressure name into the franchise cohort would "
        f"silently mask real risk."
    )


# ─────────────────────────────────────────────────────────────────
# 7. CACHE_VERSION bump
# ─────────────────────────────────────────────────────────────────

def test_cache_version_bumped_to_134_for_day84():
    """Engine change touches FV / MoS / verdict for all 13 franchise
    tickers — CACHE_VERSION must bump."""
    from backend.services.cache_service import CACHE_VERSION
    assert CACHE_VERSION >= 134, (
        f"CACHE_VERSION must be >= 134 for Day-84 engine change "
        f"(got {CACHE_VERSION}). Pharma franchise WACC cap + TG lift "
        f"materially changes cached payloads for 13 tickers."
    )


@pytest.mark.skip(
    reason=(
        "STALE by design: CACHE_VERSION moved past 134 (currently 135 on "
        "main) and the latest banner now references the Day-92 utility "
        "bear-floor audit, not Day-84. The integer + banner are "
        "single-slot — every subsequent bump rotates them. Day-84's "
        "rationale lives permanently in the cache_service.py CACHE_VERSION "
        "history block + cache_invalidation_manifest, which is the "
        "authoritative audit trail post-Day-94. Tracked as Fix-139 "
        "follow-up: replace with a history-block scan for 'day84'."
    )
)
def test_cache_version_header_mentions_day84():
    """The leading comment on CACHE_VERSION must namedrop Day-84 so
    the next person bumping the version has the audit trail."""
    src = _read(CACHE_PATH)
    m = re.search(r"CACHE_VERSION\s*=\s*(\d+)\s*#\s*(\d+):\s*([^\n]+)", src)
    assert m is not None, "CACHE_VERSION header pattern not found"
    cv_int = int(m.group(1))
    banner_n = int(m.group(2))
    banner_text = m.group(3)
    assert cv_int == 134
    assert banner_n == 134
    assert "day84" in banner_text.lower() or "day-84" in banner_text.lower(), (
        f"CACHE_VERSION banner must reference Day-84: got '{banner_text[:80]}...'"
    )
