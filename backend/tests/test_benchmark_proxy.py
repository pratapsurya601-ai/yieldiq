"""Unit tests for scripts/build_benchmark_proxy.synth_proxy_tri.

The proxy TRI must grow by price return PLUS reinvested dividend yield,
anchored at the first valid close, skipping bad closes. Imported via
importlib-from-path to dodge the scripts-package shadowing under pytest.
"""
from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PATH = REPO_ROOT / "scripts" / "build_benchmark_proxy.py"


def _mod():
    spec = importlib.util.spec_from_file_location("build_benchmark_proxy_uut", PATH)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_proxy_anchors_at_first_close_then_adds_price_and_yield():
    m = _mod()
    # Flat price (ratio 1.0) with 2.52% annual yield → daily div = 0.0252/252
    # = 0.0001/day. Over one step TRI grows from 100 to 100*(1+0.0001).
    series = [
        (date(2020, 1, 1), 100.0, 2.52),
        (date(2020, 1, 2), 100.0, 2.52),
    ]
    out = m.synth_proxy_tri(series)
    assert out[0] == (date(2020, 1, 1), 100.0)
    assert abs(out[1][1] - 100.0 * (1.0 + 0.0001)) < 1e-9


def test_proxy_tracks_price_return_plus_yield():
    m = _mod()
    # +10% price day with 0 yield → TRI ratio 1.10 exactly.
    series = [(date(2021, 1, 1), 200.0, 0.0), (date(2021, 1, 2), 220.0, 0.0)]
    out = m.synth_proxy_tri(series)
    assert abs(out[1][1] / out[0][1] - 1.10) < 1e-9


def test_proxy_skips_nonpositive_closes():
    m = _mod()
    series = [
        (date(2022, 1, 1), 0.0, 1.0),     # skipped (anchor moves to next)
        (date(2022, 1, 2), 100.0, 0.0),
        (date(2022, 1, 3), None, 0.0),    # skipped
        (date(2022, 1, 4), 110.0, 0.0),
    ]
    out = m.synth_proxy_tri(series)
    assert [d for d, _ in out] == [date(2022, 1, 2), date(2022, 1, 4)]
    assert abs(out[1][1] / out[0][1] - 1.10) < 1e-9


def test_equity_benchmark_codes_are_sourceable():
    m = _mod()
    # The big-coverage equity codes must resolve to an NSE index name.
    for code in ("NIFTY_100_TRI", "NIFTY_500_TRI", "NIFTY_MIDCAP_150_TRI",
                 "NIFTY_SMALLCAP_250_TRI", "NIFTY_50_TRI"):
        assert code in m.TRI_CODE_TO_NSE_NAME
    # CRISIL debt benchmarks must NOT be claimed as sourceable.
    assert "CRISIL_LIQUID_DEBT_TRI" not in m.TRI_CODE_TO_NSE_NAME
