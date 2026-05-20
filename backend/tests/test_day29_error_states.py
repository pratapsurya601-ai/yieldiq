"""Day-29 (2026-05-20): regression guards for the 4 error-state fixes
that close the Day-27 UX audit's HIGH/MED error-state items.

Source-text grep over .tsx files — same pattern as Day-28.
"""
from __future__ import annotations
from pathlib import Path


_FRONTEND = Path(__file__).resolve().parents[2] / "frontend" / "src"
_HOME = _FRONTEND / "app" / "(app)" / "home" / "page.tsx"
_SCREENER = _FRONTEND / "app" / "(app)" / "screener" / "page.tsx"
_DISCOVER = _FRONTEND / "app" / "(app)" / "discover" / "page.tsx"
_LOGIN = _FRONTEND / "app" / "auth" / "login" / "page.tsx"


# ── /home PanelFallback ──────────────────────────────────────


def test_home_panel_fallback_has_retry_button():
    """Day-27 audit HIGH: PanelFallback was generic
    '{label} temporarily unavailable' with no recovery path.
    Now: shows 'Try again' button + clearer copy."""
    src = _HOME.read_text(encoding="utf-8")
    assert "Try again" in src, (
        "PanelFallback missing the new 'Try again' button label."
    )
    assert "window.location.reload()" in src, (
        "Try again button must trigger window.location.reload() — "
        "panel-level refetch isn't possible from inside the "
        "ErrorBoundary fallback."
    )
    assert "{label} unavailable" in src, (
        "Updated copy '{label} unavailable' missing — should replace "
        "old 'temporarily unavailable' verbiage."
    )
    assert 'data-testid={`panel-fallback-' in src, (
        "PanelFallback should expose a data-testid for future "
        "visual-regression / accessibility tests."
    )


# ── /screener error banner ───────────────────────────────────


def test_screener_error_429_distinguished():
    """Day-27 audit HIGH: 429 rate-limit errors showed misleading
    'Check that every filter has a field' copy. Now: dedicated
    'Too many screener requests' message before the generic fallback."""
    src = _SCREENER.read_text(encoding="utf-8")
    assert "if (status === 429)" in src, (
        "extractScreenerError missing the 429 branch."
    )
    assert "Too many screener requests" in src, (
        "429-specific copy missing — users should see a rate-limit "
        "message, not the generic 'check your filters' fallback."
    )


def test_screener_error_banner_has_retry_button():
    """Day-27 audit HIGH: error banner had no Retry button — users
    had to manually tweak filters and re-run."""
    src = _SCREENER.read_text(encoding="utf-8")
    assert 'data-testid="screener-error-banner"' in src
    # Retry button wires to triggerRun
    assert "onClick={triggerRun}" in src, (
        "Retry button must call triggerRun to re-execute the query."
    )
    # Disabled while running OR when there are no clauses
    assert "disabled={isFetching || clauses.length === 0}" in src
    # Dark-mode variants
    assert "dark:border-amber-700" in src, (
        "Day-29 also adds dark-mode variants to the error banner — "
        "the old amber-50/amber-800 was light-mode only."
    )


# ── /discover YieldIQ 50 warming-up ──────────────────────────


def test_discover_warming_up_has_refresh_button():
    """Day-27 audit MED: 'warming up' card lacked retry mechanism."""
    src = _DISCOVER.read_text(encoding="utf-8")
    # Captured refetch + isFetching
    assert "refetch: refetchYiq50" in src, (
        "useQuery destructure must expose refetch as refetchYiq50."
    )
    assert "isFetching: yiq50Fetching" in src, (
        "useQuery destructure must expose isFetching as yiq50Fetching."
    )
    # Button wires correctly
    assert "onClick={() => refetchYiq50()}" in src
    assert "disabled={yiq50Fetching}" in src
    assert "Refreshing…" in src, (
        "In-flight button label should say 'Refreshing…'."
    )


# ── /login OAuth in-flight feedback ──────────────────────────


def test_login_button_has_inline_spinner():
    """Day-27 audit LOW: login button only flipped text 'Sign in' →
    'Signing in...' with no visual spinner. Easy to miss on fast nets."""
    src = _LOGIN.read_text(encoding="utf-8")
    assert 'data-testid="login-submit-button"' in src
    # Inline spinner element present
    assert "animate-spin" in src
    # Spinner is aria-hidden (decorative)
    assert 'aria-hidden="true"' in src
    # Disabled cursor-not-allowed for clearer affordance
    assert "disabled:cursor-not-allowed" in src
    # Text uses ellipsis char (… not "..." for typographic correctness)
    assert "Signing in…" in src, (
        "Updated login-loading text should use '…' (single char) "
        "for typographic correctness."
    )
