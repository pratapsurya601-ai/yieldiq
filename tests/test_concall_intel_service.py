"""Tests for backend.services.concall_intel_service (Phase-0 scaffold).

Phase-0 contract:
  * extract_concall_signals() must REFUSE to run without a client
    (no silent live API calls from misconfigured code paths).
  * When a mocked anthropic client is injected, the parsing path
    must produce the documented schema dict.
  * No real network or DB calls in these tests.

Run:
    python -m pytest tests/test_concall_intel_service.py -v
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from unittest.mock import MagicMock

# Make `backend` importable when pytest isn't configuring the path.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from backend.services.concall_intel_service import (  # noqa: E402
    EXTRACTOR_VERSION,
    extract_concall_signals,
)


_FAKE_LLM_PAYLOAD = {
    "fiscal_period": "Q1FY26",
    "concall_date": "2026-04-25",
    "transcript_source": "user_paste",
    "guidance_changes": [
        {
            "metric": "revenue_growth_fy26",
            "previous": "12-15%",
            "new": "14-16%",
            "direction": "raised",
            "quote": "We are raising our FY26 revenue growth guidance to 14-16%.",
        }
    ],
    "capex_commitments": [
        {
            "amount_cr": 1200,
            "horizon": "FY26-FY28",
            "purpose": "new fab in Sanand",
            "quote": "We will commit Rs 1200 Cr over FY26-FY28 for the Sanand fab.",
        }
    ],
    "margin_commentary": [
        {
            "segment": "consumer",
            "direction": "expansion",
            "drivers": ["RM tailwind", "premiumisation"],
            "quote": "Consumer margins expanded 120 bps on RM tailwinds.",
        }
    ],
    "management_tone": "bullish",
    "key_quotes": [
        {
            "speaker": "CFO",
            "topic": "working capital",
            "quote": "Working capital days improved to 32 from 38.",
        }
    ],
}


def _make_mock_client(payload: dict) -> MagicMock:
    """Build a MagicMock that mimics the anthropic SDK response shape.

    The real SDK returns ``response.content[0].text`` as a string when
    the model emits a text block. We mirror that shape so swapping in
    the real client in Phase 1 is minimal.
    """
    text_block = MagicMock()
    text_block.text = json.dumps(payload)

    response = MagicMock()
    response.content = [text_block]

    client = MagicMock()
    client.messages.create.return_value = response
    return client


# A 250-char-plus filler to satisfy the >=200 char transcript guard.
_FAKE_TRANSCRIPT = (
    "Operator: Welcome to the Q1FY26 earnings call. CFO: Thank you. "
    "Revenue grew 18% YoY. EBITDA margins expanded 120 bps. "
    "We are raising our FY26 revenue growth guidance to 14-16% from "
    "12-15% earlier. We will commit Rs 1200 Cr over FY26-FY28 for "
    "the Sanand fab. Working capital days improved to 32 from 38. "
)


class TestExtractConcallSignals(unittest.TestCase):
    def test_refuses_without_client(self):
        """Phase-0 guard: no client -> NotImplementedError."""
        with self.assertRaises(NotImplementedError):
            extract_concall_signals("TCS", _FAKE_TRANSCRIPT)

    def test_rejects_short_transcript(self):
        client = _make_mock_client(_FAKE_LLM_PAYLOAD)
        with self.assertRaises(ValueError):
            extract_concall_signals("TCS", "too short", anthropic_client=client)

    def test_rejects_empty_ticker(self):
        client = _make_mock_client(_FAKE_LLM_PAYLOAD)
        with self.assertRaises(ValueError):
            extract_concall_signals("", _FAKE_TRANSCRIPT, anthropic_client=client)

    def test_parses_mocked_response_into_schema(self):
        client = _make_mock_client(_FAKE_LLM_PAYLOAD)
        result = extract_concall_signals(
            "TCS", _FAKE_TRANSCRIPT, anthropic_client=client
        )

        # Mock was actually called (we never hit the network).
        client.messages.create.assert_called_once()

        # All documented schema keys are present.
        for key in (
            "fiscal_period",
            "concall_date",
            "transcript_source",
            "guidance_changes",
            "capex_commitments",
            "margin_commentary",
            "management_tone",
            "key_quotes",
        ):
            self.assertIn(key, result, f"missing schema key: {key}")

        self.assertEqual(result["management_tone"], "bullish")
        self.assertEqual(result["fiscal_period"], "Q1FY26")
        self.assertEqual(len(result["guidance_changes"]), 1)
        self.assertEqual(result["guidance_changes"][0]["direction"], "raised")
        self.assertEqual(result["capex_commitments"][0]["amount_cr"], 1200)
        # Extractor version is stamped automatically.
        self.assertEqual(result["extractor_version"], EXTRACTOR_VERSION)

    def test_invalid_json_raises(self):
        text_block = MagicMock()
        text_block.text = "not json {{{"
        response = MagicMock()
        response.content = [text_block]
        client = MagicMock()
        client.messages.create.return_value = response

        with self.assertRaises(ValueError):
            extract_concall_signals(
                "TCS", _FAKE_TRANSCRIPT, anthropic_client=client
            )


if __name__ == "__main__":
    unittest.main()
