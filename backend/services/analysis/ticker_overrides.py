"""Per-ticker model overrides for unusual businesses.

Each entry can specify:
- model: alternate valuation engine ("sotp" for sum-of-parts, "asset_based", "skip")
- model_caveat: honest message shown on the analysis page
- excluded_pillars: pillars that don't apply
- override_fv: hardcoded fair value if model can't run
- verdict_label_prefix: optional prefix for the verdict label

ROADMAP: build sum-of-parts engine for RELIANCE/ITC/holdcos.
Currently surfaces caveat banner. See: ticker_overrides.py.
"""

TICKER_OVERRIDES: dict[str, dict] = {
    # Conglomerates — generic DCF gives wrong answer
    "RELIANCE": {
        "model_caveat": (
            "Reliance is a conglomerate (oil, telecom, retail, new energy). "
            "Generic DCF blends segments inappropriately. Sum-of-parts "
            "valuation in roadmap."
        ),
        "verdict_label_prefix": "Conglomerate — model approximate",
    },
    "ITC": {
        "model_caveat": (
            "ITC operates 5 distinct segments (cigarettes, FMCG, hotels, "
            "agri, paperboards). Generic DCF blends them. Each deserves "
            "its own model."
        ),
        "verdict_label_prefix": "Multi-segment — model approximate",
    },
    "ITC.NS": {"_alias_to": "ITC"},
    "RELIANCE.NS": {"_alias_to": "RELIANCE"},

    # Holding companies — value driven by underlying holdings, not own cash flow
    "BAJAJHLDNG": {
        "model": "skip",
        "model_caveat": (
            "Bajaj Holdings is a pure holding company. Its fair value is "
            "driven by stakes in Bajaj Auto, Bajaj Finance, Bajaj Finserv, "
            "etc. Use sum-of-parts on the underlying. DCF on holdco itself "
            "produces meaningless output."
        ),
    },
    "BAJAJHLDNG.NS": {"_alias_to": "BAJAJHLDNG"},
    "TATAINVEST": {"_alias_to": "BAJAJHLDNG"},  # Same model — Tata Investment Corp

    # Turnarounds — historical financials don't predict future
    "VEDL": {
        "model_caveat": (
            "Vedanta is undergoing demerger + debt restructuring. Historical "
            "financials don't predict post-restructure value. DCF output is "
            "exploratory."
        ),
    },

    # Pre-profitability — DCF on negative FCF is meaningless
    "ZOMATO": {"_alias_to": "ETERNAL"},
    "ETERNAL": {
        "model_caveat": (
            "Eternal (formerly Zomato) recently turned cash-flow positive. "
            "<3 years of positive FCF history. DCF terminal value dominates "
            "the FV — small assumption changes swing the answer wildly."
        ),
    },
    "PAYTM": {
        "model_caveat": (
            "Paytm is pre-sustained-profit. Loss-making historically. DCF "
            "requires assuming a future profitability inflection that may "
            "or may not happen."
        ),
    },
    "POLICYBZR": {"_alias_to": "PAYTM"},  # Same pattern
    "NYKAA": {"_alias_to": "PAYTM"},
    "OLAELEC": {
        "model_caveat": (
            "Ola Electric is loss-making with thin operating history "
            "(IPO 2024). DCF exploratory at best."
        ),
    },
}


def get_override(ticker: str) -> dict | None:
    """Return override config for ticker, resolving aliases."""
    if not ticker:
        return None
    bare = ticker.replace(".NS", "").replace(".BO", "").upper()
    entry = TICKER_OVERRIDES.get(bare)
    if entry and "_alias_to" in entry:
        entry = TICKER_OVERRIDES.get(entry["_alias_to"])
    return entry
