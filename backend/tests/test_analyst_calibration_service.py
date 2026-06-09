"""T1.5 Phase A — analyst calibration service unit tests.

Pins the read-only deviation-report semantics:

  - YieldIQ FV is read from ``valuation.fair_value``.
  - Wall St avg is read from ``analyst_consensus.price_target.mean``,
    with ``insight_cards.wall_street_avg_target`` as a legacy fallback.
  - Tickers without BOTH sides are skipped (coverage drops, no raise).
  - Signed deviation polarity: positive => YIQ above the herd.
  - Aligned threshold is inclusive on the boundary.
  - By-sector bucketing handles None as ``Unknown``.
  - Top-outliers sorted by abs_deviation descending.
  - Empty universe returns a zero summary, not a crash.

All tests use the ``data_provider`` injection — no DB / cache /
network is touched. Phase B (the endpoint wiring) will own its own
integration tests against the real cache layer.
"""
from __future__ import annotations

from backend.services.analyst_calibration_service import (
    DEFAULT_ALIGNED_THRESHOLD,
    UNKNOWN_SECTOR_BUCKET,
    CalibrationDatapoint,
    CalibrationSummary,
    compute_calibration_report,
    to_dict,
)


# ─────────────────────────────────────────────────────────────────
# Payload builders — keep the tests' setup tight + readable.
# ─────────────────────────────────────────────────────────────────


def _payload(
    fv: float | None,
    wall_avg: float | None,
    *,
    sector: str | None = "IT",
    analyst_count: int | None = 12,
    legacy: bool = False,
) -> dict:
    """Build a minimal analysis-response payload.

    By default, populates the preferred ``analyst_consensus.price_target.
    mean`` field. When ``legacy=True``, populates the
    ``insight_cards.wall_street_avg_target`` fallback path instead, so
    the extractor's fallback branch is exercised.

    Any positional value passed as None is omitted from the payload,
    which is what the engine emits when the upstream data is missing.
    """
    payload: dict = {"company": {"sector": sector}}
    if fv is not None:
        payload["valuation"] = {"fair_value": fv}
    if wall_avg is not None:
        if legacy:
            payload["insight_cards"] = {
                "wall_street_avg_target": wall_avg,
                "wall_street_target_count": analyst_count,
            }
        else:
            payload["analyst_consensus"] = {
                "coverage_count": analyst_count,
                "price_target": {"mean": wall_avg},
            }
    return payload


def _provider(mapping: dict[str, dict | None]):
    """Build a data_provider that returns mapping[ticker] or None."""
    def _get(ticker: str):
        return mapping.get(ticker)
    return _get


# ─────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────


def test_three_tickers_full_coverage_summary_computes():
    """All three tickers have both sides — coverage == total == 3."""
    data = {
        "A.NS": _payload(110.0, 100.0, sector="IT"),     # +10% (above)
        "B.NS": _payload(90.0, 100.0, sector="IT"),      # -10% (below)
        "C.NS": _payload(102.0, 100.0, sector="Banks"),  # +2% (aligned)
    }
    summary = compute_calibration_report(
        tickers=list(data.keys()),
        data_provider=_provider(data),
    )
    assert summary.total_tickers == 3
    assert summary.coverage_tickers == 3
    assert summary.above_wall_st == 1
    assert summary.below_wall_st == 1
    assert summary.aligned == 1
    # median |dev| of {0.10, 0.10, 0.02} == 0.10
    assert abs(summary.median_abs_deviation_pct - 0.10) < 1e-9
    # signed mean of {+0.10, -0.10, +0.02} == +0.02/3 ~= 0.00666...
    assert abs(summary.mean_signed_deviation_pct - (0.02 / 3)) < 1e-9


def test_missing_wall_st_skipped_drops_coverage():
    """A ticker without a Wall St avg is excluded from coverage."""
    data = {
        "A.NS": _payload(110.0, 100.0),                # full
        "B.NS": _payload(90.0, None),                  # no wall-st  -> skip
        "C.NS": _payload(105.0, 100.0),                # full
    }
    summary = compute_calibration_report(
        tickers=list(data.keys()),
        data_provider=_provider(data),
    )
    assert summary.total_tickers == 3
    assert summary.coverage_tickers == 2


