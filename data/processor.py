# data/processor.py
# ═══════════════════════════════════════════════════════════════
# DATA PROCESSOR v3 — Sector-Aware Growth Guardrails
# ═══════════════════════════════════════════════════════════════
# Changes from v2:
#   1. Sector-specific growth caps (not one global cap for all)
#      Airlines max FCF growth 12%, not 35%
#      FMCG max FCF growth 14%, not 35%
#      IT max FCF growth 20%, not 35%
#   2. Sector capex/WC context stored in enriched dict
#   3. Sector diagnostics (warnings) attached to enriched
#   4. Bank detection improved — FCF/Revenue check tightened
#   5. All existing logic preserved
# ═══════════════════════════════════════════════════════════════

from __future__ import annotations
import numpy as np
import pandas as pd
from utils.logger import get_logger

log = get_logger(__name__)

# ── Global fallback caps (sector-specific caps override these) ──
MAX_REV_GROWTH  =  0.40   # fallback only — sector caps are tighter
MIN_REV_GROWTH  = -0.15
MAX_FCF_GROWTH  =  0.50   # fallback cap — sector-specific caps override this
MIN_FCF_GROWTH  = -0.20

# ── Minimum viable company thresholds ─────────────────────────
MIN_MARKET_CAP     = 500e7
MIN_REVENUE_INR    = 1e8        # ₹10 Cr — Indian stocks
MIN_REVENUE_USD    = 1e8        # $100M  — US stocks
MIN_REVENUE        = 1e8        # kept for backward compat


def _safe_cagr(series: pd.Series) -> float:
    """Compute CAGR from a series of positive values. Returns 0 on failure."""
    vals = series.dropna().values.astype(float)
    vals = vals[vals > 0]
    if len(vals) < 2:
        return 0.0
    try:
        n = len(vals) - 1
        first, last = float(vals[0]), float(vals[-1])
        if first <= 0:
            return 0.0
        return float((last / first) ** (1.0 / n) - 1.0)
    except Exception:
        return 0.0


def _apply_sector_guardrails(enriched: dict) -> dict:
    """
    Apply sector-specific growth caps, capex context, and diagnostics.

    Uses models/industry_wacc.py to get per-sector assumptions.
    Falls back gracefully if industry_wacc is not available.
    """
    ticker = enriched.get("ticker", "?")

    try:
        from models.industry_wacc import get_industry_wacc, run_diagnostics

        sector_info = get_industry_wacc(ticker=ticker)

        # ── Apply sector-specific growth caps ─────────────────
        rev_growth_max = sector_info["rev_growth_max"]
        rev_growth_min = sector_info["rev_growth_min"]
        fcf_growth_max = sector_info["fcf_growth_max"]

        raw_rev_g = enriched.get("revenue_growth", 0)
        raw_fcf_g = enriched.get("fcf_growth",     0)

        capped_rev_g = float(np.clip(raw_rev_g, rev_growth_min, rev_growth_max))
        capped_fcf_g = float(np.clip(raw_fcf_g, MIN_FCF_GROWTH, fcf_growth_max))

        if abs(capped_rev_g - raw_rev_g) > 0.001:
            log.debug(
                f"[{ticker}] Rev growth sector-capped ({sector_info['sector']}): "
                f"{raw_rev_g:.1%} → {capped_rev_g:.1%} (max {rev_growth_max:.1%})"
            )
        if abs(capped_fcf_g - raw_fcf_g) > 0.001:
            log.debug(
                f"[{ticker}] FCF growth sector-capped ({sector_info['sector']}): "
                f"{raw_fcf_g:.1%} → {capped_fcf_g:.1%} (max {fcf_growth_max:.1%})"
            )

        enriched["revenue_growth"]   = capped_rev_g
        enriched["fcf_growth"]       = capped_fcf_g

        # ── Store sector context ───────────────────────────────
        enriched["sector"]           = sector_info["sector"]
        enriched["sector_name"]      = sector_info["sector_name"]
        enriched["sector_notes"]     = sector_info.get("notes", "")
        enriched["capex_intensity"]  = sector_info["capex_intensity"]
        enriched["wc_pct_revenue"]   = sector_info["wc_pct_revenue"]
        enriched["wc_days"]          = sector_info["wc_days"]
        enriched["rd_pct_revenue"]   = sector_info["rd_pct_revenue"]
        enriched["depreciation_pct"] = sector_info["depreciation_pct"]
        enriched["fcf_conv_factor"]  = sector_info["fcf_conv_factor"]

        # ── Run diagnostics ────────────────────────────────────
        diag_warnings = run_diagnostics(
            sector=sector_info["sector"],
            wacc_used=sector_info["wacc"],
            fcf_growth=capped_fcf_g,
            terminal_growth=sector_info["terminal_growth"],
            tv_pct_of_ev=0,     # not available at this stage
            capex_reported=0,
            revenue=enriched.get("latest_revenue", 0),
        )
        enriched["sector_diagnostics"] = diag_warnings

        if diag_warnings:
            log.debug(
                f"[{ticker}] Sector diagnostics: "
                + " | ".join([w["message"] for w in diag_warnings])
            )

    except ImportError:
        log.debug(f"[{ticker}] industry_wacc not available — using global caps")
    except Exception as exc:
        log.debug(f"[{ticker}] Sector guardrails failed: {exc}")

    return enriched


