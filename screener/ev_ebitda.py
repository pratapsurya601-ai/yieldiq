# screener/ev_ebitda.py
# ═══════════════════════════════════════════════════════════════
# EV/EBITDA MULTIPLES VALUATION
# ═══════════════════════════════════════════════════════════════
#
# What it does:
#   Computes a third valuation method alongside DCF and PE.
#   EV/EBITDA is the most widely-used multiple in M&A, private
#   equity, and professional equity research because it is:
#     • Capital-structure neutral (compares across debt levels)
#     • Less distorted by depreciation policy than P/E
#     • Preferred for capital-intensive sectors (energy, utilities)
#
# Methodology:
#   1. Compute EBITDA = Operating Income + D&A (from income statement)
#      OR use Yahoo's reported EBITDA directly if available
#   2. Look up sector median EV/EBITDA multiple (Damodaran 2025)
#   3. Implied EV = EBITDA × sector multiple
#   4. Implied equity value = EV - Net Debt
#   5. IV per share = equity value / shares
#   6. Blend with DCF and PE for final crosscheck
#
# Sources:
#   Sector multiples from Damodaran NYU January 2025
#   https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/vebitda.html
# ═══════════════════════════════════════════════════════════════

from __future__ import annotations
import numpy as np
import time
from utils.logger import get_logger

log = get_logger(__name__)


# ── SECTOR PEER TICKERS ───────────────────────────────────────
# For each sector, 3-5 representative peers to fetch live multiples
# Keep small — only fetched when user runs analysis, cached for session
SECTOR_PEERS: dict[str, list[str]] = {
    "us_mega_tech":       ["AAPL","MSFT","GOOGL","META"],
    "us_semiconductors":  ["NVDA","AMD","AVGO","TXN"],
    "us_it_services":     ["ACN","CRM","ORCL","NOW"],
    "us_financial_data":  ["SPGI","MCO","MSCI","NDAQ","CME"],
    "us_pharma":          ["JNJ","LLY","ABBV","MRK"],
    "us_healthcare_services": ["UNH","CVS","HCA","TMO"],
    "us_energy":          ["XOM","CVX","COP","VLO"],
    "us_industrials":     ["HON","CAT","RTX","GE"],
    "us_utilities":       ["NEE","DUK","SO","AEP"],
    "us_consumer_staples":["KO","PEP","PG","CL"],
    "us_consumer_disc":   ["HD","MCD","NKE","TJX"],
    "us_materials":       ["LIN","APD","ECL","FCX"],
    "us_communication":   ["T","VZ","CMCSA","DIS"],
    "it_services":        ["TCS.NS","INFY.NS","WIPRO.NS","HCLTECH.NS"],
    "fmcg":               ["HINDUNILVR.NS","NESTLEIND.NS","BRITANNIA.NS"],
    "pharma":             ["SUNPHARMA.NS","DRREDDY.NS","CIPLA.NS"],
    "capital_goods":      ["LT.NS","SIEMENS.NS","ABB.NS"],
}

# Session-level cache: {sector_key: {multiple, peers, timestamp}}
_PEER_CACHE: dict = {}
_CACHE_TTL  = 3600   # 1 hour — refresh if stale


