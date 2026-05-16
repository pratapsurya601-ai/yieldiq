"""Tests for backend.services.annual_report_service (Phase-1 scaffold).

Phase-1 contract:
  * discover_ar_url, download_ar_pdf, extract_ar_structured_data
    must REFUSE to run without explicit injection (no silent live
    API calls from misconfigured code paths).
  * save_ar_data validates the extracted schema before insert
    (typo'd keys fail fast instead of writing wrong columns).
  * get_ar_for_ticker returns None cleanly when there's no DB
    (DATABASE_URL unset).
  * No real network, no real PDF, no real DB calls in these tests.

Run:
    python -m pytest backend/tests/test_annual_report_service.py -v
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from unittest.mock import MagicMock

# Make `backend` importable when pytest isn't configuring the path.
_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from backend.services.annual_report_service import (  # noqa: E402
    EXTRACTOR_VERSION,
    discover_ar_url,
    download_ar_pdf,
    extract_ar_structured_data,
    get_ar_for_ticker,
    save_ar_data,
)


# Path to the invented Zomato FY24 fixture.
_FIXTURE_PATH = os.path.join(
    _ROOT, "tests", "fixtures", "sample_ar_zomato_fy24.json"
)


def _load_fixture() -> dict:
    with open(_FIXTURE_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


class TestPhase1Stubs(unittest.TestCase):
    """Stubs must refuse to silently run -- no live API calls from
    misconfigured code paths."""

    def test_discover_ar_url_refuses_without_client(self):
        with self.assertRaises(NotImplementedError):
            discover_ar_url("ZOMATO", 2024)

    def test_download_ar_pdf_refuses_without_client(self):
        with self.assertRaises(NotImplementedError):
            download_ar_pdf("https://example.com/ar.pdf")

    def test_extract_refuses_without_anthropic_client(self):
        with self.assertRaises(NotImplementedError):
            extract_ar_structured_data(
                b"x" * 2048, "ZOMATO", 2024, anthropic_client=None
            )

    def test_extract_validates_inputs_even_with_client(self):
        client = MagicMock()
        with self.assertRaises(ValueError):
            extract_ar_structured_data(
                b"", "ZOMATO", 2024, anthropic_client=client
            )
        with self.assertRaises(ValueError):
            extract_ar_structured_data(
                b"x" * 2048, "", 2024, anthropic_client=client
            )
        with self.assertRaises(ValueError):
            extract_ar_structured_data(
                b"x" * 2048, "ZOMATO", 1800, anthropic_client=client
            )


class TestSaveArDataValidation(unittest.TestCase):
    """save_ar_data must reject malformed input BEFORE attempting
    the DB call so a typo in a key doesn't silently write the
    wrong column."""

    def test_rejects_empty_ticker(self):
        with self.assertRaises(ValueError):
            save_ar_data("", 2024, None, _load_fixture())

    def test_rejects_bad_fiscal_year(self):
        with self.assertRaises(ValueError):
            save_ar_data("ZOMATO", 1800, None, _load_fixture())

    def test_rejects_unknown_source(self):
        with self.assertRaises(ValueError):
            save_ar_data(
                "ZOMATO", 2024, None, _load_fixture(),
                source="bogus_source",
            )

    def test_rejects_non_dict_extracted(self):
        with self.assertRaises(ValueError):
            save_ar_data("ZOMATO", 2024, None, ["not", "a", "dict"])  # type: ignore[arg-type]

    def test_rejects_non_list_segment_data(self):
        bad = _load_fixture()
        bad["segment_data"] = {"segment": "oops"}  # should be a list
        with self.assertRaises(ValueError):
            save_ar_data("ZOMATO", 2024, None, bad)

    def test_rejects_non_string_mda_summary(self):
        bad = _load_fixture()
        bad["mda_summary"] = 12345  # should be a string
        with self.assertRaises(ValueError):
            save_ar_data("ZOMATO", 2024, None, bad)

    def test_returns_false_when_db_unreachable(self):
        """With no DATABASE_URL, save_ar_data should return False
        (not raise) -- callers decide whether to retry."""
        prior = os.environ.pop("DATABASE_URL", None)
        try:
            ok = save_ar_data("ZOMATO", 2024, None, _load_fixture())
            self.assertFalse(ok)
        finally:
            if prior is not None:
                os.environ["DATABASE_URL"] = prior


class TestGetArForTicker(unittest.TestCase):
    def test_returns_none_when_db_unreachable(self):
        prior = os.environ.pop("DATABASE_URL", None)
        try:
            result = get_ar_for_ticker("ZOMATO")
            self.assertIsNone(result)
            result = get_ar_for_ticker("ZOMATO", fiscal_year=2024)
            self.assertIsNone(result)
        finally:
            if prior is not None:
                os.environ["DATABASE_URL"] = prior

    def test_rejects_empty_ticker(self):
        with self.assertRaises(ValueError):
            get_ar_for_ticker("")


class TestFixtureShape(unittest.TestCase):
    """The Zomato fixture is the source-of-truth contract between
    the Phase-2 extractor and Phase-3 analysis consumers. Lock its
    top-level shape here so any rename is a deliberate change."""

    def test_fixture_has_all_documented_keys(self):
        fx = _load_fixture()
        for key in (
            "segment_data",
            "capex_commitments",
            "auditor_flags",
            "contingent_liabilities",
            "related_party_transactions",
            "mda_summary",
        ):
            self.assertIn(key, fx, f"fixture missing key: {key}")

    def test_fixture_segment_data_has_expected_columns(self):
        fx = _load_fixture()
        self.assertGreater(len(fx["segment_data"]), 0)
        for row in fx["segment_data"]:
            for col in ("segment", "revenue_cr", "ebitda_cr", "fy"):
                self.assertIn(col, row, f"segment row missing {col}")

    def test_fixture_extractor_version_present(self):
        fx = _load_fixture()
        self.assertEqual(fx.get("extractor_version"), EXTRACTOR_VERSION)


if __name__ == "__main__":
    unittest.main()
