"""Unit tests for detect_unit_scale() — divisor selection from declared
rounding + magnitude sanity bypasses.

Regression coverage for the PR that adds a 'Millions' bypass to match the
existing 'Crores' / 'Lakhs' bypasses. NSE filers tagged
LevelOfRoundingUsedInFinancialStatements='Millions' (divisor=10) sometimes
embed raw-rupee values in the XBRL anyway (legacy upload template bug),
producing values off by 1e6. BHARTIARTL / MARUTI / SUNPHARMA Q2 FY25 hit
this in production.

We exercise detect_unit_scale() directly with a synthetic `sfacts` dict
rather than parsing full XBRLs: the function only consumes
LevelOfRoundingUsedInFinancialStatements + the revenue_raw magnitude, so
a minimal dict is faithful and far less brittle than fixture XML.
"""

from __future__ import annotations

import pytest

from pathlib import Path

from data_pipeline.sources.nse_quarterly_xbrl import _string_facts, detect_unit_scale

_FIXTURES = Path(__file__).parent / "fixtures" / "xbrl"


def _sfacts(rounding: str) -> dict[str, list[tuple[str, str]]]:
    """Build a minimal sfacts dict carrying just the rounding tag."""
    return {"LevelOfRoundingUsedInFinancialStatements": [(rounding, "OneD")]}


# ── BUG REGRESSION: Millions declared but raw INR (the new bypass) ──────


def test_bhartiartl_millions_declared_but_raw_inr():
    """BHARTIARTL Q2 FY25: rev_raw ~3.7e11 INR, tagged 'Millions'.

    Without the bypass detect_unit_scale returns 10 → value_in_cr ~3.7e10
    (₹37 billion Cr — absurd). With the bypass it returns 1e7 →
    value_in_cr ~37,000 Cr (matches BHARTIARTL's actual ~₹37k Cr quarterly
    revenue).
    """
    rev_raw = 3.7e11  # ₹37,000 Cr in raw INR
    divisor = detect_unit_scale(_sfacts("Millions"), rev_raw)
    assert divisor == 1e7, (
        f"expected raw-INR divisor 1e7 for Millions-tagged raw-INR file, got {divisor}"
    )
    value_in_cr = rev_raw / divisor
    assert 2_000 <= value_in_cr <= 80_000, (
        f"BHARTIARTL revenue should resolve to 2k-80k Cr, got {value_in_cr:,.0f} Cr"
    )


def test_maruti_millions_declared_but_raw_inr():
    """MARUTI Q2 FY25: ~₹37k Cr quarterly revenue tagged 'Millions'."""
    rev_raw = 3.7e11
    divisor = detect_unit_scale(_sfacts("Millions"), rev_raw)
    assert divisor == 1e7
    assert 2_000 <= rev_raw / divisor <= 80_000


def test_sunpharma_millions_declared_but_raw_inr():
    """SUNPHARMA Q2 FY25: ~₹13k Cr quarterly revenue tagged 'Millions'."""
    rev_raw = 1.3e11
    divisor = detect_unit_scale(_sfacts("Millions"), rev_raw)
    assert divisor == 1e7
    assert 1_000 <= rev_raw / divisor <= 50_000


# ── NEGATIVE CONTROLS: correctly tagged filings must be unchanged ───────


def test_reliance_crores_declared_correctly():
    """RELIANCE consolidated Q2 FY25: declared='Crores', rev_raw=235,481 Cr
    (literal). Must remain divisor=1.0."""
    rev_raw = 235_481.0
    divisor = detect_unit_scale(_sfacts("Crores"), rev_raw)
    assert divisor == 1.0
    assert rev_raw / divisor == pytest.approx(235_481.0)


def test_hdfcbank_crores_declared_correctly():
    """HDFCBANK Q2 FY25 banking schema: declared='Crores',
    rev_raw=~76,000 Cr. Must remain divisor=1.0."""
    rev_raw = 76_000.0
    divisor = detect_unit_scale(_sfacts("Crores"), rev_raw)
    assert divisor == 1.0


def test_legit_millions_filing_unchanged():
    """A real Millions-tagged filing with sane values (small-cap reporting
    in Mn) must still be divided by 10, not 1e7."""
    # ₹500 Cr quarterly revenue, written as 5000 Mn = rev_raw=5000
    rev_raw = 5_000.0
    divisor = detect_unit_scale(_sfacts("Millions"), rev_raw)
    assert divisor == 10.0
    assert rev_raw / divisor == pytest.approx(500.0)


