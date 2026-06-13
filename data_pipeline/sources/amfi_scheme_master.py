"""AMFI scheme master ingest.

Source: https://portal.amfiindia.com/spages/NAVAll.txt
        (used both for daily NAV and as the de-facto scheme master —
        AMFI does not publish a separate machine-readable master;
        the SchemeData CSV requires a session token. Parsing the
        scheme list out of NAVAll is the standard pragmatic approach.)

This module populates the `funds` table from the same AMFI feed that
amfi_nav.py reads. It runs weekly (Sunday 06:00 IST) and:

    1. Pulls the current NAVAll snapshot.
    2. For each scheme row, parses the scheme_name into structured
       plan (Direct/Regular) + option (Growth/IDCW/IDCW-Reinvest).
    3. Upserts to `funds` keyed on scheme_code.
    4. Soft-deactivates schemes that have disappeared from the feed
       (is_active = FALSE), preserving historical NAV rows.

Naming is messy — there is no AMFI-mandated format. Observed shapes:

    HDFC Mid-Cap Opportunities Fund - Direct Plan - Growth
    Axis Bluechip Fund - Regular Plan (IDCW)
    SBI Magnum Children Benefit Fund - Investment Plan - Direct - IDCW Reinvestment
    Mirae Asset Large Cap Fund Direct Growth
    Nippon India Small Cap Fund - Growth Plan          (= legacy Regular)

Heuristics in parse_plan_option:
    * "Direct" anywhere → Direct; else Regular (Regular is the
      AMFI default when not specified, matching SEBI 2018 rules).
    * "IDCW Reinvest" / "IDCW-Reinvest" / "Reinvestment" → IDCW-Reinvest
    * "IDCW" / "Dividend" / "Div" → IDCW
    * Otherwise → Growth (NAVAll only carries the growth/IDCW split;
      schemes that exist only as Growth fall through cleanly).

The category, sub_category, benchmark_index_code, inception_date, and
riskometer_level columns are NOT populated by this module — they are
operator-curated (top-500 in Phase 1) or scraped from AMC factsheets
in Phase 4.
"""
from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from typing import Iterable, Iterator

from data_pipeline.sources.amfi_nav import (
    fetch_navall_text,
    parse_navall,
)

logger = logging.getLogger(__name__)


# ── Name parsing ─────────────────────────────────────────────────────


_DIRECT_RE = re.compile(r"\bdirect\b", re.IGNORECASE)
_REGULAR_RE = re.compile(r"\bregular\b", re.IGNORECASE)
_IDCW_REINVEST_RE = re.compile(
    r"\b(idcw[\s_-]*reinvest|reinvest(?:ment)?|reinv)\b",
    re.IGNORECASE,
)
_IDCW_RE = re.compile(r"\b(idcw|dividend|div\.?(?:\s|$))\b", re.IGNORECASE)


def parse_plan_option(scheme_name: str) -> tuple[str, str]:
    """Return (plan, option) parsed out of an AMFI scheme name.

    plan   ∈ {'Direct', 'Regular'}        — Regular is the default when
                                            "Direct" is absent (matches
                                            SEBI 2018 default-plan rule).
    option ∈ {'Growth', 'IDCW', 'IDCW-Reinvest'}
                                          — Growth is the default when
                                            no payout/reinvest token is
                                            present.

    Designed to be robust to AMFI's inconsistent formatting (different
    AMCs use different separators, capitalization, and ordering). See
    the module docstring for observed name shapes.
    """
    if not scheme_name:
        return ("Regular", "Growth")
    name = scheme_name

    # Plan
    if _DIRECT_RE.search(name):
        plan = "Direct"
    else:
        plan = "Regular"

    # Option — check Reinvest BEFORE plain IDCW because the IDCW
    # regex is a subset of the Reinvest regex.
    if _IDCW_REINVEST_RE.search(name):
        option = "IDCW-Reinvest"
    elif _IDCW_RE.search(name):
        option = "IDCW"
    else:
        option = "Growth"

    return (plan, option)


# ── Persistence ─────────────────────────────────────────────────────


# Neither AMC nor category are in the per-row NAVAll data — both are
# section headers above each block. amfi_nav.parse_navall ignores
# section headers; we re-parse here capturing the two header kinds so
# funds.amc AND funds.category land populated.
#
# In NAVAll the block separators (lines with no ';') are two kinds:
#   * Category header — e.g. "Open Ended Schemes(Equity Scheme - Large
#     Cap Fund)". No "Mutual Fund"; carries the SEBI category in parens.
#   * AMC banner — e.g. "Aditya Birla Sun Life Mutual Fund". Contains
#     "Mutual Fund".
# The category header precedes the AMC banner(s) it applies to, so we
# carry the most-recently-seen value of each forward onto scheme rows.

# Pull the SEBI category out of a header line's outermost parentheses,
# e.g. "Open Ended Schemes(Equity Scheme - Large Cap Fund)" ->
# "Equity Scheme - Large Cap Fund".
_CATEGORY_RE = re.compile(r"\((.+)\)")


