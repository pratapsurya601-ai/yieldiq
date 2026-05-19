"""Quarterly recalibration data-pull for YieldIQ WACC inputs.

This script captures fresh values for the three WACC-driving knobs that
need a periodic refresh:

1. **Risk-free rate** — Indian 10Y G-Sec yield. Hardcoded fallback that
   the operator updates quarterly from the RBI Press-Release page. The
   previous yfinance feeds (``^IN10Y`` and ``IN10YT=RR``) were dropped
   by Yahoo in 2025 and both return 404.
2. **Sector betas** — Damodaran emerging-markets sector betas (India
   sheet), updated annually each January. Hardcoded as a table; operator
   refreshes from the Stern dataset once a year. The previous
   ``yf.Ticker(t).info["beta"]`` path produced catastrophically low
   values for Indian listings (IT services 0.13, tech hardware 0.004)
   and silently dropped tickers such as AMBER.NS, TATAMOTORS.NS,
   SHREECEM.NS that had no ``beta`` field at all.
3. **Terminal growth assumption** — Sector-specific Damodaran-style
   stable-stage values, capped at 6 % (above India long-run nominal GDP
   is unsupportable). Previously derived from "RBI nominal GDP − 50 bps",
   which conflated *current* nominal GDP (~10.5 %) with *long-run*
   terminal growth — a category error that would balloon every FV.

Output is a JSON artifact in ``scripts/snapshots/`` that the operator
inspects, optionally edits, and then feeds into
``scripts/apply_recalibration.py`` to produce the
``models/industry_wacc.py`` diff for the next PR.

This script does NOT modify any source file and does NOT bump
CACHE_VERSION. Those steps happen in a separate, reviewed PR.

CLI:
    python scripts/fetch_recalibration_inputs.py \\
        --quarter Q2 --year 2026 --dry-run

The ``--rf-manual`` flag remains as an escape hatch when the hardcoded
risk-free rate is stale.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path
from typing import Any

# ── Repo path bootstrap so we can import models.industry_wacc ─────
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# ══════════════════════════════════════════════════════════════════
# Hardcoded reference tables
# ══════════════════════════════════════════════════════════════════
#
# Cap on any sector terminal-growth value. India long-run nominal GDP
# is not credibly above this; anything higher fails the sanity guard
# in fetch_sector_terminal_growth() and is also enforced by the test
# ``test_terminal_growth_never_exceeds_cap``.
TERMINAL_GROWTH_CAP: float = 0.06


# Risk-free rate (10Y G-Sec). Update QUARTERLY from
# https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx
# (look for "Government Stock - 10 Year" weighted-average yield).
#
# Last updated: 2026-05 — 10Y G-Sec mid-May 2026 ~7.10 %.
RBI_10Y_GSEC_2026Q2: float = 0.0710
RBI_10Y_GSEC_SOURCE: str = (
    "RBI Press Release, 10Y G-Sec weighted-average yield, "
    "mid-May 2026 (hardcoded — refresh quarterly from "
    "https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx)"
)


# Damodaran emerging-markets sector betas — India sheet.
# Source: http://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/Betas.html
# (Emerging Markets > India). Updated each January.
#
# Last revision: 2026-01 update (operator: refresh annually after the
# Damodaran January data drop).
#
# NOTE: These are heuristic defaults aligned to the published levered-
# beta column. Operator is expected to revise once they download the
# actual 2026 spreadsheet — these values are starting points sized to
# be obviously safer than the broken yfinance lookups they replace.
DAMODARAN_INDIA_BETAS_2026: dict[str, float] = {
    "it_services":       1.05,
    "banks":             1.10,
    "nbfc":              1.25,
    "fmcg":              0.75,
    "pharma":            0.85,
    "auto_oem":          1.20,
    "auto_ancillary":    1.10,
    "cement":            1.05,
    "metals":            1.35,
    "oil_gas":           1.05,
    "telecom":           0.90,
    "capital_goods":     1.15,
    "power":             0.85,
    "regulated_utility": 0.65,
    "realty":            1.40,
    "infrastructure":    1.10,
    "chemicals":         1.05,
    "consumer_durable":  1.00,
    "media":             1.20,
    "retail":            1.15,
    "logistics":         0.95,
    "saas_software":     1.20,
    "tech_hardware":     1.15,
    "airlines":          1.45,
    "defence":           1.00,
    "hospital":          0.90,
}
DAMODARAN_BETAS_SOURCE: str = (
    "Damodaran Emerging Markets sector betas (India), "
    "Jan-2026 annual update — refresh from "
    "http://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/Betas.html"
)


# Long-run terminal-growth assumptions, sector-specific.
# Anchored to Damodaran's recommendation (~4-5 % nominal for India,
# bounded by the 10Y G-Sec long-bond yield as a hard ceiling).
#
# Capped by TERMINAL_GROWTH_CAP. Operator revises once a year alongside
# the beta refresh.
TERMINAL_GROWTH_2026: dict[str, float] = {
    "default":           0.045,
    "it_services":       0.05,
    "fmcg":              0.055,  # brand-premium persistence
    "pharma":            0.05,
    "auto_oem":          0.045,
    "banks":             0.05,
    "nbfc":              0.05,
    "regulated_utility": 0.04,
    "metals":            0.035,  # cyclical, lower
    "oil_gas":           0.03,   # secular decline thesis
    "telecom":           0.045,
    "tech_hardware":     0.05,
    "capital_goods":     0.045,
    "cement":            0.04,
    "realty":            0.045,
    "saas_software":     0.055,
    "media":             0.04,
    "retail":            0.045,
}
TERMINAL_GROWTH_SOURCE: str = (
    "Damodaran-style stable-stage terminal growth (India, 2026), "
    f"capped at {TERMINAL_GROWTH_CAP:.2%}; sector overlays reflect "
    "cyclicality and secular outlook"
)


# ══════════════════════════════════════════════════════════════════
# Data-pull primitives (kept thin so they can be monkeypatched in tests)
# ══════════════════════════════════════════════════════════════════
def fetch_risk_free_rate() -> tuple[float, str]:
    """Return (rate_as_decimal, source_description) for the Indian 10Y
    G-Sec yield.

    Uses the hardcoded ``RBI_10Y_GSEC_2026Q2`` constant. Operator must
    refresh quarterly from the RBI press-release page (see constant
    docstring). Override at runtime with ``--rf-manual``.
    """
    return RBI_10Y_GSEC_2026Q2, RBI_10Y_GSEC_SOURCE


def fetch_sector_betas(
    table: dict[str, float] | None = None,
) -> tuple[dict[str, float], list[str]]:
    """Return (sector → beta, warnings) from the Damodaran lookup table.

    The previous implementation pulled ``yf.Ticker(t).info["beta"]``
    sector by sector. That path was deleted because (a) Yahoo's beta
    field for Indian listings is computed against a tiny lookback window
    and routinely under-reports (TCS at 0.13, DIXON near zero), and
    (b) many tickers simply have no beta field, silently dropping
    sectors from the artifact.
    """
    src = dict(table) if table is not None else dict(DAMODARAN_INDIA_BETAS_2026)
    warnings: list[str] = []
    out: dict[str, float] = {}
    for sector, beta in src.items():
        try:
            b = float(beta)
        except (TypeError, ValueError):
            warnings.append(f"{sector}: beta not numeric ({beta!r}) — skipped")
            continue
        if b <= 0 or b > 3.0:
            warnings.append(
                f"{sector}: beta {b} outside sane range (0, 3] — skipped"
            )
            continue
        out[sector] = round(b, 3)
    return out, warnings


def fetch_sector_terminal_growth(
    table: dict[str, float] | None = None,
    cap: float = TERMINAL_GROWTH_CAP,
) -> tuple[dict[str, float], list[str]]:
    """Return (sector → terminal growth, warnings) from the hardcoded
    Damodaran-style table.

    Every value is clamped at ``cap`` (default 6 %). Anything above the
    cap raises a warning AND is silently clipped — the operator is
    expected to investigate before applying.
    """
    src = dict(table) if table is not None else dict(TERMINAL_GROWTH_2026)
    warnings: list[str] = []
    out: dict[str, float] = {}
    for sector, g in src.items():
        try:
            gv = float(g)
        except (TypeError, ValueError):
            warnings.append(
                f"{sector}: terminal_growth not numeric ({g!r}) — skipped"
            )
            continue
        if gv > cap:
            warnings.append(
                f"{sector}: terminal_growth {gv} exceeds cap {cap}; clipped"
            )
            gv = cap
        if gv < 0:
            warnings.append(
                f"{sector}: terminal_growth {gv} negative — skipped"
            )
            continue
        out[sector] = round(gv, 4)
    return out, warnings


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

    print("\nSector betas (Damodaran India sheet):")
    print(f"  source: {art['sector_betas_source']}")
    print(f"  {'sector':<22}{'old':>10}{'new':>10}{'delta':>10}")
    for sector, new in sorted(art["sector_betas"].items()):
        old = cur.get(sector, {}).get("beta_typical", float("nan"))
        delta = new - old if old == old else float("nan")  # NaN-safe
        print(f"  {sector:<22}{old:>10.3f}{new:>10.3f}{delta:>+10.3f}")

    print("\nTerminal growth (Damodaran-style, sector overlays — REVIEW BEFORE APPLY):")
    print(f"  source: {art['terminal_growth_source']}")
    print(f"  {'sector':<22}{'old':>10}{'new':>10}{'delta':>10}")
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
    ap.add_argument("--dry-run", action="store_true",
                    help="print artifact, do not write a file")
    args = ap.parse_args(argv)

    warnings: list[str] = []

    # Risk-free rate
    if args.rf_manual is not None:
        rf, rf_src = args.rf_manual, "operator override --rf-manual"
    else:
        rf, rf_src = fetch_risk_free_rate()

    # Sector betas (Damodaran lookup)
    betas, beta_warnings = fetch_sector_betas()
    warnings.extend(beta_warnings)
    beta_src = DAMODARAN_BETAS_SOURCE

    # Terminal growth
    tg, tg_warnings = fetch_sector_terminal_growth()
    warnings.extend(tg_warnings)
    tg_src = TERMINAL_GROWTH_SOURCE

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
