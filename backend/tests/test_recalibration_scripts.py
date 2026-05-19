"""Tests for the quarterly recalibration tooling.

Covers:
- fetch_recalibration_inputs.py
    * risk-free rate uses hardcoded RBI constant unless overridden
    * Damodaran beta-table lookup produces sane sector values
    * terminal growth table is capped at TERMINAL_GROWTH_CAP
    * artifact shape is correct
- apply_recalibration.py
    * dry-run preview produces expected diff rows
    * --apply rewrites models/industry_wacc.py in place
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Ensure repo root + scripts/ are importable.
_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (_REPO_ROOT, _REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import fetch_recalibration_inputs as fri  # noqa: E402
import apply_recalibration as ar          # noqa: E402


# ── fetch_recalibration_inputs: risk-free rate ────────────────────
def test_fetch_risk_free_rate_returns_hardcoded_constant():
    rate, src = fri.fetch_risk_free_rate()
    assert rate == pytest.approx(fri.RBI_10Y_GSEC_2026Q2)
    assert "RBI" in src
    assert "rbi.org.in" in src.lower()


def test_fetch_risk_free_rate_in_sane_band():
    """Sanity guard: India 10Y G-Sec should fall in (4%, 12%) for
    any plausible decade. If this fails the operator forgot to refresh
    the constant or made a unit error (entered 7.1 instead of 0.071).
    """
    rate, _ = fri.fetch_risk_free_rate()
    assert 0.04 <= rate <= 0.12


# ── fetch_recalibration_inputs: sector betas (Damodaran table) ────
def test_fetch_sector_betas_returns_damodaran_table():
    betas, warnings = fri.fetch_sector_betas()
    assert warnings == []
    # Spot-check anchor values from the published table.
    assert betas["it_services"] == pytest.approx(1.05)
    assert betas["fmcg"] == pytest.approx(0.75)
    assert betas["tech_hardware"] == pytest.approx(1.15)


def test_fetch_sector_betas_all_in_sane_range():
    """Every sector beta must fall in a sane range. Catches the
    regression that motivated this PR: yfinance was returning
    0.004 for tech_hardware (essentially zero) which would balloon
    DCF fair values.
    """
    betas, _ = fri.fetch_sector_betas()
    for sector in (
        "it_services", "fmcg", "pharma", "auto_oem", "banks",
        "metals", "oil_gas", "tech_hardware",
    ):
        assert sector in betas, f"missing sector: {sector}"
        assert 0.4 <= betas[sector] <= 2.0, (
            f"{sector} beta {betas[sector]} outside sane range"
        )


def test_fetch_sector_betas_warns_on_garbage_input():
    """If operator hand-edits the table with garbage, surface a warning."""
    bad = {"it_services": 1.05, "broken": "nope", "negative": -0.5,
           "too_high": 4.0}
    betas, warnings = fri.fetch_sector_betas(table=bad)
    assert betas == {"it_services": 1.05}
    assert any("broken" in w for w in warnings)
    assert any("negative" in w for w in warnings)
    assert any("too_high" in w for w in warnings)


# ── fetch_recalibration_inputs: terminal growth ───────────────────
def test_fetch_terminal_growth_returns_table_values():
    tg, warnings = fri.fetch_sector_terminal_growth()
    assert warnings == []
    assert tg["default"] == pytest.approx(0.045)
    assert tg["fmcg"] == pytest.approx(0.055)
    assert tg["oil_gas"] == pytest.approx(0.030)


def test_terminal_growth_never_exceeds_cap():
    """Acceptance test: no sector terminal-growth value may exceed the
    6 % cap. India long-run nominal GDP is not credibly above this.
    """
    tg, _ = fri.fetch_sector_terminal_growth()
    for sector, g in tg.items():
        assert g <= fri.TERMINAL_GROWTH_CAP, (
            f"{sector} terminal_growth {g} exceeds cap "
            f"{fri.TERMINAL_GROWTH_CAP}"
        )


def test_terminal_growth_clips_above_cap_with_warning():
    bad = {"reckless": 0.10, "ok": 0.04}
    tg, warnings = fri.fetch_sector_terminal_growth(table=bad)
    assert tg["reckless"] == pytest.approx(fri.TERMINAL_GROWTH_CAP)
    assert tg["ok"] == pytest.approx(0.04)
    assert any("reckless" in w and "exceeds cap" in w for w in warnings)


def test_terminal_growth_skips_non_numeric_and_negative():
    bad = {"text": "oops", "neg": -0.01, "ok": 0.05}
    tg, warnings = fri.fetch_sector_terminal_growth(table=bad)
    assert "text" not in tg
    assert "neg" not in tg
    assert tg["ok"] == pytest.approx(0.05)
    assert any("text" in w for w in warnings)
    assert any("neg" in w for w in warnings)


# ── artifact shape ────────────────────────────────────────────────
def test_build_artifact_shape():
    art = fri.build_artifact(
        rf=0.072, rf_src="src",
        betas={"it_services": 1.05}, beta_src="b-src",
        tg={"default": 0.045, "it_services": 0.05}, tg_src="t-src",
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
        "risk_free_rate": 0.071,
        "sector_betas": {"it_services": 0.92, "fmcg": 0.70},
        "terminal_growth": {"default": 0.045,
                            "it_services": 0.045,
                            "fmcg": 0.050},  # fmcg unchanged
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
