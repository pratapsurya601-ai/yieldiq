# backend/services/sample_portfolio.py
# ═══════════════════════════════════════════════════════════════
# Day-97 (2026-05-22): onboarding sample portfolio.
#
# Hardcoded fixture served to brand-new signups so the very first
# /portfolio page render shows the Portfolio Prism + observation
# engine against believable data — instead of an empty state.
#
# IMPORTANT: this is a static fixture. Nothing is written to the
# DB, no CACHE_VERSION bump, no manifest entry. The frontend only
# renders the sample view when:
#   1. real holdings list is empty
#   2. sample_portfolio is present on the response payload
#   3. the user has not dismissed it (localStorage flag)
#
# Picked to span sectors / cycle posture / valuation regime so the
# Prism radar shows variety across all 6 pillars.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

from datetime import date, timedelta

# Anchored to today so "acquired_on" stays a believable mix of ST
# (< 12 months) and LT (> 12 months) without rewriting the fixture
# every quarter. Anchor moved by importer, not by the fixture itself.
def _months_ago(months: int) -> str:
    today = date.today()
    # rough month math; good enough for a UI demo
    day = min(today.day, 28)
    month = today.month - months
    year = today.year
    while month <= 0:
        month += 12
        year -= 1
    return date(year, month, day).isoformat()


# 6 holdings: FMCG, Bank, IT, Conglomerate, Cyclical, Pharma.
# Notional cost basis ≈ ₹2.5L — typical Indian retail size.
# `avg_cost` values are believable historical prints; we explicitly
# do NOT claim them as current prices.
SAMPLE_HOLDINGS: list[dict] = [
    {
        "ticker": "ITC.NS",
        "company_name": "ITC Ltd",
        "sector": "FMCG",
        "quantity": 100,
        "avg_cost": 410.0,
        "acquired_on": _months_ago(14),  # LT
    },
    {
        "ticker": "HDFCBANK.NS",
        "company_name": "HDFC Bank Ltd",
        "sector": "Bank",
        "quantity": 20,
        "avg_cost": 1520.0,
        "acquired_on": _months_ago(16),  # LT
    },
    {
        "ticker": "TCS.NS",
        "company_name": "Tata Consultancy Services",
        "sector": "Information Technology",
        "quantity": 10,
        "avg_cost": 3680.0,
        "acquired_on": _months_ago(13),  # LT
    },
    {
        "ticker": "RELIANCE.NS",
        "company_name": "Reliance Industries",
        "sector": "Conglomerate",
        "quantity": 30,
        "avg_cost": 2540.0,
        "acquired_on": _months_ago(15),  # LT
    },
    {
        "ticker": "TATASTEEL.NS",
        "company_name": "Tata Steel Ltd",
        "sector": "Metals",
        "quantity": 100,
        "avg_cost": 135.0,
        "acquired_on": _months_ago(7),  # ST
    },
    {
        "ticker": "SUNPHARMA.NS",
        "company_name": "Sun Pharmaceutical",
        "sector": "Pharmaceuticals",
        "quantity": 30,
        "avg_cost": 1180.0,
        "acquired_on": _months_ago(5),  # ST
    },
]


def build_sample_portfolio() -> dict:
    """Return the sample-portfolio payload shipped beside an empty
    holdings list. Shape mirrors a stripped-down LiveHolding so the
    frontend can render with the same row component.
    """
    rows: list[dict] = []
    total_invested = 0.0
    for h in SAMPLE_HOLDINGS:
        qty = float(h["quantity"])
        cost = float(h["avg_cost"])
        invested = qty * cost
        total_invested += invested
        rows.append({
            "ticker": h["ticker"],
            "display_ticker": h["ticker"].replace(".NS", ""),
            "company_name": h["company_name"],
            "sector": h["sector"],
            "quantity": qty,
            "entry_price": cost,
            "invested_value": invested,
            "acquired_on": h["acquired_on"],
            "is_sample": True,
        })
    return {
        "holdings": rows,
        "summary": {
            "total_invested": round(total_invested, 2),
            "count": len(rows),
        },
        "label": "Sample portfolio",
        "note": (
            "Illustrative fixture — six well-known Indian large-caps "
            "spanning FMCG, Banks, IT, Conglomerate, Metals and Pharma. "
            "Replace with your real positions when you import."
        ),
    }


# ── First-session detection ───────────────────────────────────
# Heuristic: JWT `iat` (issued-at) within the last SESSION_WINDOW_S
# is a proxy for "this is their first login session". Cheap, no DB
# write, no schema change. A returning user with a > 5-min-old token
# silently sees the normal empty state instead of the sample.

SESSION_WINDOW_S: int = 5 * 60  # 5 minutes


def is_first_session(iat_epoch: float | int | None, now_epoch: float | None = None) -> bool:
    """True iff `iat_epoch` (JWT issued-at) is within SESSION_WINDOW_S
    of `now_epoch`. Returns False on missing / future-dated iat.
    """
    if iat_epoch is None:
        return False
    try:
        iat = float(iat_epoch)
    except (TypeError, ValueError):
        return False
    if now_epoch is None:
        import time as _t
        now_epoch = _t.time()
    delta = now_epoch - iat
    # Future-dated iat (clock skew) → treat as not-first-session;
    # negative delta would otherwise pass the < window check.
    if delta < 0:
        return False
    return delta <= SESSION_WINDOW_S
