"""Phase I-frontend (2026-05-26) -- banks router tests.

Covers the GET /api/v1/banks/{ticker}/kpis endpoint without
requiring a live Postgres -- the connection layer is monkey-
patched to a fake psycopg2-like connection. Async endpoints
are driven via asyncio.run to avoid a hard pytest-asyncio dep.
"""
from __future__ import annotations

import asyncio
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from backend.routers import banks as banks_router  # noqa: E402


def _call(coro):
    return asyncio.get_event_loop().run_until_complete(coro) \
        if False else asyncio.run(coro)


class _FakeCursor:
    def __init__(self, conn: "_FakeConn"):
        self._conn = conn
        self._last = None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):  # noqa: D401
        scripted = self._conn._scripted  # noqa: SLF001
        idx = self._conn._idx            # noqa: SLF001
        if idx >= len(scripted):
            self._last = []
        else:
            self._last = scripted[idx]
        self._conn._idx = idx + 1        # noqa: SLF001

    def fetchone(self):
        return self._last[0] if self._last else None

    def fetchall(self):
        return list(self._last or [])


class _FakeConn:
    def __init__(self, scripted: list):
        self._scripted = scripted
        self._idx = 0
        self.closed = False

    def cursor(self):
        return _FakeCursor(self)

    def close(self):
        self.closed = True


def _patch_conn(monkeypatch, scripted):
    fake = _FakeConn(scripted)
    monkeypatch.setattr(banks_router, "_connect", lambda: fake)
    return fake


# ---------- endpoint tests --------------------------------------------------

def test_non_bank_returns_is_bank_false_no_db(monkeypatch):
    called = {"hit": False}

    def _should_not_call():
        called["hit"] = True
        return None
    monkeypatch.setattr(banks_router, "_connect", _should_not_call)

    out = _call(banks_router.get_bank_kpis("RELIANCE"))
    assert out["is_bank"] is False
    assert out["latest_annual"] is None
    assert out["quarterly_trend"] == {
        m: [] for m in banks_router._QUARTERLY_METRICS  # noqa: SLF001
    }
    assert called["hit"] is False


def test_bank_with_no_db_returns_empty_payload(monkeypatch):
    monkeypatch.setattr(banks_router, "_connect", lambda: None)
    out = _call(banks_router.get_bank_kpis("HDFCBANK"))
    assert out["is_bank"] is True
    assert out["latest_annual"] is None


def test_bank_with_data_returns_merged_snapshot_and_trend(monkeypatch):
    pe_annual = date(2024, 3, 31)

    bse_row = (
        None, None, None, None,
        None, None,
        1.20, 0.30, 72.5,
        38.0, 40.1, 87.0,
        "bse_xbrl",
    )
    ar_row = (
        7821, 3100, 2700, 2021,
        19500, 92.0,
        None, None, None,
        None, None, None,
        "ar_anthropic",
    )
    quarterly_rows = [
        (date(2024, 12, 31), "bse_xbrl", 1.10, 0.25, 72.0, 37.5, 40.0, 86.5),
        (date(2024, 9, 30),  "bse_xbrl", 1.15, 0.28, 71.5, 38.0, 40.2, 86.8),
        (date(2024, 6, 30),  "bse_xbrl", 1.18, 0.29, 71.0, 38.2, 40.3, 87.0),
    ]
    scripted = [
        [(pe_annual,)],
        [bse_row, ar_row],
        quarterly_rows,
    ]
    _patch_conn(monkeypatch, scripted)

    out = _call(banks_router.get_bank_kpis("HDFCBANK"))

    assert out["is_bank"] is True
    la = out["latest_annual"]
    assert la["branches_total"] == 7821
    assert la["atms_total"] == 19500
    assert la["customers_millions"] == pytest.approx(92.0)
    assert la["gnpa_pct"] == pytest.approx(1.20)
    assert la["pcr_pct"] == pytest.approx(72.5)
    assert la["period_end"] == "2024-03-31"
    assert set(la["sources"]) == {"bse_xbrl", "ar_anthropic"}

    gnpa = out["quarterly_trend"]["gnpa_pct"]
    assert [pt["period_end"] for pt in gnpa] == [
        "2024-12-31", "2024-09-30", "2024-06-30",
    ]
    assert gnpa[0]["value"] == pytest.approx(1.10)


def test_bank_falls_back_to_quarterly_when_no_annual(monkeypatch):
    bse_q_row = (
        None, None, None, None,
        None, None,
        1.10, 0.25, 72.0, 37.5, 40.0, 86.5,
        "bse_xbrl",
    )
    scripted = [
        [(None,)],
        [(date(2024, 12, 31),)],
        [bse_q_row],
        [],
    ]
    _patch_conn(monkeypatch, scripted)

    out = _call(banks_router.get_bank_kpis("AXISBANK"))
    assert out["is_bank"] is True
    assert out["latest_annual"] is not None
    assert out["latest_annual"]["period_type"] == "quarterly"
    assert out["latest_annual"]["gnpa_pct"] == pytest.approx(1.10)


# ---------- pure helpers ---------------------------------------------------

def test_bare_ticker_strips_suffixes():
    assert banks_router._bare_ticker("HDFCBANK.NS") == "HDFCBANK"  # noqa: SLF001
    assert banks_router._bare_ticker("hdfcbank.bo") == "HDFCBANK"  # noqa: SLF001
    assert banks_router._bare_ticker("HDFCBANK") == "HDFCBANK"     # noqa: SLF001
    assert banks_router._bare_ticker("") == ""                     # noqa: SLF001


def test_is_pure_bank_matches_sector_overrides():
    assert banks_router._is_pure_bank("HDFCBANK") is True   # noqa: SLF001
    assert banks_router._is_pure_bank("SBIN") is True       # noqa: SLF001
    assert banks_router._is_pure_bank("RELIANCE") is False  # noqa: SLF001
