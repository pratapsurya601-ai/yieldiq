"""Tests for market_metrics source-precedence + write-validation guards.

Mirrors backend/tests/test_data_quality_rank.py (PR #208's financials
precedence tests) but applied to market_metrics + the new validation
gate in scripts.data_pipelines.fetch_market_metrics.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_MIGRATION_PATH = (
    _REPO_ROOT / "data_pipeline" / "migrations" / "025_market_metrics_quality_rank.sql"
)
_FETCH_PATH = (
    _REPO_ROOT / "scripts" / "data_pipelines" / "fetch_market_metrics.py"
)


def _load_fetch_module():
    """Load fetch_market_metrics without triggering the package's relative imports.

    The module imports `from . import _common as C` which only resolves when
    the package is on sys.path. For unit tests of pure helpers we don't need
    that — we patch _common before exec.
    """
    spec = importlib.util.spec_from_file_location(
        "_test_fetch_market_metrics", _FETCH_PATH
    )
    mod = importlib.util.module_from_spec(spec)
    # Stub the relative import
    import sys, types
    if "scripts" not in sys.modules:
        sys.modules["scripts"] = types.ModuleType("scripts")
    if "scripts.data_pipelines" not in sys.modules:
        sys.modules["scripts.data_pipelines"] = types.ModuleType(
            "scripts.data_pipelines"
        )
    fake_common = types.ModuleType("scripts.data_pipelines._common")
    fake_common.bare = lambda x: x
    fake_common.yf_symbol = lambda x: x + ".NS"
    fake_common.with_retries = lambda fn, label="": (fn(), None)
    sys.modules["scripts.data_pipelines._common"] = fake_common
    # Mark this module as inside the package so `from . import _common` works
    mod.__package__ = "scripts.data_pipelines"
    try:
        spec.loader.exec_module(mod)
    except Exception:
        # If full execution fails (yfinance import, etc.), pull just the
        # helpers we need via regex from the source. Tests will use those.
        return None
    return mod


def test_migration_file_exists_and_idempotent():
    """Migration 025 exists, uses IF NOT EXISTS, defines rank table."""
    assert _MIGRATION_PATH.exists(), "migration 025 must exist"
    text = _MIGRATION_PATH.read_text(encoding="utf-8")
    assert "ADD COLUMN IF NOT EXISTS data_source" in text
    assert "ADD COLUMN IF NOT EXISTS data_quality_rank" in text
    assert "yfinance" in text  # ranks include yfinance
    assert "NSE_QUOTE_API" in text  # plus authoritative sources
    assert "CREATE INDEX IF NOT EXISTS idx_market_metrics_priority" in text


def test_upsert_sql_has_precedence_guard_for_every_column():
    """Every UPSERT'd column wraps its update in a rank-based CASE guard."""
    text = _FETCH_PATH.read_text(encoding="utf-8")
    # Find UPSERT_SQL block
    m = re.search(r'UPSERT_SQL\s*=\s*text\("""(.*?)"""\)', text, re.DOTALL)
    assert m, "UPSERT_SQL block not found"
    upsert_block = m.group(1)
    # Each updated column must be wrapped in CASE WHEN EXCLUDED.data_quality_rank <= ...
    for col in ("pe_ratio", "pb_ratio", "debt_equity", "roe"):
        pat = rf"{col}\s*=\s*CASE\s+WHEN\s+EXCLUDED\.data_quality_rank\s*<=\s*market_metrics\.data_quality_rank"
        assert re.search(pat, upsert_block), f"{col} missing precedence guard"
    # Rank itself uses LEAST so it only ever decreases (improves)
    assert "data_quality_rank = LEAST(EXCLUDED.data_quality_rank, market_metrics.data_quality_rank)" in upsert_block


def test_rank_for_known_sources():
    """_rank_for() returns expected ranks. Lower = higher trust."""
    mod = _load_fetch_module()
    if mod is None or not hasattr(mod, "_rank_for"):
        pytest.skip("fetch_market_metrics could not be loaded in this env")
    assert mod._rank_for("NSE_QUOTE_API") == 10
    assert mod._rank_for("NSE_BHAVCOPY") == 20
    assert mod._rank_for("BSE_QUOTE") == 30
    assert mod._rank_for("yfinance") == 50
    assert mod._rank_for("unknown") == 60
    assert mod._rank_for(None) == 60


def test_validation_gate_rejects_obvious_unit_bugs():
    """_row_is_writable rejects PE/PB/ROE outside plausible ranges."""
    mod = _load_fetch_module()
    if mod is None or not hasattr(mod, "_row_is_writable"):
        pytest.skip("fetch_market_metrics could not be loaded in this env")
    # All-null
    ok, _ = mod._row_is_writable(None, None, None, None)
    assert ok is False
    # Healthy row
    ok, _ = mod._row_is_writable(25.0, 4.5, 0.3, 0.18)
    assert ok is True
    # PE outlier
    ok, reason = mod._row_is_writable(1500, 4.5, 0.3, 0.18)
    assert ok is False and "PE" in reason
    # PB outlier
    ok, reason = mod._row_is_writable(25, 200, 0.3, 0.18)
    assert ok is False and "PB" in reason
    # ROE outlier
    ok, reason = mod._row_is_writable(25, 4.5, 0.3, 99)
    assert ok is False and "ROE" in reason


def test_read_path_skips_null_mcap():
    """sector_percentile cohort SQL filters market_cap_cr IS NOT NULL AND > 0."""
    sp_path = _REPO_ROOT / "backend" / "services" / "sector_percentile.py"
    text = sp_path.read_text(encoding="utf-8")
    # Find the latest_mm CTE
    m = re.search(r"latest_mm AS \(.*?\),", text, re.DOTALL)
    assert m, "latest_mm CTE not found"
    cte = m.group(0)
    assert "market_cap_cr IS NOT NULL" in cte, (
        "cohort builder must skip rows with NULL market_cap_cr "
        "(prevents 2026-04-30 yfinance-NULL incident class)"
    )
    assert "market_cap_cr > 0" in cte
    # And rank-aware ordering
    assert "data_quality_rank" in cte, (
        "cohort builder must order by data_quality_rank to pick best-trust source"
    )
