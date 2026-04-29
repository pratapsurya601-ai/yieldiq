"""scripts/resolve_prev_quarter.py

Resolve the just-closed Indian fiscal quarter for a given date.

Indian fiscal year runs Apr 1 → Mar 31. FY26 = Apr 2025 – Mar 2026.
The publication cron fires on Aug 1 / Nov 1 / Feb 1 / May 1, one
month after the close of each quarter.

  Aug 1, 2026 → Q1FY27 just closed (Apr 2026 – Jun 2026)
  Nov 1, 2026 → Q2FY27 just closed (Jul 2026 – Sep 2026)
  Feb 1, 2027 → Q3FY27 just closed (Oct 2026 – Dec 2026)
  May 1, 2027 → Q4FY27 just closed (Jan 2027 – Mar 2027)

Usage::

    python scripts/resolve_prev_quarter.py
    python scripts/resolve_prev_quarter.py --as-of 2026-08-01
    python scripts/resolve_prev_quarter.py --as-of 2026-08-01 --format json
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, asdict
from datetime import date, timedelta


@dataclass
class QuarterInfo:
    """Just-closed Indian fiscal quarter info."""

    label: str          # e.g. "Q1FY27"
    fiscal_year: int    # 27 for FY27 (i.e. Apr 2026 – Mar 2027)
    quarter: int        # 1..4
    start: str          # ISO date
    end: str            # ISO date (inclusive)


def _fy_label(fy_two_digit: int) -> str:
    return f"FY{fy_two_digit:02d}"


def resolve_prev_quarter(as_of: date) -> QuarterInfo:
    """Return the most recently CLOSED Indian fiscal quarter as of `as_of`.

    Convention: a quarter is "closed" once we have moved past its last day
    AND we have at least 30 more days for outcome data to settle. In
    practice the publication cron fires on the 1st of the month one month
    after close (Aug 1 / Nov 1 / Feb 1 / May 1). For any `as_of`, we walk
    back to find the quarter whose end date is at least 30 days behind us.
    """
    y = as_of.year

    # Quarter ranges in calendar terms; FY of each is computed below.
    # Q1: Apr-Jun, Q2: Jul-Sep, Q3: Oct-Dec, Q4: Jan-Mar.
    candidates = [
        (date(y, 1, 1),  date(y, 3, 31), 4, y % 100),         # Q4 of FY ending this Mar
        (date(y, 4, 1),  date(y, 6, 30), 1, (y + 1) % 100),   # Q1 of FY ending next Mar
        (date(y, 7, 1),  date(y, 9, 30), 2, (y + 1) % 100),
        (date(y, 10, 1), date(y, 12, 31), 3, (y + 1) % 100),
        # Also include last year's Q3/Q4 for early-year as_of dates
        (date(y - 1, 10, 1), date(y - 1, 12, 31), 3, y % 100),
        (date(y - 1, 7, 1),  date(y - 1, 9, 30),  2, y % 100),
    ]

    # Pick the most recent end-date that is >= 30 days before as_of.
    closed = [
        (s, e, q, fy) for (s, e, q, fy) in candidates
        if (as_of - e) >= timedelta(days=30)
    ]
    if not closed:
        # Fallback: shouldn't happen, but be safe.
        s, e, q, fy = candidates[-1]
    else:
        closed.sort(key=lambda r: r[1], reverse=True)
        s, e, q, fy = closed[0]

    return QuarterInfo(
        label=f"Q{q}{_fy_label(fy)}",
        fiscal_year=fy,
        quarter=q,
        start=s.isoformat(),
        end=e.isoformat(),
    )


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--as-of", help="Date in YYYY-MM-DD (default: today UTC)")
    p.add_argument("--format", choices=["text", "json", "github"],
                   default="text",
                   help="text=human, json=parsable, github=GITHUB_OUTPUT lines")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    if args.as_of:
        as_of = date.fromisoformat(args.as_of)
    else:
        as_of = date.today()

    info = resolve_prev_quarter(as_of)

    if args.format == "json":
        print(json.dumps(asdict(info), indent=2))
    elif args.format == "github":
        # Emit GITHUB_OUTPUT-style lines for cron workflow consumption.
        print(f"quarter={info.label}")
        print(f"start={info.start}")
        print(f"end={info.end}")
    else:
        print(
            f"As of {as_of.isoformat()}, the just-closed Indian fiscal "
            f"quarter is:\n"
            f"  --quarter {info.label}\n"
            f"  range: {info.start} -> {info.end}\n"
            f"  (FY={info.fiscal_year}, Q={info.quarter})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
