# backend/services/tax_service.py
# ═══════════════════════════════════════════════════════════════
# Capital Gains Tax Calculator (India, FY 2025-26 / AY 2026-27)
#
# Rules applied (post 23 July 2024 Budget):
#   STCG on listed equity: 20% (Section 111A)
#   LTCG on listed equity: 12.5% above Rs 1.25L exemption (Section 112A)
#   Holding period: 12 months threshold for LTCG
#
# Grandfathering: Not applied (users rarely have pre-Feb 2018
# positions; when they do, they should use broker's Tax P&L
# which already applies FMV rule and upload that file directly.)
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import csv
import io
import logging
from datetime import date, datetime, timedelta
from typing import Optional

logger = logging.getLogger("yieldiq.tax")

# ── FY 2025-26 tax rules ──────────────────────────────────────
LTCG_RATE = 0.125         # 12.5% on LTCG above exemption
STCG_RATE = 0.20          # 20% on STCG (listed equity with STT)
LTCG_EXEMPTION = 125_000  # Rs 1.25L per FY (all LTCG combined)
HOLDING_PERIOD_DAYS = 365  # 12 months threshold


def _parse_date(s: str) -> Optional[date]:
    """Parse a date string in common formats (DD-MM-YYYY, YYYY-MM-DD, DD/MM/YYYY)."""
    s = (s or "").strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d-%b-%Y", "%d %b %Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _fy_label(d: date) -> str:
    """Return FY label for a given date. Apr 2025 → Mar 2026 is 'FY 2025-26'."""
    if d.month >= 4:
        return f"FY {d.year}-{(d.year + 1) % 100:02d}"
    return f"FY {d.year - 1}-{d.year % 100:02d}"


def _fy_for_date(d: date) -> tuple[date, date]:
    """Return (fy_start, fy_end) for the FY containing date d."""
    if d.month >= 4:
        return date(d.year, 4, 1), date(d.year + 1, 3, 31)
    return date(d.year - 1, 4, 1), date(d.year, 3, 31)


def compute_trade_gain(trade: dict) -> dict:
    """
    Compute capital gain for a single buy/sell pair.

    Input trade dict must have:
        ticker, quantity, buy_date, buy_price, sell_date, sell_price

    Returns trade with added fields:
        holding_days, category (STCG/LTCG), gain, cost_basis, proceeds, fy
    """
    buy_d = _parse_date(str(trade.get("buy_date", "")))
    sell_d = _parse_date(str(trade.get("sell_date", "")))
    qty = float(trade.get("quantity", 0) or 0)
    buy_price = float(trade.get("buy_price", 0) or 0)
    sell_price = float(trade.get("sell_price", 0) or 0)

    if not buy_d or not sell_d or qty <= 0:
        return {**trade, "error": "Missing date or quantity"}

    if sell_d < buy_d:
        return {**trade, "error": "Sell date before buy date"}

    cost_basis = qty * buy_price
    proceeds = qty * sell_price
    gain = proceeds - cost_basis

    holding_days = (sell_d - buy_d).days
    category = "LTCG" if holding_days >= HOLDING_PERIOD_DAYS else "STCG"

    return {
        **trade,
        "ticker": str(trade.get("ticker", "")).upper().replace(".NS", "").replace(".BO", ""),
        "quantity": qty,
        "buy_date": buy_d.isoformat(),
        "sell_date": sell_d.isoformat(),
        "buy_price": round(buy_price, 2),
        "sell_price": round(sell_price, 2),
        "cost_basis": round(cost_basis, 2),
        "proceeds": round(proceeds, 2),
        "gain": round(gain, 2),
        "holding_days": holding_days,
        "category": category,
        "fy": _fy_label(sell_d),
    }


