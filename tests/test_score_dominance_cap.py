"""Tests for the Score-MoS dominance cap exemption.

The dominance cap (backend/services/analysis/service.py ~lines 1906-1934)
caps the composite YIQ score based on |MoS| magnitude so a deeply
overvalued name cannot ride moat/Piotroski to a misleading score.

EXEMPTION (2026-05-03): tickers with an explicit ``model_caveat`` in
their ticker_overrides entry bypass the cap. We've already declared the
DCF approximate for these names (ITC, RELIANCE, etc.) — capping the
composite based on the model's MoS contradicts the caveat.

These tests exercise the cap logic in isolation by replicating the
production block with the override-aware skip flag.
"""
from __future__ import annotations

import pytest

from backend.services.analysis.ticker_overrides import (
    get_override as _get_ticker_override,
)


def _apply_dominance_cap(
    ticker: str,
    mos_pct: float,
    yiq_score: dict,
) -> dict:
    """Mirror of the production cap logic in service.py.

    Kept in lockstep with the implementation. If the production cap
    changes, update this helper and its callers.
    """
    try:
        _override = _get_ticker_override(ticker)
    except Exception:
        _override = None
    _skip_dominance_cap = bool(
        _override and _override.get("model_caveat")
    )
    try:
        if (
            mos_pct is not None
            and yiq_score
            and "score" in yiq_score
            and not _skip_dominance_cap
        ):
            _mos_abs = abs(mos_pct)
            if _mos_abs > 50:
                _composite_max = 40
            elif _mos_abs > 30:
                _composite_max = 50
            elif _mos_abs > 15:
                _composite_max = 65
            else:
                _composite_max = 100
            _orig_score = int(yiq_score.get("score", 0) or 0)
            if _orig_score > _composite_max:
                yiq_score["score"] = _composite_max
                _cap = _composite_max
                yiq_score["grade"] = (
                    "A" if _cap >= 75
                    else "B" if _cap >= 55
                    else "C" if _cap >= 35
                    else "D" if _cap >= 20
                    else "F"
                )
    except Exception:
        pass
    return yiq_score


class TestDominanceCapNoOverride:
    """Plain tickers (no override) get the cap applied as before."""

    def test_no_override_extreme_mos_caps_to_40(self):
        # Use a ticker that has no override entry.
        score = {"score": 75, "grade": "A"}
        out = _apply_dominance_cap("ZZZ_NO_OVERRIDE_TICKER", -60.0, score)
        assert out["score"] == 40
        assert out["grade"] == "C"

    def test_no_override_moderate_mos_caps_to_65(self):
        score = {"score": 80, "grade": "A"}
        out = _apply_dominance_cap("ZZZ_NO_OVERRIDE_TICKER", -20.0, score)
        assert out["score"] == 65
        assert out["grade"] == "B"

    def test_no_override_small_mos_no_cap(self):
        score = {"score": 80, "grade": "A"}
        out = _apply_dominance_cap("ZZZ_NO_OVERRIDE_TICKER", -5.0, score)
        assert out["score"] == 80
        assert out["grade"] == "A"


class TestDominanceCapWithOverride:
    """Tickers with model_caveat overrides bypass the cap."""

    def test_itc_extreme_mos_bypasses_cap(self):
        """ITC has model_caveat — even with |MoS|>50% the raw score flows."""
        # Sanity: confirm fixture has the expected shape.
        ov = _get_ticker_override("ITC")
        assert ov is not None
        assert ov.get("model_caveat"), (
            "test fixture invalid: ITC override should carry model_caveat"
        )

        score = {"score": 75, "grade": "A"}
        out = _apply_dominance_cap("ITC", -60.0, score)
        # Cap NOT applied — raw score and grade preserved.
        assert out["score"] == 75
        assert out["grade"] == "A"

    def test_reliance_extreme_mos_bypasses_cap(self):
        ov = _get_ticker_override("RELIANCE")
        assert ov is not None and ov.get("model_caveat")

        score = {"score": 70, "grade": "B"}
        out = _apply_dominance_cap("RELIANCE", 80.0, score)
        assert out["score"] == 70
        assert out["grade"] == "B"

    def test_itc_alias_also_bypasses_cap(self):
        """ITC.NS is aliased to ITC and should also bypass the cap."""
        ov = _get_ticker_override("ITC.NS")
        assert ov is not None and ov.get("model_caveat")

        score = {"score": 72, "grade": "A"}
        out = _apply_dominance_cap("ITC.NS", -55.0, score)
        assert out["score"] == 72


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
