"""Day-111a (2026-05-23) — Industry serializer key fix.

`backend/services/local_data_service.assemble_local()` fetched the
``industry`` column from the ``stocks`` table but collapsed both
``sector`` and ``industry`` into a single ``sector_name`` key. The
returned dict never emitted an ``industry`` key, so the downstream
``analysis/service.py:1091`` lookup (``raw.get("industry", ...)``) fell
through to ``""`` for 93/97 tickers in the public stock-summary
payload.

This silently broke:
  - Day-99 percentile cohort detection (keys off industry string)
  - is_bank_like / REIT / holdco classification cascades
  - AI description ROE / D-E surfacing for banks

Pure serializer bug — the data IS in the DB. Confirmed via
data-pipeline investigation: 19/20 sampled top tickers have a
populated ``industry`` value in ``stocks``.

These tests pin:
  - assemble_local returns ``industry`` distinctly from ``sector_name``
  - assemble_local also returns ``sector`` (parity with ``industry``)
  - Backwards-compat: ``sector_name`` still present
  - The SELECT still pulls ``company_name, sector, industry``
  - TATAMOTORS.NS → TMPV.NS alias is registered
  - Manifest entry exists with the spec'd version_id + applied_at
  - No CACHE_VERSION bump
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock


REPO_ROOT = Path(__file__).resolve().parents[2]
LOCAL_DATA_PATH = (
    REPO_ROOT / "backend" / "services" / "local_data_service.py"
)
ANALYSIS_ROUTER_PATH = REPO_ROOT / "backend" / "routers" / "analysis.py"
MANIFEST_PATH = (
    REPO_ROOT / "backend" / "services" / "cache_invalidation_manifest.py"
)
CACHE_PATH = REPO_ROOT / "backend" / "services" / "cache_service.py"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8-sig")


# ─────────────────────────────────────────────────────────────────
# 1. Source-level guarantees (no DB required)
# ─────────────────────────────────────────────────────────────────

def test_local_data_returns_industry_key_in_dict_literal():
    """The returned dict must include an ``industry`` key."""
    src = _read(LOCAL_DATA_PATH)
    assert re.search(r'"industry"\s*:', src), (
        "local_data_service must emit an 'industry' key in its return dict"
    )


def test_local_data_returns_sector_key_in_dict_literal():
    """Companion ``sector`` key (parity with the new ``industry``)."""
    src = _read(LOCAL_DATA_PATH)
    assert re.search(r'"sector"\s*:', src), (
        "local_data_service should emit a 'sector' key alongside 'industry'"
    )


def test_local_data_preserves_sector_name_backcompat():
    """Existing callers that read ``sector_name`` must keep working."""
    src = _read(LOCAL_DATA_PATH)
    assert re.search(r'"sector_name"\s*:', src), (
        "Backwards-compat: 'sector_name' key must remain in the dict"
    )


def test_local_data_select_still_pulls_industry_column():
    src = _read(LOCAL_DATA_PATH)
    assert "company_name, sector, industry FROM stocks" in src, (
        "SQL SELECT must still fetch the industry column"
    )


def test_local_data_assigns_industry_from_row():
    """Verify there's an assignment like ``industry_name = row.get(...)``."""
    src = _read(LOCAL_DATA_PATH)
    assert re.search(
        r'industry_name\s*=\s*row\.get\(\s*["\']industry["\']',
        src,
    ), (
        "industry must be pulled from row.get('industry'), not collapsed "
        "into sector_name"
    )


# ─────────────────────────────────────────────────────────────────
# 2. Runtime check with a mocked DB session
# ─────────────────────────────────────────────────────────────────

def _mock_session_for(stocks_row: dict | None):
    """Build a SQLAlchemy-ish mock session.

    - FROM stocks → returns ``stocks_row`` via .first()
    - FROM financials (annual) → returns a single revenue row via .all()
      (just enough to clear the ``if not revenue_list`` early-return)
    - Everything else (market_metrics, company_financials, …) → None
    """
    session = MagicMock()
    fake_fin_row = {
        "revenue": 10000.0,
        "pat": 1000.0,
        "ebitda": 2000.0,
        "eps_diluted": 10.0,
        "cfo": 1500.0,
        "capex": 500.0,
        "free_cash_flow": 1000.0,
        "total_assets": 50000.0,
        "total_equity": 20000.0,
        "total_debt": 10000.0,
        "cash_and_equivalents": 2000.0,
        "shares_outstanding": 100.0,
        "shares_outstanding_raw": 1_000_000_000.0,
        "roe": 0.15,
        "debt_to_equity": 0.5,
        "net_margin": 0.10,
        "period_end": "2025-03-31",
        "currency": "INR",
    }

    def execute(stmt, params=None):
        sql = str(stmt)
        result = MagicMock()
        mappings = MagicMock()
        if "FROM stocks" in sql:
            mappings.first.return_value = stocks_row
            mappings.all.return_value = [stocks_row] if stocks_row else []
        elif "FROM financials" in sql:
            mappings.first.return_value = fake_fin_row
            mappings.all.return_value = [fake_fin_row]
        else:
            mappings.first.return_value = None
            mappings.all.return_value = []
        result.mappings.return_value = mappings
        return result

    session.execute.side_effect = execute
    return session


