#!/usr/bin/env python
# scripts/audit_classification.py
# ═══════════════════════════════════════════════════════════════
# Loops over every active ticker, computes classify(t) AND reads
# stocks.sector + stocks.industry, flags mismatches and ranks them
# by impact (mcap × mismatch severity).
#
# Output: docs/ops/classification_audit_<DATE>.md (top-N section
# at the head, full results below).
#
# Usage:
#   DATABASE_URL=$NEON_URL python scripts/audit_classification.py \
#       [--limit 50] [--out docs/ops/classification_audit_TODAY.md]
#
# This script is non-functional / read-only. It is safe to run any
# time and never writes to the DB. Intended cadence: weekly.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from pathlib import Path

# Ensure repo root on path so the backend package imports work when
# the script is run as `python scripts/audit_classification.py`.
_THIS = Path(__file__).resolve()
sys.path.insert(0, str(_THIS.parent.parent))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=50,
                    help="Top-N section length (default 50).")
    ap.add_argument(
        "--out",
        default=None,
        help="Output markdown path. Default docs/ops/classification_audit_<TODAY>.md",
    )
    args = ap.parse_args()

    today = dt.date.today().isoformat()
    out_path = Path(
        args.out
        or f"docs/ops/classification_audit_{today}.md"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)

    from backend.services.classification import classify
    from backend.services.analysis.db import _get_pipeline_session
    from sqlalchemy import text

    db = _get_pipeline_session()
    if db is None:
        print("FATAL: could not get DB session — set DATABASE_URL", file=sys.stderr)
        return 2

    try:
        active = db.execute(
            text(
                "SELECT s.ticker, s.company_name, s.sector, s.industry, "
                "       COALESCE(mm.market_cap_cr, 0) AS mcap "
                "FROM stocks s "
                "LEFT JOIN LATERAL ("
                "  SELECT market_cap_cr FROM market_metrics "
                "  WHERE ticker = s.ticker "
                "  ORDER BY trade_date DESC LIMIT 1"
                ") mm ON TRUE "
                "WHERE s.is_active = TRUE"
            )
        ).fetchall()
    except Exception as exc:
        print(f"FATAL: query failed: {exc}", file=sys.stderr)
        return 3

    rows: list[dict] = []
    for r in active:
        ticker = r[0]
        company = r[1] or ""
        stored_sector = r[2]
        stored_industry = r[3]
        mcap = float(r[4] or 0)

        try:
            result = classify(f"{ticker}.NS", db)
        except Exception as exc:
            rows.append({
                "ticker": ticker,
                "company": company,
                "stored_sector": stored_sector,
                "stored_industry": stored_industry,
                "canonical": "ERROR",
                "confidence": 0.0,
                "sources": [],
                "mcap_cr": mcap,
                "severity": 1.0,
                "impact": mcap,
                "note": f"classify() raised: {exc}",
            })
            continue

        # Severity heuristic: mismatch if classifier picked a meaningfully
        # different bucket than what's stored. We can't directly compare —
        # stored is yfinance label, canonical is our label — so we look
        # for the obvious cases:
        #   - Unclassified output (classifier failed) -> severity 1.0
        #   - Bank vs non-Banks-industry stored      -> severity 0.9
        #   - Pharma but stored sector NOT Healthcare -> severity 0.8
        #   - IT Services but stored NOT Technology  -> severity 0.7
        #   - any other downgrade mismatch           -> severity 0.4
        canonical = result.canonical_sector
        sev = 0.0
        note_bits: list[str] = []

        if canonical == "Unclassified":
            sev = 1.0
            note_bits.append("classifier_unclassified")
        elif result.is_bank and (
            not stored_industry or "bank" not in (stored_industry or "").lower()
        ):
            sev = max(sev, 0.9)
            note_bits.append("bank_classification_no_bank_industry")
        elif canonical == "Pharma" and (stored_sector or "") != "Healthcare":
            sev = max(sev, 0.8)
            note_bits.append("pharma_outside_healthcare")
        elif canonical == "IT Services" and (stored_sector or "") != "Technology":
            sev = max(sev, 0.7)
            note_bits.append("it_outside_technology")
        elif (
            stored_sector
            and stored_sector.strip().lower() in {"general", "diversified", "general/diversified", ""}
        ):
            sev = max(sev, 0.6)
            note_bits.append("stored_sector_generic")

        # Anything below 0.4 is "fine, no action" — skip from output.
        if sev < 0.4:
            continue

        rows.append({
            "ticker": ticker,
            "company": company,
            "stored_sector": stored_sector or "",
            "stored_industry": stored_industry or "",
            "canonical": canonical,
            "confidence": result.data_quality_score,
            "sources": result.sources_used,
            "mcap_cr": mcap,
            "severity": sev,
            "impact": sev * (mcap or 1.0),  # tickers without mcap still rank, just lower
            "note": ",".join(note_bits),
        })

    db.close()

    rows.sort(key=lambda x: x["impact"], reverse=True)
    top = rows[: args.limit]

    lines: list[str] = []
    lines.append(f"# Classification audit — {today}")
    lines.append("")
    lines.append(
        "Generated by `scripts/audit_classification.py`. Mismatches are ranked "
        "by `severity * market_cap_cr`. The top section is the most-impactful "
        "issues; the full list follows."
    )
    lines.append("")
    lines.append(f"Total flagged: **{len(rows)}** active tickers (severity ≥ 0.4).")
    lines.append("")
    lines.append("## Top {} by impact".format(min(args.limit, len(rows))))
    lines.append("")
    lines.append(
        "| # | Ticker | Company | Stored sector | Stored industry | "
        "Classifier → | Confidence | Sources | MCap (Cr) | Severity | Note |"
    )
    lines.append(
        "|---|--------|---------|---------------|-----------------|"
        "--------------|------------|---------|-----------|----------|------|"
    )
    for i, r in enumerate(top, start=1):
        lines.append(
            "| {i} | {t} | {c} | {ss} | {si} | {can} | {conf:.2f} | {src} | "
            "{mc:,.0f} | {sev:.2f} | {note} |".format(
                i=i,
                t=r["ticker"],
                c=(r["company"][:32] or "—"),
                ss=(r["stored_sector"] or "—"),
                si=(r["stored_industry"] or "—"),
                can=r["canonical"],
                conf=r["confidence"],
                src=",".join(r["sources"]),
                mc=r["mcap_cr"],
                sev=r["severity"],
                note=r["note"],
            )
        )
    lines.append("")
    lines.append("## Full flagged list")
    lines.append("")
    lines.append("Tickers below the top-N, in the same ranking.")
    lines.append("")
    lines.append("```")
    for r in rows[args.limit:]:
        lines.append(
            f"{r['ticker']:<14} sev={r['severity']:.2f} mcap={r['mcap_cr']:>10,.0f} "
            f"stored={r['stored_sector'] or '—'}/{r['stored_industry'] or '—'} -> "
            f"{r['canonical']} ({','.join(r['sources'])})"
        )
    lines.append("```")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {out_path} — {len(rows)} flagged, top {len(top)} in table.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
