"""Day-65 (2026-05-21): dividend sustainability classifier rewrite.

Audit 2026-05-20: ITC tagged 'At Risk · Payout 89%' --- a 5-year-
consistent payer at high but stable payout is the OPPOSITE of
at-risk. The old classifier triggered at-risk at payout > 90% with
no consideration of track record or coverage.

Rewrite uses coverage ratio + track record as primary at-risk
signals; raw payout % only escalates to at-risk when:
  - payout > 100%        (paying more than earnings — arithmetic)
  - coverage < 1.0       (FCF doesn't cover the dividend)
  - payout > 80% AND consecutive_years == 0 (unproven)

Strong gate unchanged: payout < 50 AND coverage >= 2 AND ≥5y record.
Everything else is moderate, with reason text picking the most
informative signal.
"""
from __future__ import annotations
import sys
from pathlib import Path

# Make backend importable
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def _classifier():
    """Pull the private method into a callable via a minimal stub."""
    from backend.services.dividend_service import DividendService
    return DividendService()._sustainability


# ── The ITC-class repro (the audit's smoking gun) ──────────


def test_itc_class_high_payout_long_record_is_moderate_not_at_risk():
    """ITC: payout 89%, coverage ~1.5x, 5+ year consistent payer.
    Old classifier said at_risk. New classifier must say moderate."""
    label, reason = _classifier()(payout_pct=89.0, coverage=1.5, consecutive_years=10)
    assert label == "moderate", f"got {label}, reason={reason!r}"
    assert "track record" in reason.lower()


def test_high_payout_no_record_stays_at_risk():
    """89% payout BUT 0-year track record → still at_risk
    (sustainability unproven)."""
    label, reason = _classifier()(payout_pct=85.0, coverage=1.5, consecutive_years=0)
    assert label == "at_risk"
    assert "track record" in reason.lower() or "unproven" in reason.lower()


def test_payout_exceeds_earnings_always_at_risk():
    """>100% payout → arithmetic problem, at_risk regardless of
    track record."""
    label, _ = _classifier()(payout_pct=120.0, coverage=2.0, consecutive_years=20)
    assert label == "at_risk"


def test_coverage_below_one_always_at_risk():
    """Coverage < 1.0 → at_risk regardless of payout % or record."""
    label, reason = _classifier()(payout_pct=40.0, coverage=0.8, consecutive_years=10)
    assert label == "at_risk"
    assert "0.8" in reason


# ── Strong-gate preserved ───────────────────────────────────


def test_low_payout_strong_coverage_long_record_is_strong():
    label, reason = _classifier()(payout_pct=35.0, coverage=3.0, consecutive_years=10)
    assert label == "strong"
    assert "healthy" in reason.lower()


def test_low_payout_long_record_no_coverage_data_still_strong():
    """The strong gate accepts coverage=None (data missing) per
    the OR clause."""
    label, _ = _classifier()(payout_pct=30.0, coverage=None, consecutive_years=8)
    assert label == "strong"


# ── Moderate fallback cases ─────────────────────────────────


def test_elevated_but_not_extreme_payout_is_moderate():
    """65% payout, decent coverage, no record → moderate (not at_risk)."""
    label, reason = _classifier()(payout_pct=65.0, coverage=1.5, consecutive_years=0)
    assert label == "moderate"
    assert "elevated" in reason.lower()


def test_short_record_low_payout_is_moderate():
    """40% payout but only 2-year record → not yet "strong", still
    moderate."""
    label, _ = _classifier()(payout_pct=40.0, coverage=2.5, consecutive_years=2)
    assert label == "moderate"


# ── No-data path ────────────────────────────────────────────


def test_no_data_is_moderate_with_caveat():
    label, reason = _classifier()(payout_pct=0.0, coverage=None, consecutive_years=0)
    assert label == "moderate"
    assert "limited data" in reason.lower()


# ── Boundary cases ──────────────────────────────────────────


def test_exactly_100_payout_is_not_yet_at_risk_gate1():
    """Boundary: strictly > 100% is the gate, so 100% itself falls
    through to other gates."""
    label, _ = _classifier()(payout_pct=100.0, coverage=1.5, consecutive_years=5)
    # Lands in the "moderate, elevated" path with long record
    assert label == "moderate"


def test_exactly_80_payout_no_record_is_moderate():
    """Boundary: strictly > 80 + 0-year is the gate, so 80 itself
    falls through."""
    label, _ = _classifier()(payout_pct=80.0, coverage=1.5, consecutive_years=0)
    assert label == "moderate"


def test_long_record_legitimately_at_risk_when_arithmetic_fails():
    """Even a 20-year payer is at_risk if payout suddenly >100%."""
    label, _ = _classifier()(payout_pct=110.0, coverage=2.0, consecutive_years=20)
    assert label == "at_risk"