def test_missing_yieldiq_fv_skipped():
    """A ticker without a YieldIQ FV is excluded from coverage."""
    data = {
        "A.NS": _payload(None, 100.0),  # no FV       -> skip
        "B.NS": _payload(120.0, 100.0),
    }
    summary = compute_calibration_report(
        tickers=list(data.keys()),
        data_provider=_provider(data),
    )
    assert summary.total_tickers == 2
    assert summary.coverage_tickers == 1


def test_all_yiq_above_wall_st_positive_signed_mean():
    """When every YIQ FV exceeds Wall St, mean_signed_deviation > 0."""
    data = {
        "A.NS": _payload(120.0, 100.0),  # +20%
        "B.NS": _payload(115.0, 100.0),  # +15%
        "C.NS": _payload(140.0, 100.0),  # +40%
    }
    summary = compute_calibration_report(
        tickers=list(data.keys()),
        data_provider=_provider(data),
    )
    assert summary.mean_signed_deviation_pct > 0
    assert summary.above_wall_st == 3
    assert summary.below_wall_st == 0
    assert summary.aligned == 0


def test_all_yiq_below_wall_st_negative_signed_mean():
    """When every YIQ FV undercuts Wall St, mean_signed_deviation < 0."""
    data = {
        "A.NS": _payload(80.0, 100.0),   # -20%
        "B.NS": _payload(85.0, 100.0),   # -15%
        "C.NS": _payload(60.0, 100.0),   # -40%
    }
    summary = compute_calibration_report(
        tickers=list(data.keys()),
        data_provider=_provider(data),
    )
    assert summary.mean_signed_deviation_pct < 0
    assert summary.above_wall_st == 0
    assert summary.below_wall_st == 3
    assert summary.aligned == 0


def test_mixed_devs_near_zero_signed_mean():
    """Symmetric mix of +/- deviations -> mean signed close to zero."""
    data = {
        "A.NS": _payload(120.0, 100.0),  # +20%
        "B.NS": _payload(80.0, 100.0),   # -20%
        "C.NS": _payload(110.0, 100.0),  # +10%
        "D.NS": _payload(90.0, 100.0),   # -10%
    }
    summary = compute_calibration_report(
        tickers=list(data.keys()),
        data_provider=_provider(data),
    )
    assert abs(summary.mean_signed_deviation_pct) < 1e-9


def test_aligned_threshold_respected_4pct_and_6pct():
    """4% deviation is aligned at 5% threshold; 6% is not."""
    data = {
        "FOUR.NS": _payload(104.0, 100.0),   # +4% — aligned
        "SIX.NS":  _payload(106.0, 100.0),   # +6% — not aligned (above)
        "MINUS4.NS": _payload(96.0, 100.0),  # -4% — aligned
        "MINUS6.NS": _payload(94.0, 100.0),  # -6% — not aligned (below)
    }
    summary = compute_calibration_report(
        tickers=list(data.keys()),
        data_provider=_provider(data),
        aligned_threshold=0.05,
    )
    assert summary.aligned == 2
    assert summary.above_wall_st == 1
    assert summary.below_wall_st == 1


def test_aligned_threshold_inclusive_on_boundary():
    """Exactly-at-threshold deviation is treated as aligned."""
    data = {
        "EDGE.NS": _payload(105.0, 100.0),   # +5% exactly
    }
    summary = compute_calibration_report(
        tickers=list(data.keys()),
        data_provider=_provider(data),
        aligned_threshold=0.05,
    )
    assert summary.aligned == 1
    assert summary.above_wall_st == 0


def test_by_sector_bucketing_two_sectors_correct_counts():
    """Per-sector aggregator buckets correctly and tracks signed bias."""
    data = {
        "IT1.NS": _payload(120.0, 100.0, sector="IT"),    # +20%
        "IT2.NS": _payload(110.0, 100.0, sector="IT"),    # +10%
        "BNK1.NS": _payload(80.0, 100.0, sector="Banks"), # -20%
        "BNK2.NS": _payload(85.0, 100.0, sector="Banks"), # -15%
        "BNK3.NS": _payload(90.0, 100.0, sector="Banks"), # -10%
    }
    summary = compute_calibration_report(
        tickers=list(data.keys()),
        data_provider=_provider(data),
    )
    assert set(summary.by_sector.keys()) == {"IT", "Banks"}
    assert summary.by_sector["IT"]["count"] == 2
    assert summary.by_sector["Banks"]["count"] == 3
    # IT median |dev| of {0.10, 0.20} == 0.15
    assert abs(summary.by_sector["IT"]["median_abs_dev"] - 0.15) < 1e-9
    # Banks signed bias < 0 (all undercutting), IT > 0 (all above).
    assert summary.by_sector["Banks"]["signed_bias"] < 0
    assert summary.by_sector["IT"]["signed_bias"] > 0


