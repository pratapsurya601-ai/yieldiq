"""Day-32 (2026-05-20): regression guards for the WatchlistButton
component + 2 placement sites.

Day-27 audit found backend routers/watchlist.py is complete (4
endpoints). Day-32 builds the missing frontend control: a single
reusable WatchlistButton wired into the existing API surface.

Source-text grep — same pattern as Days 28-30.
"""
from __future__ import annotations
from pathlib import Path


_F = Path(__file__).resolve().parents[2] / "frontend" / "src"
_BUTTON = _F / "components" / "watchlist" / "WatchlistButton.tsx"
_PUBLIC_ANALYSIS = _F / "app" / "(app)" / "analysis" / "[ticker]" / "PublicAnalysis.tsx"
_RESULTS_TABLE = _F / "components" / "screener" / "ResultsTable.tsx"


# ── Component ────────────────────────────────────────────────


def test_watchlist_button_component_exists():
    assert _BUTTON.exists(), (
        "WatchlistButton.tsx must exist at "
        "frontend/src/components/watchlist/WatchlistButton.tsx"
    )


def test_watchlist_button_wires_to_correct_api_endpoints():
    """Day-27 backend audit found 4 endpoints. Component must use 3 of
    them (add via POST /, remove via DELETE /{ticker}, check via
    GET /check/{ticker})."""
    src = _BUTTON.read_text(encoding="utf-8")
    assert '"/api/v1/watchlist/"' in src or "'/api/v1/watchlist/'" in src
    assert "/api/v1/watchlist/check/" in src
    # DELETE uses backtick template literal
    assert "`/api/v1/watchlist/${bare}`" in src


def test_watchlist_button_strips_ns_bo_suffix():
    """Backend stores bare ticker symbols (uppercase, no suffix).
    Component must strip .NS/.BO before posting."""
    src = _BUTTON.read_text(encoding="utf-8")
    assert 'replace(/\\.(NS|BO)$/i, "")' in src, (
        "_bareTicker must strip .NS/.BO suffix before API calls."
    )
    assert ".toUpperCase()" in src


def test_watchlist_button_supports_three_variants():
    """default (hero), compact (table), icon-only (tight rows)."""
    src = _BUTTON.read_text(encoding="utf-8")
    for variant in ("default", "compact", "icon-only"):
        assert f'"{variant}"' in src, (
            f"WatchlistButtonVariant missing '{variant}' branch."
        )


def test_watchlist_button_has_optimistic_ui():
    """Click flips state immediately; on failure, reverts."""
    src = _BUTTON.read_text(encoding="utf-8")
    assert "// optimistic" in src
    assert "setInWatchlist(prevState)" in src, (
        "Optimistic revert path missing — failed API calls must restore "
        "the previous state."
    )


def test_watchlist_button_redirects_unauthed_to_login():
    """No token → redirect to /auth/login with return_to."""
    src = _BUTTON.read_text(encoding="utf-8")
    assert 'router.push("/auth/login?return_to=' in src
    assert "encodeURIComponent(window.location.pathname)" in src


def test_watchlist_button_carries_testid_and_data_state():
    """Visual-regression hooks for Day-38."""
    src = _BUTTON.read_text(encoding="utf-8")
    assert 'data-testid="watchlist-button"' in src
    assert 'data-state={inWatchlist === null' in src, (
        "data-state attr should expose unknown/in/out so tests + "
        "stylesheets can react without parsing internal state."
    )


# ── Placement site 1: /analysis/[ticker] hero ────────────────


def test_public_analysis_uses_watchlist_button():
    src = _PUBLIC_ANALYSIS.read_text(encoding="utf-8")
    assert 'import WatchlistButton from "@/components/watchlist/WatchlistButton"' in src
    # Placement next to company name in the hero
    assert "<WatchlistButton" in src
    assert 'variant="compact"' in src
    assert "ticker={tickerUpper}" in src


# ── Placement site 2: /screener results table rows ───────────


def test_results_table_uses_watchlist_button():
    src = _RESULTS_TABLE.read_text(encoding="utf-8")
    assert 'import WatchlistButton from "@/components/watchlist/WatchlistButton"' in src
    # Icon-only variant inside ticker cell — must NOT break the Link
    assert "<WatchlistButton" in src
    assert 'variant="icon-only"' in src
    # Heuristic: button lives next to the ticker Link in the same TD
    ticker_cell = src[src.find('col === "ticker"'):src.find('col === "ticker"') + 800]
    assert "WatchlistButton" in ticker_cell, (
        "WatchlistButton should live inside the ticker cell so the "
        "icon stays next to the link."
    )
