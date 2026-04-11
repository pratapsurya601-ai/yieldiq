# config/countries.py
# ═══════════════════════════════════════════════════════════════
# Multi-country configuration for YieldIQ.
# Add a new country = add a new dict. Zero code changes needed.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

COUNTRIES: dict[str, dict] = {

    "IN": {
        "name":           "India",
        "flag":           "🇮🇳",
        "currency_code":  "INR",
        "currency_symbol": "₹",
        "locale":         "en-IN",

        # ── Market ────────────────────────────────────────────
        "exchanges":      ["NSE", "BSE"],
        "ticker_suffix":  [".NS", ".BO"],
        "market_hours":   "09:15–15:30 IST",
        "indices": {
            "NIFTY 50":    "^NSEI",
            "SENSEX":      "^BSESN",
            "NIFTY Bank":  "^NSEBANK",
            "India VIX":   "^INDIAVIX",
        },
        "popular_stocks": [
            "RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS",
            "ICICIBANK.NS", "HINDUNILVR.NS", "ITC.NS", "BHARTIARTL.NS",
        ],
        "popular_display": [
            "RELIANCE", "TCS", "INFY", "HDFC BANK",
            "ICICI BANK", "HUL", "ITC", "AIRTEL",
        ],

        # ── Valuation defaults ────────────────────────────────
        "risk_free_rate_ticker": "^IRX",  # India 10Y proxy
        "risk_free_rate_fallback": 0.07,  # 7%
        "equity_risk_premium":    0.08,   # 8% for India
        "default_terminal_growth": 0.04,  # 4% (higher inflation)

        # ── Payment ──────────────────────────────────────────
        "payment_gateway":  "razorpay",
        "pricing": {
            "starter_monthly":  499_00,   # paise
            "starter_annual":   4_788_00,
            "pro_monthly":      1_999_00,
            "pro_annual":       19_188_00,
        },
        "pricing_display": {
            "starter_monthly":  "₹499/mo",
            "starter_annual":   "₹399/mo",
            "pro_monthly":      "₹1,999/mo",
            "pro_annual":       "₹1,599/mo",
        },

        # ── Legal ────────────────────────────────────────────
        "regulator":      "SEBI",
        "disclaimer":     (
            "YieldIQ is not registered with SEBI as an investment adviser or research analyst. "
            "All outputs are model-generated estimates for educational purposes only. "
            "Not investment advice."
        ),
    },

    "US": {
        "name":           "United States",
        "flag":           "🇺🇸",
        "currency_code":  "USD",
        "currency_symbol": "$",
        "locale":         "en-US",

        # ── Market ────────────────────────────────────────────
        "exchanges":      ["NYSE", "NASDAQ", "AMEX"],
        "ticker_suffix":  [],  # no suffix for US stocks
        "market_hours":   "09:30–16:00 ET",
        "indices": {
            "S&P 500":    "^GSPC",
            "NASDAQ":     "^IXIC",
            "Dow Jones":  "^DJI",
            "VIX":        "^VIX",
        },
        "popular_stocks": [
            "AAPL", "MSFT", "GOOGL", "NVDA",
            "AMZN", "META", "TSLA", "JPM",
        ],
        "popular_display": [
            "AAPL", "MSFT", "GOOGL", "NVDA",
            "AMZN", "META", "TSLA", "JPM",
        ],

        # ── Valuation defaults ────────────────────────────────
        "risk_free_rate_ticker": "^TNX",  # US 10Y Treasury
        "risk_free_rate_fallback": 0.043,  # 4.3%
        "equity_risk_premium":    0.055,   # 5.5% for US
        "default_terminal_growth": 0.03,   # 3%

        # ── Payment ──────────────────────────────────────────
        "payment_gateway":  "stripe",
        "pricing": {
            "starter_monthly":  9_00,   # cents
            "starter_annual":   86_00,
            "pro_monthly":      29_00,
            "pro_annual":       278_00,
        },
        "pricing_display": {
            "starter_monthly":  "$9/mo",
            "starter_annual":   "$7/mo",
            "pro_monthly":      "$29/mo",
            "pro_annual":       "$23/mo",
        },

        # ── Legal ────────────────────────────────────────────
        "regulator":      "SEC",
        "disclaimer":     (
            "YieldIQ is not registered as an investment adviser under the Investment Advisers Act "
            "of 1940 or any state securities law. All outputs are model-generated estimates for "
            "educational purposes only. Not investment advice."
        ),
    },

    "UK": {
        "name":           "United Kingdom",
        "flag":           "🇬🇧",
        "currency_code":  "GBP",
        "currency_symbol": "£",
        "locale":         "en-GB",

        # ── Market ────────────────────────────────────────────
        "exchanges":      ["LSE"],
        "ticker_suffix":  [".L"],
        "market_hours":   "08:00–16:30 GMT",
        "indices": {
            "FTSE 100":   "^FTSE",
            "FTSE 250":   "^FTMC",
        },
        "popular_stocks": [
            "SHEL.L", "AZN.L", "HSBA.L", "ULVR.L",
            "BP.L", "GSK.L", "RIO.L", "LSEG.L",
        ],
        "popular_display": [
            "Shell", "AstraZeneca", "HSBC", "Unilever",
            "BP", "GSK", "Rio Tinto", "LSEG",
        ],

        # ── Valuation defaults ────────────────────────────────
        "risk_free_rate_ticker": "^TNX",  # proxy
        "risk_free_rate_fallback": 0.045,
        "equity_risk_premium":    0.06,
        "default_terminal_growth": 0.025,

        # ── Payment ──────────────────────────────────────────
        "payment_gateway":  "stripe",
        "pricing": {
            "starter_monthly":  7_00,
            "pro_monthly":      23_00,
        },
        "pricing_display": {
            "starter_monthly":  "£7/mo",
            "pro_monthly":      "£23/mo",
        },

        # ── Legal ────────────────────────────────────────────
        "regulator":      "FCA",
        "disclaimer":     (
            "YieldIQ is not authorised or regulated by the Financial Conduct Authority. "
            "All outputs are model-generated estimates for educational purposes only."
        ),
    },
}

# ── Active country (set via env var or session state) ─────────
import os
DEFAULT_COUNTRY = os.environ.get("YIELDIQ_COUNTRY", "IN")


def get_country(code: str | None = None) -> dict:
    """Get country config. Falls back to DEFAULT_COUNTRY."""
    return COUNTRIES.get(code or DEFAULT_COUNTRY, COUNTRIES[DEFAULT_COUNTRY])


def get_active_country() -> dict:
    """Get the currently active country config."""
    try:
        import streamlit as st
        code = st.session_state.get("country", DEFAULT_COUNTRY)
    except Exception:
        code = DEFAULT_COUNTRY
    return get_country(code)


def list_countries() -> list[dict]:
    """List all available countries with code, name, flag."""
    return [
        {"code": k, "name": v["name"], "flag": v["flag"]}
        for k, v in COUNTRIES.items()
    ]
