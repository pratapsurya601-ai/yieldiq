# screener/sector_relative.py
# ═══════════════════════════════════════════════════════════════
# SECTOR RELATIVE VALUATION
# ═══════════════════════════════════════════════════════════════
#
# "Is this stock cheap or expensive vs its peers?"
#
# The core insight: a stock's valuation only means something in
# context. AAPL at 30× EV/EBITDA looks expensive in isolation.
# But if mega-cap tech peers average 28×, AAPL is essentially
# in line. If peers average 18×, AAPL is genuinely expensive.
#
# This module provides THREE layers of relative context:
#
# Layer 1 — Screener-based (from your CSV):
#   Uses the batch screener results to rank the stock vs every
#   other stock in the same sector. Shows percentile, top picks,
#   and how the stock compares on MoS, margins, and signals.
#
# Layer 2 — Live peer comparison (from Yahoo Finance):
#   Fetches current EV/EBITDA, P/E, and FCF yield for 3-5 direct
#   peers and compares the stock to each one individually.
#
# Layer 3 — Sector summary statistics:
#   Mean/median MoS in sector, % of sector that is BUY/SELL,
#   sector quality grade distribution.
#
# Output:
#   • Percentile rank in sector (e.g. "Top 15% cheapest in IT Services")
#   • Sector heat map — which signal dominates?
#   • Peer table — head-to-head vs 3-5 direct competitors
#   • Plain-English verdict: "cheap vs sector" / "sector itself is expensive"
# ═══════════════════════════════════════════════════════════════

from __future__ import annotations
import numpy as np
import pandas as pd
from pathlib import Path
from utils.logger import get_logger
from utils.config import RESULTS_PATH

log = get_logger(__name__)


# ── DIRECT PEER MAPS ─────────────────────────────────────────
# Curated peer groups for head-to-head comparison
# Used for live Yahoo Finance fetch
PEER_GROUP_LABELS: dict[str, str] = {
    "us_mega_tech":           "Mega-cap Tech",
    "us_semiconductors":      "US Semiconductors",
    "us_it_services":         "US IT Services / Enterprise Software",
    "us_financial_data":      "US Financial Data & Analytics",
    "us_pharma":              "US Pharmaceuticals",
    "us_healthcare_services": "US Healthcare Services",
    "us_energy":              "US Energy",
    "us_industrials":         "US Industrials",
    "us_utilities":           "US Utilities",
    "us_consumer_staples":    "US Consumer Staples",
    "us_consumer_disc":       "US Consumer Discretionary",
    "us_materials":           "US Materials",
    "us_communication":       "US Communication Services",
    "us_banks":               "US Banks & Financial",
    "us_reits":               "US REITs",
    "it_services":            "Indian IT Services",
    "fmcg":                   "Indian FMCG",
    "pharma":                 "Indian Pharmaceuticals",
    "capital_goods":          "Indian Capital Goods",
    "auto_oem":               "Indian Auto OEM",
    "oil_gas":                "Indian Oil & Gas",
    "metals":                 "Indian Metals & Mining",
    "telecom":                "Indian Telecom",
    "banking":                "Indian Banking",
    "nbfc":                   "Indian NBFC / Lending",
    "cement":                 "Indian Cement",
    "defence":                "Indian Defence",
    "infra":                  "Indian Infrastructure",
    "chemicals":              "Indian Chemicals",
    "healthcare":             "Indian Healthcare",
    "retail":                 "Indian Retail",
    "power":                  "Indian Power & Utilities",
}

