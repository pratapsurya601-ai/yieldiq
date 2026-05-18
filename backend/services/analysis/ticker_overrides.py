"""Per-ticker model overrides for unusual businesses.

Each entry can specify:
- model: alternate valuation engine ("sotp" for sum-of-parts, "asset_based", "skip")
- model_caveat: honest message shown on the analysis page
- excluded_pillars: pillars that don't apply
- override_fv: hardcoded fair value if model can't run
- verdict_label_prefix: optional prefix for the verdict label
- terminal_growth_override: float, override DCF terminal growth (e.g. 0.06 for wide-moat compounders)
- ipo_framework: bool, if true, route through IPO-specific DCF (recent listing,
  elevated WACC, prospectus-anchored projections). See: ipo_framework.py.
- ipo_listing_date: str, ISO date (YYYY-MM-DD) of NSE/BSE listing — used by
  ipo_framework.is_recent_ipo() to decide whether IPO routing still applies.
- skip_ipo_routing: bool, if true, force `_is_recent_ipo = False` in
  service.py even when the sector-aware window would otherwise route
  through `compute_sector_relative_fv`. Use for named recent-IPO tickers
  where we have (a) a calibrated `terminal_growth_override` and
  (b) the cohort P/E median materially under-prices the franchise (e.g.
  MANKIND's domestic OTC scarcity premium not reflected in the broad
  pharma cohort). The ticker stays on the DCF path so the override + R&D
  candidate actually take effect. Service.py reads this in the
  `_is_recent_ipo` gate (Step 7).

ROADMAP: build sum-of-parts engine for RELIANCE/ITC/holdcos.
Currently surfaces caveat banner. See: ticker_overrides.py.
IPO framework scaffold lives in ipo_framework.py (Phase 0 — schema + helpers,
no DCF routing wired yet; real prospectus financials populated in a later session).
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

    # Holding companies — value driven by underlying holdings, not own cash flow.
    # Curated entries here keep their richer caveat copy; the auto-detect
    # path in service.py covers anything not enumerated. See also
    # backend/services/analysis/constants.py::HOLDING_COMPANIES /
    # is_holding_company() for the detection logic.
    "BAJAJHLDNG": {
        "model": "skip",
        "valuation_method": "holding_company_sotp_required",
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

    # MANKIND — recent IPO (2023-05-09), domestic OTC scarcity premium not
    # captured by generic DCF. EV/EBITDA ~30x reflects pricing power on
    # branded OTC franchises (Manforce, Prega News, Unwanted-72) plus
    # chronic-care branded generics — closer to FMCG economics than a
    # commodity-generic exporter. Bumping terminal growth to 5% (vs 4%
    # default) splits the difference between FMCG TITAN's 6% and the
    # generic-pharma 4%, acknowledging the OTC moat without claiming
    # FMCG-tier permanence. Belt-and-braces alongside the 60-month
    # pharma IPO window — even after the window expires, the override
    # keeps MANKIND's terminal value defensible. See
    # docs/design/pharma-dcf-fix.md §3.2 for the full reasoning.
    "MANKIND": {
        "model_caveat": (
            "Mankind Pharma is a recent IPO (May 2023) with a domestic OTC "
            "franchise (Manforce, Prega News, Unwanted-72) whose pricing "
            "power resembles branded FMCG more than commodity generics. "
            "Generic DCF cannot price this scarcity premium; using 5% "
            "terminal growth (vs 4% default) to acknowledge the OTC moat. "
            "DCF path is retained (skip_ipo_routing) because the pharma "
            "cohort P/E median (~17x) materially under-prices the OTC "
            "franchise — sector-relative routing would peg FV at ~₹1,050 "
            "vs the DCF + override band of ₹1,500-1,800."
        ),
        "terminal_growth_override": 0.05,
        # 2026-05-18 prod regression fix: PR #320 widened the pharma
        # IPO window to 60 months, which routed MANKIND through
        # compute_sector_relative_fv (cohort PE median × EPS_ttm). The
        # actual cohort median is ~17x — well below SUNPHARMA/DRREDDY's
        # 25-30x — so MANKIND's FV dropped to ₹1,046 in prod (vs
        # pre-PR ₹1,244 and the design-doc target band [₹1,500, ₹1,800]).
        # The terminal_growth_override and pharma_rd_adjusted candidate
        # never fired because the IPO path bypassed DCF entirely.
        # `skip_ipo_routing` forces the DCF path so the calibrated
        # levers actually take effect. The 60-month window stays in
        # place for unnamed pharma IPOs (where cohort routing is the
        # least-bad option pending Phase 2 prospectus DCF).
        "skip_ipo_routing": True,
    },
    "MANKIND.NS": {"_alias_to": "MANKIND"},
    "MANKINDPHARMA": {"_alias_to": "MANKIND"},
    "MANKINDPHARMA.NS": {"_alias_to": "MANKIND"},

    # ── Capital Goods sector engine (v113, 2026-05-18) ─────────────
    # See docs/design/capital-goods-dcf-fix.md §4 for the recommendation.
    # The cap-goods 7y WC-smoothed FCF candidate + nopat fcf_conv=0.60
    # handle 12+ tickers cohort-wide. Two names need targeted overrides
    # on top of the sector engine: BHEL (PSU regime change post-2023)
    # and KAYNES (defence-EMS hyper-grower whose terminal_g cannot stay
    # at 4% with a rev_3y of 40%).
    "BHEL": {
        "model_caveat": (
            "BHEL is a PSU heavy-electrical / thermal-power equipment "
            "maker that went through a decade-long orderbook decline "
            "(FY13-FY22) followed by a Make-in-India + defence + nuclear "
            "orders revival post-2023. Pre-2023 FCF is structurally "
            "different from post-2023; the cap-goods 7y WC-smoothed "
            "anchor is restricted to FY2023+ rows (CAPITAL_GOODS_REGIME_"
            "CHANGE['BHEL']=2023) so the median doesn't reflect a dead "
            "cycle. DCF is still exploratory — a proper SOTP across "
            "thermal / nuclear / defence segments is on the Q3 roadmap."
        ),
        "verdict_label_prefix": "Regime change post-2023",
    },
    "BHEL.NS": {"_alias_to": "BHEL"},

    "KAYNES": {
        "model_caveat": (
            "Kaynes Technology is a defence + EMS hyper-grower "
            "(rev_3y ≈ 40%). yfinance tags it 'Tech Hardware / "
            "Electronics' but the defence-EMS franchise is project-driven "
            "capital goods — TICKER_SECTOR_OVERRIDES routes it to "
            "'Capital Goods' so it picks up the 7y WC-smoothed FCF "
            "anchor + fcf_conv=0.60. A 30%+ near-term CAGR cannot "
            "compound to perpetuity, so terminal growth is capped at 6% "
            "(min(rev_cagr_3y × 0.5, 0.06)) via the cap-goods hyper-"
            "growth fade in models/forecaster.predict()."
        ),
        "verdict_label_prefix": "Hyper-growth — terminal capped",
        # 0.06 = the cap from CAPITAL_GOODS_HYPER_GROWTH_TERMINAL_CAP.
        # Belt-and-braces: even if the hyper-growth-fade branch in
        # predict() doesn't fire (e.g. revenue_cagr_3y missing from
        # enriched in a future code path), the override still pulls
        # terminal_g down from the 4% default. Same shape as TITAN /
        # MANKIND / ITC bumps but in the opposite direction.
        "terminal_growth_override": 0.06,
    },
    "KAYNES.NS": {"_alias_to": "KAYNES"},
    "KAYNESTECH": {"_alias_to": "KAYNES"},
    "KAYNESTECH.NS": {"_alias_to": "KAYNES"},

    # Sector-mistag caveat strings — surfaced on the analysis page so
    # readers understand why TIMKEN / SCHAEFFLER / GRINDWELL FVs moved.
    "TIMKEN": {
        "model_caveat": (
            "Re-sectored from 'Auto Components' to 'Capital Goods' "
            "(v113, 2026-05-18). Bearings are historically auto-supply "
            "but ~50% of revenue is now industrial / general "
            "engineering — auto-components benchmarks gave wrong "
            "terminal_g and capex assumptions. Now uses the 7y "
            "WC-smoothed cap-goods FCF anchor."
        ),
    },
    "TIMKEN.NS": {"_alias_to": "TIMKEN"},
    "SCHAEFFLER": {
        "model_caveat": (
            "Re-sectored from 'Auto Components' to 'Capital Goods' "
            "(v113, 2026-05-18). Industrial / general-engineering bearings "
            "+ cap-goods fcf_conv=0.60 corrects a +280% over-valuation."
        ),
    },
    "SCHAEFFLER.NS": {"_alias_to": "SCHAEFFLER"},
    "GRINDWELL": {
        "model_caveat": (
            "Re-sectored from 'General / Diversified' to 'Capital Goods' "
            "(v113, 2026-05-18). Abrasives are an industrial consumable; "
            "the 7y WC-smoothed FCF anchor corrects a -59% under-valuation."
        ),
    },
    "GRINDWELL.NS": {"_alias_to": "GRINDWELL"},
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
