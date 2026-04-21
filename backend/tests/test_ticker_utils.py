"""Unit tests for backend.services.ticker_utils.

Covers the canonical <-> bare round-trip across all documented edge
cases: bare, .NS, .BO, hyphen suffixes, mixed case, whitespace, None.
"""
from __future__ import annotations

import pytest

from backend.services.ticker_utils import from_canonical, to_canonical


class TestToCanonical:
    def test_bare_upper_gets_ns(self):
        assert to_canonical("TCS") == "TCS.NS"

    def test_bare_lower_is_upper_cased(self):
        assert to_canonical("tcs") == "TCS.NS"

    def test_already_ns_passthrough(self):
        assert to_canonical("TCS.NS") == "TCS.NS"

    def test_bo_kept_as_bo(self):
        # BSE-only listings must NOT be forced to NSE.
        assert to_canonical("PREMCO.BO") == "PREMCO.BO"

    def test_bo_lowercase_is_upper(self):
        assert to_canonical("premco.bo") == "PREMCO.BO"

    def test_hyphen_x_stripped(self):
        assert to_canonical("PREMCO-X") == "PREMCO.NS"

    def test_hyphen_eq_stripped(self):
        assert to_canonical("RELIANCE-EQ") == "RELIANCE.NS"

    def test_hyphen_be_stripped(self):
        assert to_canonical("abc-be") == "ABC.NS"

    def test_hyphen_suffix_on_bo(self):
        # PREMCO-X.BO: strip -X, keep .BO
        assert to_canonical("PREMCO-X.BO") == "PREMCO.BO"

    def test_whitespace_trimmed(self):
        assert to_canonical("  tcs  ") == "TCS.NS"

    def test_empty_string(self):
        assert to_canonical("") == ""

    def test_none_safe(self):
        # Should not raise; treat as empty.
        assert to_canonical(None) == ""  # type: ignore[arg-type]


class TestFromCanonical:
    def test_ns_stripped(self):
        assert from_canonical("TCS.NS") == "TCS"

    def test_bo_stripped(self):
        assert from_canonical("PREMCO.BO") == "PREMCO"

    def test_bare_upper_pass(self):
        assert from_canonical("TCS") == "TCS"

    def test_lower_upper_cased(self):
        assert from_canonical("tcs") == "TCS"

    def test_hyphen_suffix_stripped(self):
        assert from_canonical("RELIANCE-EQ") == "RELIANCE"

    def test_hyphen_on_suffixed(self):
        assert from_canonical("PREMCO-X.BO") == "PREMCO"

    def test_empty_string(self):
        assert from_canonical("") == ""

    def test_none_safe(self):
        assert from_canonical(None) == ""  # type: ignore[arg-type]


class TestRoundTrip:
    @pytest.mark.parametrize(
        "raw,expected_canonical,expected_bare",
        [
            ("TCS",          "TCS.NS",    "TCS"),
            ("tcs.ns",       "TCS.NS",    "TCS"),
            ("PREMCO.BO",    "PREMCO.BO", "PREMCO"),
            ("RELIANCE-EQ",  "RELIANCE.NS", "RELIANCE"),
            ("PREMCO-X",     "PREMCO.NS", "PREMCO"),
            ("  hdfc  ",     "HDFC.NS",   "HDFC"),
        ],
    )
    def test_roundtrip(self, raw, expected_canonical, expected_bare):
        canonical = to_canonical(raw)
        assert canonical == expected_canonical
        bare = from_canonical(canonical)
        assert bare == expected_bare
        # canonical is idempotent
        assert to_canonical(canonical) == canonical
        # from_canonical is idempotent
        assert from_canonical(bare) == bare
