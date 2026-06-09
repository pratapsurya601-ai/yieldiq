# backend/services/monthly_accuracy_report.py
# ═══════════════════════════════════════════════════════════════
# Monthly accuracy report — T5.7 of the engine refinement roadmap.
#
# Looks back at every fair_value_history row published in the
# target calendar month, joins it forward 30 days to daily_prices,
# and asks: how often did the verdict's implied direction match
# what the market actually did?
#
# This is the trust + accountability surface. Sell-side analysts
# publish accuracy reports; this service produces one automatically
# on the 1st of every month for the prior month.
#
# Output shape
# ────────────
#   MonthlyAccuracyReport
#     report_month                    "2026-05"
#     total_verdicts_published        N rows in fair_value_history
#                                     dated within the target month
#     coverage_count                  rows that had a 30d-forward
#                                     close (everyone else excluded
#                                     from accuracy math)
#     direction_accuracy_pct          % of covered rows where the
#                                     verdict direction matched
#     median_abs_error_pct            |FV − price_30d_later| /
#                                     price_30d_later (median)
#     top_5_winners                   biggest correct-direction wins
#     top_5_misses                    wrong direction or magnitude
#                                     blown out
#     by_sector_summary               sector → coverage / dir_acc /
#                                     median_err
#     by_verdict_summary              verdict_at_publish → same
#     generated_at                    ISO-8601 UTC
#
# All compute is pure: a callable ``data_provider`` returns the raw
# rows so unit tests skip the DB. The default provider opens a
# read-only pipeline session and runs two queries.
#
# Vocabulary note
# ───────────────
# The fair_value_history table stores legacy internal verdicts —
# "undervalued", "fairly_valued", "overvalued". This module is
# server-side and operator-facing only; the public /calibration
# page already maps these to SEBI-safe band names via
# backend.services.fv_accuracy_service when surfaced anonymously.
# The to_markdown() output here is for the operator email only.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Iterable, Optional, Sequence

log = logging.getLogger("yieldiq.monthly_accuracy")


# ─────────────────────────────────────────────────────────────────
# Direction thresholds (in percent). Match fv_accuracy_service so
# the monthly and 12-month dashboards use the same definition of
# "correct direction".
# ─────────────────────────────────────────────────────────────────
DIR_BELOW_THRESHOLD = 5.0   # undervalued → return > +5%
DIR_ABOVE_THRESHOLD = -5.0  # overvalued  → return < −5%
DIR_NEAR_BAND = 10.0        # fairly_valued → |return| ≤ 10%

LOOKBACK_DAYS = 30          # forward window
PRICE_LOOKUP_SLACK_DAYS = 7  # NSE holidays / weekend slack


# ─────────────────────────────────────────────────────────────────
# Data structures
# ─────────────────────────────────────────────────────────────────
@dataclass
class TickerAccuracyEntry:
    ticker: str
    sector: Optional[str]
    verdict_at_publish: str
    fv_at_publish: float
    price_at_publish: float
    mos_at_publish: float
    price_30d_later: Optional[float]
    actual_return_pct: Optional[float]
    direction_correct: Optional[bool]
    abs_error_pct: Optional[float]


@dataclass
class MonthlyAccuracyReport:
    report_month: str
    total_verdicts_published: int
    coverage_count: int
    direction_accuracy_pct: float
    median_abs_error_pct: float
    top_5_winners: list[TickerAccuracyEntry] = field(default_factory=list)
    top_5_misses: list[TickerAccuracyEntry] = field(default_factory=list)
    by_sector_summary: dict[str, dict] = field(default_factory=dict)
    by_verdict_summary: dict[str, dict] = field(default_factory=dict)
    generated_at: str = ""


# ─────────────────────────────────────────────────────────────────
# Small helpers
# ─────────────────────────────────────────────────────────────────
def _safe_float(x) -> Optional[float]:
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _median(xs: Sequence[float]) -> Optional[float]:
    if not xs:
        return None
    s = sorted(xs)
    n = len(s)
    mid = n // 2
    if n % 2 == 1:
        return round(s[mid], 4)
    return round((s[mid - 1] + s[mid]) / 2.0, 4)