def test_top_outliers_sorted_descending_by_abs_dev():
    """top_outliers list is sorted by |deviation| descending."""
    data = {
        "SMALL.NS":  _payload(102.0, 100.0),   # +2%
        "BIG.NS":    _payload(180.0, 100.0),   # +80%
        "MEDIUM.NS": _payload(70.0, 100.0),    # -30%
        "TINY.NS":   _payload(101.0, 100.0),   # +1%
    }
    summary = compute_calibration_report(
        tickers=list(data.keys()),
        data_provider=_provider(data),
    )
    # All four covered.
    assert summary.coverage_tickers == 4
    # BIG should be first, MEDIUM second, SMALL third, TINY last.
    order = [d.ticker for d in summary.top_outliers]
    assert order[0] == "BIG.NS"
    assert order[1] == "MEDIUM.NS"
    assert order[2] == "SMALL.NS"
    assert order[3] == "TINY.NS"


def test_top_outliers_capped_at_ten():
    """If >10 covered tickers, top_outliers contains exactly 10."""
    data = {
        f"T{i}.NS": _payload(100.0 + i, 100.0) for i in range(1, 25)
    }
    summary = compute_calibration_report(
        tickers=list(data.keys()),
        data_provider=_provider(data),
    )
    assert summary.coverage_tickers == 24
    assert len(summary.top_outliers) == 10


def test_empty_tickers_returns_zero_summary_no_crash():
    """Empty input universe -> zero counts, no exception."""
    summary = compute_calibration_report(
        tickers=[],
        data_provider=_provider({}),
    )
    assert isinstance(summary, CalibrationSummary)
    assert summary.total_tickers == 0
    assert summary.coverage_tickers == 0
    assert summary.above_wall_st == 0
    assert summary.below_wall_st == 0
    assert summary.aligned == 0
    assert summary.median_abs_deviation_pct == 0.0
    assert summary.p90_abs_deviation_pct == 0.0
    assert summary.mean_signed_deviation_pct == 0.0
    assert summary.by_sector == {}
    assert summary.top_outliers == []
    assert summary.generated_at  # ISO string non-empty


def test_sector_none_buckets_under_unknown():
    """Tickers with sector=None bucket under the 'Unknown' label."""
    data = {
        "NS1.NS": _payload(120.0, 100.0, sector=None),
        "NS2.NS": _payload(80.0, 100.0, sector=None),
        "KNOWN.NS": _payload(110.0, 100.0, sector="IT"),
    }
    summary = compute_calibration_report(
        tickers=list(data.keys()),
        data_provider=_provider(data),
    )
    assert UNKNOWN_SECTOR_BUCKET in summary.by_sector
    assert summary.by_sector[UNKNOWN_SECTOR_BUCKET]["count"] == 2
    assert summary.by_sector["IT"]["count"] == 1


def test_sector_empty_string_treated_as_missing():
    """An empty / whitespace-only sector string is treated as missing."""
    data = {
        "EMPTY.NS": _payload(120.0, 100.0, sector="   "),
        "BLANK.NS": _payload(80.0, 100.0, sector=""),
    }
    summary = compute_calibration_report(
        tickers=list(data.keys()),
        data_provider=_provider(data),
    )
    assert UNKNOWN_SECTOR_BUCKET in summary.by_sector
    assert summary.by_sector[UNKNOWN_SECTOR_BUCKET]["count"] == 2


def test_legacy_wall_street_avg_target_fallback_used():
    """When analyst_consensus is absent, legacy field is read."""
    data = {
        "LEG.NS": _payload(120.0, 100.0, legacy=True, analyst_count=5),
    }
    summary = compute_calibration_report(
        tickers=list(data.keys()),
        data_provider=_provider(data),
    )
    assert summary.coverage_tickers == 1
    assert summary.top_outliers[0].analyst_count == 5
    assert abs(summary.top_outliers[0].deviation_pct - 0.20) < 1e-9