def test_legit_lakhs_filing_unchanged():
    """A Lakhs-tagged filing with sane values must still be divided by 100."""
    # ₹100 Cr quarterly revenue, written as 10000 Lakhs
    rev_raw = 10_000.0
    divisor = detect_unit_scale(_sfacts("Lakhs"), rev_raw)
    assert divisor == 100.0


# ── Existing bypasses kept intact ───────────────────────────────────────


def test_bajajfinsv_crores_bypass_still_works():
    """BAJAJFINSV standalone Q3 FY25 regression: declared='Crores',
    rev_raw=708,200,000 (= ₹70.82 Cr in raw INR). Bypass must override
    to divisor=1e7."""
    rev_raw = 708_200_000.0
    divisor = detect_unit_scale(_sfacts("Crores"), rev_raw)
    assert divisor == 1e7
    assert rev_raw / divisor == pytest.approx(70.82)


def test_lakhs_raw_inr_bypass():
    """Lakhs declared but raw INR (rev_raw > 1e8)."""
    rev_raw = 5e9  # ₹500 Cr in raw INR
    divisor = detect_unit_scale(_sfacts("Lakhs"), rev_raw)
    assert divisor == 1e7


def test_actual_tag():
    """'Actual' (raw INR) always divisor=1e7."""
    rev_raw = 5e10
    divisor = detect_unit_scale(_sfacts("Actual"), rev_raw)
    assert divisor == 1e7


# ── SEBI 2025 in-capmkt integrated-filing schema (new tag name) ────────


def test_gayahws_new_schema_rounding_tag_recognized():
    """GAYAHWS Q2 FY26 integrated filing uses the SEBI 2025 in-capmkt
    schema which declares rounding via <in-capmkt:LevelOfRounding> (the
    legacy tag <in-bse-fin:LevelOfRoundingUsedInFinancialStatements> is
    absent). Before the fix, detect_unit_scale missed the tag entirely
    and fell through to the magnitude heuristic — for tickers with
    revenue_raw=0 that returns divisor=1.0, causing raw rupees to be
    stored as Crores. After the fix the new tag name is in the lookup
    list and the declared 'Lakhs' value is honoured.
    """
    xml_bytes = (_FIXTURES / "gayahws_integrated_q2_fy26.xml").read_bytes()
    sfacts = _string_facts(xml_bytes)
    # Sanity: the new tag is present, the legacy tag is not.
    assert "LevelOfRounding" in sfacts
    assert "LevelOfRoundingUsedInFinancialStatements" not in sfacts
    # With revenue_raw=0 the magnitude fallback would return 1.0; the
    # declared 'Lakhs' tag must now win → divisor=100.0.
    divisor = detect_unit_scale(sfacts, 0.0)
    assert divisor != 1.0, (
        "new in-capmkt:LevelOfRounding tag must be recognized; got "
        "magnitude-fallback divisor 1.0 (raw rupees would be stored as Cr)"
    )
    assert divisor == 100.0, (
        f"GAYAHWS declares 'Lakhs' → expected divisor 100.0, got {divisor}"
    )


def test_legacy_rounding_tag_still_recognized():
    """Regression guard: the legacy
    LevelOfRoundingUsedInFinancialStatements tag (used by every
    pre-SEBI-2025 NSE filing) must still drive the divisor after we
    extended the lookup list."""
    sfacts = {"LevelOfRoundingUsedInFinancialStatements": [("Crores", "OneD")]}
    assert detect_unit_scale(sfacts, 1_000.0) == 1.0
    sfacts = {"LevelOfRoundingUsedInFinancialStatements": [("Lakhs", "OneD")]}
    assert detect_unit_scale(sfacts, 1_000.0) == 100.0


def test_no_rounding_tag_magnitude_fallback():
    """Missing rounding tag → pure magnitude heuristic."""
    # > 1e9 → raw INR
    assert detect_unit_scale({}, 5e10) == 1e7
    # 1e4..1e9 → Lakhs
    assert detect_unit_scale({}, 5e5) == 100.0
    # < 1e4 → Crores
    assert detect_unit_scale({}, 500.0) == 1.0
    # None → conservative raw INR
    assert detect_unit_scale({}, None) == 1e7