def iter_scheme_master_rows(text: str) -> Iterator[dict]:
    """Yield one dict per scheme row WITH amc AND category populated.

    Walks the NAVAll text in order, tracking the most recently seen
    AMC banner ("... Mutual Fund") and category header (the
    parenthetical SEBI category). Both are no-';'/no-pipe lines.
    """
    current_amc: str | None = None
    current_category: str | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if ";" not in line:
            # Block separator: AMC banner OR category header.
            if "Mutual Fund" in line:
                current_amc = line
            else:
                m = _CATEGORY_RE.search(line)
                if m:
                    current_category = m.group(1).strip() or None
            continue
        # Hand off to the existing single-line parser via a tiny
        # iterable so we reuse its column-count / scheme-code /
        # date validation. parse_navall yields zero or one rows for
        # a single-line input.
        for row in parse_navall(line):
            plan, option = parse_plan_option(row["scheme_name"])
            yield {
                "scheme_code":  row["scheme_code"],
                "isin_growth":  row["isin_growth"],
                "isin_div":     row["isin_div"],
                "scheme_name":  row["scheme_name"],
                "amc":          current_amc or "Unknown",
                "category":     current_category,
                "plan":         plan,
                "option":       option,
            }


# Batched via psycopg2.extras.execute_values: the VALUES list is filled
# in with one row-group per scheme, so the whole ~14k-row master lands in
# a handful of multi-row INSERTs instead of 14k single-row round-trips.
# (The row-by-row executemany this replaced blew the workflow's
# 15-minute timeout against the remote DB — the weekly cron was being
# cancelled mid-run, so the master never refreshed.)
UPSERT_SQL = """
INSERT INTO funds (
    scheme_code, isin_growth, isin_div, scheme_name, amc,
    category, plan, option, is_active, updated_at
) VALUES %s
ON CONFLICT (scheme_code) DO UPDATE SET
    isin_growth = COALESCE(EXCLUDED.isin_growth, funds.isin_growth),
    isin_div    = COALESCE(EXCLUDED.isin_div,    funds.isin_div),
    scheme_name = EXCLUDED.scheme_name,
    amc         = EXCLUDED.amc,
    category    = COALESCE(EXCLUDED.category, funds.category),
    plan        = EXCLUDED.plan,
    option      = EXCLUDED.option,
    is_active   = TRUE,
    updated_at  = now()
"""

# Per-row template for execute_values. Named placeholders match the dict
# rows from iter_scheme_master_rows; TRUE / now() are per-row literals.
UPSERT_TEMPLATE = (
    "(%(scheme_code)s, %(isin_growth)s, %(isin_div)s, %(scheme_name)s, "
    "%(amc)s, %(category)s, %(plan)s, %(option)s, TRUE, now())"
)

# Schemes that were active last run but are absent this run get soft-
# deactivated. The historical NAV partitions are NOT touched — they
# stay queryable by scheme_code forever.
SOFT_DEACTIVATE_SQL = """
UPDATE funds
   SET is_active  = FALSE,
       updated_at = now()
 WHERE is_active = TRUE
   AND scheme_code NOT IN %(active_codes)s
"""


def _dedupe_last_by_scheme_code(rows: list[dict]) -> list[dict]:
    """Keep one row per scheme_code, last occurrence wins.

    scheme_code is AMFI's primary key so duplicates are not expected — but
    a single multi-row VALUES batch with ON CONFLICT DO UPDATE raises
    "cannot affect row a second time" if the same code appears twice in
    one page. Deduping makes the batched upsert robust to a malformed
    feed while preserving the per-row path's last-write-wins behaviour.
    """
    by_code: dict[str, dict] = {}
    for r in rows:
        by_code[r["scheme_code"]] = r
    return list(by_code.values())


def upsert_funds(rows: Iterable[dict], conn) -> tuple[int, int]:
    """Upsert each row to funds, then soft-deactivate missing schemes.

    Returns (upserted_count, deactivated_count).
    """
    rows = _dedupe_last_by_scheme_code(list(rows))
    if not rows:
        return (0, 0)
    # Lazy import so the parse-only path (and tests that import
    # iter_scheme_master_rows) don't require psycopg2 to be installed.
    from psycopg2.extras import execute_values

    active_codes = tuple(r["scheme_code"] for r in rows)
    with conn.cursor() as cur:
        # Batched multi-row upsert — see UPSERT_SQL for why this replaced
        # the row-by-row executemany (15-min workflow timeout).
        execute_values(
            cur, UPSERT_SQL, rows,
            template=UPSERT_TEMPLATE, page_size=1000,
        )
        # NOT IN () is a syntax error in psycopg2 if the tuple is
        # empty — guarded above by the rows-empty early return.
        cur.execute(SOFT_DEACTIVATE_SQL, {"active_codes": active_codes})
        deactivated = cur.rowcount
    conn.commit()
    return (len(rows), deactivated)


# ── CLI ─────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--url", default=None,
                   help="Override the AMFI NAVAll endpoint (test fixture).")
    p.add_argument("--dry-run", action="store_true",
                   help="Parse only; do not write to DB.")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.url:
        text = fetch_navall_text(args.url)
    else:
        text = fetch_navall_text()
    rows = list(iter_scheme_master_rows(text))
    logger.info("amfi_scheme_master: parsed %d schemes", len(rows))

    if args.dry_run:
        for r in rows[:5]:
            logger.info("sample: %s", r)
        return 0

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        logger.error("DATABASE_URL not set")
        return 2
    if db_url.startswith("postgres://"):
        db_url = "postgresql://" + db_url[len("postgres://"):]

    import psycopg2
    conn = psycopg2.connect(db_url)
    try:
        n_up, n_off = upsert_funds(rows, conn)
        logger.info(
            "amfi_scheme_master: upserted=%d soft_deactivated=%d",
            n_up, n_off,
        )
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
