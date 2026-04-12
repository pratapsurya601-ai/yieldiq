# dashboard/utils/feedback_copy.py
# ═══════════════════════════════════════════════════════════════
# Single source of truth for all user-facing feedback messages.
# Outcome-focused: tells users what happened, not what the system did.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations


def msg_alert_set(ticker: str, price: float = 0, direction: str = "below") -> str:
    _t = ticker.replace(".NS", "").replace(".BO", "")
    if price > 0:
        return f"Alert set — we'll notify you when {_t} drops {direction} {price:,.0f}"
    return f"Alert set for {_t} — we'll notify you when the price target is hit"


def msg_alert_removed(ticker: str) -> str:
    _t = ticker.replace(".NS", "").replace(".BO", "")
    return f"Alert removed — we'll stop tracking that target for {_t}"


def msg_watchlist_added(ticker: str) -> str:
    _t = ticker.replace(".NS", "").replace(".BO", "")
    return f"{_t} added to watchlist — we'll track it for you"


def msg_watchlist_removed(ticker: str) -> str:
    _t = ticker.replace(".NS", "").replace(".BO", "")
    return f"{_t} removed from watchlist"


def msg_portfolio_added(ticker: str) -> str:
    _t = ticker.replace(".NS", "").replace(".BO", "")
    return f"{_t} added to your portfolio"


def msg_portfolio_updated(ticker: str) -> str:
    _t = ticker.replace(".NS", "").replace(".BO", "")
    return f"{_t} position updated in your portfolio"


def msg_portfolio_removed(ticker: str) -> str:
    _t = ticker.replace(".NS", "").replace(".BO", "")
    return f"{_t} removed from portfolio"


def msg_analysis_ready(company_name: str = "") -> str:
    if company_name:
        return f"Analysis ready for {company_name}"
    return "Analysis ready"


def msg_export_ready(fmt: str = "PDF") -> str:
    return f"{fmt} report ready — check your downloads"


def msg_data_refreshed(ticker: str = "") -> str:
    if ticker:
        _t = ticker.replace(".NS", "").replace(".BO", "")
        return f"Latest data loaded for {_t}"
    return "Latest data loaded"


def msg_notes_saved() -> str:
    return "Got it — your notes are saved"


def msg_settings_saved() -> str:
    return "Got it — your preferences are updated"


def msg_login_success(name: str = "") -> str:
    if name:
        return f"Welcome back, {name}"
    return "Welcome back"


def msg_portfolio_synced() -> str:
    return "Portfolio synced with latest data"


def msg_screener_done(count: int) -> str:
    return f"Found {count} stocks matching your criteria"
