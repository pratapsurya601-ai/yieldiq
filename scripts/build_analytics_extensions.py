"""Compute Tier-1 analytic extensions on ratio_history.

Populates the columns added by migration 006:

    piotroski_f_score   — 0-9 financial-strength checklist
    altman_z_score      — distress predictor (manufacturing variant)
    dupont_margin       — net_income / revenue (percent)
    dupont_asset_turn   — revenue / total_assets (ratio)
    dupont_leverage     — total_assets / total_equity (ratio)
    revenue_cagr_7y / 10y, pat_cagr_3y/5y/7y/10y

Reads from `financials` for primitives, updates `ratio_history` rows in
place via UPDATE (not UPSERT — rows already exist from the main builder).

Usage:
    DATABASE_URL=... python scripts/build_analytics_extensions.py --all
    DATABASE_URL=... python scripts/build_analytics_extensions.py --tickers RELIANCE,TCS

Idempotent. Safe to rerun after each ratio_history rebuild.

Piotroski F-Score components (1 point each, 0 if criterion fails):
    1. ROA > 0
    2. OCF > 0
    3. ΔROA > 0   (improving profitability)
    4. OCF > NI   (earnings quality)
    5. ΔD/E < 0   (deleveraging)
    6. ΔCurrent Ratio > 0  (improving liquidity)
    7. No new share issuance (shares_outstanding_t ≤ shares_outstanding_{t-1})
    8. ΔGross Margin > 0
    9. ΔAsset Turnover > 0

Altman Z-Score (manufacturing formula, Altman 1968):
    Z = 1.2·(WC/TA) + 1.4·(RE/TA) + 3.3·(EBIT/TA) + 0.6·(MCap/TL) + 1.0·(Sales/TA)
    Z > 2.99  → safe
    1.81–2.99 → grey zone
    Z < 1.81  → distressed

For companies where WC or RE can't be resolved from our schema, we
substitute conservative proxies (WC ≈ current_assets − current_liab
from raw_data; RE ≈ total_equity − share_capital if available, else
skip the term and flag the row).
"""
from __future__ import annotations

import argparse
import logging
import math
import os
import signal
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("analytics_extensions")


_interrupted = False
_processed = 0


def _sigint_handler(*_: Any) -> None:
    global _interrupted
    _interrupted = True


signal.signal(signal.SIGINT, _sigint_handler)


def _finite(x: Any) -> bool:
    if x is None:
        return False
    try:
        xf = float(x)
        return not math.isnan(xf) and not math.isinf(xf)
    except (TypeError, ValueError):
        return False


def _safe_div(n: Any, d: Any) -> float | None:
    if not (_finite(n) and _finite(d)):
        return None
    dv = float(d)
    if dv == 0:
        return None
    return float(n) / dv


def _parse_raw(s: str | None) -> dict:
    if not s:
        return {}
    try:
        import json
        if isinstance(s, dict):
            return s
        return json.loads(s)
    except Exception:
        return {}


def _get_num(d: dict, *keys: str) -> float | None:
    for k in keys:
        v = d.get(k)
        if _finite(v):
            try:
                return float(v)
            except (TypeError, ValueError):
                pass
    return None


def _cagr(start: float, end: float, years: int) -> float | None:
    if not (_finite(start) and _finite(end)) or start <= 0 or end <= 0:
        return None
    if years <= 0:
        return None
    return (end / start) ** (1.0 / years) - 1.0


# ──────────────────────────────────────────────────────────────────────
# Piotroski F-Score — 9-point checklist
# ──────────────────────────────────────────────────────────────────────
def piotroski_f_score(f: dict, prior: dict | None) -> int | None:
    """Returns 0-9 or None when insufficient data."""
    # Need at least 3 criteria resolvable; otherwise return None.
    score = 0
    resolved = 0

    def p(cond: bool | None) -> None:
        nonlocal score, resolved
        if cond is None:
            return
        resolved += 1
        if cond:
            score += 1

    # 1. ROA > 0
    p(_finite(f.get("roa")) and f["roa"] > 0 if f.get("roa") is not None else None)
    # 2. CFO > 0
    p(_finite(f.get("cfo")) and f["cfo"] > 0 if f.get("cfo") is not None else None)
    # 3. ΔROA > 0
    if prior and _finite(f.get("roa")) and _finite(prior.get("roa")):
        p(f["roa"] > prior["roa"])
    # 4. CFO > Net Income (earnings quality — cash flow backs up reported profit)
    if _finite(f.get("cfo")) and _finite(f.get("pat")):
        p(f["cfo"] > f["pat"])
    # 5. ΔD/E < 0 (deleveraging)
    if prior and _finite(f.get("debt_to_equity")) and _finite(prior.get("debt_to_equity")):
        p(f["debt_to_equity"] < prior["debt_to_equity"])
    # 6. ΔCurrent Ratio > 0 (need raw_data.current_assets / current_liab)
    ca_now = f.get("_current_ratio")
    ca_prev = prior.get("_current_ratio") if prior else None
    if _finite(ca_now) and _finite(ca_prev):
        p(ca_now > ca_prev)
    # 7. No new share issuance
    if prior and _finite(f.get("shares_outstanding")) and _finite(prior.get("shares_outstanding")):
        p(f["shares_outstanding"] <= prior["shares_outstanding"])
    # 8. ΔGross Margin > 0
    if prior and _finite(f.get("gross_margin")) and _finite(prior.get("gross_margin")):
        p(f["gross_margin"] > prior["gross_margin"])
    # 9. ΔAsset Turnover > 0
    if prior:
        turn_now = _safe_div(f.get("revenue"), f.get("total_assets"))
        turn_prev = _safe_div(prior.get("revenue"), prior.get("total_assets"))
        if turn_now is not None and turn_prev is not None:
            p(turn_now > turn_prev)

    if resolved < 4:
        return None  # not enough data — don't report a fake-precise score
    return score