def _month_bounds(month_year: str) -> tuple[date, date]:
    """Parse "YYYY-MM" → (first_day, first_day_of_next_month)."""
    parts = month_year.split("-")
    if len(parts) != 2:
        raise ValueError(f"month_year must be 'YYYY-MM', got {month_year!r}")
    year = int(parts[0])
    month = int(parts[1])
    if month < 1 or month > 12:
        raise ValueError(f"invalid month: {month}")
    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1)
    else:
        end = date(year, month + 1, 1)
    return start, end


def _direction_correct(verdict: str, ret_pct: float) -> bool:
    """Did the verdict's implied direction match the actual 30d return?"""
    v = (verdict or "").strip().lower()
    if v == "undervalued":
        return ret_pct > DIR_BELOW_THRESHOLD
    if v == "overvalued":
        return ret_pct < DIR_ABOVE_THRESHOLD
    if v == "fairly_valued":
        return abs(ret_pct) <= DIR_NEAR_BAND
    # Unknown verdicts (e.g. "data_limited") are never "correct" —
    # we report them in coverage but they don't get scored.
    return False


def _is_scorable_verdict(verdict: str) -> bool:
    v = (verdict or "").strip().lower()
    return v in ("undervalued", "fairly_valued", "overvalued")


# ─────────────────────────────────────────────────────────────────
# Raw row shape (returned by the data provider)
# ─────────────────────────────────────────────────────────────────
#   {
#     "ticker":          str,         # bare, no .NS
#     "sector":          str | None,
#     "verdict":         str,         # undervalued/fairly_valued/overvalued/...
#     "fair_value":      float,
#     "price":           float,       # close on publish date
#     "mos_pct":         float,
#     "publish_date":    date,
#     "price_30d_later": float | None,
#   }
DataProvider = Callable[[date, date], list[dict]]


def _default_data_provider(start: date, end: date) -> list[dict]:
    """Query the pipeline DB for FV publishes in [start, end) and join
    forward 30 days to daily_prices.

    Returns [] when the DB session can't be opened — the report
    becomes the empty-report shape, not a crash.
    """
    try:
        from data_pipeline.db import Session  # type: ignore
    except Exception as exc:  # pragma: no cover — import-time path
        log.warning("data_pipeline.db unavailable: %s", exc)
        return []
    if Session is None:  # pragma: no cover
        log.warning("data_pipeline.db.Session is None")
        return []

    from sqlalchemy import text

    try:
        sess = Session()
    except Exception as exc:  # pragma: no cover
        log.warning("cannot open pipeline session: %s", exc)
        return []

    try:
        # Two-step query:
        #   1. Every fair_value_history row published in [start, end).
        #      We take ONE row per (ticker, publish_date) — the latest
        #      updated_at — to avoid double-counting same-day rewrites.
        #   2. Per-row: closest close_price within
        #      [publish_date+30d, publish_date+30d+slack].
        # The sector join is best-effort: if stocks.ticker is missing
        # the row still appears, with sector=None.
        rows = sess.execute(
            text(
                """
                SELECT DISTINCT ON (fvh.ticker, fvh.date)
                       fvh.ticker,
                       s.sector AS sector,
                       fvh.verdict,
                       fvh.fair_value,
                       fvh.price,
                       fvh.mos_pct,
                       fvh.date AS publish_date
                FROM fair_value_history fvh
                LEFT JOIN stocks s ON s.ticker = fvh.ticker
                WHERE fvh.date >= :start
                  AND fvh.date <  :end
                  AND fvh.fair_value IS NOT NULL
                  AND fvh.price IS NOT NULL
                  AND fvh.price > 0
                ORDER BY fvh.ticker, fvh.date, fvh.updated_at DESC
                """
            ),
            {"start": start, "end": end},
        ).fetchall()
    except Exception as exc:
        log.warning("FV-history query failed for %s..%s: %s", start, end, exc)
        try:
            sess.close()
        except Exception:
            pass
        return []

    out: list[dict] = []
    for r in rows:
        ticker = (r[0] or "").strip()
        if not ticker:
            continue
        try:
            sector = r[1]
            verdict = (r[2] or "").strip()
            fv = float(r[3])
            price = float(r[4])
            mos = float(r[5]) if r[5] is not None else 0.0
            publish_date = r[6]
        except (TypeError, ValueError):
            continue

        # Forward 30d close lookup. We accept the closest trade_date
        # within [+30d, +30d+slack] so weekend/holiday alignment
        # doesn't kill coverage.
        target = publish_date + timedelta(days=LOOKBACK_DAYS)
        floor = target
        ceiling = target + timedelta(days=PRICE_LOOKUP_SLACK_DAYS)
        try:
            fwd_row = sess.execute(
                text(
                    """
                    SELECT close_price
                      FROM daily_prices
                     WHERE ticker IN (:bare, :with_ns)
                       AND trade_date >= :floor
                       AND trade_date <= :ceiling
                       AND close_price IS NOT NULL
                       AND close_price > 0
                     ORDER BY trade_date ASC
                     LIMIT 1
                    """
                ),
                {
                    "bare": ticker,
                    "with_ns": f"{ticker}.NS",
                    "floor": floor,
                    "ceiling": ceiling,
                },
            ).fetchone()
        except Exception as exc:
            log.debug("forward-price lookup failed for %s: %s", ticker, exc)
            fwd_row = None

        price_30d = None
        if fwd_row is not None and fwd_row[0] is not None:
            try:
                price_30d = float(fwd_row[0])
                if price_30d <= 0:
                    price_30d = None
            except (TypeError, ValueError):
                price_30d = None

        out.append(
            {
                "ticker": ticker,
                "sector": sector,
                "verdict": verdict,
                "fair_value": fv,
                "price": price,
                "mos_pct": mos,
                "publish_date": publish_date,
                "price_30d_later": price_30d,
            }
        )

    try:
        sess.close()
    except Exception:
        pass
    return out


