"""ROOT CAUSE #10 — Audit concall AI summary coverage.

For each ticker in the canary universe, list the most recent N concalls
along with whether an AI summary exists. Emits a CSV of missing
summaries grouped by ticker so the operator can decide which tickers to
re-run through the existing concall-backfill workflow.

The script intentionally does NOT trigger any LLM calls — it only reads
the concall_transcripts table and reports. Pair with the new
concall_summary_retry.yml workflow (see
.github/workflows/concall_summary_retry.yml) when the audit shows gaps.

Usage (run from repo root with miniconda Python):

    python scripts/audit_concall_summary_coverage.py
    python scripts/audit_concall_summary_coverage.py --latest 4
    python scripts/audit_concall_summary_coverage.py --universe canary_180
    python scripts/audit_concall_summary_coverage.py --out coverage.csv

Flags:
    --latest N      How many of the most recent concalls per ticker to
                    audit (default 4 — typically one fiscal year).
    --universe NAME Ticker list to walk. One of `canary_180`, `canary_50`,
                    or `all_active`. Default `canary_180`.
    --out PATH      Where to write the CSV (default
                    `_audit_concall_coverage.csv` in the cwd).

Exit codes:
    0  ran cleanly. Missing summaries are reported via stderr count +
       the CSV — non-zero coverage gaps are NOT treated as failures.
    1  no DB session / canary file missing / fatal init error.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

logger = logging.getLogger("yieldiq.audit.concall_coverage")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


_UNIVERSE_FILES = {
    "canary_180": "scripts/canary_universe_180.json",
    "canary_50": "scripts/canary_stocks_50.json",
}


def _load_universe(name: str) -> list[str]:
    """Return a list of bare (no .NS) tickers for the requested universe."""
    if name == "all_active":
        # Read directly from the DB — every active stock.
        from data_pipeline.db import Session as PipelineSession
        if PipelineSession is None:
            raise RuntimeError("no DB session for all_active universe")
        session = PipelineSession()
        try:
            from sqlalchemy import text as _t
            rows = session.execute(_t(
                "SELECT DISTINCT symbol FROM stocks WHERE active = true ORDER BY symbol"
            )).fetchall()
            return [str(r[0]) for r in rows if r[0]]
        finally:
            try:
                session.close()
            except Exception:
                pass

    path = _UNIVERSE_FILES.get(name)
    if not path:
        raise ValueError(f"unknown universe {name!r}")
    full = ROOT / path
    if not full.exists():
        raise FileNotFoundError(f"universe file missing: {full}")
    raw = json.loads(full.read_text())
    # The canary files are either a list of strings, a list of dicts
    # with {"ticker": ...}, or a dict {"tickers": [...]}.
    if isinstance(raw, dict):
        raw = raw.get("tickers") or raw.get("stocks") or []
    out: list[str] = []
    for item in raw:
        if isinstance(item, str):
            out.append(item)
        elif isinstance(item, dict):
            t = item.get("ticker") or item.get("symbol")
            if t:
                out.append(str(t))
    # Strip suffixes — concall_transcripts stores .NS so we'll
    # normalise on the read side.
    return [t.replace(".NS", "").replace(".BO", "") for t in out]


def _normalise_library_ticker(ticker: str) -> str:
    t = (ticker or "").upper().strip()
    if not t:
        return ""
    if t.endswith(".NS") or t.endswith(".BO"):
        return t
    return f"{t}.NS"


def audit_coverage(universe: list[str], latest: int) -> list[dict]:
    """Walk the universe and return one row per (ticker, concall).

    Each row carries:
        ticker, period, filing_date, has_pdf, has_summary,
        summary_age_days, ai_model
    """
    from backend.models.concalls import ConcallTranscript
    from backend.services import concall_service
    from data_pipeline.db import Session as PipelineSession

    if PipelineSession is None:
        raise RuntimeError("no DB session available")
    session = PipelineSession()
    out: list[dict] = []
    try:
        from datetime import date as _date
        today = _date.today()
        for bare in universe:
            full = _normalise_library_ticker(bare)
            rows = (
                session.query(ConcallTranscript)
                .filter(ConcallTranscript.ticker == full)
                .order_by(
                    ConcallTranscript.filing_date.desc(),
                    ConcallTranscript.id.desc(),
                )
                .limit(latest)
                .all()
            )
            if not rows:
                out.append({
                    "ticker": bare,
                    "period": "",
                    "filing_date": "",
                    "has_pdf": False,
                    "has_summary": False,
                    "summary_age_days": None,
                    "ai_model": "",
                    "note": "no concalls in table",
                })
                continue
            for r in rows:
                summary_present = bool((r.ai_summary or "").strip())
                age_days: int | None = None
                if r.ai_summary_generated_at:
                    try:
                        age_days = (today - r.ai_summary_generated_at.date()).days
                    except Exception:
                        age_days = None
                out.append({
                    "ticker": bare,
                    "period": concall_service._parse_period_from_subject(
                        r.subject or ""
                    ),
                    "filing_date": r.filing_date.isoformat() if r.filing_date else "",
                    "has_pdf": bool(r.pdf_url),
                    "has_summary": summary_present,
                    "summary_age_days": age_days,
                    "ai_model": r.ai_summary_model or "",
                    "note": "",
                })
    finally:
        try:
            session.close()
        except Exception:
            pass
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest", type=int, default=4)
    parser.add_argument("--universe", default="canary_180",
                        choices=list(_UNIVERSE_FILES) + ["all_active"])
    parser.add_argument("--out", default="_audit_concall_coverage.csv")
    args = parser.parse_args()

    try:
        universe = _load_universe(args.universe)
    except Exception as exc:
        logger.error("failed to load universe %s: %s", args.universe, exc)
        return 1
    logger.info("auditing %d tickers from universe=%s (latest=%d)",
                len(universe), args.universe, args.latest)

    try:
        rows = audit_coverage(universe, args.latest)
    except Exception as exc:
        logger.error("audit failed: %s", exc, exc_info=True)
        return 1

    out_path = Path(args.out)
    fieldnames = [
        "ticker", "period", "filing_date", "has_pdf", "has_summary",
        "summary_age_days", "ai_model", "note",
    ]
    with out_path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        for row in rows:
            w.writerow(row)

    # Coverage stats
    total = len(rows)
    missing = [r for r in rows if r["has_pdf"] and not r["has_summary"]]
    no_concalls = [r for r in rows if r["note"] == "no concalls in table"]
    grouped: dict[str, list[str]] = {}
    for r in missing:
        grouped.setdefault(r["ticker"], []).append(r["period"] or r["filing_date"])

    logger.info(
        "coverage report: %d total rows, %d missing summaries (%d distinct tickers), %d tickers with no concalls",
        total, len(missing), len(grouped), len(no_concalls),
    )
    if grouped:
        logger.info("missing summaries by ticker (first 20 shown):")
        for ticker, periods in sorted(grouped.items())[:20]:
            logger.info("  %-12s %s", ticker, ", ".join(periods))
        # Emit a single comma-separated list to make the retry workflow
        # input copy-paste-friendly.
        logger.info("RETRY_TICKERS (csv input): %s", ",".join(sorted(grouped.keys())))

    logger.info("wrote CSV to %s", out_path.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
