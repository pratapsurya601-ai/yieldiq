"""Day-90 (2026-05-22): tax-loss harvesting calculator unit tests.

This is the user's MONEY math — a 1-day boundary bug on the ST/LT
bucket misclassifies the position and gives a WRONG tax-saved
estimate. We test the 12-month boundary explicitly: 11.9mo / 12mo /
12.1mo. We also test the offset cascade rules (STCL offsets both;
LTCL offsets only LTCG) because mis-applying these would also give
the user a wrong number.
"""
from __future__ import annotations

from datetime import date

import pytest

from backend.services.tlh_service import (
    LTCG_EXEMPTION_RS,
    LTCG_RATE,
    LT_HOLDING_MONTHS,
    STCG_RATE,
    classify_bucket,
    compute_suggestions,
    fy_for_date,
    months_held,
)


# ── Bucket boundary: this is the money-critical test ──────────


def test_months_held_exactly_12_is_long_term():
    """Position bought 2024-01-15, sold 2025-01-15 = 12mo exactly.
    Per CBDT, "held for more than 12 months" is interpreted as the
    12-month anniversary itself qualifying for LT. Off-by-one here
    would cost users (20% vs 12.5% rate)."""
    assert months_held(date(2024, 1, 15), date(2025, 1, 15)) == 12
    assert classify_bucket(date(2024, 1, 15), date(2025, 1, 15)) == "LT"


def test_months_held_one_day_short_is_short_term():
    """One day shy of 12 months -> still ST. This is the most
    common boundary mistake."""
    assert months_held(date(2024, 1, 15), date(2025, 1, 14)) == 11
    assert classify_bucket(date(2024, 1, 15), date(2025, 1, 14)) == "ST"


def test_months_held_one_day_over_is_long_term():
    assert months_held(date(2024, 1, 15), date(2025, 1, 16)) == 12
    assert classify_bucket(date(2024, 1, 15), date(2025, 1, 16)) == "LT"


def test_months_held_11_months_is_short_term():
    """11.9-ish months -> ST. Mid-month boundary case."""
    bucket = classify_bucket(date(2024, 6, 1), date(2025, 5, 15))
    assert bucket == "ST"


def test_months_held_13_months_is_long_term():
    """12.1-ish months -> LT."""
    bucket = classify_bucket(date(2024, 1, 1), date(2025, 2, 5))
    assert bucket == "LT"


def test_missing_acquired_date_defaults_to_short_term():
    """When buy date is unknown, classify as ST (conservative —
    higher rate, larger estimated saving on a loss, and we caveat
    it in the UI)."""
    assert classify_bucket(None, date(2026, 5, 22)) == "ST"


# ── FY label sanity ──────────────────────────────────────────────


def test_fy_label_apr_belongs_to_new_fy():
    assert fy_for_date(date(2026, 4, 1)) == "FY26-27"


def test_fy_label_mar_belongs_to_old_fy():
    assert fy_for_date(date(2026, 3, 31)) == "FY25-26"


# ── Empty + edge inputs: must not crash ──────────────────────────


def test_empty_portfolio_returns_no_suggestions():
    out = compute_suggestions([], as_of=date(2026, 5, 22))
    assert out["suggestions"] == []
    assert out["totals"]["candidate_count"] == 0
    assert out["totals"]["estimated_tax_saved"] == 0


def test_all_gains_returns_no_suggestions():
    """Holdings entirely in profit -> no harvesting candidates."""
    holdings = [
        {"ticker": "TCS", "qty": 10, "avg_cost": 3000, "current_price": 3850,
         "acquired_on": "2024-01-15"},
        {"ticker": "INFY", "qty": 5, "avg_cost": 1400, "current_price": 1900,
         "acquired_on": "2025-03-01"},
    ]
    out = compute_suggestions(holdings, as_of=date(2026, 5, 22))
    assert out["suggestions"] == []


def test_missing_avg_cost_skipped():
    """Holding with avg_cost=0 must not crash and must not be
    surfaced (we can't compute a meaningful P&L)."""
    out = compute_suggestions(
        [{"ticker": "X", "qty": 10, "avg_cost": 0, "current_price": 100,
          "acquired_on": "2024-01-01"}],
        as_of=date(2026, 5, 22),
    )
    assert out["suggestions"] == []


