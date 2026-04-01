# ═══════════════════════════════════════════════════════════════
# SECTOR GROWTH GUARDRAILS
# Add this to data/processor.py after the FCF growth calculation
# ═══════════════════════════════════════════════════════════════
#
# Replace the existing FCF/Revenue growth caps with sector-specific ones.
# This ensures Airlines can't show 30% FCF growth, FMCG can't show 25%, etc.
# ═══════════════════════════════════════════════════════════════

def apply_sector_guardrails(enriched: dict) -> dict:
    """
    Apply sector-specific growth guardrails to enriched metrics.

    Replaces the global MAX_FCF_GROWTH cap with per-sector caps from
    the industry assumptions engine.

    Returns enriched dict with capped/adjusted growth rates.
    """
    from models.industry_wacc import get_industry_wacc, run_diagnostics

    ticker   = enriched.get("ticker", "?")
    sector   = "general"

    try:
        sector_info = get_industry_wacc(ticker=ticker)
        sector      = sector_info["sector"]

        rev_growth_max = sector_info["rev_growth_max"]
        rev_growth_min = sector_info["rev_growth_min"]
        fcf_growth_max = sector_info["fcf_growth_max"]

        raw_rev_g = enriched.get("revenue_growth", 0)
        raw_fcf_g = enriched.get("fcf_growth",     0)

        # Apply sector-specific caps
        capped_rev_g = float(np.clip(raw_rev_g, rev_growth_min, rev_growth_max))
        capped_fcf_g = float(np.clip(raw_fcf_g, -0.15,          fcf_growth_max))

        if capped_rev_g != raw_rev_g:
            log.debug(f"[{ticker}] Rev growth capped by sector ({sector}): {raw_rev_g:.1%} → {capped_rev_g:.1%}")
        if capped_fcf_g != raw_fcf_g:
            log.debug(f"[{ticker}] FCF growth capped by sector ({sector}): {raw_fcf_g:.1%} → {capped_fcf_g:.1%}")

        enriched["revenue_growth"] = capped_rev_g
        enriched["fcf_growth"]     = capped_fcf_g
        enriched["sector"]         = sector
        enriched["sector_name"]    = sector_info["sector_name"]
        enriched["sector_notes"]   = sector_info.get("notes","")
        enriched["capex_intensity"] = sector_info["capex_intensity"]
        enriched["fcf_conv_factor"] = sector_info["fcf_conv_factor"]

        # Run diagnostics
        diag_warnings = run_diagnostics(
            sector=sector,
            wacc_used=sector_info["wacc"],
            fcf_growth=capped_fcf_g,
            terminal_growth=sector_info["terminal_growth"],
            tv_pct_of_ev=0,   # not available at this stage
            capex_reported=0,
            revenue=enriched.get("latest_revenue", 0),
        )
        enriched["sector_diagnostics"] = diag_warnings

    except Exception as exc:
        log.debug(f"[{ticker}] Sector guardrails failed: {exc}")

    return enriched
