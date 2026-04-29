# tests/test_sector_percentile.py
# ═══════════════════════════════════════════════════════════════
# Tests for backend.services.sector_percentile (Stage 1).
#
# Hermetic — no Aiven Postgres. The compute_sector_cohort test
# uses a fake db_session that returns SQLAlchemy-Row-like objects
# with a `_mapping` attribute, matching production code paths.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from backend.services import sector_percentile as sp


# ─── percentile_rank ─────────────────────────────────────────────
def test_percentile_rank_smallest_is_zero():
    assert sp.percentile_rank(10, [10, 20, 30, 40, 50]) == 0


def test_percentile_rank_largest_is_eighty():
    # 4 of 5 values strictly less than 50 → 80%.
    assert sp.percentile_rank(50, [10, 20, 30, 40, 50]) == 80


def test_percentile_rank_middle_is_forty():
    # 2 of 5 strictly less than 30 → 40%.
    assert sp.percentile_rank(30, [10, 20, 30, 40, 50]) == 40


def test_percentile_rank_empty_cohort_returns_zero():
    assert sp.percentile_rank(10, []) == 0


def test_percentile_rank_skips_nan_in_cohort():
    # NaN entries are dropped from the cohort denominator.
    cohort = [10, 20, float("nan"), 30]
    # 2 of 3 valid entries are < 30 → 67% rounded.
    assert sp.percentile_rank(30, cohort) == 67


def test_percentile_rank_handles_non_finite_value():
    assert sp.percentile_rank(float("nan"), [10, 20, 30]) == 0
    assert sp.percentile_rank(float("inf"), [10, 20, 30]) == 0


# ─── value_band_for_percentile ───────────────────────────────────
def test_band_strong_discount():
    assert sp.value_band_for_percentile(5)["band"] == "strong_discount"


def test_band_in_range():
    assert sp.value_band_for_percentile(50)["band"] == "in_range"


def test_band_notably_overvalued():
    assert sp.value_band_for_percentile(95)["band"] == "notably_overvalued"


def test_band_none_is_data_limited():
    out = sp.value_band_for_percentile(None)
    assert out["band"] == "data_limited"
    assert "label" in out


def test_band_below_peers_boundary():
    # 10 → not strong_discount (< 10), 30 → not below_peers (< 30).
    assert sp.value_band_for_percentile(10)["band"] == "below_peers"
    assert sp.value_band_for_percentile(29)["band"] == "below_peers"
    assert sp.value_band_for_percentile(30)["band"] == "in_range"


def test_band_above_peers_boundary():
    assert sp.value_band_for_percentile(70)["band"] == "above_peers"
    assert sp.value_band_for_percentile(89)["band"] == "above_peers"
    assert sp.value_band_for_percentile(90)["band"] == "notably_overvalued"


def test_band_out_of_range_is_data_limited():
    assert sp.value_band_for_percentile(-1)["band"] == "data_limited"
    assert sp.value_band_for_percentile(101)["band"] == "data_limited"


# ─── compute_sector_cohort (mocked DB) ───────────────────────────
class _FakeRow:
    """Mimics SQLAlchemy Row with ._mapping access."""
    def __init__(self, mapping: dict):
        self._mapping = mapping


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _FakeSession:
    def __init__(self, rows):
        self._rows = rows
        self.last_params = None

    def execute(self, _stmt, params=None):
        self.last_params = params
        return _FakeResult(self._rows)


def _payload(mos_pct):
    return json.dumps({"valuation": {"margin_of_safety": mos_pct}})


def test_compute_sector_cohort_filters_micro_caps_and_extracts_mos(monkeypatch):
    sp._clear_cohort_cache()
    rows = [
        _FakeRow({
            "ticker": "TCS",
            "market_cap_cr": 1_500_000.0,
            "pe_ratio": 28.0,
            "pb_ratio": 12.0,
            "payload": _payload(0.18),
        }),
        _FakeRow({
            "ticker": "INFY",
            "market_cap_cr": 700_000.0,
            "pe_ratio": 24.0,
            "pb_ratio": 8.0,
            "payload": _payload(0.12),
        }),
        _FakeRow({
            # Micro-cap → must be filtered out.
            "ticker": "TINYCO",
            "market_cap_cr": 50.0,
            "pe_ratio": 5.0,
            "pb_ratio": 0.5,
            "payload": _payload(0.9),
        }),
        _FakeRow({
            # No usable metrics → dropped.
            "ticker": "EMPTY",
            "market_cap_cr": 5000.0,
            "pe_ratio": None,
            "pb_ratio": None,
            "payload": None,
        }),
    ]
    sess = _FakeSession(rows)

    cohort = sp.compute_sector_cohort("IT Services", sess)

    tickers = [c["ticker"] for c in cohort]
    assert "TCS" in tickers
    assert "INFY" in tickers
    assert "TINYCO" not in tickers       # micro-cap filtered
    assert "EMPTY" not in tickers        # no metrics
    # Sector parameter is the canonical key, not the user input.
    assert sess.last_params == {"sector": "IT Services"}

    tcs = next(c for c in cohort if c["ticker"] == "TCS")
    assert tcs["pe_ratio"] == 28.0
    assert tcs["pb_ratio"] == 12.0
    assert abs(tcs["mos_pct"] - 0.18) < 1e-9


def test_compute_sector_cohort_resolves_alias():
    sp._clear_cohort_cache()
    sess = _FakeSession([])
    sp.compute_sector_cohort("software", sess)  # alias → IT Services
    assert sess.last_params == {"sector": "IT Services"}


def test_compute_sector_cohort_unmapped_returns_empty_without_db():
    sp._clear_cohort_cache()

    class _Boom:
        def execute(self, *a, **kw):
            raise AssertionError("DB must not be touched for unmapped sector")

    assert sp.compute_sector_cohort("Asteroid Mining", _Boom()) == []
    assert sp.compute_sector_cohort("", _Boom()) == []
    assert sp.compute_sector_cohort(None, _Boom()) == []  # type: ignore[arg-type]


def test_compute_sector_cohort_caches_per_sector():
    sp._clear_cohort_cache()
    sess = _FakeSession([
        _FakeRow({
            "ticker": "TCS",
            "market_cap_cr": 1_500_000.0,
            "pe_ratio": 28.0,
            "pb_ratio": 12.0,
            "payload": _payload(0.18),
        }),
    ])

    call_count = {"n": 0}
    real_execute = sess.execute

    def counting_execute(*a, **kw):
        call_count["n"] += 1
        return real_execute(*a, **kw)

    sess.execute = counting_execute  # type: ignore[assignment]

    sp.compute_sector_cohort("IT Services", sess)
    sp.compute_sector_cohort("IT Services", sess)
    sp.compute_sector_cohort("software", sess)  # alias → same canonical

    assert call_count["n"] == 1


def test_compute_sector_cohort_handles_dict_payload():
    """psycopg2 returns JSONB as dict, not str — make sure we cope."""
    sp._clear_cohort_cache()
    rows = [
        _FakeRow({
            "ticker": "HDFCBANK",
            "market_cap_cr": 1_200_000.0,
            "pe_ratio": 18.0,
            "pb_ratio": 2.5,
            "payload": {"valuation": {"margin_of_safety": 0.25}},
        }),
    ]
    sess = _FakeSession(rows)
    cohort = sp.compute_sector_cohort("Banks", sess)
    assert len(cohort) == 1
    assert abs(cohort[0]["mos_pct"] - 0.25) < 1e-9