# ──────────────────────────────────────────────────────────────────────
# Altman Z-Score (manufacturing formula)
# ──────────────────────────────────────────────────────────────────────
def altman_z_score(f: dict, market_cap_cr: float | None) -> float | None:
    """Manufacturing formula. Returns None when any component can't be
    resolved rather than silently using a zero."""
    ta = f.get("total_assets")
    rev = f.get("revenue")
    ebit = f.get("ebit") or f.get("_ebit_effective")
    te = f.get("total_equity")
    td = f.get("total_debt")
    wc = f.get("_working_capital")
    re = f.get("_retained_earnings")

    if not (_finite(ta) and ta > 0):
        return None
    if market_cap_cr is None or not _finite(market_cap_cr):
        return None

    tl = None
    if _finite(ta) and _finite(te):
        tl = float(ta) - float(te)
    elif _finite(td):
        tl = float(td)   # crude proxy — total debt not total liabilities

    if tl is None or tl <= 0:
        return None
    if not _finite(ebit) or not _finite(rev) or not _finite(wc) or not _finite(re):
        return None

    z = (
        1.2 * (wc / ta)
        + 1.4 * (re / ta)
        + 3.3 * (ebit / ta)
        + 0.6 * (market_cap_cr / tl)
        + 1.0 * (rev / ta)
    )
    return round(z, 3)


# ──────────────────────────────────────────────────────────────────────
# Per-ticker driver
# ──────────────────────────────────────────────────────────────────────
SELECT_FIN = text("""
    SELECT period_end, period_type, revenue, ebitda, ebit, pat, cfo,
           total_assets, total_equity, total_debt, cash_and_equivalents,
           shares_outstanding, roe, roa, debt_to_equity, gross_margin,
           operating_margin, net_margin, fcf_margin, raw_data, currency
    FROM financials
    WHERE ticker = :t AND period_end IS NOT NULL
    ORDER BY period_end ASC
""")

SELECT_RH_MCAP = text("""
    SELECT period_end, period_type, market_cap_cr
    FROM ratio_history
    WHERE ticker = :t
""")

UPDATE_SQL = text("""
    UPDATE ratio_history SET
        piotroski_f_score = :p,
        altman_z_score    = :z,
        dupont_margin     = :dm,
        dupont_asset_turn = :dt,
        dupont_leverage   = :dl,
        revenue_cagr_7y   = :rc7,
        revenue_cagr_10y  = :rc10,
        pat_cagr_3y       = :pc3,
        pat_cagr_5y       = :pc5,
        pat_cagr_7y       = :pc7,
        pat_cagr_10y      = :pc10
    WHERE ticker = :t AND period_end = :pe AND period_type = :pt
""")


def _normalise_row(row) -> dict:
    """Build the computational row dict from a financials row."""
    d = {
        "period_end": row[0],
        "period_type": row[1],
        "revenue": float(row[2]) if _finite(row[2]) else None,
        "ebitda":  float(row[3]) if _finite(row[3]) else None,
        "ebit":    float(row[4]) if _finite(row[4]) else None,
        "pat":     float(row[5]) if _finite(row[5]) else None,
        "cfo":     float(row[6]) if _finite(row[6]) else None,
        "total_assets": float(row[7]) if _finite(row[7]) else None,
        "total_equity": float(row[8]) if _finite(row[8]) else None,
        "total_debt":   float(row[9]) if _finite(row[9]) else None,
        "cash":         float(row[10]) if _finite(row[10]) else None,
        "shares_outstanding": float(row[11]) if _finite(row[11]) else None,
        "roe": float(row[12]) if _finite(row[12]) else None,
        "roa": float(row[13]) if _finite(row[13]) else None,
        "debt_to_equity": float(row[14]) if _finite(row[14]) else None,
        "gross_margin":   float(row[15]) if _finite(row[15]) else None,
        "currency": row[20] or "INR",
    }
    raw = _parse_raw(row[19])
    # Current ratio components from raw_data
    ca = _get_num(raw, "current_assets", "total_current_assets")
    cl = _get_num(raw, "current_liabilities", "total_current_liabilities")
    d["_current_ratio"] = (ca / cl) if (ca is not None and cl and cl > 0) else None
    # Working capital & retained earnings for Altman
    if ca is not None and cl is not None:
        d["_working_capital"] = ca - cl
    else:
        d["_working_capital"] = None
    re_val = _get_num(raw, "retained_earnings", "reserves_and_surplus", "reserves")
    d["_retained_earnings"] = re_val
    # EBIT fallback (mirror build_ratio_history logic)
    if not _finite(d["ebit"]):
        ebit_raw = _get_num(raw, "ebit", "operating_income", "operating_profit")
        if ebit_raw is not None:
            d["_ebit_effective"] = ebit_raw
        else:
            ie = _get_num(raw, "interest_expense", "finance_cost", "finance_costs")
            if d.get("pat") is not None and ie is not None:
                d["_ebit_effective"] = d["pat"] + ie   # crude; better than nothing
            elif d.get("ebitda") is not None:
                d["_ebit_effective"] = d["ebitda"]
    return d


