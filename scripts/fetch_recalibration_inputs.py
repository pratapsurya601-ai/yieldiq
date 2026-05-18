"""Quarterly recalibration data-pull for YieldIQ WACC inputs.

This script pulls fresh values for the three WACC-driving knobs that
need a quarterly refresh:

1. **Risk-free rate** — Indian 10Y G-Sec yield (via yfinance).
2. **Sector betas** — median 1Y beta from top-3 names per sector
   (via ``yf.Ticker(t).info["beta"]``).
3. **Terminal growth assumption** — heuristic derived from RBI's
   published nominal GDP forecast minus a long-run convergence
   haircut (default 50 bps). The operator MUST sanity-check these.

Output is a JSON artifact in ``scripts/snapshots/`` that the operator
inspects, optionally edits, and then feeds into
``scripts/apply_recalibration.py`` to produce the
``models/industry_wacc.py`` diff for the next PR.

This script does NOT modify any source file and does NOT bump
CACHE_VERSION. Those steps happen in a separate, reviewed PR.

CLI:
    python scripts/fetch_recalibration_inputs.py \\
        --quarter Q2 --year 2026 --dry-run

If yfinance is not installed or the G-Sec feed returns empty, the
script raises a hard error pointing the operator at the manual-entry
escape hatch (``--rf-manual``).
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import statistics
import sys
from pathlib import Path
from typing import Any

# ── Repo path bootstrap so we can import models.industry_wacc ─────
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# ── Sector → ticker map for beta sampling ─────────────────────────
# Keys mirror INDUSTRY_WACC keys in models/industry_wacc.py.
# Tickers are NSE symbols (yfinance suffix .NS). Top-3 by market-cap
# within each sector — operator updates as cohort membership changes.
SECTOR_BETA_TICKERS: dict[str, list[str]] = {
    "it_services":      ["TCS.NS", "INFY.NS", "HCLTECH.NS"],
    "saas_software":    ["INTELLECT.NS", "TANLA.NS", "NEWGEN.NS"],
    "tech_hardware":    ["DIXON.NS", "AMBER.NS", "KAYNES.NS"],
    "fmcg":             ["ITC.NS", "HINDUNILVR.NS", "NESTLEIND.NS"],
    "consumer_durable": ["HAVELLS.NS", "VOLTAS.NS", "WHIRLPOOL.NS"],
    "pharma":           ["SUNPHARMA.NS", "DRREDDY.NS", "CIPLA.NS"],
    "hospital":         ["APOLLOHOSP.NS", "MAXHEALTH.NS", "FORTIS.NS"],
    "auto_oem":         ["MARUTI.NS", "TATAMOTORS.NS", "M&M.NS"],
    "auto_ancillary":   ["BOSCHLTD.NS", "MOTHERSON.NS", "BHARATFORG.NS"],
    "capital_goods":    ["LT.NS", "SIEMENS.NS", "ABB.NS"],
    "defence":          ["HAL.NS", "BEL.NS", "BHEL.NS"],
    "infrastructure":   ["LT.NS", "ADANIPORTS.NS", "GMRAIRPORT.NS"],
    "regulated_utility":["POWERGRID.NS", "GAIL.NS", "IGL.NS"],
    "oil_gas":          ["RELIANCE.NS", "ONGC.NS", "IOC.NS"],
    "power":            ["NTPC.NS", "TATAPOWER.NS", "ADANIGREEN.NS"],
    "metals":           ["TATASTEEL.NS", "JSWSTEEL.NS", "HINDALCO.NS"],
    "cement":           ["ULTRACEMCO.NS", "AMBUJACEM.NS", "SHREECEM.NS"],
    "realty":           ["DLF.NS", "GODREJPROP.NS", "OBEROIRLTY.NS"],
    "telecom":          ["BHARTIARTL.NS", "IDEA.NS", "TATACOMM.NS"],
    "retail":           ["DMART.NS", "TRENT.NS", "VMART.NS"],
    "chemicals":        ["PIDILITIND.NS", "SRF.NS", "NAVINFLUOR.NS"],
    "media":            ["ZEEL.NS", "PVRINOX.NS", "SUNTV.NS"],
    "logistics":        ["CONCOR.NS", "DELHIVERY.NS", "TCI.NS"],
    "airlines":         ["INDIGO.NS"],
}


# ── Heuristic terminal-growth defaults (operator edits before commit)─
#
# Method: RBI's published nominal-GDP forecast minus a long-run
# convergence haircut (~50 bps). Per-sector overlays reflect typical
# Damodaran emerging-markets stable-stage growth assumptions.
#
# These numbers are STARTING POINTS for operator review, not gospel.
def default_terminal_growth(rbi_nominal_gdp_fy: float,
                            haircut_bps: int = 50) -> dict[str, float]:
    base = round(rbi_nominal_gdp_fy - haircut_bps / 10_000.0, 4)
    # Sector overlays expressed as additive deltas in decimal terms.
    overlays = {
        "it_services":       +0.005,   # global demand exposure
        "saas_software":     +0.005,
        "tech_hardware":     -0.005,
        "fmcg":              +0.005,
        "consumer_durable":  +0.000,
        "pharma":            +0.000,
        "hospital":          +0.005,
        "auto_oem":          -0.010,
        "auto_ancillary":    -0.010,
        "capital_goods":     +0.000,
        "defence":           +0.005,
        "infrastructure":    +0.000,
        "regulated_utility": -0.020,
        "oil_gas":           -0.015,
        "power":             -0.015,
        "metals":            -0.020,
        "cement":            -0.015,
        "realty":            -0.005,
        "telecom":           -0.005,
        "retail":            +0.000,
        "chemicals":         -0.005,
        "media":             -0.010,
        "logistics":         -0.005,
        "airlines":          -0.005,
        "general":           +0.000,
    }
    out: dict[str, float] = {"default": base}
    for sector, delta in overlays.items():
        out[sector] = round(base + delta, 4)
    return out


# ══════════════════════════════════════════════════════════════════
# Data-pull primitives (kept thin so they can be monkeypatched in tests)
# ══════════════════════════════════════════════════════════════════
def fetch_risk_free_rate(yf_module: Any = None) -> tuple[float, str]:
    """Return (rate_as_decimal, source_description) for the Indian 10Y
    G-Sec yield.

    Tries ``^IN10Y`` first; falls back to ``IN10YT=RR``. Raises
    ``RuntimeError`` if both feeds are empty.
    """
    if yf_module is None:
        try:
            import yfinance as yf_module  # type: ignore[no-redef]
        except ImportError as e:
            raise RuntimeError(
                "yfinance not installed. Run `pip install yfinance` or "
                "supply --rf-manual <decimal>."
            ) from e

    candidates = ["^IN10Y", "IN10YT=RR"]
    last_err: Exception | None = None
    for sym in candidates:
        try:
            hist = yf_module.Ticker(sym).history(period="5d")
        except Exception as e:  # network / parser errors
            last_err = e
            continue
        if hist is None or len(hist) == 0:
            continue
        # G-Sec yield feeds quote in percent units (e.g. 7.2 → 7.2%).
        close = float(hist["Close"].dropna().iloc[-1])
        if close <= 0:
            continue
        as_of = str(hist.index[-1].date()) if hasattr(hist.index[-1], "date") else "latest"
        # Convert percent → decimal (7.2 → 0.072). Heuristic: if close > 1
        # assume percent units; else assume already decimal.
        rate = close / 100.0 if close > 1 else close
        return round(rate, 4), f"yfinance {sym}, {as_of} close"
    raise RuntimeError(
        "10Y G-Sec yield unavailable from yfinance "
        f"(tried {candidates}; last error: {last_err}). "
        "Pass --rf-manual <decimal, e.g. 0.072> to override."
    )


def fetch_sector_betas(yf_module: Any = None,
                       universe: dict[str, list[str]] | None = None
                       ) -> tuple[dict[str, float], list[str]]:
    """Return (sector → median beta, warnings) using top-3-per-sector."""
    if yf_module is None:
        try:
            import yfinance as yf_module  # type: ignore[no-redef]
        except ImportError as e:
            raise RuntimeError(
                "yfinance not installed. Run `pip install yfinance`."
            ) from e
    universe = universe or SECTOR_BETA_TICKERS
    out: dict[str, float] = {}
    warnings: list[str] = []
    for sector, tickers in universe.items():
        betas: list[float] = []
        for t in tickers:
            try:
                info = yf_module.Ticker(t).info or {}
            except Exception as e:
                warnings.append(f"{sector}: {t} info fetch failed ({e})")
                continue
            b = info.get("beta")
            if b is None:
                warnings.append(f"{sector}: {t} has no beta in info")
                continue
            try:
                betas.append(float(b))
            except (TypeError, ValueError):
                warnings.append(f"{sector}: {t} beta not numeric ({b!r})")
        if not betas:
            warnings.append(f"{sector}: no beta samples — skipped")
            continue
        out[sector] = round(statistics.median(betas), 3)
    return out, warnings


def fetch_rbi_nominal_gdp() -> tuple[float, str]:
    """Return (nominal_gdp_forecast_decimal, source).

    yfinance has no RBI GDP feed and scraping the MPC statement is
    brittle. Use the most recently published RBI nominal-GDP projection
    as a hardcoded fallback; operator updates this constant once a
    year (or overrides via ``--gdp-nominal``).
    """
    # RBI Monetary Policy Report (Oct 2025): nominal GDP growth ~10.5%
    # for FY26. Update when next MPC report lands.
    return 0.105, "RBI MPC Oct-2025 nominal-GDP projection (hardcoded fallback)"


# ══════════════════════════════════════════════════════════════════
# Industry-WACC snapshot (current values, for the artifact)
# ══════════════════════════════════════════════════════════════════
def snapshot_current_industry_wacc() -> dict[str, dict[str, float]]:
    """Read the current INDUSTRY_WACC dict for the artifact's before-image.

    Returns a slimmed-down view containing only the three knobs this
    script targets, keyed by sector.
    """
    from models.industry_wacc import INDUSTRY_WACC  # local import (heavy)
    out: dict[str, dict[str, float]] = {}
    for sector, cfg in INDUSTRY_WACC.items():
        out[sector] = {
            "beta_typical":    float(cfg.get("beta_typical", 0.0)),
            "terminal_growth": float(cfg.get("terminal_growth", 0.0)),
            "wacc_default":    float(cfg.get("wacc_default", 0.0)),
        }
    return out


# ══════════════════════════════════════════════════════════════════
# Quarter auto-detect + main
# ══════════════════════════════════════════════════════════════════
def auto_quarter(today: _dt.date | None = None) -> tuple[str, int]:
    today = today or _dt.date.today()
    q = (today.month - 1) // 3 + 1
    return f"Q{q}", today.year


def build_artifact(rf: float, rf_src: str,
                   betas: dict[str, float], beta_src: str,
                   tg: dict[str, float], tg_src: str,
                   current_snap: dict[str, dict[str, float]],
                   warnings: list[str]) -> dict[str, Any]:
    return {
        "captured_at": _dt.datetime.now(_dt.timezone.utc)
                                   .isoformat(timespec="seconds")
                                   .replace("+00:00", "Z"),
        "captured_by": "scripts/fetch_recalibration_inputs.py",
        "risk_free_rate": rf,
        "rf_source": rf_src,
        "sector_betas": betas,
        "sector_betas_source": beta_src,
        "terminal_growth": tg,
        "terminal_growth_source": tg_src,
        "current_industry_wacc_snapshot": current_snap,
        "warnings": warnings,
    }


def print_summary(art: dict[str, Any]) -> None:
    cur = art["current_industry_wacc_snapshot"]
    print()
    print("=" * 72)
    print(f"Recalibration inputs captured at {art['captured_at']}")
    print("=" * 72)
    print(f"\nRisk-free rate (10Y G-Sec): {art['risk_free_rate']:.4f}")
    print(f"  source: {art['rf_source']}")

    print("\nSector betas (median, top-3 per sector):")
    print(f"  source: {art['sector_betas_source']}")
    print(f"  {'sector':<22}{'old':>10}{'new':>10}{'Δ':>10}")
    for sector, new in sorted(art["sector_betas"].items()):
        old = cur.get(sector, {}).get("beta_typical", float("nan"))
        delta = new - old if old == old else float("nan")  # NaN-safe
        print(f"  {sector:<22}{old:>10.3f}{new:>10.3f}{delta:>+10.3f}")

    print("\nTerminal growth (RBI-anchored heuristic — REVIEW BEFORE APPLY):")
    print(f"  source: {art['terminal_growth_source']}")
    print(f"  {'sector':<22}{'old':>10}{'new':>10}{'Δ':>10}")
    for sector, new in sorted(art["terminal_growth"].items()):
        old = cur.get(sector, {}).get("terminal_growth", float("nan"))
        delta = new - old if old == old else float("nan")
        print(f"  {sector:<22}{old:>10.4f}{new:>10.4f}{delta:>+10.4f}")

    if art["warnings"]:
        print("\nWarnings:")
        for w in art["warnings"]:
            print(f"  - {w}")
    print()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    auto_q, auto_y = auto_quarter()
    ap.add_argument("--quarter", default=auto_q,
                    help=f"quarter label (default: {auto_q})")
    ap.add_argument("--year", type=int, default=auto_y,
                    help=f"year (default: {auto_y})")
    ap.add_argument("--output", default=None,
                    help="output JSON path (default: scripts/snapshots/...)")
    ap.add_argument("--rf-manual", type=float, default=None,
                    help="override 10Y G-Sec rate as decimal (e.g. 0.072)")
    ap.add_argument("--gdp-nominal", type=float, default=None,
                    help="override RBI nominal-GDP forecast as decimal "
                         "(e.g. 0.105)")
    ap.add_argument("--haircut-bps", type=int, default=50,
                    help="convergence haircut applied to GDP forecast "
                         "(default: 50)")
    ap.add_argument("--dry-run", action="store_true",
                    help="print artifact, do not write a file")
    args = ap.parse_args(argv)

    # Risk-free rate
    if args.rf_manual is not None:
        rf, rf_src = args.rf_manual, "operator override --rf-manual"
    else:
        rf, rf_src = fetch_risk_free_rate()

    # Sector betas
    betas, warnings = fetch_sector_betas()
    beta_src = "yfinance Ticker.info median of top-3 per sector"

    # Terminal growth
    if args.gdp_nominal is not None:
        gdp, gdp_src_label = args.gdp_nominal, "operator override --gdp-nominal"
    else:
        gdp, gdp_src_label = fetch_rbi_nominal_gdp()
    tg = default_terminal_growth(gdp, haircut_bps=args.haircut_bps)
    tg_src = f"{gdp_src_label} − {args.haircut_bps}bps convergence"

    # Current state
    try:
        current = snapshot_current_industry_wacc()
    except Exception as e:
        current = {}
        warnings.append(f"could not snapshot current INDUSTRY_WACC: {e}")

    art = build_artifact(rf, rf_src, betas, beta_src, tg, tg_src,
                         current, warnings)
    print_summary(art)

    if args.dry_run:
        print("[dry-run] no file written.")
        return 0

    if args.output:
        out_path = Path(args.output)
    else:
        ts = _dt.datetime.now().strftime("%Y%m%dT%H%M%S")
        out_path = (_REPO_ROOT / "scripts" / "snapshots" /
                    f"recalibration_{args.quarter.lower()}_{args.year}_{ts}.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(art, indent=2), encoding="utf-8")
    print(f"[ok] wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