def compute_tax_summary(trades: list[dict]) -> dict:
    """
    Aggregate all trades by FY and compute STCG/LTCG tax liability.

    Returns:
        {
            by_fy: {
                "FY 2025-26": {
                    stcg_gain, stcg_loss, stcg_net, stcg_tax,
                    ltcg_gain, ltcg_loss, ltcg_net, ltcg_taxable, ltcg_tax,
                    total_tax,
                    trade_count,
                }
            }
            overall: {
                total_stcg_net, total_ltcg_net, total_tax,
                trade_count, error_count,
            }
            trades: [enriched trades...]
        }
    """
    enriched = [compute_trade_gain(t) for t in trades]
    by_fy: dict[str, dict] = {}
    error_count = 0

    for t in enriched:
        if t.get("error"):
            error_count += 1
            continue
        fy = t["fy"]
        if fy not in by_fy:
            by_fy[fy] = {
                "stcg_gain": 0.0, "stcg_loss": 0.0,
                "ltcg_gain": 0.0, "ltcg_loss": 0.0,
                "stcg_trades": [], "ltcg_trades": [],
            }
        gain = t["gain"]
        if t["category"] == "STCG":
            if gain >= 0:
                by_fy[fy]["stcg_gain"] += gain
            else:
                by_fy[fy]["stcg_loss"] += abs(gain)
            by_fy[fy]["stcg_trades"].append(t)
        else:
            if gain >= 0:
                by_fy[fy]["ltcg_gain"] += gain
            else:
                by_fy[fy]["ltcg_loss"] += abs(gain)
            by_fy[fy]["ltcg_trades"].append(t)

    # Compute tax per FY
    for fy, data in by_fy.items():
        stcg_net = data["stcg_gain"] - data["stcg_loss"]
        ltcg_net = data["ltcg_gain"] - data["ltcg_loss"]

        # STCG: tax on net if positive; losses can be set off vs LTCG gains
        # (as per Income Tax Act — STCL can offset LTCG).
        if stcg_net < 0 and ltcg_net > 0:
            offset = min(abs(stcg_net), ltcg_net)
            ltcg_net -= offset
            stcg_net += offset  # move toward zero
        stcg_taxable = max(stcg_net, 0)
        stcg_tax = stcg_taxable * STCG_RATE

        # LTCG: apply ₹1.25L exemption
        ltcg_taxable = max(ltcg_net - LTCG_EXEMPTION, 0)
        ltcg_tax = ltcg_taxable * LTCG_RATE

        total_tax = stcg_tax + ltcg_tax

        data.update({
            "stcg_net": round(stcg_net, 2),
            "stcg_gain": round(data["stcg_gain"], 2),
            "stcg_loss": round(data["stcg_loss"], 2),
            "stcg_taxable": round(stcg_taxable, 2),
            "stcg_tax": round(stcg_tax, 2),
            "ltcg_net": round(ltcg_net, 2),
            "ltcg_gain": round(data["ltcg_gain"], 2),
            "ltcg_loss": round(data["ltcg_loss"], 2),
            "ltcg_exemption_applied": round(min(ltcg_net, LTCG_EXEMPTION), 2) if ltcg_net > 0 else 0,
            "ltcg_taxable": round(ltcg_taxable, 2),
            "ltcg_tax": round(ltcg_tax, 2),
            "total_tax": round(total_tax, 2),
            "trade_count": len(data["stcg_trades"]) + len(data["ltcg_trades"]),
        })

    # Overall
    total_stcg_net = sum(v["stcg_net"] for v in by_fy.values())
    total_ltcg_net = sum(v["ltcg_net"] for v in by_fy.values())
    total_tax = sum(v["total_tax"] for v in by_fy.values())

    return {
        "by_fy": by_fy,
        "overall": {
            "total_stcg_net": round(total_stcg_net, 2),
            "total_ltcg_net": round(total_ltcg_net, 2),
            "total_tax": round(total_tax, 2),
            "trade_count": len([t for t in enriched if not t.get("error")]),
            "error_count": error_count,
        },
        "trades": enriched,
        "rules": {
            "fy_applicable": "FY 2025-26 (post 23 July 2024 Budget)",
            "stcg_rate_pct": STCG_RATE * 100,
            "ltcg_rate_pct": LTCG_RATE * 100,
            "ltcg_exemption_rs": LTCG_EXEMPTION,
            "holding_period_days": HOLDING_PERIOD_DAYS,
        },
    }