def test_provider_returning_none_skips_silently():
    """When provider returns None, ticker is excluded from coverage."""
    data: dict[str, dict | None] = {
        "GOOD.NS": _payload(110.0, 100.0),
        "GONE.NS": None,  # provider returns None — must not raise
    }
    summary = compute_calibration_report(
        tickers=list(data.keys()),
        data_provider=_provider(data),
    )
    assert summary.total_tickers == 2
    assert summary.coverage_tickers == 1


def test_provider_raising_does_not_propagate():
    """When provider raises on a ticker, others still flow through."""
    def _raises(ticker: str):
        if ticker == "BAD.NS":
            raise RuntimeError("simulated upstream failure")
        return _payload(110.0, 100.0)

    summary = compute_calibration_report(
        tickers=["GOOD.NS", "BAD.NS", "ALSO_GOOD.NS"],
        data_provider=_raises,
    )
    assert summary.total_tickers == 3
    assert summary.coverage_tickers == 2


def test_non_positive_fair_value_treated_as_missing():
    """fair_value == 0 (the engine's data_limited sentinel) -> skip."""
    data = {
        "ZERO.NS": _payload(0.0, 100.0),       # FV=0 -> skip
        "NEG.NS":  _payload(-5.0, 100.0),      # FV<0 -> skip
        "GOOD.NS": _payload(110.0, 100.0),
    }
    summary = compute_calibration_report(
        tickers=list(data.keys()),
        data_provider=_provider(data),
    )
    assert summary.coverage_tickers == 1


def test_non_positive_wall_st_target_treated_as_missing():
    """wall_st_avg <= 0 (nonsense data) -> skip."""
    data = {
        "ZERO.NS": _payload(110.0, 0.0),       # avg=0 -> skip
        "NEG.NS":  _payload(110.0, -50.0),     # avg<0 -> skip
        "GOOD.NS": _payload(110.0, 100.0),
    }
    summary = compute_calibration_report(
        tickers=list(data.keys()),
        data_provider=_provider(data),
    )
    assert summary.coverage_tickers == 1


def test_default_aligned_threshold_is_five_percent():
    """Sanity: the public default constant matches the brief."""
    assert DEFAULT_ALIGNED_THRESHOLD == 0.05


def test_to_dict_is_json_safe():
    """to_dict() output round-trips through json.dumps without error."""
    import json
    data = {
        "A.NS": _payload(120.0, 100.0, sector="IT"),
        "B.NS": _payload(80.0, 100.0, sector="Banks"),
    }
    summary = compute_calibration_report(
        tickers=list(data.keys()),
        data_provider=_provider(data),
    )
    serialized = to_dict(summary)
    encoded = json.dumps(serialized)
    decoded = json.loads(encoded)
    assert decoded["coverage_tickers"] == 2
    assert isinstance(decoded["top_outliers"], list)
    assert decoded["top_outliers"][0]["ticker"] in {"A.NS", "B.NS"}
    assert "deviation_pct" in decoded["top_outliers"][0]


def test_p90_above_median_when_skewed():
    """Verify p90 > median on a skewed distribution (sanity)."""
    # 9 small + 1 huge -> p90 should pull toward the huge outlier.
    data = {
        f"SMALL{i}.NS": _payload(101.0, 100.0)  # +1%
        for i in range(9)
    }
    data["HUGE.NS"] = _payload(200.0, 100.0)    # +100%
    summary = compute_calibration_report(
        tickers=list(data.keys()),
        data_provider=_provider(data),
    )
    assert summary.coverage_tickers == 10
    assert summary.median_abs_deviation_pct < summary.p90_abs_deviation_pct


def test_datapoint_to_dict_round_trip():
    """CalibrationDatapoint.to_dict() carries every public field."""
    dp = CalibrationDatapoint(
        ticker="X.NS",
        yieldiq_fv=110.0,
        wall_st_avg=100.0,
        deviation_pct=0.10,
        abs_deviation_pct=0.10,
        direction="yieldiq_above",
        analyst_count=8,
        sector="IT",
    )
    d = dp.to_dict()
    assert d["ticker"] == "X.NS"
    assert d["analyst_count"] == 8
    assert d["direction"] == "yieldiq_above"
    assert d["sector"] == "IT"