def fetch_live_peer_multiples(
    sector:         str,
    exclude_ticker: str = "",
) -> dict:
    """
    Fetch live EV/EBITDA multiples for sector peers via yfinance.
    Returns:
        {
            "peer_median":  float,
            "peer_avg":     float,
            "peers":        [{"ticker", "multiple", "valid"}],
            "fetched":      bool,
            "error":        str | None,
        }

    Results are cached for _CACHE_TTL seconds per sector.
    Excludes the stock being analysed from peer average.
    """
    global _PEER_CACHE

    # Check cache
    cached = _PEER_CACHE.get(sector)
    if cached and (time.time() - cached.get("ts", 0)) < _CACHE_TTL:
        # Remove the current ticker from cached result if needed
        return _filter_peer_result(cached["data"], exclude_ticker)

    peers = SECTOR_PEERS.get(sector, [])
    if not peers:
        return {"peer_median": None, "peer_avg": None, "peers": [],
                "fetched": False, "error": "No peers defined for sector"}

    try:
        import yfinance as yf

        results = []
        for p in peers:
            if p.replace(".NS","").replace(".BO","").upper() == exclude_ticker.upper():
                continue
            try:
                info = yf.Ticker(p).info
                ev   = info.get("enterpriseValue", 0) or 0
                ebitda = info.get("ebitda", 0) or 0
                # Also try enterpriseToEbitda directly
                ev_ebitda = info.get("enterpriseToEbitda", 0) or 0
                if ev_ebitda and ev_ebitda > 0:
                    mult = float(ev_ebitda)
                elif ev > 0 and ebitda > 0:
                    mult = ev / ebitda
                else:
                    mult = None

                valid = mult is not None and 3 < mult < 150  # sanity bounds
                results.append({
                    "ticker":   p,
                    "multiple": round(mult, 1) if mult else None,
                    "valid":    valid,
                })
            except Exception as e:
                results.append({"ticker": p, "multiple": None, "valid": False})
                log.debug(f"Peer fetch failed for {p}: {e}")

        valid_mults = [r["multiple"] for r in results if r["valid"]]

        if not valid_mults:
            result = {"peer_median": None, "peer_avg": None, "peers": results,
                      "fetched": True, "error": "No valid peer multiples retrieved"}
        else:
            peer_median = float(np.median(valid_mults))
            peer_avg    = float(np.mean(valid_mults))
            result = {
                "peer_median": round(peer_median, 1),
                "peer_avg":    round(peer_avg, 1),
                "peers":       results,
                "fetched":     True,
                "error":       None,
            }

        # Cache it
        _PEER_CACHE[sector] = {"data": result, "ts": time.time()}
        return _filter_peer_result(result, exclude_ticker)

    except ImportError:
        return {"peer_median": None, "peer_avg": None, "peers": [],
                "fetched": False, "error": "yfinance not available"}
    except Exception as e:
        return {"peer_median": None, "peer_avg": None, "peers": [],
                "fetched": False, "error": str(e)}


def _filter_peer_result(result: dict, exclude_ticker: str) -> dict:
    """Remove the analysed ticker from peer results if present."""
    if not exclude_ticker:
        return result
    filtered_peers = [
        p for p in result.get("peers", [])
        if p["ticker"].replace(".NS","").upper() != exclude_ticker.upper()
    ]
    valid_mults = [p["multiple"] for p in filtered_peers if p.get("valid")]
    if valid_mults:
        return {**result,
                "peers":       filtered_peers,
                "peer_median": round(float(np.median(valid_mults)), 1),
                "peer_avg":    round(float(np.mean(valid_mults)), 1)}
    return {**result, "peers": filtered_peers}


# ── SECTOR EV/EBITDA MULTIPLES (Damodaran Jan 2025, US) ──────
# Format: sector_key: {median, bear (10th pctile), bull (90th pctile)}
# N/A sectors use P/FFO or P/Book instead — marked with None

