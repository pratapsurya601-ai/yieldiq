"""Tests for backend.services.coverage_tier_service.

Coverage tier is labeling-only (does NOT touch FV/score/verdict), so
these tests focus on the rubric edges. The DB layer is bypassed by
calling `_evaluate_criteria` and `_assign_tier` directly with hand-rolled
signal dicts — that lets us assert the boundary conditions without
spinning up Postgres.

Specifically we verify:
  * A perfect 7/7 produces Tier A.
  * Just-shy-of-A (one criterion at the threshold-minus-one) produces B.
  * A score of 5/7 still produces B (the "partial" floor).
  * A score of 4/7 drops to C.
  * Even with 5/7 strict passes, breaching the Tier B floor (e.g. 1y
    of annual data) drops to C.
  * Missing-data signals (None) count as failures, never as passes.

Run:
    python -m pytest tests/test_coverage_tier_service.py -v
"""

from __future__ import annotations

import os
import sys
import unittest

# Make the repo root importable regardless of where pytest is invoked from.
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from backend.services import coverage_tier_service as cts


def _signals_perfect() -> dict:
    """Build a signals dict that should pass every criterion."""
    return {
        "annual_years": 15,
        "quarter_count": 12,
        "peer_cohort": 25,
        "market_cap_cr": 250_000.0,
        "validator_warnings": 0,
        "latest_annual_age_days": 120,
        "shares_outstanding": 1_350_000_000.0,
        "sector": "Energy",
    }


class TestRubricEdges(unittest.TestCase):
    """Boundary tests for the 7-criteria rubric."""

    def test_perfect_signals_yield_tier_A(self) -> None:
        signals = _signals_perfect()
        criteria = cts._evaluate_criteria(signals)
        tier, _ = cts._assign_tier(criteria, signals)
        self.assertEqual(tier, "A")
        self.assertTrue(all(c["passed"] for c in criteria))

    def test_just_shy_of_A_drops_to_B(self) -> None:
        # 6/7: validator_warnings = 1 fails the strict 0-warning bar but
        # everything else still passes. Floors are well clear.
        signals = _signals_perfect()
        signals["validator_warnings"] = 1
        criteria = cts._evaluate_criteria(signals)
        tier, reasons = cts._assign_tier(criteria, signals)
        self.assertEqual(tier, "B")
        self.assertTrue(any("validator" in r.lower() for r in reasons))

    def test_five_of_seven_with_floors_ok_is_B(self) -> None:
        # Fail two strict criteria but stay above Tier B floors.
        signals = _signals_perfect()
        signals["annual_years"] = 7        # below A=10, above B=5
        signals["peer_cohort"] = 6         # below A=10, above B=5
        criteria = cts._evaluate_criteria(signals)
        n_passed = sum(1 for c in criteria if c["passed"])
        self.assertEqual(n_passed, 5)
        tier, _ = cts._assign_tier(criteria, signals)
        self.assertEqual(tier, "B")

    def test_four_of_seven_drops_to_C(self) -> None:
        # Fail three strict criteria → only 4 pass → C.
        signals = _signals_perfect()
        signals["annual_years"] = 6
        signals["peer_cohort"] = 6
        signals["validator_warnings"] = 2
        criteria = cts._evaluate_criteria(signals)
        n_passed = sum(1 for c in criteria if c["passed"])
        self.assertEqual(n_passed, 4)
        tier, _ = cts._assign_tier(criteria, signals)
        self.assertEqual(tier, "C")

    def test_floor_breach_pulls_5_of_7_down_to_C(self) -> None:
        # 5/7 strict passes BUT only 1y of annual data — Tier B requires
        # >= 5y. Should drop to C even though the count would otherwise
        # qualify for B.
        signals = _signals_perfect()
        signals["annual_years"] = 1   # fails BOTH A and B floors
        signals["peer_cohort"] = 7    # fails A only
        criteria = cts._evaluate_criteria(signals)
        n_passed = sum(1 for c in criteria if c["passed"])
        self.assertEqual(n_passed, 5)
        tier, _ = cts._assign_tier(criteria, signals)
        self.assertEqual(tier, "C")

    def test_micro_cap_floor_breach_drops_to_C(self) -> None:
        # mcap below the Tier B floor (₹2,000 cr) should drop to C even
        # if other inputs look fine.
        signals = _signals_perfect()
        signals["market_cap_cr"] = 800.0   # below B floor of 2000
        signals["validator_warnings"] = 1  # fail one more to land at 5/7
        criteria = cts._evaluate_criteria(signals)
        n_passed = sum(1 for c in criteria if c["passed"])
        self.assertEqual(n_passed, 5)
        tier, _ = cts._assign_tier(criteria, signals)
        self.assertEqual(tier, "C")

    def test_missing_signals_treated_as_failures(self) -> None:
        # All-None signals: nothing passes → C.
        signals = {
            "annual_years": None,
            "quarter_count": None,
            "peer_cohort": None,
            "market_cap_cr": None,
            "validator_warnings": None,
            "latest_annual_age_days": None,
            "shares_outstanding": None,
            "sector": None,
        }
        criteria = cts._evaluate_criteria(signals)
        for c in criteria:
            self.assertFalse(c["passed"], f"{c['key']} should fail on missing data")
        tier, _ = cts._assign_tier(criteria, signals)
        self.assertEqual(tier, "C")

    def test_recent_xbrl_boundary(self) -> None:
        # Exactly at the threshold passes; one day over fails.
        signals = _signals_perfect()
        signals["latest_annual_age_days"] = cts.RECENT_XBRL_DAYS
        criteria = cts._evaluate_criteria(signals)
        recent = next(c for c in criteria if c["key"] == "recent_xbrl")
        self.assertTrue(recent["passed"])

        signals["latest_annual_age_days"] = cts.RECENT_XBRL_DAYS + 1
        criteria = cts._evaluate_criteria(signals)
        recent = next(c for c in criteria if c["key"] == "recent_xbrl")
        self.assertFalse(recent["passed"])

    def test_zero_shares_fails_shares_data(self) -> None:
        signals = _signals_perfect()
        signals["shares_outstanding"] = 0.0
        criteria = cts._evaluate_criteria(signals)
        sd = next(c for c in criteria if c["key"] == "shares_data")
        self.assertFalse(sd["passed"])


class TestComputeCoverageTierShape(unittest.TestCase):
    """Shape contract for the public compute_coverage_tier() entrypoint."""

    def test_failure_returns_safe_C(self) -> None:
        # _gather_signals will return all-None when DB is unreachable in
        # the test env. compute_coverage_tier must still return a
        # well-formed dict (never raise).
        out = cts.compute_coverage_tier("__NONEXISTENT__.NS", refresh=True)
        self.assertIn(out["tier"], {"A", "B", "C"})
        self.assertIn("criteria_met", out)
        self.assertIn("rubric", out)
        self.assertIn("reasons", out)
        self.assertEqual(out["criteria_total"], 7)


if __name__ == "__main__":
    unittest.main()