def _assemble_for(ticker: str, fake_company: dict):
    """Helper: call assemble_local with a stocks-row mock."""
    from backend.services import local_data_service as lds
    import data_pipeline.nse_prices.db_integration as dbi

    orig_price = dbi.get_latest_price
    orig_hl = dbi.get_52w_high_low
    dbi.get_latest_price = lambda c: 100.0
    dbi.get_52w_high_low = lambda c: (120.0, 80.0)
    try:
        session = _mock_session_for(fake_company)
        return lds.assemble_local(ticker, session)
    finally:
        dbi.get_latest_price = orig_price
        dbi.get_52w_high_low = orig_hl


def test_assemble_local_emits_industry_for_hdfcbank():
    out = _assemble_for("HDFCBANK.NS", {
        "company_name": "HDFC Bank Ltd",
        "sector": "Financial Services",
        "industry": "Private Sector Bank",
    })
    assert out is not None
    assert out.get("industry") == "Private Sector Bank"
    assert out.get("sector_name") == "Financial Services"


def test_assemble_local_emits_industry_for_diverse_tickers():
    cases = {
        "RELIANCE.NS": ("Energy", "Refineries & Marketing"),
        "TCS.NS": ("Information Technology", "IT Services"),
        "NTPC.NS": ("Utilities", "Power Generation"),
        "MARUTI.NS": ("Consumer Discretionary", "Passenger Cars"),
        "BAJFINANCE.NS": ("Financial Services", "NBFC"),
    }
    for tic, (sector, industry) in cases.items():
        out = _assemble_for(tic, {
            "company_name": tic.replace(".NS", ""),
            "sector": sector,
            "industry": industry,
        })
        assert out is not None, f"{tic}: assemble_local returned None"
        assert out.get("industry") == industry, (
            f"{tic}: expected industry={industry!r}, "
            f"got {out.get('industry')!r}"
        )
        assert out.get("sector_name") == sector, (
            f"{tic}: sector_name regression"
        )


def test_assemble_local_industry_empty_when_db_lacks_value():
    """Defensive: empty industry stays empty (no None leakage)."""
    out = _assemble_for("XXXX.NS", {
        "company_name": "Mystery Co",
        "sector": "Unknown",
        "industry": None,
    })
    assert out is not None
    assert out.get("industry") == ""


# ─────────────────────────────────────────────────────────────────
# 3. TATAMOTORS alias (already exists — pin it)
# ─────────────────────────────────────────────────────────────────

def test_tatamotors_alias_resolves_to_tmpv():
    from backend.routers.analysis import TICKER_ALIASES

    assert TICKER_ALIASES.get("TATAMOTORS.NS") == "TMPV.NS"
    assert TICKER_ALIASES.get("TATAMOTORS") == "TMPV.NS"


# ─────────────────────────────────────────────────────────────────
# 4. Manifest entry + no CACHE_VERSION bump
# ─────────────────────────────────────────────────────────────────

def test_manifest_has_day111a_entry():
    src = _read(MANIFEST_PATH)
    assert "v_day111a_industry_serializer_2026_05_23" in src
    assert 'datetime(2026, 5, 23, 22, 0, 0' in src
    # scope must cover all tickers + at least these two fields.
    assert '"industry"' in src
    assert '"sector"' in src


def test_manifest_entry_loads_in_python():
    """Sanity: the new dict literal parses + matcher returns it."""
    from backend.services import cache_invalidation_manifest as cim

    ids = [r.get("version_id") for r in cim.MANIFEST]
    assert "v_day111a_industry_serializer_2026_05_23" in ids

    # scope.tickers == "*" → must apply to any ticker.
    entry = next(
        r for r in cim.MANIFEST
        if r["version_id"] == "v_day111a_industry_serializer_2026_05_23"
    )
    assert entry["scope"]["tickers"] == "*"
    assert "industry" in entry["scope"]["fields"]
    assert isinstance(entry["applied_at"], datetime)
    assert entry["applied_at"].tzinfo == timezone.utc


def test_cache_version_not_bumped():
    """Day-111a is a serializer fix; CACHE_VERSION stays put.

    The data-fix discipline (CLAUDE.md rule #2) requires a before/after
    canary snapshot for any CACHE_VERSION bump — this PR has neither,
    so the invalidation must ride on the manifest entry, not a bump.
    """
    src = _read(CACHE_PATH)
    # CACHE_VERSION is an int constant like ``CACHE_VERSION = 135``.
    m = re.search(r'CACHE_VERSION\s*=\s*(\d+)', src)
    assert m, "CACHE_VERSION integer literal not found in cache_service.py"
    # No marker for day111a should appear inside the CACHE_VERSION line
    # itself or its inline trailing comment (a bump would mention it).
    line_start = src.rfind("\n", 0, m.start()) + 1
    line_end = src.find("\n", m.end())
    cache_line = src[line_start:line_end if line_end != -1 else len(src)]
    assert "day111a" not in cache_line.lower(), (
        "Day-111a must not appear in CACHE_VERSION line — use the manifest"
    )