DIRECT_PEERS: dict[str, list[str]] = {
    # US sectors
    "us_mega_tech":       ["AAPL","MSFT","GOOGL","META","AMZN"],
    "us_semiconductors":  ["NVDA","AMD","AVGO","TXN","QCOM"],
    "us_it_services":     ["ACN","CRM","ORCL","NOW","INTU"],
    "us_financial_data":  ["SPGI","MCO","MSCI","NDAQ","VRSK"],
    "us_pharma":          ["LLY","JNJ","ABBV","MRK","PFE"],
    "us_healthcare_services":["UNH","CVS","HCA","CI","HUM"],
    "us_energy":          ["XOM","CVX","COP","VLO","PSX"],
    "us_industrials":     ["HON","CAT","RTX","GE","UPS"],
    "us_utilities":       ["NEE","DUK","SO","AEP","EXC"],
    "us_consumer_staples":["KO","PEP","PG","CL","MO"],
    "us_consumer_disc":   ["HD","MCD","NKE","TJX","BKNG"],
    "us_materials":       ["LIN","APD","ECL","FCX","NEM"],
    "us_communication":   ["T","VZ","CMCSA","DIS","NFLX"],
    "us_banks":           ["JPM","BAC","WFC","GS","MS"],
    "us_reits":           ["PLD","AMT","EQIX","SPG","O"],
    # Indian sectors
    "it_services":        ["TCS.NS","INFY.NS","WIPRO.NS","HCLTECH.NS","TECHM.NS"],
    "fmcg":               ["ITC.NS","HINDUNILVR.NS","NESTLEIND.NS","BRITANNIA.NS","DABUR.NS"],
    "pharma":             ["SUNPHARMA.NS","DRREDDY.NS","CIPLA.NS","DIVISLAB.NS"],
    "capital_goods":      ["LT.NS","SIEMENS.NS","ABB.NS","CUMMINSIND.NS"],
    "auto_oem":           ["MARUTI.NS","TATAMOTORS.NS","M&M.NS","BAJAJ-AUTO.NS"],
    "oil_gas":            ["RELIANCE.NS","ONGC.NS","IOC.NS","BPCL.NS"],
    "metals":             ["TATASTEEL.NS","JSWSTEEL.NS","HINDALCO.NS","VEDL.NS"],
    "telecom":            ["BHARTIARTL.NS","IDEA.NS","TATACOMM.NS"],
    "banking":            ["HDFCBANK.NS","ICICIBANK.NS","AXISBANK.NS","KOTAKBANK.NS",
                           "SBIN.NS","INDUSINDBK.NS","BANDHANBNK.NS","FEDERALBNK.NS"],
    "nbfc":               ["BAJFINANCE.NS","BAJAJFINSV.NS","CHOLAFIN.NS","MUTHOOTFIN.NS",
                           "SHRIRAMFIN.NS","LICHSGFIN.NS"],
    "cement":             ["ULTRACEMCO.NS","AMBUJACEM.NS","ACC.NS","SHREECEM.NS",
                           "JKCEMENT.NS","DALMIABHARAT.NS"],
    "defence":            ["HAL.NS","BEL.NS","BHEL.NS","COCHINSHIP.NS",
                           "MAZAGON.NS","BDL.NS","GRSE.NS"],
    "infra":              ["LT.NS","ADANIPORTS.NS","GMRAIRPORT.NS",
                           "IRB.NS","IRCON.NS"],
    "chemicals":          ["PIDILITIND.NS","SRF.NS","ATUL.NS","DEEPAKNITRO.NS",
                           "NAVINFLUOR.NS","CLEAN.NS"],
    "healthcare":         ["APOLLOHOSP.NS","MAXHEALTH.NS","FORTIS.NS",
                           "YATHARTH.NS","KIMS.NS"],
    "retail":             ["DMART.NS","TRENT.NS","VMART.NS","SHOPERSTOP.NS"],
    "power":              ["NTPC.NS","POWERGRID.NS","TATAPOWER.NS","ADANIGREEN.NS",
                           "NHPC.NS","SJVN.NS"],
}


# ── Public helpers for peer lookup ───────────────────────────────
def get_peers_for_ticker(ticker: str) -> list[str]:
    """Return peer list (excluding the ticker itself) or [] if not grouped."""
    t = (ticker or "").upper()
    for group_peers in DIRECT_PEERS.values():
        if t in group_peers:
            return [p for p in group_peers if p != t]
    return []


