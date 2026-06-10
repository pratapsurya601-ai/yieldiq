"""
test_screener_preset_relaxation.py — pin the 2026-06-11 P0 fix:

When the strict preset filter (e.g. score>=60 AND mos>=0 AND moat=='Wide'
for the `buffett` preset) returns ZERO candidates against the current
analysis cache, _query_preset_from_db now falls back to a relaxed pass
that progressively widens score, mos, and moat thresholds. The relax
pass signals the caller via the `last_relaxed` flag so the /home
Quant-Picks tile can render "Closest matches" instead of an empty 0.

Without this fix, the /home page showed Wide-Moat=0, Deep Value=0,
High-Margin Growers=0, Quality at a Discount=0 — all four tiles dead
because the strict gates excluded everything in the live cache.

We hermetically populate the in-memory cache_service so the test runs
without DB access (the analysis_cache PG tier is skipped via a try/
except path inside _query_preset_from_db itself, so cache-only test
fixtures are sufficient).
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def _make_fake_analysis(ticker: str, score: float, mos: float,
                        moat: str, rev_cagr: float | None = None,
                        data_limited: bool = False):
    """Build a stand-in object that quacks like a CachedAnalysis row.

    The screener tier-2 path accesses `.valuation`, `.quality`, and
    `.ticker` — nothing else. Using SimpleNamespace keeps the test
    fixture decoupled from the full pydantic CachedAnalysis schema.
    """
    valuation = SimpleNamespace(
        margin_of_safety=mos,
        current_price=1000.0,
        eps_ttm=50.0,
        data_limited=data_limited,
    )
    quality = SimpleNamespace(
        yieldiq_score=score,
        moat=moat,
        revenue_cagr_3y=rev_cagr,
    )
    return SimpleNamespace(
        ticker=ticker,
        valuation=valuation,
        quality=quality,
    )


def _seed(cache_obj, ticker: str, **kw):
    """Set a fixture row via the public cache.set() so the entry has
    the correct (value, expires_at, version) tuple shape. Writing
    directly to `_c._store` skips the version-stamping and produces
    rows that the version-check inside cache.get() invalidates on
    first read — the test would then see an empty universe regardless
    of what we put in.
    """
    cache_obj.set(f"analysis:{ticker}", _make_fake_analysis(ticker, **kw), ttl=3600)


@pytest.fixture(autouse=True)
def _clean_cache(monkeypatch):
    """Reset cache between tests AND short-circuit the analysis_cache
    DB tier so the test is hermetic.

    _query_preset_from_db has TWO data sources:
      • tier-1 — postgres `analysis_cache` table (via data_pipeline.db)
      • tier-2 — in-memory cache_service._store

    We're testing the FILTER LOGIC, not the DB. Mocking
    `data_pipeline.db.Session` to raise forces tier-1 to short-circuit
    via its try/except, so only the in-memory rows we seed via
    `_seed()` are visible to the filter. Without this, dev machines
    with a real DATABASE_URL pull in hundreds of live analysis_cache
    rows and any threshold assertion blows up with "assert 18 == 2".
    """
    from backend.services.cache_service import cache as _c

    # Force tier-1 to fail-closed. data_pipeline.db.Session() raising
    # is the documented "DB unavailable" path inside
    # _query_preset_from_db (see the `except Exception as _exc:` line
    # after the SQL block).
    def _raise_db(*args, **kwargs):
        raise RuntimeError("test: db tier disabled")

    try:
        from data_pipeline import db as _dbmod
        monkeypatch.setattr(_dbmod, "Session", _raise_db)
    except Exception:
        # data_pipeline.db not importable — tier-1 already raises on
        # import, nothing to mock. Good.
        pass

    saved = dict(_c._store)
    _c._store.clear()
    yield
    _c._store.clear()
    _c._store.update(saved)


def test_buffett_strict_pass_returns_matching_rows():
    """Sanity: strict pass still works when matches exist."""
    from backend.services.cache_service import cache as _c
    from backend.routers.screener import _query_preset_from_db

    # Two rows that clear strict buffett gates (score>=60, mos>=0, wide).
    _seed(_c, "HDFCBANK.NS", score=72, mos=15, moat="Wide")
    _seed(_c, "TCS.NS", score=68, mos=8, moat="Wide")

    stocks, total = _query_preset_from_db("buffett")
    assert total == 2
    tickers = {s.ticker for s in stocks}
    assert "HDFCBANK.NS" in tickers
    assert "TCS.NS" in tickers
    # Strict pass succeeded — relax flag must be False.
    assert _query_preset_from_db.last_relaxed is False


def test_buffett_zero_strict_kicks_off_relax_pass():
    """P0 bug: strict pass returns 0 → relax pass surfaces closest matches.

    Pre-fix, an empty strict pass simply returned 0 and the home tile
    showed "Wide-Moat at Discount: 0". With the relax pass, score>=50
    and narrow-moat is acceptable on /home; the tile shows N>0.
    """
    from backend.services.cache_service import cache as _c
    from backend.routers.screener import _query_preset_from_db

    # All rows FAIL strict buffett (no wide moat, low mos, etc.) but
    # several clear the relaxed pass (score>=50, mos>=-10, wide OR
    # narrow moat).
    _seed(_c, "INFY.NS", score=58, mos=-5, moat="Narrow")
    _seed(_c, "WIPRO.NS", score=55, mos=-8, moat="Narrow")

    stocks, total = _query_preset_from_db("buffett")
    # Relax pass surfaced both rows.
    assert total >= 1, "relax pass should surface at least one closest match"
    assert _query_preset_from_db.last_relaxed is True


def test_buffett_moat_check_is_case_insensitive():
    """P0 bug root cause: `moat == 'Wide'` strict-CAP-W compare
    skipped rows where the cache wrote 'wide' or 'WIDE'. The fix
    switched to case-insensitive substring match. Pin the new
    behaviour so it can't regress to strict equality.
    """
    from backend.services.cache_service import cache as _c
    from backend.routers.screener import _query_preset_from_db

    _seed(_c, "LOWERCASE.NS", score=70, mos=10, moat="wide")
    _seed(_c, "UPPERCASE.NS", score=68, mos=5, moat="WIDE")
    _seed(_c, "LONGFORM.NS", score=72, mos=12, moat="Wide moat")

    stocks, total = _query_preset_from_db("buffett")
    assert total == 3
    tickers = {s.ticker for s in stocks}
    assert tickers == {"LOWERCASE.NS", "UPPERCASE.NS", "LONGFORM.NS"}
    # Strict pass succeeded — no relaxation needed.
    assert _query_preset_from_db.last_relaxed is False


def test_deep_value_relax_pass_lowers_mos_floor():
    """Strict deep_value: mos>=30, score>=50. Relax: mos>=20, score>=40.

    Pin that a row with mos=22, score=45 fails strict but passes relax.
    """
    from backend.services.cache_service import cache as _c
    from backend.routers.screener import _query_preset_from_db

    # Below the strict mos>=30 floor but above the relaxed mos>=20.
    _seed(_c, "RELAXED.NS", score=45, mos=22, moat="Narrow")

    stocks, total = _query_preset_from_db("deep_value")
    assert total == 1
    assert stocks[0].ticker == "RELAXED.NS"
    assert _query_preset_from_db.last_relaxed is True


def test_relax_pass_keeps_data_limited_guard():
    """Even on the relaxed pass, rows with data_limited=True are
    dropped for the three opinionated presets — those have known FV
    clamp artefacts and should never show up on /home tiles.
    """
    from backend.services.cache_service import cache as _c
    from backend.routers.screener import _query_preset_from_db

    _seed(_c, "TAINTED.NS", score=70, mos=40, moat="Wide", data_limited=True)

    stocks, total = _query_preset_from_db("buffett")
    assert total == 0, "data_limited rows must never reach a buffett tile"


def test_growth_quality_relax_pass_lowers_score_and_growth_floors():
    """Strict growth_quality: score>=70 AND rev_cagr>=0.08.
    Relax: score>=60 AND rev_cagr>=0.04.
    """
    from backend.services.cache_service import cache as _c
    from backend.routers.screener import _query_preset_from_db

    # Below strict (score=65 < 70, growth=0.05 < 0.08) but above relax
    # (score>=60, growth>=0.04).
    _seed(_c, "RELAXG.NS", score=65, mos=5, moat="Wide", rev_cagr=0.05)

    stocks, total = _query_preset_from_db("growth_quality")
    assert total == 1
    assert stocks[0].ticker == "RELAXG.NS"
    assert _query_preset_from_db.last_relaxed is True
