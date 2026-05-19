"""Day-13: lock in the pharma generic-exporter expansion.

Two assertions:

  1. The bare-NSE-ticker entries in ``models/forecaster._PHARMA_GENERIC_TICKERS``
     and ``_PHARMA_GENERIC_TICKERS_TG`` match — the earlier split (15 vs 9)
     meant the 6 Day-6 expansion tickers had WACC tightening but no
     terminal-g cap. Sync makes the behaviour consistent.

  2. The expected name set is present — NATCOPHARM (added Day-13 to
     catch the 3.57× consensus outlier flagged by the live scan) and
     NEULANDLAB (renamed from "NEULAND" — old entry never fired
     because the lookup is against the actual NSE bare symbol).

The third assertion locks in the constants.py TICKER_SECTOR_OVERRIDES
contract: every generic exporter we expect to route through pharma
treatment must classify as "Pharma" via the override map. If a
yfinance sector flip undoes this routing the test fires.
"""
from __future__ import annotations

# Frozenset literals copied from models/forecaster.py — this is a
# regression guard. If you change the engine, change this test in the
# same PR.
EXPECTED_PHARMA_GENERIC = {
    "DRREDDY", "AUROPHARMA", "ZYDUSLIFE", "GLENMARK", "IPCALAB",
    "LAURUSLABS", "ALEMBICLTD", "GRANULES", "WOCKPHARMA",
    "NEULANDLAB", "GLANDPHARMA", "PPLPHARMA", "JBCHEPHARM",
    "STAR", "SAILIFE", "NATCOPHARM",
}


def _read_frozenset_from_source(name: str) -> set[str]:
    """Extract the frozenset literal members from models/forecaster.py
    without importing the heavy forecaster module (which would require
    numpy/pandas/sklearn at test-import time)."""
    import re
    from pathlib import Path
    src = (
        Path(__file__).resolve().parents[2]
        / "models" / "forecaster.py"
    ).read_text(encoding="utf-8")
    # Find the assignment block: `_PHARMA_..._TICKERS{_TG?} = frozenset({...})`
    pat = rf"{name}\s*=\s*frozenset\(\{{(.*?)\}}\)"
    m = re.search(pat, src, flags=re.DOTALL)
    assert m, f"could not locate {name} in models/forecaster.py"
    body = m.group(1)
    # Collect quoted bare-uppercase identifiers
    return set(re.findall(r'"([A-Z0-9]+)"', body))


def test_pharma_generic_wacc_set_matches_expected():
    members = _read_frozenset_from_source("_PHARMA_GENERIC_TICKERS")
    missing = EXPECTED_PHARMA_GENERIC - members
    extra = members - EXPECTED_PHARMA_GENERIC
    assert not missing, f"missing from _PHARMA_GENERIC_TICKERS: {sorted(missing)}"
    assert not extra, f"unexpected in _PHARMA_GENERIC_TICKERS: {sorted(extra)}"


def test_pharma_generic_terminal_g_set_synced_with_wacc_set():
    """Day-13 fix: the two sets MUST match. A WACC tightening without
    a terminal-g tightening leaves a 30y DCF anchored on a too-high
    perpetuity — the +25-50% over-shoots we saw on the Day-6 expansion
    tickers."""
    wacc_set = _read_frozenset_from_source("_PHARMA_GENERIC_TICKERS")
    tg_set = _read_frozenset_from_source("_PHARMA_GENERIC_TICKERS_TG")
    only_wacc = wacc_set - tg_set
    only_tg = tg_set - wacc_set
    assert not only_wacc, (
        f"these tickers get WACC tightening but no terminal-g cap "
        f"(asymmetric — fix in PR): {sorted(only_wacc)}"
    )
    assert not only_tg, (
        f"these tickers get terminal-g cap but no WACC tightening "
        f"(asymmetric — fix in PR): {sorted(only_tg)}"
    )


def test_sector_overrides_route_all_generics_to_pharma():
    """Every ticker in the generic set MUST resolve to 'Pharma' via the
    TICKER_SECTOR_OVERRIDES map — otherwise yfinance can silently flip
    the sector and the generic-exporter treatment goes dark."""
    from backend.services.analysis.constants import TICKER_SECTOR_OVERRIDES

    # A small set of pharma tickers may be classified correctly by
    # yfinance and not need an override — we only assert that the
    # generics WE explicitly expanded are pinned.
    must_be_pinned = {
        "GRANULES", "NEULANDLAB", "GLANDPHARMA", "PPLPHARMA",
        "JBCHEPHARM", "STAR", "SAILIFE", "NATCOPHARM",
    }
    failures = [
        t for t in must_be_pinned
        if (TICKER_SECTOR_OVERRIDES.get(t) or "").lower() != "pharma"
    ]
    assert not failures, (
        "TICKER_SECTOR_OVERRIDES missing or wrong for: " + ", ".join(failures)
    )


def test_old_neuland_alias_removed():
    """Day-13 fix: 'NEULAND' was the wrong NSE symbol. The actual
    listed ticker is NEULANDLAB. Lock in that the rename happened in
    both forecaster sets AND the sector-override map."""
    from backend.services.analysis.constants import TICKER_SECTOR_OVERRIDES
    members = _read_frozenset_from_source("_PHARMA_GENERIC_TICKERS")
    assert "NEULAND" not in members, (
        "'NEULAND' must be removed — it was a dead entry (never matched "
        "any real NSE ticker). Use 'NEULANDLAB'."
    )
    # Sector-override map: same rule.
    assert "NEULAND" not in TICKER_SECTOR_OVERRIDES, (
        "TICKER_SECTOR_OVERRIDES still has stale 'NEULAND' entry."
    )
    assert TICKER_SECTOR_OVERRIDES.get("NEULANDLAB") == "Pharma"