def get_sector_label_for_ticker(ticker: str) -> str | None:
    """Return display label for the ticker's peer group, or None."""
    t = (ticker or "").upper()
    for key, peers in DIRECT_PEERS.items():
        if t in peers:
            return PEER_GROUP_LABELS.get(key)
    return None

# Cache live peer data (avoid repeated Yahoo calls)
_PEER_CACHE: dict = {}
_CACHE_TTL  = 1800  # 30 min


def _safe(v, default=0.0) -> float:
    try:
        f = float(v)
        return f if np.isfinite(f) else default
    except Exception:
        return default


# ── SCREENER-BASED ANALYSIS ──────────────────────────────────

def _load_screener(sector_name: str) -> pd.DataFrame | None:
    """Load screener CSV and filter to the same sector."""
    try:
        p = Path(RESULTS_PATH)
        if not p.exists():
            return None
        df = pd.read_csv(p)
        if "sector" not in df.columns:
            return None
        # Case-insensitive partial match
        mask = df["sector"].str.lower().str.contains(
            sector_name.lower().replace("us_","").replace("_"," "), na=False
        )
        sector_df = df[mask].copy()
        return sector_df if not sector_df.empty else None
    except Exception as e:
        log.debug(f"Screener load error: {e}")
        return None


def _screener_stats(ticker: str, sector_name: str, current_mos: float) -> dict:
    """
    Compute sector stats from screener CSV.
    Returns percentile rank, sector summary, top/bottom stocks.
    """
    df = _load_screener(sector_name)

    if df is None or df.empty:
        return {"available": False}

    # Remove extreme outliers (MoS capped at ±200%)
    df = df[df["margin_of_safety"].between(-200, 200)].copy()
    if df.empty:
        return {"available": False}

    total    = len(df)
    mos_vals = df["margin_of_safety"].dropna()

    # Percentile rank (how cheap vs sector?)
    percentile = float((mos_vals < current_mos).sum() / len(mos_vals) * 100) if len(mos_vals) > 0 else 50

    # Signal distribution
    sig_counts = df["signal"].value_counts().to_dict()
    buy_pct   = (sig_counts.get("Undervalued 🟢", 0) / total * 100) if total > 0 else 0
    sell_pct  = (sig_counts.get("Overvalued 🔴", 0) / total * 100) if total > 0 else 0
    watch_pct = (sig_counts.get("Near Fair Value 🟡", 0) / total * 100) if total > 0 else 0

    # Sector median stats
    median_mos      = float(mos_vals.median())
    mean_mos        = float(mos_vals.mean())
    median_margin   = float(df["op_margin"].median()) if "op_margin" in df.columns else 0
    sector_quality  = df["fundamental_grade"].mode()[0] if "fundamental_grade" in df.columns and not df["fundamental_grade"].dropna().empty else "N/A"

    # Top 5 most undervalued (excluding the current ticker)
    buys = df[
        df["signal"].str.contains("BUY|WATCH", na=False) &
        ~df["ticker"].str.upper().eq(ticker.upper())
    ].nlargest(5, "margin_of_safety")[
        ["ticker","price","intrinsic_value","margin_of_safety","signal","fundamental_grade"]
    ].copy()

    # Where does current stock rank?
    rank = int((mos_vals >= current_mos).sum())
    rank_of = total

    return {
        "available":       True,
        "total_stocks":    total,
        "percentile":      round(percentile, 1),
        "rank":            rank,
        "rank_of":         rank_of,
        "median_mos":      round(median_mos, 1),
        "mean_mos":        round(mean_mos, 1),
        "median_margin":   round(median_margin, 1),
        "sector_quality":  sector_quality,
        "buy_pct":         round(buy_pct, 1),
        "sell_pct":        round(sell_pct, 1),
        "watch_pct":       round(watch_pct, 1),
        "signal_counts":   sig_counts,
        "top_picks":       buys,
    }


# ── LIVE PEER COMPARISON ────────────────────────────────────