def compute_metrics(data_bundle: dict) -> dict:
    """
    Derive financial metrics with sector-aware validation.

    Steps:
    1. Compute revenue growth, FCF growth, operating margin
    2. Apply global growth caps as initial filter
    3. Flag unreliable companies (banks, loss-making, tiny)
    4. Apply sector-specific guardrails (tighter per-sector caps)
    5. Attach sector context (capex, WC, diagnostics)
    """
    if data_bundle is None:
        return {}

    income_df = data_bundle.get("income_df", pd.DataFrame())
    cf_df     = data_bundle.get("cf_df",     pd.DataFrame())
    ticker    = data_bundle.get("ticker",    "?")

    # ══ STEP 1: Revenue metrics ════════════════════════════════
    revenue_growth = 0.0
    latest_revenue = 0.0
    op_margin      = 0.0

    if not income_df.empty and "revenue" in income_df.columns:
        rev_series = income_df["revenue"].replace(0, np.nan).dropna()

        # IB standard: weight recent growth heavily
        # 60% most-recent YoY + 40% 3yr CAGR
        # This catches both post-COVID normalization (TCS) AND
        # patent cliff situations (NATCO) where recent growth is reversing
        raw_rev_growth = 0.0
        if len(rev_series) >= 2:
            recent_yoy = (rev_series.iloc[-1] / rev_series.iloc[-2]) - 1

            if len(rev_series) >= 4:
                cagr_3yr = (rev_series.iloc[-1] / rev_series.iloc[-4]) ** (1/3) - 1
                # If recent YoY and 3yr CAGR diverge significantly (>15pp),
                # weight recent YoY even more heavily — momentum is shifting
                divergence = abs(recent_yoy - cagr_3yr)
                if len(rev_series) >= 5:
                    # 4-year CAGR smooths COVID and capex-cycle distortions
                    # (e.g. AAPL 3yr ≈ 2.3% but 4yr ≈ 9.2%; TSLA 3yr ≈ 7% but 4yr ≈ 33%)
                    cagr_4yr = (rev_series.iloc[-1] / rev_series.iloc[-5]) ** (1/4) - 1
                    if divergence > 0.15:
                        # Recent momentum shift — trust recent data most, add long-run context
                        raw_rev_growth = 0.60 * recent_yoy + 0.25 * cagr_3yr + 0.15 * cagr_4yr
                    else:
                        raw_rev_growth = 0.45 * recent_yoy + 0.30 * cagr_3yr + 0.25 * cagr_4yr
                elif divergence > 0.15:
                    # Strong momentum shift — trust recent data 80%
                    raw_rev_growth = 0.80 * recent_yoy + 0.20 * cagr_3yr
                else:
                    raw_rev_growth = 0.60 * recent_yoy + 0.40 * cagr_3yr
            elif len(rev_series) >= 3:
                cagr_2yr = (rev_series.iloc[-1] / rev_series.iloc[-3]) ** (1/2) - 1
                raw_rev_growth = 0.55 * recent_yoy + 0.45 * cagr_2yr
            else:
                raw_rev_growth = recent_yoy

        raw_rev_growth = float(np.nan_to_num(float(raw_rev_growth), nan=0.0, posinf=0.0, neginf=0.0))

        # Initial global cap — sector cap applied later
        revenue_growth = float(np.clip(raw_rev_growth, MIN_REV_GROWTH, MAX_REV_GROWTH))

        latest_revenue = float(income_df["revenue"].iloc[-1]) \
            if income_df["revenue"].iloc[-1] > 0 else 0.0

        if "operating_income" in income_df.columns and latest_revenue > 0:
            latest_op = float(income_df["operating_income"].iloc[-1])
            op_margin = latest_op / latest_revenue

    # ══ STEP 2: FCF metrics ════════════════════════════════════
    fcf_growth = 0.0
    latest_fcf = 0.0
    fcf_margin = 0.0

    if not cf_df.empty and "fcf" in cf_df.columns:
        fcf_series = cf_df["fcf"].dropna()

        # Only use years with meaningful FCF (> 0.05% of revenue or > ₹10L)
        min_fcf_threshold = max(latest_revenue * 0.0005, 1e6)
        valid_fcf = fcf_series[fcf_series > min_fcf_threshold]

        if len(valid_fcf) >= 2:
            raw_fcf_growth = _safe_cagr(valid_fcf)
        else:
            raw_fcf_growth = 0.0

        # Initial global cap — sector cap applied later
        fcf_growth = float(np.clip(raw_fcf_growth, MIN_FCF_GROWTH, MAX_FCF_GROWTH))

        if abs(raw_fcf_growth - fcf_growth) > 0.001:
            log.debug(
                f"[{ticker}] FCF growth initially capped: "
                f"{raw_fcf_growth:.1%} → {fcf_growth:.1%}"
            )

        latest_fcf = float(cf_df["fcf"].iloc[-1])

        if latest_revenue > 0:
            fcf_margin = latest_fcf / latest_revenue

    # ══ STEP 3: DCF reliability flags ════════════════════════

    dcf_reliable      = True
    unreliable_reason = ""
    net_margin        = 0.0   # initialise so it is always defined for the enriched dict

    # ── Handle financial companies (banks show op_margin ≈ 0) ──
    is_financial = False
    if not income_df.empty and "net_income" in income_df.columns and latest_revenue > 0:
        net_income = float(income_df["net_income"].iloc[-1])
        net_margin = net_income / latest_revenue if latest_revenue > 0 else 0.0

        if op_margin == 0 and net_margin > 0:
            # Bank/financial — use net margin as proxy
            is_financial = True
            op_margin    = net_margin
        elif op_margin < -0.05 and net_margin < 0:
            dcf_reliable      = False
            unreliable_reason = f"Negative margins (op={op_margin:.1%}, net={net_margin:.1%})"

    # Inventory-heavy retail stocks: negative FCF from working capital cycles, not weakness
    INVENTORY_HEAVY = {'TITAN', 'TRENT', 'ABFRL', 'DMART', 'PAGEIND', 'RAYMOND'}
    _clean = ticker.replace('.NS', '').replace('.BO', '').upper() if isinstance(ticker, str) else ''

    # ── Negative operating margin ──────────────────────────────
    if not is_financial and op_margin < 0 and _clean not in INVENTORY_HEAVY:
        dcf_reliable      = False
        unreliable_reason = f"Negative operating margin ({op_margin:.1%})"
        log.debug(f"[{ticker}] DCF unreliable: {unreliable_reason}")

    # ── Both FCF and margins negative ─────────────────────────
    if latest_fcf < 0 and op_margin < 0 and _clean not in INVENTORY_HEAVY:
        dcf_reliable      = False
        unreliable_reason = "Negative FCF + negative operating margin"

    # ── Bank / NBFC / financial detection ─────────────────────
    BANK_KEYWORDS = [
        # Indian banks & NBFCs
        "bank", "sbi", "hdfc", "icici", "kotak", "axis",
        "indusind", "idbi", "idfc", "bandhan", "federal", "pnb",
        "canara", "union", "centralbnk", "ucobank", "yesbank",
        "rblbank", "dcbbank", "ktkbank", "csbbank", "j&kbank",
        "aubank", "equitas", "ujjivan", "suryoday", "esaf",
        "insurance", "licsg", "sbilife", "hdfclife", "icicipru",
        "starhealth", "niacl", "gicre", "muthootfin", "manappuram",
        "cholafin", "bajfinance", "bajajfinsv", "shriramfin",
        "m&mfin", "sundarmfin", "ltf",
    ]
    # US banks/financials — exact ticker match only
    # DATA/ANALYTICS companies (spgi, mco, msci, ndaq, cme, ice, cboe, br, vrsk)
    # are NOT banks — they have asset-light models and DCF works fine for them.
    US_BANK_TICKERS = {
        "jpm","bac","wfc","c","gs","ms","schw","blk","axp",
        "usb","pnc","cof","aig","met","pru","afl","all","trv","cb","mmc","aon",
    }
    # V, MA, PYPL, SQ = payment networks with strong FCF → DCF works, not in bank set
    t_clean = ticker.lower().replace("-","").replace(".ns","").replace(".bo","")
    is_bank = any(kw in ticker.lower() for kw in BANK_KEYWORDS) or t_clean in US_BANK_TICKERS

    # NBFCs: negative FCF from loan disbursements
    if latest_fcf < -100e9 and is_bank:
        dcf_reliable      = False
        unreliable_reason = "NBFC/Lending — negative FCF from loan disbursements"

    # FCF/Revenue sanity: > 30% is suspicious for capital-heavy sectors,
    # but is completely normal for asset-light US companies.
    # SPGI, MCO, MSCI = data/analytics → 35-45% FCF margin is expected.
    # Rule: only flag if sector is genuinely capital-heavy AND ticker not in known-ok list.
    HIGH_FCF_OK = {
        # Indian IT
        "infy","wipro","hcltech","techm","persistent","coforge",
        "ltim","ltimindtr","mphasis","tcs","ofss","hexaware",
        # US Mega-tech & fabless semis
        "aapl","msft","googl","goog","meta","amzn","nvda","nflx",
        "qcom","txn","avgo","amd","intc","mu","mrvl","on","mpwr",
        "klac","lam","amat","asml",
        # US IT services / enterprise software / SaaS
        "acn","crm","orcl","intu","adbe","csco","now","ibm","sap",
        "adsk","cdns","snps","anss","wday","veev","team","ddog",
        "net","snow","mdb","zs","okta","hubs","ttd","panw","crwd",
        "ftnt","epam","ctsh","keys","aph","tel",
        # US data & analytics (SPGI, MCO, MSCI etc — very high FCF margin by design)
        "spgi","mco","msci","ndaq","cboe","ice","cme","br","vrsk",
        # US pharma / biotech
        "jnj","pfe","mrk","abbv","lly","amgn","bmy","gild","biib",
        "regn","vrtx","zts","mrna","bsx","isrg","ew","dxcm",
        # US consumer staples (brand = pricing power = high FCF)
        "ko","pep","pg","cl","gis","mo","pm","cost","wmt","tgt",
        "kr","sbux","mcd","yum","cmg","hsy","mkc","mdlz","stz",
        # US healthcare services / managed care
        "unh","cvs","ci","hum","elv","hca","tmo","abt","dhr",
        "iqv","wat","idxx","a","mtd",
        # US financials that ARE valued on FCF (asset managers, exchanges)
        "blk","schw","axp","v","ma","pypl","sq",
        # US media / communication (high FCF after capex)
        "dis","cmcsa","t","vz","tmus","chtr",
        # US industrials with high FCF
        "unp","csx","nsc","ctas","rsp","wm","rsg",
    }
    if latest_revenue > 0 and latest_fcf > 0:
        fcf_to_rev = latest_fcf / latest_revenue
        is_high_fcf_ok = t_clean in HIGH_FCF_OK
        if fcf_to_rev > 0.30 and not is_high_fcf_ok and not is_bank:
            dcf_reliable      = False
            unreliable_reason = f"FCF/Revenue = {fcf_to_rev:.0%} unusually high — verify data"
        elif is_bank:
            dcf_reliable      = False
            unreliable_reason = "Bank/Financial — use P/B or DDM instead of DCF"

    # Revenue too small
    if latest_revenue < MIN_REVENUE:
        dcf_reliable      = False
        unreliable_reason = f"Revenue too small ({latest_revenue/1e7:.1f} Cr)"

    # ══ STEP 4: Build enriched bundle ════════════════════════

    enriched = {**data_bundle}
    enriched.update({
        "revenue_growth":    revenue_growth,
        "fcf_growth":        fcf_growth,
        "op_margin":         op_margin,
        "net_margin":        net_margin,
        "fcf_margin":        fcf_margin,
        "latest_fcf":        latest_fcf,
        "latest_revenue":    latest_revenue,
        "dcf_reliable":      dcf_reliable,
        "unreliable_reason": unreliable_reason,
        # Sector fields — populated by guardrails below
        "sector":            "general",
        "sector_name":       "General",
        "sector_notes":      "",
        "sector_diagnostics": [],
        "capex_intensity":   0.05,
        "wc_pct_revenue":    0.09,
        "wc_days":           45,
        "rd_pct_revenue":    0.01,
        "depreciation_pct":  0.04,
        "fcf_conv_factor":   0.72,
    })

    # ══ STEP 5: Sector-specific guardrails ════════════════════
    # This applies tighter per-sector growth caps and attaches
    # capex/WC context for use in the forecaster and DCF engine
    enriched = _apply_sector_guardrails(enriched)

    # ══ STEP 6: EV/EBITDA fields (pass through from Yahoo) ═══
    enriched["ebitda"]           = data_bundle.get("ebitda", 0)
    enriched["enterprise_value"] = data_bundle.get("enterprise_value", 0)
    enriched["ev_to_ebitda"]     = data_bundle.get("ev_to_ebitda", 0)
    enriched["ev_to_revenue"]    = data_bundle.get("ev_to_revenue", 0)
    enriched["yahoo_fcf_ttm"]    = data_bundle.get("yahoo_fcf_ttm", 0)
    enriched["dividend_yield"]   = data_bundle.get("dividend_yield", 0)
    enriched["dividend_rate"]    = data_bundle.get("dividend_rate", 0)
    enriched["payout_ratio"]     = data_bundle.get("payout_ratio", 0)
    enriched["five_yr_avg_div_yield"] = data_bundle.get("five_yr_avg_div_yield", 0)

    return enriched
