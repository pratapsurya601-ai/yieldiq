# backend/tests/test_multiples_fv.py
# ═══════════════════════════════════════════════════════════════
# Unit tests for backend/services/multiples_fv.py.
#
# Sprint A2 (2026-06-09) — DCF + Multiples cross-confirmation chip.
# The service is pure derivation from the response payload + the
# already-injected sector medians, so the tests need no DB / cache
# fixtures.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

from backend.services.multiples_fv import compute_multiples_fv


def _payload(price: float, pe: float | None = None, pb: float | None = None) -> dict:
    """Build the minimum payload shape compute_multiples_fv reads."""
    return {
        "valuation": {"current_price": price},
        "quality": {"pe_ratio": pe, "pb_ratio": pb},
    }


class TestComputeMultiplesFv:
    """Path coverage for the (payload, sector_medians) -> (fv, method) function."""

    def test_pe_path_picked_when_available(self):
        # DABUR-shaped fixture: PE 55, sector median PE 50, price 420.
        # FV = 420 * (50 / 55) = ~381.82
        payload = _payload(price=420.0, pe=55.0, pb=10.0)
        medians = {"pe": 50.0, "pb": 9.5}
        fv, method = compute_multiples_fv(payload, medians)
        assert method == "pe"
        assert fv is not None
        assert abs(fv - 381.82) < 0.05

    def test_pb_fallback_when_pe_missing(self):
        # Bank-shaped: PE missing, PB 2.0, sector median PB 1.6.
        # FV = 1500 * (1.6 / 2.0) = 1200
        payload = _payload(price=1500.0, pe=None, pb=2.0)
        medians = {"pe": None, "pb": 1.6}
        fv, method = compute_multiples_fv(payload, medians)
        assert method == "pb"
        assert fv == 1200.0

    def test_pb_fallback_when_pe_negative(self):
        # Loss-making ticker: PE = -25, sector median PE present.
        # PE path is skipped (non-positive), PB takes over.
        payload = _payload(price=100.0, pe=-25.0, pb=4.0)
        medians = {"pe": 18.0, "pb": 3.0}
        fv, method = compute_multiples_fv(payload, medians)
        assert method == "pb"
        assert fv == 75.0

    def test_returns_none_when_both_paths_fail(self):
        # Out-of-cohort ticker — both medians missing.
        payload = _payload(price=420.0, pe=55.0, pb=10.0)
        medians = {"pe": None, "pb": None}
        fv, method = compute_multiples_fv(payload, medians)
        assert fv is None
        assert method is None

    def test_returns_none_when_price_missing(self):
        payload = {"valuation": {"current_price": None}, "quality": {"pe_ratio": 55.0}}
        medians = {"pe": 50.0, "pb": 9.5}
        fv, method = compute_multiples_fv(payload, medians)
        assert fv is None
        assert method is None

    def test_returns_none_when_medians_dict_is_none(self):
        payload = _payload(price=420.0, pe=55.0)
        fv, method = compute_multiples_fv(payload, None)
        assert fv is None
        assert method is None

    def test_returns_none_when_ticker_pe_and_pb_both_missing(self):
        payload = _payload(price=420.0, pe=None, pb=None)
        medians = {"pe": 50.0, "pb": 9.5}
        fv, method = compute_multiples_fv(payload, medians)
        assert fv is None
        assert method is None

    def test_handles_string_inputs_via_coercion(self):
        # Cache writers sometimes leave numeric strings on the payload.
        payload = {
            "valuation": {"current_price": "420"},
            "quality": {"pe_ratio": "55", "pb_ratio": "10"},
        }
        medians = {"pe": "50", "pb": "9.5"}
        fv, method = compute_multiples_fv(payload, medians)
        assert method == "pe"
        assert fv is not None
        assert abs(fv - 381.82) < 0.05

    def test_handles_nan_inputs(self):
        # NaN in any slot should drop that slot — and route to the next path.
        payload = _payload(price=420.0, pe=float("nan"), pb=10.0)
        medians = {"pe": 50.0, "pb": 9.5}
        fv, method = compute_multiples_fv(payload, medians)
        assert method == "pb"
        assert fv is not None

    def test_handles_non_dict_payload(self):
        fv, method = compute_multiples_fv(None, {"pe": 50.0})  # type: ignore[arg-type]
        assert fv is None
        assert method is None

    def test_rounding_is_2dp(self):
        # Make the math come out to a non-trivial decimal.
        payload = _payload(price=100.0, pe=3.0, pb=None)
        medians = {"pe": 1.0, "pb": None}
        fv, method = compute_multiples_fv(payload, medians)
        assert method == "pe"
        assert fv == 33.33  # 100 * 1/3 = 33.333... rounded
