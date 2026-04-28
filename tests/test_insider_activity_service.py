"""Tests for backend.services.insider_activity_service.

Pure-Python: feeds the service in-memory fixture rows, no DB needed.
Run:
    python -m pytest tests/test_insider_activity_service.py -v
or:
    python tests/test_insider_activity_service.py
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from datetime import date

# Make `backend` importable when pytest isn't configuring the path.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from backend.services.insider_activity_service import (  # noqa: E402
    get_recent_bulk_block,
    get_recent_insider_txns,
    summarize_insider_activity,
)

_FIXTURE_PATH = os.path.join(
    _ROOT, "tests", "fixtures", "insider_activity_sample.json"
)


def _load_fixture():
    with open(_FIXTURE_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return (
        date.fromisoformat(data["today"]),
        data["bulk_block_deals"],
        data["insider_transactions"],
    )


class TestGetRecentBulkBlock(unittest.TestCase):
    def setUp(self):
        self.today, self.bb, self.ins = _load_fixture()

    def test_filters_by_ticker(self):
        rel = get_recent_bulk_block(
            "RELIANCE", days=90, rows=self.bb, today=self.today
        )
        self.assertEqual(len(rel), 3)
        self.assertTrue(all(r["ticker"] == "RELIANCE" for r in rel))

    def test_case_insensitive_ticker(self):
        rel = get_recent_bulk_block(
            "reliance", days=90, rows=self.bb, today=self.today
        )
        self.assertEqual(len(rel), 3)

    def test_window_excludes_old_rows(self):
        # ITC has one block deal on 2026-04-25 — within 90d, but if we
        # narrow the window to 1 day from 2026-04-27, it survives;
        # narrow to a window that excludes it and it's filtered.
        itc_recent = get_recent_bulk_block(
            "ITC", days=5, rows=self.bb, today=self.today
        )
        self.assertEqual(len(itc_recent), 1)
        # HDFCBANK Jan 30 deal is ~87d before today — in 90d but not 30d.
        hdfc_30 = get_recent_bulk_block(
            "HDFCBANK", days=30, rows=self.bb, today=self.today
        )
        hdfc_90 = get_recent_bulk_block(
            "HDFCBANK", days=90, rows=self.bb, today=self.today
        )
        self.assertEqual(len(hdfc_30), 1)
        self.assertEqual(len(hdfc_90), 2)

    def test_sorted_descending(self):
        rel = get_recent_bulk_block(
            "RELIANCE", days=180, rows=self.bb, today=self.today
        )
        dates = [r["deal_date"] for r in rel]
        self.assertEqual(dates, sorted(dates, reverse=True))

    def test_unknown_ticker_returns_empty(self):
        self.assertEqual(
            get_recent_bulk_block(
                "NOSUCH", days=90, rows=self.bb, today=self.today
            ),
            [],
        )


class TestGetRecentInsiderTxns(unittest.TestCase):
    def setUp(self):
        self.today, self.bb, self.ins = _load_fixture()

    def test_filters_by_ticker(self):
        rel = get_recent_insider_txns(
            "RELIANCE", days=180, rows=self.ins, today=self.today
        )
        self.assertEqual(len(rel), 2)

    def test_window(self):
        # INFY has a Jan 12 filing (~106 days) and an Apr 8 filing (~19 days)
        infy_30 = get_recent_insider_txns(
            "INFY", days=30, rows=self.ins, today=self.today
        )
        infy_180 = get_recent_insider_txns(
            "INFY", days=180, rows=self.ins, today=self.today
        )
        self.assertEqual(len(infy_30), 1)
        self.assertEqual(len(infy_180), 2)


class TestSummarizeInsiderActivity(unittest.TestCase):
    def setUp(self):
        self.today, self.bb, self.ins = _load_fixture()

    def test_reliance_summary(self):
        s = summarize_insider_activity(
            "RELIANCE",
            bulk_block_rows=self.bb,
            insider_rows=self.ins,
            today=self.today,
        )
        self.assertEqual(s["ticker"], "RELIANCE")
        # 3 bulk/block rows in last 90d: 2 buys (250k @ 2940.5, 500k @ 2880),
        # 1 sell (180k @ 2941.1).
        self.assertEqual(s["bulk_block"]["count"], 3)
        self.assertEqual(s["bulk_block"]["buy_count"], 2)
        self.assertEqual(s["bulk_block"]["sell_count"], 1)
        self.assertEqual(
            s["bulk_block"]["net_quantity"], 250000 + 500000 - 180000
        )
        expected_net = (
            250000 * 2940.50 + 500000 * 2880.00 - 180000 * 2941.10
        )
        self.assertAlmostEqual(
            s["bulk_block"]["net_value_inr"], expected_net, places=2
        )

        # 2 insider filings: 1 promoter buy (147M), 1 director sell (34.56M)
        self.assertEqual(s["insider"]["count"], 2)
        self.assertEqual(s["insider"]["promoter_count"], 1)
        self.assertEqual(s["insider"]["director_count"], 1)
        self.assertEqual(s["insider"]["kmp_count"], 0)
        self.assertAlmostEqual(
            s["insider"]["net_value_inr"], 147000000.00 - 34560000.00, places=2
        )

    def test_empty_for_unknown_ticker(self):
        s = summarize_insider_activity(
            "NOSUCH",
            bulk_block_rows=self.bb,
            insider_rows=self.ins,
            today=self.today,
        )
        self.assertEqual(s["bulk_block"]["count"], 0)
        self.assertEqual(s["insider"]["count"], 0)
        self.assertEqual(s["bulk_block"]["net_value_inr"], 0.0)
        self.assertEqual(s["insider"]["net_value_inr"], 0.0)

    def test_itc_only_sell(self):
        s = summarize_insider_activity(
            "ITC",
            bulk_block_rows=self.bb,
            insider_rows=self.ins,
            today=self.today,
        )
        self.assertEqual(s["bulk_block"]["sell_count"], 1)
        self.assertEqual(s["bulk_block"]["buy_count"], 0)
        self.assertLess(s["bulk_block"]["net_value_inr"], 0)
        # No insider filings in fixture for ITC.
        self.assertEqual(s["insider"]["count"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