# ─────────────────────────────────────────────────────────────────
# Core compute
# ─────────────────────────────────────────────────────────────────
def _build_entry(row: dict) -> TickerAccuracyEntry:
    """Turn one raw row into a TickerAccuracyEntry with derived stats."""
    ticker = str(row.get("ticker") or "").strip()
    sector = row.get("sector")
    verdict = str(row.get("verdict") or "").strip()
    fv = _safe_float(row.get("fair_value")) or 0.0
    price = _safe_float(row.get("price")) or 0.0
    mos = _safe_float(row.get("mos_pct")) or 0.0
    price_30d = _safe_float(row.get("price_30d_later"))

    actual_return: Optional[float] = None
    direction_correct: Optional[bool] = None
    abs_error: Optional[float] = None

    if price_30d is not None and price > 0:
        actual_return = round((price_30d - price) / price * 100.0, 4)
        if _is_scorable_verdict(verdict):
            direction_correct = _direction_correct(verdict, actual_return)
        if price_30d > 0:
            abs_error = round(abs(fv - price_30d) / price_30d * 100.0, 4)

    return TickerAccuracyEntry(
        ticker=ticker,
        sector=sector,
        verdict_at_publish=verdict,
        fv_at_publish=round(fv, 4),
        price_at_publish=round(price, 4),
        mos_at_publish=round(mos, 4),
        price_30d_later=round(price_30d, 4) if price_30d is not None else None,
        actual_return_pct=actual_return,
        direction_correct=direction_correct,
        abs_error_pct=abs_error,
    )


def _bucket_summary(entries: Iterable[TickerAccuracyEntry], key_fn) -> dict[str, dict]:
    """Group entries by a string key and produce {coverage, direction_acc, median_err}."""
    bucket: dict[str, list[TickerAccuracyEntry]] = {}
    for e in entries:
        k = key_fn(e)
        if not k:
            continue
        bucket.setdefault(str(k), []).append(e)

    out: dict[str, dict] = {}
    for k, items in bucket.items():
        scored = [i for i in items if i.direction_correct is not None]
        errors = [i.abs_error_pct for i in items if i.abs_error_pct is not None]
        coverage = sum(1 for i in items if i.price_30d_later is not None)
        if scored:
            correct = sum(1 for i in scored if i.direction_correct is True)
            direction_acc = round(correct / len(scored) * 100.0, 2)
        else:
            direction_acc = 0.0
        out[k] = {
            "total": len(items),
            "coverage": coverage,
            "direction_accuracy_pct": direction_acc,
            "median_abs_error_pct": _median(errors) or 0.0,
        }
    return out