SECTOR_EV_EBITDA: dict[str, dict | None] = {

    # ── US Sectors ────────────────────────────────────────────
    "us_mega_tech":           {"median": 22, "bear": 14, "bull": 35,
                               "note": "AAPL ~22x, MSFT ~25x, GOOGL ~18x"},
    "us_semiconductors":      {"median": 18, "bear": 11, "bull": 30,
                               "note": "Cyclical — trough multiples look high"},
    "us_it_services":         {"median": 20, "bear": 13, "bull": 32,
                               "note": "SaaS at premium end (~25x), payment processors lower (~12x)"},
    # Financial data & analytics — SPGI, MCO, MSCI, NDAQ, CME, ICE, VRSK
    # These are information monopolies with >40% EBITDA margins — trade at premium
    "us_financial_data":      {"median": 26, "bear": 18, "bull": 40,
                               "note": "SPGI ~22x, MCO ~28x, MSCI ~35x, CME ~20x — info monopolies"},
    "us_pharma":              {"median": 14, "bear":  9, "bull": 22,
                               "note": "Branded pharma trades on P/E; EV/EBITDA secondary"},
    "us_healthcare_services": {"median": 12, "bear":  8, "bull": 18,
                               "note": "Managed care (UNH ~12x), hospitals (~9x)"},
    "us_banks":               None,   # Banks: use P/B and P/E, not EV/EBITDA
    "us_energy":              {"median":  7, "bear":  4, "bull": 11,
                               "note": "Commodity cycle — trough is ~4x, peak ~12x"},
    "us_industrials":         {"median": 15, "bear":  9, "bull": 22,
                               "note": "Aerospace/defence higher, basic industrials lower"},
    "us_utilities":           {"median": 12, "bear":  9, "bull": 16,
                               "note": "Regulated utilities — stable range, rate-sensitive"},
    "us_consumer_staples":    {"median": 16, "bear": 11, "bull": 22,
                               "note": "FMCG brands at premium (KO ~18x, PG ~20x)"},
    "us_consumer_disc":       {"median": 13, "bear":  7, "bull": 22,
                               "note": "Wide range: luxury high, auto low"},
    "us_reits":               None,   # REITs: use P/FFO, not EV/EBITDA
    "us_materials":           {"median":  9, "bear":  5, "bull": 14,
                               "note": "Commodity cycle — chemicals ~12x, metals ~7x"},
    "us_communication":       {"median": 10, "bear":  6, "bull": 16,
                               "note": "Telecoms capital-heavy: T ~7x, VZ ~7x, CMCSA ~8x"},
    "us_general":             {"median": 14, "bear":  8, "bull": 22,
                               "note": "Broad market median ~14x"},

    # ── Indian Sectors ────────────────────────────────────────
    "it_services":            {"median": 22, "bear": 15, "bull": 35,
                               "note": "TCS ~18x, Infosys ~16x, premium for quality"},
    "fmcg":                   {"median": 38, "bear": 25, "bull": 55,
                               "note": "Indian FMCG commands premium — HUL ~45x"},
    "pharma":                 {"median": 22, "bear": 14, "bull": 35,
                               "note": "Sun Pharma ~20x, branded generic premium"},
    "hospital":               {"median": 28, "bear": 18, "bull": 42,
                               "note": "Apollo ~30x — India healthcare re-rating"},
    "auto_oem":               {"median": 10, "bear":  6, "bull": 16,
                               "note": "Maruti ~14x (premium), Tata Motors ~8x"},
    "auto_ancillary":         {"median": 14, "bear":  9, "bull": 20},
    "capital_goods":          {"median": 28, "bear": 18, "bull": 45,
                               "note": "India capex boom — L&T ~25x, Siemens ~35x"},
    "defence":                {"median": 35, "bear": 20, "bull": 55,
                               "note": "HAL, BEL trade at high multiples on order book"},
    "oil_gas":                {"median":  8, "bear":  5, "bull": 12,
                               "note": "Reliance ~10x (includes retail), ONGC ~4x"},
    "power":                  {"median": 12, "bear":  8, "bull": 18,
                               "note": "NTPC ~8x, Adani Power ~10x"},
    "metals":                 {"median":  6, "bear":  3, "bull": 10,
                               "note": "Tata Steel, JSW — commodity cycle"},
    "cement":                 {"median": 14, "bear":  9, "bull": 20,
                               "note": "UltraTech ~16x, ACC ~12x"},
    "realty":                 {"median": 20, "bear": 12, "bull": 35,
                               "note": "India real estate — DLF, Godrej Properties"},
    "telecom":                {"median": 10, "bear":  6, "bull": 16,
                               "note": "Jio ~15x, Airtel ~12x (includes digital)"},
    "retail":                 {"median": 22, "bear": 14, "bull": 35,
                               "note": "D-Mart ~55x (premium quality), Avenue ~40x"},
    "chemicals":              {"median": 18, "bear": 11, "bull": 28,
                               "note": "Specialty chemicals premium — Deepak ~22x"},
    "consumer_durable":       {"median": 28, "bear": 18, "bull": 42,
                               "note": "Titan ~45x, Voltas ~25x"},
    "general":                {"median": 14, "bear":  8, "bull": 22},
}


# ── EBITDA COMPUTATION ────────────────────────────────────────