def process_ticker(sess, ticker: str) -> tuple[int, int]:
    """Returns (rows_updated, rows_skipped)."""
    fin_rows = sess.execute(SELECT_FIN, {"t": ticker}).fetchall()
    if not fin_rows:
        return (0, 0)

    mcap_rows = sess.execute(SELECT_RH_MCAP, {"t": ticker}).fetchall()
    mcap_by_key: dict[tuple[date, str], float | None] = {}
    for pe_end, pt, mcap in mcap_rows:
        mcap_by_key[(pe_end, pt)] = float(mcap) if _finite(mcap) else None

    rows = [_normalise_row(r) for r in fin_rows]

    # Group by period_type for prior-year lookups
    by_type: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_type[r["period_type"]].append(r)

    updated = skipped = 0

    for i, r in enumerate(rows):
        pt = r["period_type"]
        # Prior-year row within same period_type
        same_type_idx = by_type[pt]
        pos = same_type_idx.index(r)
        prior = same_type_idx[pos - 1] if pos > 0 else None

        # Piotroski
        pio = piotroski_f_score(r, prior)

        # Altman
        mcap = mcap_by_key.get((r["period_end"], pt))
        z = altman_z_score(r, mcap)

        # DuPont decomposition
        dm = None  # margin
        dt = None  # turnover
        dl = None  # leverage
        if _finite(r["pat"]) and _finite(r["revenue"]) and r["revenue"] != 0:
            dm = r["pat"] / r["revenue"] * 100.0
        if _finite(r["revenue"]) and _finite(r["total_assets"]) and r["total_assets"] != 0:
            dt = r["revenue"] / r["total_assets"]
        if _finite(r["total_assets"]) and _finite(r["total_equity"]) and r["total_equity"] != 0:
            dl = r["total_assets"] / r["total_equity"]

        # CAGRs
        def _nth_prior(n: int) -> dict | None:
            idx = pos - n
            return same_type_idx[idx] if idx >= 0 else None

        def _cagr_for(n: int, field: str) -> float | None:
            pr = _nth_prior(n)
            if pr is None:
                return None
            start = pr.get(field)
            end = r.get(field)
            return _cagr(start, end, n)

        rc7 = _cagr_for(7, "revenue")
        rc10 = _cagr_for(10, "revenue")
        pc3 = _cagr_for(3, "pat")
        pc5 = _cagr_for(5, "pat")
        pc7 = _cagr_for(7, "pat")
        pc10 = _cagr_for(10, "pat")

        res = sess.execute(UPDATE_SQL, {
            "t": ticker, "pe": r["period_end"], "pt": pt,
            "p": pio, "z": z,
            "dm": dm, "dt": dt, "dl": dl,
            "rc7": rc7, "rc10": rc10,
            "pc3": pc3, "pc5": pc5, "pc7": pc7, "pc10": pc10,
        })
        if res.rowcount:
            updated += 1
        else:
            skipped += 1  # no matching ratio_history row — ok
    sess.commit()
    return (updated, skipped)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--tickers", default=None)
    args = ap.parse_args()

    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL not set", file=sys.stderr)
        return 2
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]

    engine = create_engine(url, pool_pre_ping=True)
    Session = sessionmaker(bind=engine)
    sess = Session()

    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    else:
        tickers = [r[0] for r in sess.execute(
            text("SELECT DISTINCT ticker FROM ratio_history ORDER BY ticker")
        ).fetchall()]

    logger.info("processing %d tickers", len(tickers))
    tot_upd = tot_skip = 0
    global _processed
    for i, t in enumerate(tickers, 1):
        if _interrupted:
            logger.info("interrupted at %d/%d", i, len(tickers))
            break
        try:
            u, s = process_ticker(sess, t)
            tot_upd += u
            tot_skip += s
            _processed = i
            if i % 100 == 0:
                logger.info("[%d/%d] processed — updated=%d skipped=%d",
                            i, len(tickers), tot_upd, tot_skip)
        except Exception as e:  # noqa: BLE001
            logger.warning("ticker %s failed: %s", t, e)
            sess.rollback()

    sess.close()
    engine.dispose()
    logger.info("done. updated=%d, skipped=%d", tot_upd, tot_skip)
    return 0


if __name__ == "__main__":
    sys.exit(main())