def _winner_score(e: TickerAccuracyEntry) -> float:
    """Rank correct-direction calls by magnitude of the right move."""
    if e.direction_correct is not True or e.actual_return_pct is None:
        return -1.0
    v = (e.verdict_at_publish or "").lower()
    if v == "undervalued":
        return float(e.actual_return_pct)             # bigger up = better
    if v == "overvalued":
        return float(-e.actual_return_pct)            # bigger down = better
    if v == "fairly_valued":
        # Tighter to zero = better. Map onto [0..]: small |return| → high score.
        return float(DIR_NEAR_BAND - abs(e.actual_return_pct))
    return -1.0


def _miss_score(e: TickerAccuracyEntry) -> float:
    """Rank misses by "how badly wrong" — wrong direction first, then
    magnitude of error.
    """
    if e.actual_return_pct is None:
        return -1.0
    v = (e.verdict_at_publish or "").lower()
    # Wrong-direction calls dominate magnitude misses.
    if e.direction_correct is False:
        if v == "undervalued":
            # Predicted up, went down: more down = worse miss.
            return 100.0 + abs(e.actual_return_pct)
        if v == "overvalued":
            return 100.0 + abs(e.actual_return_pct)
        if v == "fairly_valued":
            return 100.0 + (abs(e.actual_return_pct) - DIR_NEAR_BAND)
    # Direction correct or unscored — fall back to magnitude error.
    return float(e.abs_error_pct or 0.0)