def compute_ebitda(enriched: dict) -> tuple[float, str]:
    """
    Compute EBITDA from available data.
    Returns (ebitda_value, method_used)

    Priority:
    1. Yahoo Finance reported EBITDA (most accurate)
    2. Operating income + estimated D&A
    3. Revenue × sector EBITDA margin estimate
    """
    ticker = enriched.get("ticker", "?")

    # Priority 1: Yahoo reported EBITDA
    yahoo_ebitda = enriched.get("ebitda", 0)
    if yahoo_ebitda and yahoo_ebitda > 0:
        return float(yahoo_ebitda), "Yahoo reported EBITDA"

    # Priority 2: Operating income + D&A
    income_df = enriched.get("income_df")
    if income_df is not None and not income_df.empty:
        op_income = 0.0
        if "operating_income" in income_df.columns:
            op_income = float(income_df["operating_income"].iloc[-1])

        # D&A typically 3-8% of revenue for most sectors
        # Use sector-specific estimate
        sector = enriched.get("sector", "general")
        DA_PCT = {
            "us_mega_tech":        0.04,   # low capex, mostly stock comp
            "us_semiconductors":   0.08,   # fabs are expensive
            "us_it_services":      0.02,
            "us_pharma":           0.05,
            "us_healthcare_services": 0.04,
            "us_energy":           0.12,   # high depletion/D&A
            "us_industrials":      0.05,
            "us_utilities":        0.10,   # heavy fixed assets
            "us_consumer_staples": 0.04,
            "us_consumer_disc":    0.05,
            "us_communication":    0.15,   # telecoms: massive network D&A
            "us_materials":        0.08,
            "us_reits":            0.20,   # depreciation is the whole story for REITs
            "it_services":         0.02,
            "fmcg":               0.04,
            "pharma":             0.04,
        }
        da_pct = DA_PCT.get(sector, 0.05)
        revenue = enriched.get("latest_revenue", 0)
        da_estimate = revenue * da_pct

        if op_income > 0:
            ebitda = op_income + da_estimate
            return ebitda, f"Op. income + D&A est. ({da_pct:.0%} of rev)"

    # Priority 3: Revenue × margin estimate
    revenue = enriched.get("latest_revenue", 0)
    op_margin = enriched.get("op_margin", 0)
    if revenue > 0 and op_margin > 0:
        # EBITDA margin ≈ op margin + ~5% D&A
        ebitda_margin = op_margin + 0.05
        ebitda = revenue * ebitda_margin
        return ebitda, f"Revenue × est. EBITDA margin ({ebitda_margin:.0%})"

    return 0.0, "No EBITDA data available"


# ── EV/EBITDA VALUATION ───────────────────────────────────────

def compute_ev_ebitda_iv(
    enriched:   dict,
    scenario:   str = "median",   # "bear", "median", "bull"
) -> tuple[float, str]:
    """
    Compute intrinsic value per share using EV/EBITDA.

    Returns (iv_per_share, detail_string)
    Returns (0, reason) if not applicable.
    """
    ticker  = enriched.get("ticker", "?")
    sector  = enriched.get("sector", "general")
    shares  = enriched.get("shares", 0)
    debt    = enriched.get("total_debt", 0)
    cash    = enriched.get("total_cash", 0)

    if shares <= 0:
        return 0.0, "No shares data"

    # Get sector multiple
    # Remap: data/analytics companies use us_financial_data multiples
    # not us_it_services (where they live for WACC purposes)
    FINANCIAL_DATA_TICKERS = {
        "spgi","mco","msci","ndaq","cboe","ice","cme","br","vrsk",
        "bl","mktx","trow","bk","ntrs"
    }
    if ticker.lower() in FINANCIAL_DATA_TICKERS and sector == "us_it_services":
        sector = "us_financial_data"

    sector_data = SECTOR_EV_EBITDA.get(sector) or SECTOR_EV_EBITDA.get("general")
    if sector_data is None:
        return 0.0, f"{sector} uses P/B or P/FFO — EV/EBITDA not applicable"

    multiple_key = {"bear": "bear", "bull": "bull"}.get(scenario, "median")
    multiple = sector_data[multiple_key]

    # Compute EBITDA
    ebitda, ebitda_method = compute_ebitda(enriched)
    if ebitda <= 0:
        return 0.0, "EBITDA not computable"

    # Implied EV
    implied_ev     = ebitda * multiple
    net_debt       = debt - cash
    equity_value   = implied_ev - net_debt

    if equity_value <= 0:
        return 0.0, f"Net debt (₹{net_debt/1e9:.1f}B) exceeds implied EV — stock value = 0"

    iv_per_share = equity_value / shares
    detail = (
        f"EBITDA ₹{ebitda/1e9:.1f}B × {multiple}x {scenario} multiple "
        f"= EV ₹{implied_ev/1e9:.1f}B − net debt ₹{net_debt/1e9:.1f}B "
        f"= equity ₹{equity_value/1e9:.1f}B ÷ {shares/1e9:.2f}B shares"
    )
    log.debug(f"[{ticker}] EV/EBITDA IV: {detail} = ${iv_per_share:.2f}")
    return iv_per_share, detail


