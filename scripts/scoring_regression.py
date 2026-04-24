"""Scoring regression test — YieldIQ HEX scores vs expert ground truth.

Compares the current `payload->quality->>yieldiq_score` in `analysis_cache`
against the hand-curated expert targets in
`docs/audit/SCORING_GROUND_TRUTH.md`. Produces a pass/fail report suitable
for a pre-launch checklist and CI.

Usage
-----
    DATABASE_URL="..." python scripts/scoring_regression.py
    DATABASE_URL="..." python scripts/scoring_regression.py --tolerance 10
    DATABASE_URL="..." python scripts/scoring_regression.py --require-all
    DATABASE_URL="..." python scripts/scoring_regression.py --json

Status values per ticker
------------------------
  PASS     observed_score in [target_min, target_max]
  AMBER    outside [min,max] but |observed - midpoint| <= tolerance
  FAIL     outside tolerance of midpoint
  NO_DATA  ticker not present in analysis_cache

Exit codes
----------
  0 — ship criterion met (PASS >= 80% AND no |gap| > 20)
  1 — ship criterion NOT met
  2 — environment/config error (DATABASE_URL missing, baseline missing, etc.)

Read-only. Never writes to the DB. Never modifies the ground-truth doc.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from sqlalchemy import text as sa_text  # noqa: E402

from data_pipeline.db import Session  # noqa: E402


GROUND_TRUTH_PATH = _REPO / "docs" / "audit" / "SCORING_GROUND_TRUTH.md"

# ANSI colors (terminal-friendly; degrade gracefully if not a TTY).
_USE_COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None
def _c(code: str, s: str) -> str:
    return f"\033[{code}m{s}\033[0m" if _USE_COLOR else s
_RED    = lambda s: _c("31", s)   # noqa: E731
_GREEN  = lambda s: _c("32", s)   # noqa: E731
_YELLOW = lambda s: _c("33", s)   # noqa: E731
_DIM    = lambda s: _c("2",  s)   # noqa: E731


@dataclass
class GroundTruthRow:
    ticker: str
    sector: str
    target_min: float
    target_max: float
    target_midpoint: float


@dataclass
class RegressionResult:
    ticker: str
    sector: str
    target_min: float
    target_max: float
    target_midpoint: float
    observed: Optional[float]
    cache_version: Optional[str]
    status: str           # PASS | AMBER | FAIL | NO_DATA
    gap: Optional[float]  # observed - midpoint; None if NO_DATA


# ────────────────────────── ground-truth parsing ──────────────────────────

# Matches rows like:
#   | HDFCBANK.NS | bank | 78-85 | 81.5 | 17 | -64.5 |
# or with fewer columns. We look for: ticker, sector (optional), range "X-Y"
# (or "X to Y"), and a midpoint number. Actual/gap columns are ignored — we
# recompute gap against live DB data.
_ROW_RE = re.compile(
    r"^\s*\|\s*"
    r"(?P<ticker>[A-Z0-9._-]+\.[A-Z]{2})\s*\|\s*"    # TICKER.NS / .BO
    r"(?P<sector>[^|]*?)\s*\|\s*"                    # sector (may be blank)
    r"(?P<lo>\d+(?:\.\d+)?)\s*(?:-|to|–|—)\s*(?P<hi>\d+(?:\.\d+)?)"  # range
    r"\s*\|\s*"
    r"(?P<mid>\d+(?:\.\d+)?)?"                       # optional explicit mid
    r".*\|\s*$",
    re.IGNORECASE,
)


def parse_ground_truth(path: Path) -> list[GroundTruthRow]:
    """Parse ground-truth markdown. Returns rows from the summary table.

    Strategy: scan all lines, match any row whose first cell looks like a
    suffixed ticker and whose target column contains "lo-hi". Tolerates
    tables anywhere in the doc; de-duplicates by ticker (last wins).
    """
    if not path.exists():
        raise FileNotFoundError(f"Ground-truth doc not found: {path}")

    rows: dict[str, GroundTruthRow] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        m = _ROW_RE.match(line)
        if not m:
            continue
        ticker = m.group("ticker").strip().upper()
        sector = (m.group("sector") or "").strip() or "—"
        lo = float(m.group("lo"))
        hi = float(m.group("hi"))
        if lo > hi:
            lo, hi = hi, lo
        mid_raw = m.group("mid")
        mid = float(mid_raw) if mid_raw is not None else (lo + hi) / 2.0
        rows[ticker] = GroundTruthRow(
            ticker=ticker,
            sector=sector,
            target_min=lo,
            target_max=hi,
            target_midpoint=mid,
        )
    return list(rows.values())


# ────────────────────────── DB fetch ──────────────────────────

def fetch_observed(tickers: list[str]) -> dict[str, dict]:
    """One row per ticker from analysis_cache. ticker is PK, so no ordering."""
    out: dict[str, dict] = {}
    with Session() as s:
        r = s.execute(
            sa_text(
                """
                SELECT ticker,
                       (payload->'quality'->>'yieldiq_score')::float AS score,
                       cache_version,
                       computed_at
                FROM analysis_cache
                WHERE ticker = ANY(:tickers)
                """
            ),
            {"tickers": tickers},
        ).mappings().all()
        for row in r:
            out[row["ticker"].upper()] = dict(row)
    return out


# ────────────────────────── classification ──────────────────────────

def classify(gt: GroundTruthRow, observed: Optional[float], tolerance: float) -> tuple[str, Optional[float]]:
    if observed is None:
        return "NO_DATA", None
    gap = observed - gt.target_midpoint
    if gt.target_min <= observed <= gt.target_max:
        return "PASS", gap
    if abs(gap) <= tolerance:
        return "AMBER", gap
    return "FAIL", gap


# ────────────────────────── reporting ──────────────────────────

def _color_status(status: str) -> str:
    return {
        "PASS":    _GREEN("PASS"),
        "AMBER":   _YELLOW("AMBER"),
        "FAIL":    _RED("FAIL"),
        "NO_DATA": _DIM("NO_DATA"),
    }.get(status, status)


def render_text(results: list[RegressionResult], tolerance: float, ship_met: bool) -> str:
    lines: list[str] = []
    lines.append("YieldIQ Scoring Regression")
    lines.append("==========================")
    lines.append(f"Baseline: docs/audit/SCORING_GROUND_TRUTH.md ({len(results)} tickers)")
    lines.append("Source:   analysis_cache (one row per ticker, PK)")
    lines.append(f"Tolerance: +/-{tolerance:g} from target_midpoint")
    lines.append("")
    header = f"{'TICKER':<14}{'SECTOR':<14}{'TARGET':<11}{'OBSERVED':<10}{'STATUS':<10}{'CACHE_V':<8}"
    lines.append(header)
    lines.append("-" * len(header))

    for r in sorted(results, key=lambda x: (_status_rank(x.status), x.ticker)):
        target = f"{r.target_min:g}-{r.target_max:g}"
        observed = f"{r.observed:g}" if r.observed is not None else "—"
        cv = r.cache_version or "—"
        sector = (r.sector or "—")[:12]
        lines.append(
            f"{r.ticker:<14}{sector:<14}{target:<11}{observed:<10}"
            f"{_color_status(r.status):<19}{cv:<8}"
        )

    # Summary
    tally = {"PASS": 0, "AMBER": 0, "FAIL": 0, "NO_DATA": 0}
    for r in results:
        tally[r.status] = tally.get(r.status, 0) + 1
    n = len(results)
    lines.append("")
    lines.append("Summary:")
    lines.append(f"  PASS:    {tally['PASS']} / {n}")
    lines.append(f"  AMBER:   {tally['AMBER']} / {n}")
    lines.append(f"  FAIL:    {tally['FAIL']} / {n}")
    lines.append(f"  NO_DATA: {tally['NO_DATA']} / {n}")
    lines.append("")
    target_pass = int(round(n * 0.80))
    lines.append(f"Ship criterion: PASS >= {target_pass} (80%) AND no ticker with |gap| > 20")
    lines.append("Current: " + (_GREEN("MET") if ship_met else _RED("NOT MET")))

    red_flags = [r for r in results if r.gap is not None and abs(r.gap) > 30]
    if red_flags:
        lines.append("")
        lines.append("Red-flag tickers (|gap| > 30):")
        for r in sorted(red_flags, key=lambda x: -abs(x.gap or 0)):
            lines.append(f"  {r.ticker} (gap {r.gap:+.0f})")
    return "\n".join(lines)


def _status_rank(status: str) -> int:
    return {"FAIL": 0, "NO_DATA": 1, "AMBER": 2, "PASS": 3}.get(status, 9)


# ────────────────────────── ship criterion ──────────────────────────

def evaluate_ship_criterion(results: list[RegressionResult]) -> bool:
    """PASS >= 80% of total AND no ticker with |gap| > 20.

    NO_DATA rows never count toward PASS. They do NOT auto-fail the gap
    check (we have no gap). --require-all handles the missing-data case.
    """
    n = len(results)
    if n == 0:
        return False
    pass_count = sum(1 for r in results if r.status == "PASS")
    pct_ok = (pass_count / n) >= 0.80
    no_big_gaps = all(r.gap is None or abs(r.gap) <= 20 for r in results)
    return pct_ok and no_big_gaps


# ────────────────────────── CLI ──────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Compare live YieldIQ scores against expert ground truth.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Exit 0 = ship criterion met. Exit 1 = regressions present.",
    )
    ap.add_argument("--tolerance", type=float, default=15.0,
                    help="AMBER band: +/-N from target_midpoint (default: 15)")
    ap.add_argument("--require-all", action="store_true",
                    help="Fail if any ground-truth ticker is missing from analysis_cache "
                         "(default: warn only)")
    ap.add_argument("--json", action="store_true",
                    help="Emit JSON instead of text (for CI)")
    ap.add_argument("--baseline", type=Path, default=GROUND_TRUTH_PATH,
                    help=f"Path to ground-truth markdown (default: {GROUND_TRUTH_PATH})")
    args = ap.parse_args()

    if not os.environ.get("DATABASE_URL"):
        print("ERROR: DATABASE_URL not set.", file=sys.stderr)
        return 2
    if Session is None:
        print("ERROR: data_pipeline.db.Session is None — engine init failed.", file=sys.stderr)
        return 2

    try:
        gt_rows = parse_ground_truth(args.baseline)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    if not gt_rows:
        print(f"ERROR: no rows parsed from {args.baseline}", file=sys.stderr)
        return 2

    observed_map = fetch_observed([g.ticker for g in gt_rows])

    results: list[RegressionResult] = []
    for g in gt_rows:
        obs_row = observed_map.get(g.ticker)
        obs_score = obs_row.get("score") if obs_row else None
        cache_v = obs_row.get("cache_version") if obs_row else None
        status, gap = classify(g, obs_score, args.tolerance)
        results.append(RegressionResult(
            ticker=g.ticker,
            sector=g.sector,
            target_min=g.target_min,
            target_max=g.target_max,
            target_midpoint=g.target_midpoint,
            observed=obs_score,
            cache_version=cache_v,
            status=status,
            gap=gap,
        ))

    ship_met = evaluate_ship_criterion(results)
    has_no_data = any(r.status == "NO_DATA" for r in results)

    if args.json:
        payload = {
            "baseline": str(args.baseline),
            "tolerance": args.tolerance,
            "total": len(results),
            "pass":    sum(1 for r in results if r.status == "PASS"),
            "amber":   sum(1 for r in results if r.status == "AMBER"),
            "fail":    sum(1 for r in results if r.status == "FAIL"),
            "no_data": sum(1 for r in results if r.status == "NO_DATA"),
            "ship_criterion_met": ship_met,
            "results": [asdict(r) for r in results],
        }
        print(json.dumps(payload, indent=2, default=str))
    else:
        print(render_text(results, args.tolerance, ship_met))

    if args.require_all and has_no_data:
        return 1
    return 0 if ship_met else 1


if __name__ == "__main__":
    sys.exit(main())