def _fetch_single_peer(t: str) -> dict | None:
    """Fetch metrics for one ticker. Called in parallel threads."""
    try:
        import yfinance as yf
        info      = yf.Ticker(t).fast_info  # fast_info is much faster than .info
        price     = float(getattr(info, "last_price", 0) or 0)
        prev      = float(getattr(info, "previous_close", 0) or 0)
        mktcap    = float(getattr(info, "market_cap", 0) or 0)
        # For valuation ratios we still need .info but we call it lazily
        # and only if fast_info price is valid
        if price <= 0:
            return None
        try:
            full    = yf.Ticker(t).info
            pe      = float(full.get("forwardPE") or full.get("trailingPE") or 0)
            ev_ebitda = float(full.get("enterpriseToEbitda") or 0)
            fcf_ttm = float(full.get("freeCashflow") or 0)
            name    = full.get("shortName") or t
        except Exception:
            pe, ev_ebitda, fcf_ttm, name = 0, 0, 0, t
        fcf_yield = fcf_ttm / mktcap if mktcap > 0 and fcf_ttm > 0 else 0
        return {
            "ticker":    t,
            "name":      name[:25],
            "price":     price,
            "pe":        pe if pe > 0 else None,
            "ev_ebitda": ev_ebitda if ev_ebitda > 0 else None,
            "fcf_yield": fcf_yield * 100 if fcf_yield > 0 else None,
            "mktcap_b":  mktcap / 1e9 if mktcap > 0 else None,
        }
    except Exception as e:
        log.debug(f"Peer fetch failed {t}: {e}")
        return None


def _fetch_peer_metrics(
    tickers:        list[str],
    exclude_ticker: str = "",
) -> list[dict]:
    """
    Fetch key valuation metrics for a list of tickers from Yahoo Finance.
    PERFORMANCE FIX: Uses ThreadPoolExecutor to fetch all peers IN PARALLEL
    instead of sequentially. 5 peers: ~2s instead of ~10-15s.
    """
    import time
    from concurrent.futures import ThreadPoolExecutor, as_completed
    global _PEER_CACHE

    targets   = [t for t in tickers if t.upper() != exclude_ticker.upper()]
    cache_key = "|".join(sorted(targets))
    cached    = _PEER_CACHE.get(cache_key)
    if cached and (time.time() - cached["ts"]) < _CACHE_TTL:
        return cached["data"]

    results = []
    # Fetch all peers in parallel — max 6 threads to avoid rate limits
    with ThreadPoolExecutor(max_workers=min(6, len(targets))) as pool:
        futures = {pool.submit(_fetch_single_peer, t): t for t in targets}
        for fut in as_completed(futures, timeout=15):
            try:
                row = fut.result()
                if row:
                    results.append(row)
            except Exception as e:
                log.debug(f"Peer parallel fetch error: {e}")

    _PEER_CACHE[cache_key] = {"data": results, "ts": time.time()}
    return results


# ── MAIN FUNCTION ────────────────────────────────────────────

