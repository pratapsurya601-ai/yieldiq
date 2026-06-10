"""ROOT CAUSE #9 — ar_segment_validator unit tests.

Covers:

* HDFCBANK FY25 reference fixture: validator flags the implausibly
  small Retail Banking — Digital row (₹8.59 Cr) and passes Treasury
  + Retail Banking — Non-Digital.
* Pure rules:
    R1 revenue_share_implausible — below 0.1 % of total
    R2 ebit_margin_implausible  — outside [-50, +90] %
    R3 unit_mismatch_cluster    — < 1 % of median revenue
* Edge cases:
    - rows with revenue_cr=null are NOT flagged (validator only
      quarantines rows that CLAIM a number and that number is
      implausible).
    - idempotence — re-running over an already-stamped list is a
      no-op modulo stamp values.
    - non-dict entries are skipped.
    - empty input returns empty output.
* count_flagged convenience helper.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
_REPO = _BACKEND.parent
for p in (_BACKEND, _REPO):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from backend.services.ar_segment_validator import (  # noqa: E402
    REASON_KEY,
    VALIDATED_KEY,
    count_flagged,
    validate_segment_rows,
)


# ---------- HDFCBANK FY25 reference fixture --------------------------------

HDFCBANK_FY25_SEGMENTS = [
    {
        "segment": "Treasury",
        "revenue_cr": 62227,
        "ebit_cr": 4605,
        "fy": "FY25",
    },
    {
        "segment": "Retail Banking - Digital",
        "revenue_cr": 8.59,
        "ebit_cr": 0.04,
        "fy": "FY25",
    },
    {
        "segment": "Retail Banking - Non-Digital",
        "revenue_cr": 283426,
        "ebit_cr": 27309,
        "fy": "FY25",
    },
]


def test_hdfcbank_fy25_digital_row_quarantined():
    """The reference fixture from the brief — validator must flag
    'Retail Banking — Digital' Revenue ₹8.59 Cr.
    """
    out = validate_segment_rows(HDFCBANK_FY25_SEGMENTS)
    assert len(out) == 3
    treasury, digital, non_digital = out
    assert treasury[VALIDATED_KEY] is True
    assert non_digital[VALIDATED_KEY] is True
    assert digital[VALIDATED_KEY] is False
    # The reason should mention the share or cluster rule.
    reason = digital[REASON_KEY]
    assert reason.startswith(("revenue_share_implausible", "unit_mismatch_cluster"))


def test_hdfcbank_fy25_treasury_and_non_digital_pass():
    """Sanity: the plausible rows must pass — false-positive guard."""
    out = validate_segment_rows(HDFCBANK_FY25_SEGMENTS)
    treasury, _digital, non_digital = out
    assert treasury[REASON_KEY] == ""
    assert non_digital[REASON_KEY] == ""


def test_count_flagged_returns_one_on_hdfcbank_fixture():
    out = validate_segment_rows(HDFCBANK_FY25_SEGMENTS)
    assert count_flagged(out) == 1


# ---------- R1 revenue_share_implausible ------------------------------------

def test_r1_flag_when_row_revenue_is_below_share_floor():
    rows = [
        {"segment": "Big", "revenue_cr": 100000},
        {"segment": "Tiny", "revenue_cr": 5},  # 0.005 % of total
    ]
    out = validate_segment_rows(rows)
    assert out[0][VALIDATED_KEY] is True
    assert out[1][VALIDATED_KEY] is False
    assert "revenue_share_implausible" in out[1][REASON_KEY] or \
        "unit_mismatch_cluster" in out[1][REASON_KEY]


def test_r1_external_total_revenue_anchor_used_when_supplied():
    """When the caller provides an externally-anchored total, the
    validator uses it instead of the row-sum.

    Here the anchor is 200_000 Cr but the row-sum is only 12 Cr —
    the row that claims 10 Cr is 0.005 % of the anchored total,
    so it must be flagged.
    """
    rows = [
        {"segment": "A", "revenue_cr": 10},
        {"segment": "B", "revenue_cr": 2},
    ]
    out = validate_segment_rows(rows, total_revenue_cr=200_000)
    # Both rows are below 0.1 % of the anchored total.
    assert out[0][VALIDATED_KEY] is False
    assert out[1][VALIDATED_KEY] is False


# ---------- R2 ebit_margin_implausible ---------------------------------------

def test_r2_flag_when_ebit_margin_exceeds_ceiling():
    rows = [
        # 95% margin — implies EBIT > revenue (unit mismatch).
        {"segment": "Bad", "revenue_cr": 100, "ebit_cr": 95},
        # 30% margin — plausible.
        {"segment": "OK", "revenue_cr": 100, "ebit_cr": 30},
    ]
    out = validate_segment_rows(rows)
    bad, ok = out
    assert bad[VALIDATED_KEY] is False
    assert "ebit_margin_implausible" in bad[REASON_KEY]
    assert ok[VALIDATED_KEY] is True


def test_r2_flag_when_ebit_margin_below_floor():
    rows = [
        {"segment": "Disaster", "revenue_cr": 100, "ebit_cr": -80},  # -80% margin
        {"segment": "Loss-making but plausible", "revenue_cr": 100, "ebit_cr": -10},
    ]
    out = validate_segment_rows(rows)
    assert out[0][VALIDATED_KEY] is False
    assert out[1][VALIDATED_KEY] is True


# ---------- R3 unit_mismatch_cluster ----------------------------------------

def test_r3_flag_outlier_relative_to_cluster_median():
    rows = [
        {"segment": "A", "revenue_cr": 50000, "ebit_cr": 5000},
        {"segment": "B", "revenue_cr": 60000, "ebit_cr": 6000},
        {"segment": "C", "revenue_cr": 55000, "ebit_cr": 5500},
        # 0.05 % of median revenue + EBIT outlier → cluster rule.
        {"segment": "D", "revenue_cr": 30, "ebit_cr": 0.01},
    ]
    out = validate_segment_rows(rows)
    assert out[0][VALIDATED_KEY] is True
    assert out[1][VALIDATED_KEY] is True
    assert out[2][VALIDATED_KEY] is True
    assert out[3][VALIDATED_KEY] is False


# ---------- edge cases -------------------------------------------------------

def test_null_revenue_row_is_not_flagged():
    """Validator only quarantines rows that CLAIM a number and the
    number is implausible. Empty / null revenue rows are 'data not
    disclosed' and pass through.
    """
    rows = [
        {"segment": "Has revenue", "revenue_cr": 50000, "ebit_cr": 5000},
        {"segment": "No revenue disclosed", "revenue_cr": None},
        {"segment": "Empty string", "revenue_cr": ""},
    ]
    out = validate_segment_rows(rows)
    for r in out:
        assert r[VALIDATED_KEY] is True


def test_idempotence_revalidating_a_stamped_list_yields_same_stamps():
    once = validate_segment_rows(HDFCBANK_FY25_SEGMENTS)
    twice = validate_segment_rows(once)
    # Strip the rest to compare only stamps + the input identity.
    for a, b in zip(once, twice):
        assert a[VALIDATED_KEY] == b[VALIDATED_KEY]
        assert a[REASON_KEY] == b[REASON_KEY]


def test_non_dict_entries_are_skipped():
    rows = [
        "garbage",
        None,
        42,
        {"segment": "OK", "revenue_cr": 100, "ebit_cr": 30},
    ]
    out = validate_segment_rows(rows)
    assert len(out) == 1
    assert out[0][VALIDATED_KEY] is True


def test_empty_list_returns_empty_list():
    assert validate_segment_rows([]) == []


def test_non_list_input_returns_empty_list():
    assert validate_segment_rows("not a list") == []   # type: ignore[arg-type]
    assert validate_segment_rows({}) == []             # type: ignore[arg-type]
    assert validate_segment_rows(None) == []           # type: ignore[arg-type]


def test_indian_thousand_separator_in_revenue_string_parses_correctly():
    rows = [
        {"segment": "A", "revenue_cr": "62,227"},
        {"segment": "B", "revenue_cr": "2,83,426"},
        # The 8.59 row, written as a comma-formatted string.
        {"segment": "C", "revenue_cr": "8.59"},
    ]
    out = validate_segment_rows(rows)
    # A & B pass, C is the < 0.1 % outlier.
    assert out[0][VALIDATED_KEY] is True
    assert out[1][VALIDATED_KEY] is True
    assert out[2][VALIDATED_KEY] is False


def test_stamps_do_not_mutate_input_rows():
    """The validator MUST return shallow copies — never mutate the
    caller's rows in place (downstream renderers may keep their own
    references to the original list)."""
    rows = [{"segment": "A", "revenue_cr": 100}]
    _ = validate_segment_rows(rows)
    assert VALIDATED_KEY not in rows[0]
    assert REASON_KEY not in rows[0]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
