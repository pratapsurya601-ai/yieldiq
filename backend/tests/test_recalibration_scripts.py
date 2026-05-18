"""Tests for the quarterly recalibration tooling.

Covers:
- fetch_recalibration_inputs.py
    * yfinance mocked → artifact shape is correct
    * empty G-Sec feed → RuntimeError with manual-entry instructions
- apply_recalibration.py
    * dry-run preview produces expected diff rows
    * --apply rewrites models/industry_wacc.py in place
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

# Ensure repo root + scripts/ are importable.
_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (_REPO_ROOT, _REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import fetch_recalibration_inputs as fri  # noqa: E402
import apply_recalibration as ar          # noqa: E402


# ── yfinance test double ──────────────────────────────────────────
class _FakeHist:
    def __init__(self, closes: list[float]):
        import datetime as _dt
        self._closes = closes
        # mimic pandas DataFrame access used by the script
        self.index = [types.SimpleNamespace(
            date=lambda d=_dt.date(2026, 5, 15): d
        )]

    def __len__(self) -> int:
        return len(self._closes)

    def __getitem__(self, key: str) -> "_FakeHist":
        return self  # ["Close"] returns self

    def dropna(self) -> "_FakeSeries":
        return _FakeSeries(self._closes)


class _FakeSeries:
    def __init__(self, vals: list[float]):
        self.vals = vals

    @property
    def iloc(self) -> "_FakeSeries":
        return self

    def __getitem__(self, i: int) -> float:
        return self.vals[i]


class _FakeTicker:
    def __init__(self, sym: str, hist_map: dict[str, list[float]],
                 info_map: dict[str, dict]):
        self._sym = sym
        self._hist_map = hist_map
        self._info_map = info_map

    def history(self, period: str = "5d") -> _FakeHist:
        return _FakeHist(self._hist_map.get(self._sym, []))

    @property
    def info(self) -> dict:
        return self._info_map.get(self._sym, {})


def _make_yf(hist_map: dict[str, list[float]],
             info_map: dict[str, dict]):
    mod = types.SimpleNamespace()
    mod.Ticker = lambda s: _FakeTicker(s, hist_map, info_map)
    return mod


# ── fetch_recalibration_inputs ────────────────────────────────────
def test_fetch_risk_free_rate_primary_ok():
    yf = _make_yf({"^IN10Y": [7.21]}, {})
    rate, src = fri.fetch_risk_free_rate(yf_module=yf)
    assert rate == pytest.approx(0.0721, rel=1e-3)
    assert "^IN10Y" in src


def test_fetch_risk_free_rate_fallback_to_reuters():
    yf = _make_yf({"^IN10Y": [], "IN10YT=RR": [7.05]}, {})
    rate, src = fri.fetch_risk_free_rate(yf_module=yf)
    assert rate == pytest.approx(0.0705, rel=1e-3)
    assert "IN10YT=RR" in src


def test_fetch_risk_free_rate_empty_raises_with_manual_hint():
    yf = _make_yf({"^IN10Y": [], "IN10YT=RR": []}, {})
    with pytest.raises(RuntimeError) as exc:
        fri.fetch_risk_free_rate(yf_module=yf)
    assert "--rf-manual" in str(exc.value)


def test_fetch_sector_betas_takes_median_of_top_3():
    info = {
        "TCS.NS":     {"beta": 0.80},
        "INFY.NS":    {"beta": 0.90},
        "HCLTECH.NS": {"beta": 1.00},
        "ITC.NS":     {"beta": 0.70},
    }
    yf = _make_yf({}, info)
    universe = {"it_services": ["TCS.NS", "INFY.NS", "HCLTECH.NS"],
                "fmcg": ["ITC.NS"]}
    betas, warnings = fri.fetch_sector_betas(yf_module=yf, universe=universe)
    assert betas["it_services"] == pytest.approx(0.90)
    assert betas["fmcg"] == pytest.approx(0.70)
    assert warnings == []


def test_fetch_sector_betas_warns_on_missing_info():
    info = {"TCS.NS": {"beta": 0.80}, "INFY.NS": {}}  # second missing
    yf = _make_yf({}, info)
    universe = {"it_services": ["TCS.NS", "INFY.NS", "MISSING.NS"]}
    betas, warnings = fri.fetch_sector_betas(yf_module=yf, universe=universe)
    assert betas["it_services"] == pytest.approx(0.80)
    # Two non-numeric peers should produce warnings.
    assert any("INFY.NS" in w for w in warnings)
    assert any("MISSING.NS" in w for w in warnings)


def test_default_terminal_growth_overlay_math():
    tg = fri.default_terminal_growth(0.105, haircut_bps=50)
    assert tg["default"] == pytest.approx(0.10)          # 10.5 − 0.5
    assert tg["it_services"] == pytest.approx(0.105)     # +50bps overlay
    assert tg["metals"] == pytest.approx(0.080)          # −200bps overlay


def test_build_artifact_shape():
    art = fri.build_artifact(
        rf=0.072, rf_src="src",
        betas={"it_services": 0.9}, beta_src="b-src",
        tg={"default": 0.05, "it_services": 0.06}, tg_src="t-src",
        current_snap={"it_services": {"beta_typical": 1.05,
                                      "terminal_growth": 0.035,
                                      "wacc_default": 0.11}},
        warnings=["x"],
    )
    for k in ("captured_at", "captured_by", "risk_free_rate",
              "rf_source", "sector_betas", "sector_betas_source",
              "terminal_growth", "terminal_growth_source",
              "current_industry_wacc_snapshot", "warnings"):
        assert k in art
    assert art["risk_free_rate"] == 0.072
    assert art["warnings"] == ["x"]


# ── apply_recalibration ───────────────────────────────────────────
_SAMPLE_WACC_SRC = '''\
# header
from __future__ import annotations

INDUSTRY_WACC = {
    "it_services": {
        "wacc_min":         0.10, "wacc_max": 0.12, "wacc_default": 0.11,
        "terminal_growth":  0.035,
        "beta_typical":     1.05,
        "notes":            "Low capex intensity.",
    },
    "fmcg": {
        "wacc_min":         0.09, "wacc_max": 0.11, "wacc_default": 0.10,
        "terminal_growth":  0.050,
        "beta_typical":     0.75,
        "notes":            "Stable consumer staples.",
    },
}

INDUSTRY_WACC_USA = {
    "us_mega_tech": {
        "beta_typical":     1.20,
        "terminal_growth":  0.030,
    },
}
'''


def _make_artifact() -> dict:
    return {
        "captured_at": "2026-05-18T00:00:00Z",
        "risk_free_rate": 0.072,
        "sector_betas": {"it_services": 0.92, "fmcg": 0.70},
        "terminal_growth": {"default": 0.10,
                            "it_services": 0.045,
                            "fmcg": 0.050},  # unchanged
        "current_industry_wacc_snapshot": {
            "it_services": {"beta_typical": 1.05,
                            "terminal_growth": 0.035,
                            "wacc_default": 0.11},
            "fmcg":        {"beta_typical": 0.75,
                            "terminal_growth": 0.050,
                            "wacc_default": 0.10},
        },
    }


def test_compute_changes_filters_unchanged_and_default():
    art = _make_artifact()
    changes = ar.compute_changes(art)
    # it_services: both fields change
    assert "beta_typical" in changes["it_services"]
    assert "terminal_growth" in changes["it_services"]
    # fmcg: only beta changes, terminal_growth is identical
    assert "beta_typical" in changes["fmcg"]
    assert "terminal_growth" not in changes["fmcg"]


def test_rewrite_wacc_file_only_touches_indian_block():
    changes = {
        "it_services": {"beta_typical": (1.05, 0.92),
                        "terminal_growth": (0.035, 0.045)},
        "fmcg":        {"beta_typical": (0.75, 0.70)},
    }
    new_src, touches = ar.rewrite_wacc_file(_SAMPLE_WACC_SRC, changes)
    # US block untouched
    assert '"beta_typical":     1.20' in new_src
    assert '"terminal_growth":  0.030' in new_src
    # Indian block updated
    assert "0.920" in new_src   # it_services beta
    assert "0.0450" in new_src  # it_services terminal growth
    assert "0.700" in new_src   # fmcg beta
    assert len(touches) == 3


def test_apply_main_dry_run_does_not_modify_file(tmp_path, monkeypatch):
    art_path = tmp_path / "art.json"
    art_path.write_text(json.dumps(_make_artifact()), encoding="utf-8")
    wacc = tmp_path / "industry_wacc.py"
    wacc.write_text(_SAMPLE_WACC_SRC, encoding="utf-8")
    monkeypatch.setattr(ar, "_WACC_FILE", wacc)
    rc = ar.main(["--input", str(art_path)])
    assert rc == 0
    assert wacc.read_text(encoding="utf-8") == _SAMPLE_WACC_SRC


def test_apply_main_with_apply_writes_file(tmp_path, monkeypatch):
    art_path = tmp_path / "art.json"
    art_path.write_text(json.dumps(_make_artifact()), encoding="utf-8")
    wacc = tmp_path / "industry_wacc.py"
    wacc.write_text(_SAMPLE_WACC_SRC, encoding="utf-8")
    monkeypatch.setattr(ar, "_WACC_FILE", wacc)
    rc = ar.main(["--input", str(art_path), "--apply"])
    assert rc == 0
    new = wacc.read_text(encoding="utf-8")
    assert new != _SAMPLE_WACC_SRC
    assert "0.920" in new
    # US block still untouched
    assert "1.20" in new
