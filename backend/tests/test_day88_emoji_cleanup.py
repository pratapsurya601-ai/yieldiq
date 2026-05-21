# backend/tests/test_day88_emoji_cleanup.py
# ═══════════════════════════════════════════════════════════════
# Day-88 regression lock-in: emojis removed from analysis-page
# summary cards.
#
# The 2026-05-20 UX audit called out emoji clutter on summary
# headers undermining the institutional feel of YieldIQ. Day-88
# swapped the remaining decorative emojis on the analysis-page
# surfaces (and the onboarding step explainer) for Lucide React
# icons, matching the convention established by MarketPulse.tsx.
#
# These tests are source-text assertions — they run without a
# Node toolchain or any frontend deps, so they are safe to put in
# CI alongside the backend pytest suite. They prevent the emoji
# from quietly creeping back in via a future edit.
# ═══════════════════════════════════════════════════════════════

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND = REPO_ROOT / "frontend" / "src"

# Files that were de-emojified in Day-88. Keep this list in sync
# with the PR — if a future edit re-adds emoji to one of these,
# the negative-assertion block below will fail loudly.
TOUCHED = {
    "red_flag_insights": FRONTEND / "components" / "analysis" / "RedFlagInsights.tsx",
    "dividend_tracker": FRONTEND / "components" / "analysis" / "DividendTracker.tsx",
    "macro_dashboard": FRONTEND / "components" / "home" / "MacroDashboard.tsx",
    "step_explainer": FRONTEND / "components" / "onboarding" / "StepExplainer.tsx",
    "fv_history": FRONTEND / "components" / "analysis" / "FairValueHistory.tsx",
    "financials": FRONTEND / "components" / "analysis" / "FinancialStatements.tsx",
    "peer_comparison": FRONTEND / "components" / "analysis" / "PeerComparison.tsx",
    "data_quality": FRONTEND / "components" / "analysis" / "DataQualityBanner.tsx",
}


def _read(key: str) -> str:
    path = TOUCHED[key]
    assert path.exists(), f"Day-88 source file missing: {path}"
    return path.read_text(encoding="utf-8")


# ───────────────────────────────────────────────────────────────
# Negative assertions: the specific emojis the audit flagged
# must NOT appear in the touched files anymore.
# ───────────────────────────────────────────────────────────────

def test_red_flag_insights_has_no_severity_emoji() -> None:
    src = _read("red_flag_insights")
    # The three offenders the audit pointed at: red/yellow circle
    # and green check. They were the SEVERITY_LABEL prefixes.
    assert "\U0001F534" not in src, "red circle emoji must be gone"
    assert "\U0001F7E1" not in src, "yellow circle emoji must be gone"
    assert "✅" not in src, "green check emoji must be gone"


def test_dividend_tracker_coverage_emojis_removed() -> None:
    src = _read("dividend_tracker")
    # The fmtCoverage helper used to inline ✓ ⚠ ✗ after the ratio.
    # Day-88 replaced it with a <CoverageValue> JSX component.
    assert "✓" not in src, "check mark must be gone"
    assert "✗" not in src, "cross mark must be gone"
    # Bare ⚠ U+26A0 (without VS16) was the moderate-coverage glyph.
    assert "⚠" not in src, "warning sign must be gone from coverage"


def test_macro_vix_zone_labels_have_no_emoji() -> None:
    src = _read("macro_dashboard")
    # The VIX zone labels used 😌 / ⚠ / 😰 as mood indicators.
    assert "\U0001F60C" not in src, "calm face emoji must be gone"
    assert "\U0001F630" not in src, "fear face emoji must be gone"
    # Color tokens still carry the semantic — these labels remain.
    assert '"Calm"' in src
    assert '"Caution"' in src
    assert '"Fear"' in src


def test_step_explainer_bullet_icons_swapped_to_lucide() -> None:
    src = _read("step_explainer")
    # 🔍 / 💡 / 🎯 were the BULLETS[].icon string values.
    assert "\U0001F50D" not in src, "magnifying glass emoji must be gone"
    assert "\U0001F4A1" not in src, "lightbulb emoji must be gone"
    assert "\U0001F3AF" not in src, "target emoji must be gone"


def test_fv_history_lock_glyph_replaced() -> None:
    src = _read("fv_history")
    assert "\U0001F512" not in src, "lock emoji must be gone"


def test_peer_comparison_main_star_replaced() -> None:
    src = _read("peer_comparison")
    # ★ U+2605 black star used as the main-ticker marker in the
    # company column AND in the leader insight string.
    assert "★" not in src, "black star glyph must be gone"


# ───────────────────────────────────────────────────────────────
# Positive assertions: Lucide imports/usage must be in place so
# the replacement icons actually render.
# ───────────────────────────────────────────────────────────────

def test_red_flag_insights_imports_lucide_severity_icons() -> None:
    src = _read("red_flag_insights")
    assert 'from "lucide-react"' in src
    assert "AlertCircle" in src
    assert "AlertTriangle" in src
    assert "CheckCircle2" in src


def test_dividend_tracker_imports_lucide() -> None:
    src = _read("dividend_tracker")
    assert 'from "lucide-react"' in src
    # Re-exports under different local names are OK — at minimum
    # the Check icon is the new ≥2× coverage marker.
    assert "Check" in src


def test_step_explainer_imports_lucide_icons() -> None:
    src = _read("step_explainer")
    assert 'from "lucide-react"' in src
    assert "Search" in src
    assert "Lightbulb" in src
    assert "Target" in src


def test_fv_history_and_financials_use_lock_icon() -> None:
    fv = _read("fv_history")
    fin = _read("financials")
    assert 'from "lucide-react"' in fv and "Lock" in fv
    assert 'from "lucide-react"' in fin and "Lock" in fin


def test_data_quality_banner_imports_lucide_icons() -> None:
    src = _read("data_quality")
    assert 'from "lucide-react"' in src
    assert "AlertTriangle" in src
    assert "Info" in src
