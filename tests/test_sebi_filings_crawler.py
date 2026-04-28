"""Tests for the SEBI filings crawler scaffolding.

We do not depend on Postgres for these tests — they construct an
in-memory SQLite that mimics the schema from
data_pipeline/migrations/018_sebi_filings_queue.sql closely enough to
exercise enqueue / process state transitions and idempotency.

If the Postgres-flavoured production code changes shape (e.g. ON
CONFLICT clause), this test will need to be re-mapped — that's
acceptable: the test's job is to lock the *behavior* (idempotency,
state transitions), not the SQL dialect.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.workers import sebi_filings_crawler as crawler  # noqa: E402


FIXTURE = ROOT / "tests" / "fixtures" / "sample_sebi_filings.json"


# ---------------------------------------------------------------------------
# SQLite shim so the tests run without a Postgres dependency
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE sebi_filings_queue (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  ticker          TEXT NOT NULL,
  filing_type     TEXT NOT NULL,
  fiscal_period   TEXT,
  filing_date     TEXT NOT NULL,
  source_exchange TEXT NOT NULL,
  source_url      TEXT NOT NULL,
  pdf_url         TEXT,
  xbrl_url        TEXT,
  status          TEXT DEFAULT 'pending',
  ingested_at     TEXT,
  error_message   TEXT,
  retry_count     INTEGER DEFAULT 0,
  detected_at     TEXT DEFAULT (datetime('now')),
  UNIQUE (ticker, filing_type, fiscal_period, source_exchange)
);
"""

# enqueue_filing / process_pending issue Postgres-flavored SQL. We
# monkey-patch the cursor.execute so the same call site works against
# sqlite (placeholder + UPSERT translation).
def _translate(sql: str) -> str:
    s = sql.replace("%s", "?")
    # crude rewrite for ON CONFLICT ... DO UPDATE — sqlite supports it
    # too but uses excluded.col not EXCLUDED.col. The crawler text
    # already uses EXCLUDED, so lowercase it.
    s = s.replace("EXCLUDED.", "excluded.")
    # Replace NOW() with datetime('now') (sqlite).
    s = s.replace("NOW()", "datetime('now')")
    # CASE WHEN %s = 'failed' THEN 1 ELSE 0 END — leave as-is, valid sqlite
    return s


class _Cur:
    def __init__(self, real):
        self._real = real
    def execute(self, sql, params=()):
        return self._real.execute(_translate(sql), params)
    def fetchone(self):
        return self._real.fetchone()
    def fetchall(self):
        return self._real.fetchall()
    def close(self):
        return self._real.close()


class _Conn:
    def __init__(self, sqlite_conn):
        self._c = sqlite_conn
    def cursor(self):
        return _Cur(self._c.cursor())
    def commit(self):
        return self._c.commit()
    def rollback(self):
        return self._c.rollback()
    def close(self):
        return self._c.close()


@pytest.fixture()
def db():
    raw = sqlite3.connect(":memory:")
    raw.executescript(_SCHEMA)
    raw.commit()
    yield _Conn(raw)
    raw.close()


def _load_fixtures(db: _Conn) -> int:
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    cur = db.cursor()
    for row in raw:
        cur.execute(
            """
            INSERT INTO sebi_filings_queue
              (ticker, filing_type, fiscal_period, filing_date,
               source_exchange, source_url, pdf_url, xbrl_url, status)
            VALUES (?,?,?,?,?,?,?,?,?)
            """,
            (row["ticker"], row["filing_type"], row.get("fiscal_period"),
             row["filing_date"], row["source_exchange"], row["source_url"],
             row.get("pdf_url"), row.get("xbrl_url"), row.get("status", "pending")),
        )
    cur.close()
    db.commit()
    return len(raw)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_filing_metadata_validates():
    md = crawler.FilingMetadata(
        ticker="reliance",
        filing_type="quarterly_results",
        fiscal_period="Q4FY25",
        filing_date=date(2026, 4, 22),
        source_exchange="NSE",
        source_url="https://example/x",
    )
    assert md.ticker == "RELIANCE"

    with pytest.raises(ValueError):
        crawler.FilingMetadata(
            ticker="X", filing_type="bogus", filing_date=date.today(),
            source_exchange="NSE", source_url="u",
        )

    with pytest.raises(ValueError):
        crawler.FilingMetadata(
            ticker="X", filing_type="quarterly_results", filing_date=date.today(),
            source_exchange="LSE", source_url="u",
        )


def test_discover_is_a_stub():
    assert crawler.discover_new_filings(lookback_hours=24) == []
    with pytest.raises(ValueError):
        crawler.discover_new_filings(lookback_hours=0)


def test_url_helpers_format_dates():
    bse = crawler._bse_url_for(date(2026, 4, 1), date(2026, 4, 27))
    assert "20260401" in bse and "20260427" in bse
    nse = crawler._nse_url_for(date(2026, 4, 1), date(2026, 4, 27))
    assert "01-04-2026" in nse and "27-04-2026" in nse


def test_enqueue_inserts_and_is_idempotent(db):
    md = crawler.FilingMetadata(
        ticker="RELIANCE",
        filing_type="quarterly_results",
        fiscal_period="Q4FY25",
        filing_date=date(2026, 4, 22),
        source_exchange="NSE",
        source_url="https://nse/u",
        xbrl_url="https://nse/x.xml",
    )

    rid1 = crawler.enqueue_filing(md, conn=db)
    db.commit()
    rid2 = crawler.enqueue_filing(md, conn=db)
    db.commit()

    assert rid1 == rid2  # same row — UPSERT, not duplicate insert

    cur = db.cursor()
    cur.execute("SELECT COUNT(*) FROM sebi_filings_queue")
    (n,) = cur.fetchone()
    cur.close()
    assert n == 1


def test_process_pending_walks_state(db):
    inserted = _load_fixtures(db)
    assert inserted == 15

    cur = db.cursor()
    cur.execute("SELECT COUNT(*) FROM sebi_filings_queue WHERE status='pending'")
    (pending_before,) = cur.fetchone()
    cur.close()
    assert pending_before > 0

    counters = crawler.process_pending(limit=50, conn=db)
    db.commit()

    assert counters["processed"] == pending_before
    # Of the pending fixtures: those with xbrl_url should be ingested,
    # those without should be skipped (PDF path is stubbed).
    assert counters["ingested"] >= 1
    assert counters["skipped"] >= 1
    assert counters["failed"] == 0

    cur = db.cursor()
    cur.execute("SELECT COUNT(*) FROM sebi_filings_queue WHERE status='pending'")
    (pending_after,) = cur.fetchone()
    cur.close()
    assert pending_after == 0


def test_process_pending_dry_run_changes_nothing(db):
    _load_fixtures(db)
    counters = crawler.process_pending(limit=50, conn=db, dry_run=True)
    assert counters["processed"] >= 1
    assert counters["ingested"] == 0
    assert counters["failed"] == 0

    cur = db.cursor()
    cur.execute("SELECT COUNT(*) FROM sebi_filings_queue WHERE status='pending'")
    (pending_after,) = cur.fetchone()
    cur.close()
    # Dry run must not transition rows.
    assert pending_after >= 1


def test_filing_alert_service_is_safe_dry_run():
    from backend.services.filing_alert_service import notify_users_of_new_quarterly
    res = notify_users_of_new_quarterly("RELIANCE", "Q4FY25", dry_run=True)
    assert res.ticker == "RELIANCE"
    assert res.dry_run is True
    assert res.notified_user_count == 0  # stub returns no eligible users