def parse_zerodha_tax_pnl_csv(csv_text: str) -> list[dict]:
    """
    Parse Zerodha Tax P&L CSV (FIFO-matched).

    Expected columns (case-insensitive, flexible):
        Symbol / Tradingsymbol
        Quantity / Qty
        Buy Date / Buy date
        Buy Price / Buy rate
        Sell Date / Sell date
        Sell Price / Sell rate

    Returns list of trade dicts ready for compute_tax_summary.
    """
    csv_text = csv_text.strip()
    if not csv_text:
        return []

    # Detect delimiter
    first_line = csv_text.split("\n")[0]
    delim = "\t" if "\t" in first_line else ","

    reader = csv.DictReader(io.StringIO(csv_text), delimiter=delim)
    if not reader.fieldnames:
        return []

    headers_lower = {h.lower().strip(): h for h in reader.fieldnames}

    def _find(candidates: list[str]) -> Optional[str]:
        for c in candidates:
            if c.lower() in headers_lower:
                return headers_lower[c.lower()]
        return None

    ticker_h = _find(["symbol", "tradingsymbol", "stock", "scrip"])
    qty_h = _find(["quantity", "qty", "qty.", "shares"])
    buy_date_h = _find(["buy date", "buy_date", "buy. date", "purchase date", "acquisition date"])
    buy_price_h = _find(["buy price", "buy_price", "buy rate", "buy value", "purchase price"])
    sell_date_h = _find(["sell date", "sell_date", "sell. date", "sale date"])
    sell_price_h = _find(["sell price", "sell_price", "sell rate", "sell value", "sale price"])

    missing = [name for name, h in [
        ("ticker", ticker_h), ("quantity", qty_h),
        ("buy_date", buy_date_h), ("buy_price", buy_price_h),
        ("sell_date", sell_date_h), ("sell_price", sell_price_h),
    ] if h is None]

    if missing:
        raise ValueError(f"Required columns not found: {', '.join(missing)}")

    trades: list[dict] = []
    for row in reader:
        try:
            ticker = (row.get(ticker_h) or "").strip().upper()
            if not ticker:
                continue
            if ":" in ticker:
                ticker = ticker.split(":")[-1]

            def _clean_num(s: str) -> float:
                return float(str(s or "0").replace(",", "").replace("\u20B9", "").strip() or 0)

            qty = _clean_num(row.get(qty_h))
            buy_price = _clean_num(row.get(buy_price_h))
            sell_price = _clean_num(row.get(sell_price_h))
            buy_date = (row.get(buy_date_h) or "").strip()
            sell_date = (row.get(sell_date_h) or "").strip()

            if qty > 0 and buy_price > 0 and sell_price > 0 and buy_date and sell_date:
                trades.append({
                    "ticker": ticker,
                    "quantity": qty,
                    "buy_date": buy_date,
                    "buy_price": buy_price,
                    "sell_date": sell_date,
                    "sell_price": sell_price,
                })
        except (ValueError, KeyError):
            continue

    return trades


def export_itr_csv(trades: list[dict]) -> str:
    """
    Export enriched trades as ITR-friendly CSV.
    Format suits Schedule CG manual entry (Items B, 1-5).
    """
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow([
        "Ticker", "Quantity", "Buy Date", "Buy Price (Rs)",
        "Sell Date", "Sell Price (Rs)", "Holding Days",
        "Cost Basis (Rs)", "Proceeds (Rs)", "Gain/Loss (Rs)",
        "Category (STCG/LTCG)", "FY",
    ])
    for t in trades:
        if t.get("error"):
            continue
        writer.writerow([
            t.get("ticker", ""), t.get("quantity", 0),
            t.get("buy_date", ""), t.get("buy_price", 0),
            t.get("sell_date", ""), t.get("sell_price", 0),
            t.get("holding_days", 0),
            t.get("cost_basis", 0), t.get("proceeds", 0), t.get("gain", 0),
            t.get("category", ""), t.get("fy", ""),
        ])
    return out.getvalue()