# ── Tax math: ST loss at 20%, LT loss at 12.5% ───────────────────


def test_stcg_loss_tax_saved_at_20_pct():
    """Short-term loss of Rs 10,000, with Rs 50,000 of realized
    STCG to offset -> saves 10000 * 20% = Rs 2,000."""
    holdings = [
        {"ticker": "RELIANCE", "qty": 10, "avg_cost": 2500,
         "current_price": 1500, "acquired_on": "2026-01-15"},
    ]
    out = compute_suggestions(
        holdings,
        realized_stcg_this_fy=50_000,
        as_of=date(2026, 5, 22),
    )
    assert len(out["suggestions"]) == 1
    s = out["suggestions"][0]
    assert s["tax_bucket"] == "ST"
    assert s["unrealized_loss"] == 10_000  # (1500-2500)*10
    # Loss 10k vs gain 50k -> fully offset at 20%.
    assert s["estimated_tax_saved"] == pytest.approx(2000, abs=0.01)


def test_ltcg_loss_tax_saved_at_12_5_pct_only_above_exemption():
    """LT loss of Rs 50,000. Realized LTCG this FY = Rs 2L
    (Rs 75k above the Rs 1.25L exemption -> taxable). The loss
    can only offset the TAXABLE slice, so 50k offsets fully at
    12.5% = Rs 6,250."""
    holdings = [
        {"ticker": "HDFCBANK", "qty": 50, "avg_cost": 1700,
         "current_price": 1700 - 1000, "acquired_on": "2024-01-01"},
    ]
    # loss = (700 - 1700) * 50 = -50,000
    out = compute_suggestions(
        holdings,
        realized_ltcg_this_fy=200_000,
        as_of=date(2026, 5, 22),
    )
    s = out["suggestions"][0]
    assert s["tax_bucket"] == "LT"
    assert s["unrealized_loss"] == 50_000
    assert s["estimated_tax_saved"] == pytest.approx(6250, abs=0.01)


def test_ltcg_loss_below_exemption_zero_immediate_saving():
    """LT loss but user's LTCG is entirely under the Rs 1.25L
    exemption -> no current-year tax to save. Loss carries
    forward (modelled as zero immediate saving)."""
    holdings = [
        {"ticker": "ITC", "qty": 100, "avg_cost": 500,
         "current_price": 400, "acquired_on": "2024-01-01"},
    ]
    out = compute_suggestions(
        holdings,
        realized_ltcg_this_fy=100_000,  # below 125k exemption
        as_of=date(2026, 5, 22),
    )
    s = out["suggestions"][0]
    assert s["tax_bucket"] == "LT"
    assert s["estimated_tax_saved"] == 0
    assert "carries forward" in s["rationale"]


# ── Offset cascade: STCL offsets both; LTCL only LTCG ────────────


def test_stcl_offsets_stcg_first_then_spills_to_ltcg():
    """ST loss = Rs 80,000. Realized STCG = Rs 30k, realized LTCG =
    Rs 300k (175k taxable). STCL applies STCG-first: 30k @ 20% =
    Rs 6,000; remaining 50k spills into LTCG @ 12.5% = Rs 6,250.
    Total saved = Rs 12,250."""
    holdings = [
        {"ticker": "ZOMATO", "qty": 1000, "avg_cost": 200,
         "current_price": 120, "acquired_on": "2026-01-01"},
    ]
    # loss = (120 - 200) * 1000 = -80,000
    out = compute_suggestions(
        holdings,
        realized_stcg_this_fy=30_000,
        realized_ltcg_this_fy=300_000,
        as_of=date(2026, 5, 22),
    )
    s = out["suggestions"][0]
    assert s["tax_bucket"] == "ST"
    assert s["estimated_tax_saved"] == pytest.approx(
        30_000 * STCG_RATE + 50_000 * LTCG_RATE, abs=0.01
    )