# ── FULL EV/EBITDA ANALYSIS ───────────────────────────────────

def run_ev_ebitda_analysis(
    enriched:      dict,
    current_price: float,
    fx:            float = 1.0,
    fetch_peers:   bool  = True,   # set False in screener batch mode
) -> dict:
    """
    Full EV/EBITDA analysis with bear/median/bull scenarios,
    live peer multiples vs Damodaran long-run median,
    and plain-English verdict.
    """
    ticker  = enriched.get("ticker", "?")
    sector  = enriched.get("sector", "general")
    shares  = enriched.get("shares", 0)
    debt    = enriched.get("total_debt", 0)
    cash    = enriched.get("total_cash", 0)
    mktcap  = enriched.get("market_cap", current_price * shares)

    # Remap: data/analytics companies use us_financial_data multiples
    # not us_it_services (where they live for WACC purposes)
    FINANCIAL_DATA_TICKERS = {
        "spgi","mco","msci","ndaq","cboe","ice","cme","br","vrsk",
        "bl","mktx","trow","bk","ntrs"
    }
    if ticker.lower() in FINANCIAL_DATA_TICKERS and sector == "us_it_services":
        sector = "us_financial_data"

    sector_data = SECTOR_EV_EBITDA.get(sector) or SECTOR_EV_EBITDA.get("general")
    not_applicable = sector_data is None

    # ── Fetch live peer multiples ─────────────────────────────
    peer_data = {"peer_median": None, "peer_avg": None, "peers": [],
                 "fetched": False, "error": "Skipped"}
    if fetch_peers and not not_applicable:
        try:
            peer_data = fetch_live_peer_multiples(sector, exclude_ticker=ticker)
        except Exception as _pe:
            log.debug(f"[{ticker}] Peer fetch error: {_pe}")

    # EBITDA
    ebitda, ebitda_method = compute_ebitda(enriched)

    if not_applicable or ebitda <= 0:
        reason = (
            f"{sector} does not use EV/EBITDA (use P/B or P/FFO)"
            if not_applicable else "EBITDA not available"
        )
        return {
            "applicable": False,
            "reason": reason,
            "ticker": ticker,
        }

    # Current market EV and multiple
    net_debt        = debt - cash
    market_ev       = mktcap + net_debt
    current_multiple = market_ev / ebitda if ebitda > 0 else 0

    # Sector benchmarks
    median_mult = sector_data["median"]
    bear_mult   = sector_data["bear"]
    bull_mult   = sector_data["bull"]

    # IV at each scenario
    bear_iv,   bear_detail   = compute_ev_ebitda_iv(enriched, "bear")
    median_iv, median_detail = compute_ev_ebitda_iv(enriched, "median")
    bull_iv,   bull_detail   = compute_ev_ebitda_iv(enriched, "bull")

    # MoS at median
    mos = (median_iv - current_price) / current_price if current_price > 0 else 0

    # How does current multiple compare to sector?
    mult_premium = current_multiple - median_mult
    mult_pct     = (current_multiple / median_mult - 1) if median_mult > 0 else 0

    # ── Extract live peer data FIRST — needed for verdict ─────
    live_peer_median = peer_data.get("peer_median")
    live_peer_avg    = peer_data.get("peer_avg")

    # Verdict (peer-aware)
    verdict, verdict_colour = _ev_verdict(
        current_multiple, median_mult, bear_mult, bull_mult, mos,
        live_peer_med=live_peer_median,
    )

    # ── Peer-adjusted verdict context ────────────────────────

    # IV at live peer median — compute directly from EBITDA
    # (can't use compute_ev_ebitda_iv since it reads sector table, not override)
    peer_iv = 0.0
    if live_peer_median and ebitda > 0 and shares > 0:
        net_d   = debt - cash
        eq_v    = ebitda * live_peer_median - net_d
        peer_iv = max(eq_v / shares, 0) * fx

    # Gap between Damodaran and live peers — tells user if whole sector is cheap/expensive
    damodaran_vs_live = None
    if live_peer_median:
        damodaran_vs_live = (median_mult - live_peer_median) / live_peer_median

    # Updated summary incorporating peer context
    summary = _ev_summary_v2(
        ticker=ticker,
        current_multiple=current_multiple,
        damodaran_median=median_mult,
        live_peer_median=live_peer_median,
        mult_pct=mult_pct,
        median_iv=median_iv * fx,
        peer_iv=peer_iv,
        verdict=verdict,
        sector=sector,
        price=current_price * fx,
    )

    return {
        "applicable":          True,
        "ticker":              ticker,
        "sector":              sector,
        "ebitda":              ebitda,
        "ebitda_method":       ebitda_method,
        "market_ev":           market_ev,
        "net_debt":            net_debt,
        "current_multiple":    current_multiple,
        "sector_median":       median_mult,        # Damodaran long-run
        "sector_bear":         bear_mult,
        "sector_bull":         bull_mult,
        "multiple_premium":    mult_premium,
        "multiple_pct":        mult_pct,
        "bear_iv":             bear_iv   * fx,
        "median_iv":           median_iv * fx,     # IV at Damodaran median
        "bull_iv":             bull_iv   * fx,
        "peer_iv":             peer_iv,            # IV at live peer median
        "live_peer_median":    live_peer_median,   # current market multiple
        "live_peer_avg":       live_peer_avg,
        "damodaran_vs_live":   damodaran_vs_live,  # gap: + means sector depressed
        "peer_data":           peer_data,          # full peer breakdown
        "mos_at_median":       mos,
        "verdict":             verdict,
        "verdict_colour":      verdict_colour,
        "summary":             summary,
        "sector_note":         sector_data.get("note", ""),
        "bear_detail":         bear_detail,
        "median_detail":       median_detail,
    }


