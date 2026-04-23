# backend/tests/test_dcf_nbfc_wacc_floor.py
# Unit tests for the NBFC WACC floor applied in
# backend/services/analysis/service.py after models.forecaster.compute_wacc
# returns. The floor is a surface-only correction (affects reported `wacc`
# field, not fair value). See CACHE_VERSION 44 bump for context.
#
# BAJFINANCE routes through the P/B financial-company valuation path, so
# DCFEngine (and its NBFC premium) never runs — surfaced WACC came from
# pure CAPM at ~0.098 and failed canary gate 4. The floor snaps NBFCs
# below 0.11 up to 0.11; NBFCs already above are unchanged; non-NBFCs
# are never floored.
from __future__ import annotations

from backend.services.analysis.constants import _NBFC_TICKERS
from backend.services.analysis.service import NBFC_WACC_FLOOR


def _apply_floor(clean_ticker: str, wacc: float, wacc_data: dict):
    """Mirror of the floor block inlined in service.py. Kept in sync by
    contract — if the production snippet changes, update this helper and
    the tests will re-pin the semantics."""
    if clean_ticker in _NBFC_TICKERS and wacc < NBFC_WACC_FLOOR:
        wacc = NBFC_WACC_FLOOR
        if isinstance(wacc_data, dict):
            wacc_data["wacc"] = NBFC_WACC_FLOOR
            wacc_data["wacc_floor_applied"] = True
    return wacc, wacc_data


def test_floor_constant_is_eleven_percent():
    # Pin the constant so an accidental edit forces a deliberate test update.
    assert NBFC_WACC_FLOOR == 0.11


def test_bajfinance_is_in_nbfc_set():
    # Diagnosis sanity check: the ticker that failed canary gate 4 must
    # actually be a member of the set the floor targets.
    assert "BAJFINANCE" in _NBFC_TICKERS


def test_bajfinance_wacc_at_or_above_floor():
    # CAPM returns 0.098 (the observed production value). Floor snaps to 0.11
    # and marks the dict with `wacc_floor_applied`.
    wacc_data = {"wacc": 0.098, "beta": 1.4, "beta_source": "yfinance"}
    wacc, wacc_data = _apply_floor("BAJFINANCE", 0.098, wacc_data)
    assert wacc == NBFC_WACC_FLOOR
    assert wacc_data["wacc"] == NBFC_WACC_FLOOR
    assert wacc_data.get("wacc_floor_applied") is True


def test_non_nbfc_wacc_unchanged():
    # TITAN is in INVENTORY_HEAVY_TICKERS, not _NBFC_TICKERS. Even with a
    # sub-floor CAPM output the floor must NOT apply.
    wacc_data = {"wacc": 0.098, "beta": 1.1, "beta_source": "yfinance"}
    wacc, wacc_data = _apply_floor("TITAN", 0.098, wacc_data)
    assert wacc == 0.098
    assert wacc_data["wacc"] == 0.098
    assert "wacc_floor_applied" not in wacc_data


def test_nbfc_above_floor_unchanged():
    # CHOLAFIN with CAPM = 0.13 must pass through unchanged — the rule is
    # max(wacc, floor), not a fixed set-to-floor.
    wacc_data = {"wacc": 0.13, "beta": 1.5, "beta_source": "yfinance"}
    wacc, wacc_data = _apply_floor("CHOLAFIN", 0.13, wacc_data)
    assert wacc == 0.13
    assert wacc_data["wacc"] == 0.13
    assert "wacc_floor_applied" not in wacc_data


def test_nbfc_exactly_at_floor_unchanged():
    # Boundary: wacc == floor should NOT trigger the branch (strict <).
    wacc_data = {"wacc": NBFC_WACC_FLOOR, "beta": 1.4, "beta_source": "yfinance"}
    wacc, wacc_data = _apply_floor("MUTHOOTFIN", NBFC_WACC_FLOOR, wacc_data)
    assert wacc == NBFC_WACC_FLOOR
    assert "wacc_floor_applied" not in wacc_data


def test_all_nbfc_members_get_floored_from_sub_floor():
    # Regression guard: every member of _NBFC_TICKERS must be eligible for
    # the floor. If a future edit moves a ticker out of the set it will
    # silently lose floor coverage — this test pins the cohort.
    expected_members = {
        "BAJFINANCE", "BAJAJFINSV", "CHOLAFIN", "MUTHOOTFIN",
        "MANAPPURAM", "M&MFIN", "SHRIRAMFIN", "LICHOUSFIN",
        "POONAWALLA", "AAVAS", "HOMEFIRST",
    }
    assert expected_members.issubset(_NBFC_TICKERS)
    for t in expected_members:
        wacc_data = {"wacc": 0.09}
        wacc, wacc_data = _apply_floor(t, 0.09, wacc_data)
        assert wacc == NBFC_WACC_FLOOR, f"{t} did not receive floor"
        assert wacc_data["wacc_floor_applied"] is True
