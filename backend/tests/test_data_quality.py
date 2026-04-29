# backend/tests/test_data_quality.py
# Unit tests for backend.services.data_quality.data_completeness_score.
#
# DB-less tests use db_session=None so the inner SELECTs all fall
# through to their default (count=0, has_*=False) branches. We
# assert the scoring weights produce the expected zero-input score
# and that the classifier-confidence component is wired in.
from __future__ import annotations

from backend.services.data_quality import (
    data_completeness_score,
    YIELDIQ50_MIN_COMPLETENESS,
    CompletenessReport,
    _W_ANNUALS,
    _W_KEY_FIELDS,
    _W_CLASSIFIER,
    _W_QUALITY,
    _W_MARKET_CAP,
)


def test_threshold_value():
    # Pinned: any change to this constant changes the YieldIQ 50
    # gate behaviour and requires a CACHE_VERSION bump.
    assert YIELDIQ50_MIN_COMPLETENESS == 0.70


def test_weights_sum_to_one():
    total = _W_ANNUALS + _W_KEY_FIELDS + _W_CLASSIFIER + _W_QUALITY + _W_MARKET_CAP
    assert abs(total - 1.0) < 1e-9


def test_dbless_known_ticker_gets_classifier_credit():
    # HDFCBANK resolves via the BANK name-pattern (confidence 0.55).
    # With no DB the score should be _W_CLASSIFIER * 0.55 (only the
    # classifier component contributes credit; all other inputs zero).
    rep = data_completeness_score("HDFCBANK.NS", db_session=None)
    assert isinstance(rep, CompletenessReport)
    assert rep.annual_rows == 0
    assert rep.has_key_fields is False
    assert rep.has_quality_metrics is False
    assert rep.has_market_cap is False
    expected = _W_CLASSIFIER * rep.classifier_confidence
    assert abs(rep.score - expected) < 1e-3
    # Below the gate — correct (no DB, can't trust the row).
    assert rep.score < YIELDIQ50_MIN_COMPLETENESS


def test_dbless_unknown_ticker_low_confidence():
    rep = data_completeness_score("ZZZUNKNOWN.NS", db_session=None)
    assert rep.score < 0.05  # only 0.15 * 0.1 classifier-fallback credit
    assert "no_annual_financials" in rep.notes
    assert "missing_market_cap" in rep.notes


def test_report_to_dict_round_trip():
    rep = data_completeness_score("HDFCBANK.NS", db_session=None)
    d = rep.to_dict()
    assert d["ticker"] == "HDFCBANK.NS"
    assert d["canonical_sector"] == "Banks"
    assert "score" in d
    assert isinstance(d["notes"], list)


def test_score_bounded_zero_to_one():
    # Even a name we know nothing about must produce a valid score.
    rep = data_completeness_score("WHATEVER.NS", db_session=None)
    assert 0.0 <= rep.score <= 1.0