def _ev_summary_v2(
    ticker:           str,
    current_multiple: float,
    damodaran_median: float,
    live_peer_median: float | None,
    mult_pct:         float,
    median_iv:        float,
    peer_iv:          float,
    verdict:          str,
    sector:           str,
    price:            float,
) -> str:
    """
    Dual-benchmark summary:
    - Damodaran long-run median = mean reversion target
    - Live peer median          = current market reality

    Explains the gap and what it means for the investment thesis.
    """
    sector_name = sector.replace("us_","").replace("_"," ").title()
    direction   = "above" if mult_pct > 0 else "below"
    abs_pct     = abs(mult_pct) * 100

    # Line 1: Where stock trades vs Damodaran
    line1 = (
        f"{ticker} trades at {current_multiple:.1f}× EV/EBITDA — "
        f"{abs_pct:.0f}% {direction} the long-run {sector_name} median of {damodaran_median:.0f}×."
    )

    # Line 2: Live peer context (the new key insight)
    if live_peer_median:
        peer_gap    = damodaran_median - live_peer_median
        peer_gap_pct = abs(peer_gap / damodaran_median) * 100
        vs_peer_pct  = (current_multiple / live_peer_median - 1) * 100
        vs_peer_dir  = "above" if vs_peer_pct > 0 else "below"

        if abs(peer_gap_pct) < 8:
            # Sector trading near Damodaran median — clean signal
            if mult_pct < -0.10:
                line2 = (
                    f"The sector currently trades at {live_peer_median:.1f}× — close to the long-run median. "
                    f"{ticker} at {current_multiple:.1f}× is {abs(vs_peer_pct):.0f}% "
                    f"{vs_peer_dir} its own peers, suggesting stock-specific undervaluation."
                )
            elif mult_pct > 0.10:
                line2 = (
                    f"The sector currently trades at {live_peer_median:.1f}× — close to the long-run median. "
                    f"{ticker} at {current_multiple:.1f}× trades {abs(vs_peer_pct):.0f}% "
                    f"{vs_peer_dir} peers — the premium likely reflects quality or moat."
                )
            else:
                line2 = (
                    f"The sector currently trades at {live_peer_median:.1f}× — in line with historical norms. "
                    f"{ticker} is priced in line with both its peers and the long-run median."
                )
        elif peer_gap > 0:
            # Sector is DEPRESSED vs Damodaran (live < Damodaran) — two-bet situation
            line2 = (
                f"However, the sector currently trades at {live_peer_median:.1f}× — "
                f"{peer_gap_pct:.0f}% below the long-run median. "
                f"The whole sector has de-rated. "
                f"{ticker} at {current_multiple:.1f}× is "
                f"{'in line with' if abs(vs_peer_pct) < 8 else f'{abs(vs_peer_pct):.0f}% {vs_peer_dir}'} peers. "
                f"Buying here is a two-part bet: the stock AND the sector re-rate to {damodaran_median:.0f}×."
            )
        else:
            # Sector is ELEVATED vs Damodaran (live > Damodaran)
            line2 = (
                f"The sector currently trades at {live_peer_median:.1f}× — "
                f"{peer_gap_pct:.0f}% above the long-run median — the sector itself looks stretched. "
                f"{ticker} at {current_multiple:.1f}× is "
                f"{'in line with' if abs(vs_peer_pct) < 8 else f'{abs(vs_peer_pct):.0f}% {vs_peer_dir}'} peers."
            )
    else:
        # No live peer data — fall back to single benchmark
        if abs_pct < 10:
            line2 = f"This is essentially in line with the long-run sector median."
        elif mult_pct < 0:
            line2 = (
                f"Trading below the long-run median suggests potential upside "
                f"if multiples mean-revert. Fair value at {damodaran_median:.0f}× = ₹{median_iv:.0f}."
            )
        else:
            line2 = (
                f"The premium vs long-run median means the stock needs to grow into its multiple. "
                f"Fair value at the long-run median = ₹{median_iv:.0f}."
            )

    # Line 3: The two IV reference points
    if live_peer_median and peer_iv > 0:
        line3 = (
            f"Fair value at current peer multiple ({live_peer_median:.0f}×): ₹{peer_iv:.0f}. "
            f"Fair value at long-run median ({damodaran_median:.0f}×): ₹{median_iv:.0f}."
        )
    else:
        line3 = f"Fair value at long-run median ({damodaran_median:.0f}×): ₹{median_iv:.0f}."

    return f"{line1} {line2} {line3}"