def compute_sector_relative(
    enriched:      dict,
    current_price: float,
    current_iv:    float,
    current_mos:   float,
    fx:            float = 1.0,
) -> dict:
    """
    Full sector relative valuation.

    Returns:
      screener_stats:  how stock ranks in sector from batch screener
      peer_metrics:    live head-to-head vs direct peers
      verdict:         plain-English relative valuation summary
    """
    ticker      = enriched.get("ticker", "?")
    sector      = enriched.get("sector", "general")
    sector_name = enriched.get("sector_name", sector)

    # ── Layer 1: Screener-based ranking ──────────────────────
    screen_stats = _screener_stats(ticker, sector_name, current_mos * 100)

    # ── Layer 2: Live peer comparison ────────────────────────
    peer_tickers     = DIRECT_PEERS.get(sector, [])
    peer_group_label = PEER_GROUP_LABELS.get(sector, sector_name)
    peer_metrics = []
    if peer_tickers:
        raw_peers    = _fetch_peer_metrics(peer_tickers, exclude_ticker=ticker)
        peer_metrics = raw_peers

    # ── Current stock metrics for comparison ─────────────────
    shares   = enriched.get("shares", 0)
    mktcap   = current_price * shares if shares > 0 else 0
    fcf      = enriched.get("yahoo_fcf_ttm") or enriched.get("latest_fcf", 0)
    fcf_yield_curr = (fcf / mktcap * 100) if mktcap > 0 and fcf > 0 else 0
    ev_ebitda_curr = enriched.get("ev_to_ebitda", 0)
    fwd_pe         = enriched.get("forward_pe", 0) or 0

    current_metrics = {
        "ticker":    ticker,
        "name":      ticker,
        "price":     current_price * fx,
        "pe":        fwd_pe if fwd_pe > 0 else None,
        "ev_ebitda": ev_ebitda_curr if ev_ebitda_curr > 0 else None,
        "fcf_yield": fcf_yield_curr if fcf_yield_curr > 0 else None,
        "mktcap_b":  mktcap * fx / 1e9 if mktcap > 0 else None,
        "mos_pct":   current_mos * 100,
        "is_current": True,
    }

    # ── Peer relative metrics ─────────────────────────────────
    peer_pe_vals       = [p["pe"] for p in peer_metrics if p.get("pe")]
    peer_ev_vals       = [p["ev_ebitda"] for p in peer_metrics if p.get("ev_ebitda")]
    peer_fcf_vals      = [p["fcf_yield"] for p in peer_metrics if p.get("fcf_yield")]

    peer_median_pe     = float(np.median(peer_pe_vals))     if peer_pe_vals  else None
    peer_median_ev     = float(np.median(peer_ev_vals))     if peer_ev_vals  else None
    peer_median_fcf    = float(np.median(peer_fcf_vals))    if peer_fcf_vals else None

    # vs peer medians — clamp to None if ratio is absurd (>500% diff = stale/bad data)
    def _sane_ratio(a, b):
        """Return (a/b)-1 only when both values are positive and ratio is plausible."""
        if not a or not b or b <= 0 or a <= 0:
            return None
        r = (a / b) - 1
        return r if abs(r) <= 5.0 else None   # discard if >500% diff

    pe_vs_peers  = _sane_ratio(fwd_pe,          peer_median_pe)
    ev_vs_peers  = _sane_ratio(ev_ebitda_curr,   peer_median_ev)
    fcf_vs_peers = (fcf_yield_curr - peer_median_fcf) if (fcf_yield_curr and peer_median_fcf) else None

    # ── Relative verdict ──────────────────────────────────────
    verdict, verdict_colour, verdict_emoji = _relative_verdict(
        current_mos=current_mos,
        screen_stats=screen_stats,
        pe_vs_peers=pe_vs_peers,
        ev_vs_peers=ev_vs_peers,
    )

    # ── Summary ───────────────────────────────────────────────
    summary = _build_summary(
        ticker=ticker,
        sector_name=sector_name,
        screen_stats=screen_stats,
        current_mos=current_mos,
        peer_median_pe=peer_median_pe,
        peer_median_ev=peer_median_ev,
        fwd_pe=fwd_pe,
        ev_ebitda_curr=ev_ebitda_curr,
        verdict=verdict,
    )

    return {
        "ticker":           ticker,
        "sector":           sector,
        "sector_name":      sector_name,
        "peer_group_label": peer_group_label,

        # Screener stats
        "screener":         screen_stats,

        # Peer data
        "current_metrics":  current_metrics,
        "peer_metrics":     peer_metrics,
        "peer_median_pe":   peer_median_pe,
        "peer_median_ev":   peer_median_ev,
        "peer_median_fcf":  peer_median_fcf,
        "pe_vs_peers":      pe_vs_peers,
        "ev_vs_peers":      ev_vs_peers,
        "fcf_vs_peers":     fcf_vs_peers,

        # Verdict
        "verdict":          verdict,
        "verdict_colour":   verdict_colour,
        "verdict_emoji":    verdict_emoji,
        "summary":          summary,
    }