def test_ltcl_does_not_offset_stcg():
    """LT loss must NEVER offset STCG (per IT Act §74). Even if
    the user has huge STCG and zero LTCG, an LTCL contributes zero
    immediate saving."""
    holdings = [
        {"ticker": "WIPRO", "qty": 100, "avg_cost": 500,
         "current_price": 300, "acquired_on": "2024-01-01"},
    ]
    out = compute_suggestions(
        holdings,
        realized_stcg_this_fy=500_000,
        realized_ltcg_this_fy=0,
        as_of=date(2026, 5, 22),
    )
    s = out["suggestions"][0]
    assert s["tax_bucket"] == "LT"
    assert s["estimated_tax_saved"] == 0


def test_no_realized_gains_carries_forward_with_caveat():
    """If user supplies no realized FY gains, every harvest loss
    is modelled as carry-forward (zero immediate saving), and a
    caveat is surfaced."""
    holdings = [
        {"ticker": "PAYTM", "qty": 50, "avg_cost": 800,
         "current_price": 400, "acquired_on": "2026-02-01"},
    ]
    out = compute_suggestions(holdings, as_of=date(2026, 5, 22))
    s = out["suggestions"][0]
    assert s["estimated_tax_saved"] == 0
    assert any("realized gains" in c.lower() or "carried forward" in c.lower()
               for c in out["context"]["caveats"])


def test_suggestions_ranked_by_tax_saved_desc():
    """When multiple candidates exist, output ordering must put
    the highest-immediate-benefit first so the UI surfaces best
    candidates above the fold."""
    holdings = [
        # ST loss 10k, fully offsettable -> saves 2,000
        {"ticker": "A", "qty": 10, "avg_cost": 2000, "current_price": 1000,
         "acquired_on": "2026-01-01"},
        # LT loss 40k, fully offsettable against taxable LTCG -> 5,000
        {"ticker": "B", "qty": 40, "avg_cost": 1500, "current_price": 500,
         "acquired_on": "2024-01-01"},
    ]
    out = compute_suggestions(
        holdings,
        realized_stcg_this_fy=10_000,
        realized_ltcg_this_fy=200_000,  # 75k above exemption, room for B
        as_of=date(2026, 5, 22),
    )
    tickers = [s["ticker"] for s in out["suggestions"]]
    # B saves 40k*12.5% = 5000; A saves 10k*20% = 2000. B first.
    assert tickers[0] == "B"
    assert tickers[1] == "A"


def test_rationale_is_sebi_clean():
    """Rationale strings must use calculator language only. No
    'buy', 'sell', 'should', 'recommend', 'hold', 'strong',
    'accumulate' — surfaced to users, so SEBI-sensitive."""
    holdings = [
        {"ticker": "X", "qty": 10, "avg_cost": 100, "current_price": 50,
         "acquired_on": "2026-01-01"},
    ]
    out = compute_suggestions(
        holdings, realized_stcg_this_fy=10_000, as_of=date(2026, 5, 22),
    )
    rationale = out["suggestions"][0]["rationale"].lower()
    forbidden = ["buy", "sell", "should", "recommend", "hold",
                 "strong", "accumulate", "outperform", "underperform"]
    for word in forbidden:
        assert word not in rationale, (
            f"SEBI-forbidden word '{word}' leaked into rationale: "
            f"{rationale!r}"
        )


def test_offset_budget_consumed_across_suggestions():
    """If two ST losses exceed the realized STCG budget, the first
    one should consume the budget; the second's immediate saving is
    capped at the spill-into-LTCG slice (or zero if no LTCG)."""
    holdings = [
        {"ticker": "A", "qty": 100, "avg_cost": 100, "current_price": 60,
         "acquired_on": "2026-01-01"},   # loss 4,000
        {"ticker": "B", "qty": 100, "avg_cost": 100, "current_price": 50,
         "acquired_on": "2026-01-01"},   # loss 5,000
    ]
    out = compute_suggestions(
        holdings,
        realized_stcg_this_fy=5_000,
        realized_ltcg_this_fy=0,
        as_of=date(2026, 5, 22),
    )
    total_saved = out["totals"]["estimated_tax_saved"]
    # Total ST loss = 9,000; STCG to offset = 5,000.
    # Only 5,000 * 20% = 1,000 saved this FY; remaining 4,000
    # carries forward.
    assert total_saved == pytest.approx(1_000, abs=0.01)