def compute_monthly_accuracy(
    month_year: str,
    data_provider: Optional[DataProvider] = None,
) -> MonthlyAccuracyReport:
    """Pull all FV publishes in the given month and produce the
    accuracy report.

    Parameters
    ----------
    month_year
        "YYYY-MM" — the calendar month to analyze.
    data_provider
        Callable(start_date, end_date_exclusive) returning the raw
        row dicts (see ``DataProvider`` typedef). When None, uses
        the default Postgres-backed provider. Tests inject a list
        provider so this function stays pure.

    Returns
    -------
    MonthlyAccuracyReport
        Always returns a fully-populated dataclass — never raises
        on missing data, never returns None. The empty-month case
        yields zero metrics and empty lists.
    """
    start, end = _month_bounds(month_year)
    provider = data_provider or _default_data_provider
    raw_rows = list(provider(start, end))

    entries = [_build_entry(r) for r in raw_rows]
    # Filter out rows we couldn't even parse a ticker for.
    entries = [e for e in entries if e.ticker]

    total = len(entries)
    coverage = sum(1 for e in entries if e.price_30d_later is not None)
    scored = [e for e in entries if e.direction_correct is not None]
    correct = sum(1 for e in scored if e.direction_correct is True)
    direction_acc_pct = round(correct / len(scored) * 100.0, 2) if scored else 0.0

    errors = [e.abs_error_pct for e in entries if e.abs_error_pct is not None]
    median_err = _median(errors) or 0.0

    # Top winners: correct direction, sorted by magnitude.
    correct_entries = [e for e in entries if e.direction_correct is True]
    correct_entries.sort(key=_winner_score, reverse=True)
    top_winners = correct_entries[:5]

    # Top misses: wrong direction first, then high magnitude error.
    miss_candidates = [e for e in entries if e.actual_return_pct is not None]
    miss_candidates.sort(key=_miss_score, reverse=True)
    top_misses = miss_candidates[:5]

    by_sector = _bucket_summary(entries, lambda e: e.sector)
    by_verdict = _bucket_summary(entries, lambda e: e.verdict_at_publish)

    return MonthlyAccuracyReport(
        report_month=month_year,
        total_verdicts_published=total,
        coverage_count=coverage,
        direction_accuracy_pct=direction_acc_pct,
        median_abs_error_pct=median_err,
        top_5_winners=top_winners,
        top_5_misses=top_misses,
        by_sector_summary=by_sector,
        by_verdict_summary=by_verdict,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


# ─────────────────────────────────────────────────────────────────
# Serialization
# ─────────────────────────────────────────────────────────────────
def to_dict(report: MonthlyAccuracyReport) -> dict:
    """JSON-safe representation. dataclasses.asdict handles the nested
    TickerAccuracyEntry lists for us — every field is a primitive,
    list, or dict by construction.
    """
    return asdict(report)


def to_markdown(report: MonthlyAccuracyReport) -> str:
    """Operator-facing markdown. NOT shown to anon users; safe to
    include internal verdict vocabulary. Used in the cron's email
    body and as the body of the /calibration snapshot file.
    """
    lines: list[str] = []
    lines.append(f"# YieldIQ Monthly Accuracy Report — {report.report_month}")
    lines.append("")
    lines.append(f"_Generated: {report.generated_at}_")
    lines.append("")
    lines.append("## Headline")
    lines.append("")
    lines.append(f"- Verdicts published: **{report.total_verdicts_published}**")
    lines.append(f"- 30-day forward coverage: **{report.coverage_count}**")
    lines.append(f"- Direction accuracy: **{report.direction_accuracy_pct}%**")
    lines.append(f"- Median |FV − price_30d| / price_30d: **{report.median_abs_error_pct}%**")
    lines.append("")

    if report.by_verdict_summary:
        lines.append("## By verdict")
        lines.append("")
        lines.append("| Verdict | Total | Coverage | Direction acc. | Median err. |")
        lines.append("|---|---:|---:|---:|---:|")
        for v in sorted(report.by_verdict_summary.keys()):
            d = report.by_verdict_summary[v]
            lines.append(
                f"| {v} | {d['total']} | {d['coverage']} | "
                f"{d['direction_accuracy_pct']}% | {d['median_abs_error_pct']}% |"
            )
        lines.append("")

    if report.by_sector_summary:
        lines.append("## By sector")
        lines.append("")
        lines.append("| Sector | Total | Coverage | Direction acc. | Median err. |")
        lines.append("|---|---:|---:|---:|---:|")
        # Sort by total verdicts published, desc — biggest sector first.
        ranked = sorted(
            report.by_sector_summary.items(),
            key=lambda kv: kv[1]["total"],
            reverse=True,
        )
        for sec, d in ranked:
            lines.append(
                f"| {sec} | {d['total']} | {d['coverage']} | "
                f"{d['direction_accuracy_pct']}% | {d['median_abs_error_pct']}% |"
            )
        lines.append("")

    if report.top_5_winners:
        lines.append("## Top 5 correct-direction calls")
        lines.append("")
        lines.append("| Ticker | Verdict | Return (30d) | FV | Price→Price30d |")
        lines.append("|---|---|---:|---:|---|")
        for e in report.top_5_winners:
            r = "—" if e.actual_return_pct is None else f"{e.actual_return_pct}%"
            p30 = "—" if e.price_30d_later is None else f"{e.price_30d_later}"
            lines.append(
                f"| {e.ticker} | {e.verdict_at_publish} | {r} | "
                f"{e.fv_at_publish} | {e.price_at_publish} → {p30} |"
            )
        lines.append("")

    if report.top_5_misses:
        lines.append("## Top 5 misses")
        lines.append("")
        lines.append("| Ticker | Verdict | Return (30d) | FV | Price→Price30d | Dir? |")
        lines.append("|---|---|---:|---:|---|:-:|")
        for e in report.top_5_misses:
            r = "—" if e.actual_return_pct is None else f"{e.actual_return_pct}%"
            p30 = "—" if e.price_30d_later is None else f"{e.price_30d_later}"
            dc = "y" if e.direction_correct is True else ("n" if e.direction_correct is False else "—")
            lines.append(
                f"| {e.ticker} | {e.verdict_at_publish} | {r} | "
                f"{e.fv_at_publish} | {e.price_at_publish} → {p30} | {dc} |"
            )
        lines.append("")

    if report.total_verdicts_published == 0:
        lines.append("")
        lines.append("_No verdicts were published in this month — nothing to score._")
        lines.append("")

    return "\n".join(lines)