def _relative_verdict(
    current_mos:   float,
    screen_stats:  dict,
    pe_vs_peers:   float | None,
    ev_vs_peers:   float | None,
) -> tuple[str, str, str]:
    """Generate relative valuation verdict."""
    signals = []

    # From screener percentile
    pctile = screen_stats.get("percentile", 50) if screen_stats.get("available") else 50
    if pctile >= 75:
        signals.append(("cheap_vs_sector", 2))
    elif pctile >= 55:
        signals.append(("slightly_cheap", 1))
    elif pctile <= 25:
        signals.append(("expensive_vs_sector", -2))
    elif pctile <= 45:
        signals.append(("slightly_expensive", -1))

    # From PE vs peers
    if pe_vs_peers is not None:
        if pe_vs_peers <= -0.15:
            signals.append(("pe_cheap", 1))
        elif pe_vs_peers >= 0.25:
            signals.append(("pe_expensive", -1))

    # From EV/EBITDA vs peers
    if ev_vs_peers is not None:
        if ev_vs_peers <= -0.15:
            signals.append(("ev_cheap", 1))
        elif ev_vs_peers >= 0.25:
            signals.append(("ev_expensive", -1))

    net = sum(v for _, v in signals)

    if net >= 2:
        return "cheap vs sector peers — relative value opportunity", "#059669", "🟢"
    elif net >= 1:
        return "modestly cheap vs sector — mild relative value", "#2563EB", "🔵"
    elif net == 0:
        return "in line with sector peers — no relative discount", "#D97706", "🟡"
    elif net >= -1:
        return "slightly expensive vs sector peers", "#EA580C", "🟠"
    else:
        return "expensive vs sector peers — premium to peers", "#DC2626", "🔴"


def _build_summary(
    ticker:          str,
    sector_name:     str,
    screen_stats:    dict,
    current_mos:     float,
    peer_median_pe:  float | None,
    peer_median_ev:  float | None,
    fwd_pe:          float,
    ev_ebitda_curr:  float,
    verdict:         str,
) -> str:
    lines = []

    # Screener context
    if screen_stats.get("available"):
        pctile = screen_stats["percentile"]
        total  = screen_stats["total_stocks"]
        med    = screen_stats["median_mos"]
        rank   = screen_stats["rank"]

        lines.append(
            f"{ticker} ranks #{rank} of {total} stocks in {sector_name} by our model's "
            f"margin of safety ({current_mos*100:+.1f}% vs sector median {med:+.1f}%)."
        )

        buy_pct  = screen_stats["buy_pct"]
        sell_pct = screen_stats["sell_pct"]
        lines.append(
            f"The sector overall: {buy_pct:.0f}% of stocks are BUY signals, "
            f"{sell_pct:.0f}% are SELL — "
            f"{'the sector as a whole looks undervalued' if buy_pct > 40 else 'the sector is mixed' if buy_pct > 20 else 'most sector peers are expensive'}."
        )

    # Live peer context
    if peer_median_pe and fwd_pe > 0:
        pe_gap = (fwd_pe / peer_median_pe - 1) * 100
        lines.append(
            f"On forward P/E: {ticker} at {fwd_pe:.1f}× vs peer median {peer_median_pe:.1f}× "
            f"({pe_gap:+.0f}% {'premium' if pe_gap > 0 else 'discount'} to peers)."
        )

    if peer_median_ev and ev_ebitda_curr > 0:
        ev_gap = (ev_ebitda_curr / peer_median_ev - 1) * 100
        lines.append(
            f"On EV/EBITDA: {ev_ebitda_curr:.1f}× vs peer median {peer_median_ev:.1f}× "
            f"({ev_gap:+.0f}% {'premium' if ev_gap > 0 else 'discount'})."
        )

    return " ".join(lines) if lines else f"{ticker} sector relative valuation — see peer table below."
