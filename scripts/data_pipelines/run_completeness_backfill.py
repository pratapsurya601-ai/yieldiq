#!/usr/bin/env python
"""Unified completeness-backfill entry point.

Reads the latest `reports/download_requirements_<date>.json` produced
by the audit agent, dispatches the matching `fetch_*` worker for each
declared field in parallel, and writes a markdown summary to
`docs/ops/backfill_summary_<date>.md`.

Usage:
    DATABASE_URL=$(sed -n '2p' .env.local) \\
        python scripts/data_pipelines/run_completeness_backfill.py [opts]

See PR body for full architecture diagram and CLI flags.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, datetime, timezone
from pathlib import Path

# Allow running both as `python -m scripts.data_pipelines.run_completeness_backfill`
# AND as `python scripts/data_pipelines/run_completeness_backfill.py`.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from scripts.data_pipelines import _common as C
    from scripts.data_pipelines import fetch_industry, fetch_annual_financials
    from scripts.data_pipelines import fetch_market_metrics, fetch_corporate_actions
else:
    from . import _common as C
    from . import fetch_industry, fetch_annual_financials
    from . import fetch_market_metrics, fetch_corporate_actions


# Map "field name in audit JSON" -> backfill module
DISPATCH = {
    "industry": fetch_industry,
    "sector": fetch_industry,                 # alias — same module fills both cols
    "annual_financials": fetch_annual_financials,
    "market_metrics_pe_pb": fetch_market_metrics,
    "corporate_actions": fetch_corporate_actions,
}


# --------------------------------------------------------------------------- #
# Requirements file discovery
# --------------------------------------------------------------------------- #
def find_requirements_file(explicit: Path | None) -> Path | None:
    if explicit:
        return explicit if explicit.exists() else None
    candidates = sorted(C.REPORTS_DIR.glob("download_requirements_*.json"))
    return candidates[-1] if candidates else None


def load_requirements(p: Path) -> dict[str, dict]:
    raw = json.loads(p.read_text(encoding="utf-8"))
    return raw.get("fields_to_download") or {}


# --------------------------------------------------------------------------- #
# Filtering
# --------------------------------------------------------------------------- #
def apply_top(tickers: list[str], n: int, session_factory) -> list[str]:
    """Trim to top-N by latest market_cap (uses existing market_metrics)."""
    if not n or n <= 0 or n >= len(tickers):
        return tickers
    from sqlalchemy import text

    bare = sorted({C.bare(t) for t in tickers})
    sess = session_factory()
    try:
        sql = text("""
            SELECT ticker FROM (
                SELECT DISTINCT ON (ticker) ticker, market_cap_cr
                  FROM market_metrics
                 WHERE ticker = ANY(:tickers)
                 ORDER BY ticker, trade_date DESC
            ) t
            ORDER BY market_cap_cr DESC NULLS LAST
            LIMIT :n
        """)
        ranked = [r[0] for r in sess.execute(sql, {"tickers": bare, "n": n}).fetchall()]
    finally:
        sess.close()
    if not ranked:
        return tickers[:n]
    return ranked


# --------------------------------------------------------------------------- #
# Summary writer
# --------------------------------------------------------------------------- #
def write_summary(reports: dict[str, C.BackfillReport], req_path: Path,
                  run_id: str, dry_run: bool) -> Path:
    out_dir = C.REPO_ROOT / "docs" / "ops"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"backfill_summary_{date.today().isoformat()}.md"

    lines: list[str] = []
    lines.append(f"# Completeness backfill — {date.today().isoformat()}")
    lines.append("")
    lines.append(f"- Run ID: `{run_id}`")
    lines.append(f"- Requirements file: `{req_path.name}`")
    lines.append(f"- Mode: {'dry-run' if dry_run else 'real'}")
    lines.append(f"- Started: {datetime.now(timezone.utc).isoformat()}")
    lines.append("")
    lines.append("## Per-source results")
    lines.append("")
    lines.append("| Field | Attempted | Succeeded | Skipped | Errored | Top sources |")
    lines.append("| --- | ---: | ---: | ---: | ---: | --- |")
    for fname, rep in reports.items():
        srcs = ", ".join(f"{k}={v}" for k, v in sorted(rep.by_source.items(),
                                                       key=lambda kv: -kv[1])[:3])
        lines.append(
            f"| {fname} | {rep.attempted} | {rep.succeeded} | "
            f"{rep.skipped} | {rep.errored} | {srcs or '—'} |"
        )
    lines.append("")
    lines.append("## Top errors")
    lines.append("")
    any_err = False
    for fname, rep in reports.items():
        if not rep.top_errors:
            continue
        any_err = True
        lines.append(f"### {fname}")
        for err, n in sorted(rep.top_errors.items(), key=lambda kv: -kv[1])[:5]:
            lines.append(f"- `{err}` × {n}")
        lines.append("")
    if not any_err:
        lines.append("_None._")
        lines.append("")

    lines.append("## Next-run estimate")
    lines.append("")
    next_total = sum(r.skipped + r.errored for r in reports.values())
    lines.append(
        f"- Tickers still missing data after this run (skipped + errored): **{next_total}**"
    )
    lines.append(
        "- These are the candidates for the next requirements JSON. Re-run "
        "weekly via the GH Action below."
    )
    lines.append("")
    lines.append("## Recommendation")
    lines.append("")
    lines.append(
        "Wire `.github/workflows/data_completeness_weekly.yml` (Sunday 06:00 "
        "UTC). It runs the audit, then this pipeline against the produced "
        "requirements JSON, and posts this summary as a GitHub issue."
    )
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--requirements", type=Path, default=None,
                   help="Path to download_requirements_<date>.json")
    p.add_argument("--fields", default="",
                   help="Comma-separated subset of fields to run (default: all)")
    p.add_argument("--top", type=int, default=0,
                   help="Restrict to top-N by market cap")
    p.add_argument("--dry-run", action="store_true",
                   help="Show what would be fetched, no writes")
    p.add_argument("--resume", action="store_true",
                   help="(Default behaviour) skip tickers already in checkpoint")
    p.add_argument("--reset-checkpoints", action="store_true",
                   help="Delete all checkpoint files before starting")
    p.add_argument("--verbose", "-v", action="store_true")
    args = p.parse_args()

    C.setup_logging(logging.DEBUG if args.verbose else logging.INFO)
    C.install_signal_handlers()

    req_path = find_requirements_file(args.requirements)
    if not req_path:
        logging.error(
            "No requirements file found. Pass --requirements or wait for the "
            "audit agent to land `reports/download_requirements_<date>.json` on main."
        )
        return 2
    logging.info("loaded requirements from %s", req_path)
    reqs = load_requirements(req_path)

    if args.reset_checkpoints:
        for f in C.CHECKPOINT_DIR.glob("*.json"):
            f.unlink()
        logging.info("checkpoints cleared")

    selected = set(s.strip() for s in args.fields.split(",") if s.strip()) or set(reqs.keys())
    run_id = C.now_run_id()
    C.init_jsonl_log(run_id)
    logging.info("run_id=%s fields=%s dry_run=%s", run_id, sorted(selected), args.dry_run)

    if not args.dry_run:
        # Fail fast if DATABASE_URL missing, before spawning workers.
        try:
            C.get_database_url()
        except RuntimeError as e:
            logging.error("%s", e)
            return 2

    session_factory = (lambda: C.make_session()) if not args.dry_run else (lambda: None)

    reports: dict[str, C.BackfillReport] = {}
    for field_name, payload in reqs.items():
        if field_name not in selected:
            continue
        if field_name not in DISPATCH:
            logging.warning("no fetch_* module for field=%s — skipping", field_name)
            continue
        tickers = list(payload.get("tickers") or [])
        if not tickers:
            logging.info("[%s] empty ticker list — skipping", field_name)
            continue
        if args.top:
            tickers = apply_top(tickers, args.top, C.make_session) if not args.dry_run else tickers[:args.top]
        module = DISPATCH[field_name]
        logging.info("[%s] dispatching %d tickers via %s",
                     field_name, len(tickers), module.__name__)
        rep = module.backfill(tickers, session_factory, dry_run=args.dry_run)
        reports[field_name] = rep

    summary_path = write_summary(reports, req_path, run_id, args.dry_run)
    logging.info("summary written to %s", summary_path)
    print(f"\nSummary: {summary_path}")
    for fname, rep in reports.items():
        print(f"  {fname}: ok={rep.succeeded} skip={rep.skipped} err={rep.errored}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
