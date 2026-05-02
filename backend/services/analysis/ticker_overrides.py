"""Per-ticker model overrides for unusual businesses.

Each entry can specify:
- model: alternate valuation engine ("sotp" for sum-of-parts, "asset_based", "skip")
- model_caveat: honest message shown on the analysis page
- excluded_pillars: pillars that don't apply
- override_fv: hardcoded fair value if model can't run
- verdict_label_prefix: optional prefix for the verdict label
- terminal_growth_override: float, override DCF terminal growth (e.g. 0.06 for wide-moat compounders)

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
            "agri, paperboards). Generic DCF blends them and routinely "
            "lands in `data_limited` despite ITC being a high-ROCE / "
            "low-debt / consistent-dividend compounder with a regulated "
            "tobacco-leaf moat. Until the SoP engine ships, terminal "
            "growth is bumped to 5% to reflect FMCG re-rating + tobacco "
            "pricing power. Each segment still deserves its own model."
        ),
        "verdict_label_prefix": "Multi-segment — model approximate",
        # 5% (vs 4% default) — between the FMCG mature compounder
        # baseline and TITAN's 6% wide-moat slot. Reflects: (a) tobacco
        # cigarette pricing power that legislatively passes through tax
        # hikes, (b) FMCG segment mid-teens revenue growth, (c) hotels +
        # paperboards cyclical-but-positive tail. Not a score floor —
        # the override system has no clean score-floor field today; the
        # terminal bump is the cleanest available lever.
        "terminal_growth_override": 0.05,
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

    # Sector-methodology gaps — surgical caveats + (TITAN) terminal-growth fix
    # Long-standing followups; real engine work is on the Q3 roadmap.
    "TITAN": {
        "model_caveat": (
            "Wide-moat consumer durables compounder — using 6% terminal "
            "growth (vs 4% default) to reflect durable jewelry-led pricing "
            "power. Generic DCF was producing FV/CMP ≈ 0.25 historically."
        ),
        "terminal_growth_override": 0.06,
    },
    "TITAN.NS": {"_alias_to": "TITAN"},

    "ULTRACEMCO": {
        "model_caveat": (
            "Cement super-cyclical — FCF anchor uses 10y signed-median "
            "which can over-correct in upcycles, widening bear/base/bull "
            "spread. Half-weight signed-median fix is on Q3 roadmap."
        ),
    },
    "ULTRACEMCO.NS": {"_alias_to": "ULTRACEMCO"},
    "SHREECEM": {"_alias_to": "ULTRACEMCO"},
    "SHREECEM.NS": {"_alias_to": "ULTRACEMCO"},

    "HINDALCO": {
        "model_caveat": (
            "Metals stocks need debt-aware DCF — current WACC under-weights "
            "cost of debt by D/(D+E). HINDALCO carries heavy debt, so FV "
            "is conservative. Debt-weighted WACC fix is on Q3 roadmap."
        ),
    },
    "HINDALCO.NS": {"_alias_to": "HINDALCO"},

    "SUNPHARMA": {
        "model_caveat": (
            "Pharma R&D treatment is approximate. R&D is currently treated "
            "as opex; capitalize-and-amortize (correct for pharma) would "
            "raise FV ~15–20%. USFDA risk is also not modeled."
        ),
    },
    "SUNPHARMA.NS": {"_alias_to": "SUNPHARMA"},
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