def _ev_verdict(
    current:         float,
    median:          float,    # Damodaran long-run
    bear:            float,
    bull:            float,
    mos:             float,
    live_peer_med:   float | None = None,  # current market reality
) -> tuple[str, str]:
    """
    Grade the current EV/EBITDA multiple.

    Priority: compare vs live peer median if available
    (more relevant than Damodaran when sector has re-rated).
    Use Damodaran for the outer trough/premium bands.
    """
    # Use live peer median as the primary fair-value anchor if available
    # Fall back to Damodaran if no live data
    fair_anchor = live_peer_med if live_peer_med else median

    # Trough: below Damodaran bear — absolute floor regardless of peers
    if current <= bear * 0.95:
        return "trading at trough multiple — deeply undervalued", "green"

    # vs live peers (or Damodaran if no peers)
    ratio = current / fair_anchor

    if ratio <= 0.85:
        return "trading below peers — attractively valued", "green"
    elif ratio <= 1.05:
        # Check also vs Damodaran to give context
        if current <= median * 0.88:
            return "in line with peers, below long-run median — fair value", "green"
        return "in line with sector peers — fairly valued", "amber"
    elif ratio <= 1.20:
        return "trading above peers — moderately expensive", "amber"
    elif current <= bull:
        return "trading well above peers — expensive", "red"
    else:
        return "trading at premium multiple — expensive vs sector", "red"


def _ev_summary(
    ticker:   str,
    current:  float,
    median:   float,
    pct:      float,
    ebitda:   float,
    ev:       float,
    price:    float,
    median_iv:float,
    verdict:  str,
    sector:   str,
) -> str:
    direction = "above" if pct > 0 else "below"
    abs_pct   = abs(pct) * 100
    sector_name = sector.replace("us_","").replace("_"," ").title()

    line1 = (
        f"{ticker} currently trades at {current:.1f}× EV/EBITDA — "
        f"{abs_pct:.0f}% {direction} the {sector_name} "
        f"sector median of {median:.0f}×."
    )

    if abs_pct < 10:
        # In line with sector
        line2 = (
            f"This is essentially in line with sector peers — "
            f"no strong signal from multiples alone. "
            f"At the sector median, fair value would be ₹{median_iv:.0f}."
        )
    elif pct < 0:
        # Trading BELOW sector median → cheap on this metric
        line2 = (
            f"Trading below the sector median suggests the stock may be "
            f"attractively valued on an EV/EBITDA basis. "
            f"At the sector median of {median}×, fair value would be ₹{median_iv:.0f} — "
            f"implying {abs_pct:.0f}% upside from here."
        )
    else:
        # Trading ABOVE sector median → expensive on this metric
        line2 = (
            f"The premium multiple suggests the market is paying up for "
            f"quality, growth, or competitive moat. "
            f"At the sector median of {median}×, fair value would be ₹{median_iv:.0f}. "
            f"This stock needs to grow into its multiple."
        )

    return f"{line1} {line2}"
