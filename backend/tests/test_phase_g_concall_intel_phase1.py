"""Phase G-intel-phase1 (2026-05-23) — Anthropic-powered concall signal
extraction.

Promotes the Phase-0 scaffold (tested by tests/test_concall_intel_service.py)
to production wiring. These tests cover the NEW surface:

  * Anthropic pricing math (compute_anthropic_cost_usd).
  * Prompt-cache marker is included in the system block sent to the SDK.
  * Token usage from the response is captured + costed.
  * JSON-walking SEBI sanitizer flags banned vocab in `management_tone`
    / `key_quotes` / `quote` / `drivers` / `purpose` (free-text fields)
    but ignores structured tokens like `direction='raised'` or
    `metric='revenue_target_fy26'` where the same words appear in
    controlled vocabulary.
  * Schema validation catches missing required keys + bad enum tones.
  * `extract_concall_signals_full` returns the rich
    ConcallIntelResult with `quality_flag='ok'` on a clean output and
    `quality_flag='sebi_withheld'` when the walker fires.
  * Legacy `extract_concall_signals(...)` still returns the bare dict
    so existing callers don't break.

No live Anthropic — the client is mocked in every test.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.services import concall_intel_service as intel  # noqa: E402


_TRANSCRIPT = (
    "Operator: Welcome to the Q1FY26 earnings call. CFO: Thank you. "
    "Revenue grew 18% YoY. EBITDA margins expanded 120 bps. "
    "We are raising our FY26 revenue growth guidance to 14-16% from "
    "12-15% earlier. We will commit Rs 1200 Cr over FY26-FY28 for "
    "the Sanand fab. Working capital days improved to 32 from 38. "
)


_CLEAN_PAYLOAD = {
    "fiscal_period": "Q1FY26",
    "concall_date": "2026-04-25",
    "transcript_source": "nse_pdf",
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


def _mock_client(payload: dict, *, in_tok: int = 1500, out_tok: int = 400,
                 cache_read: int = 0) -> MagicMock:
    text_block = MagicMock()
    text_block.text = json.dumps(payload)

    usage = MagicMock(spec=[])
    usage.input_tokens = in_tok
    usage.output_tokens = out_tok
    usage.cache_read_input_tokens = cache_read

    response = MagicMock()
    response.content = [text_block]
    response.usage = usage

    client = MagicMock()
    client.messages.create.return_value = response
    return client


# ---------- pricing ---------------------------------------------------------

def test_compute_anthropic_cost_sonnet_known_rates():
    # Sonnet 4.5: $3/Mtoken in, $15/Mtoken out.
    # 10000 * 3/1M + 500 * 15/1M = 0.03 + 0.0075 = 0.0375
    cost = intel.compute_anthropic_cost_usd("claude-sonnet-4-5", 10_000, 500)
    assert cost == pytest.approx(0.0375, abs=1e-6)


def test_compute_anthropic_cost_unknown_model_zero():
    assert intel.compute_anthropic_cost_usd("claude-mystery", 5000, 100) == 0.0


# ---------- prompt cache marker --------------------------------------------

def test_messages_create_passes_prompt_cache_marker():
    client = _mock_client(_CLEAN_PAYLOAD)
    intel.extract_concall_signals_full(
        "TCS", _TRANSCRIPT, anthropic_client=client
    )
    # Inspect the SDK call: system kwarg should be a list with one block
    # carrying cache_control marker.
    _, kwargs = client.messages.create.call_args
    sys_blocks = kwargs["system"]
    assert isinstance(sys_blocks, list)
    assert len(sys_blocks) == 1
    assert sys_blocks[0].get("cache_control") == {"type": "ephemeral"}
    assert "JSON object" in sys_blocks[0]["text"]


# ---------- usage capture + cost -------------------------------------------

def test_token_usage_captured_into_result():
    client = _mock_client(_CLEAN_PAYLOAD, in_tok=8_000, out_tok=300, cache_read=0)
    result = intel.extract_concall_signals_full(
        "TCS", _TRANSCRIPT, anthropic_client=client
    )
    assert result.input_tokens == 8_000
    assert result.output_tokens == 300
    # 8000 * 3/1M + 300 * 15/1M = 0.024 + 0.0045 = 0.0285
    assert result.cost_usd == pytest.approx(0.0285, abs=1e-6)
    assert result.model == intel.DEFAULT_ANTHROPIC_MODEL


def test_cache_read_tokens_summed_into_input():
    # cache_read tokens count toward the input total for cost.
    client = _mock_client(_CLEAN_PAYLOAD, in_tok=2_000, out_tok=300, cache_read=6_000)
    result = intel.extract_concall_signals_full(
        "TCS", _TRANSCRIPT, anthropic_client=client
    )
    assert result.input_tokens == 8_000  # 2000 + 6000


# ---------- sanitizer ------------------------------------------------------

def test_clean_payload_quality_flag_is_ok():
    client = _mock_client(_CLEAN_PAYLOAD)
    result = intel.extract_concall_signals_full(
        "TCS", _TRANSCRIPT, anthropic_client=client
    )
    assert result.quality_flag == "ok"
    assert result.sanitizer_hits == []


def test_banned_word_in_key_quote_triggers_withheld():
    bad = json.loads(json.dumps(_CLEAN_PAYLOAD))  # deep copy
    bad["key_quotes"][0]["quote"] = "Investors should buy this stock now."
    client = _mock_client(bad)
    result = intel.extract_concall_signals_full(
        "TCS", _TRANSCRIPT, anthropic_client=client
    )
    assert result.quality_flag == "sebi_withheld"
    assert any("buy" in h for h in result.sanitizer_hits)


def test_banned_word_in_drivers_triggers_withheld():
    bad = json.loads(json.dumps(_CLEAN_PAYLOAD))
    bad["margin_commentary"][0]["drivers"] = ["strong execution"]
    client = _mock_client(bad)
    result = intel.extract_concall_signals_full(
        "TCS", _TRANSCRIPT, anthropic_client=client
    )
    assert result.quality_flag == "sebi_withheld"
    assert any("strong" in h for h in result.sanitizer_hits)


def test_structured_token_direction_raised_is_NOT_banned():
    # 'raised' is not in the ban list (good), but even if a structured
    # token overlapped with a banned word, the sanitizer should ignore
    # it because it lives in a non-free-text field. Test this with
    # `direction='target'` (synthetic; 'target' IS banned) but it
    # appears in `direction`, NOT a free-text field.
    edge = json.loads(json.dumps(_CLEAN_PAYLOAD))
    edge["guidance_changes"][0]["direction"] = "target"  # structured field
    edge["guidance_changes"][0]["metric"] = "revenue_target_fy26"  # structured
    client = _mock_client(edge)
    result = intel.extract_concall_signals_full(
        "TCS", _TRANSCRIPT, anthropic_client=client
    )
    assert result.quality_flag == "ok"


def test_word_boundary_no_false_positive_on_shoulder():
    # 'should' is banned; 'shoulder' (substring) must not trip the
    # walker because of word-boundary matching.
    edge = json.loads(json.dumps(_CLEAN_PAYLOAD))
    edge["key_quotes"][0]["quote"] = "Capacity is on our shoulder this quarter."
    client = _mock_client(edge)
    result = intel.extract_concall_signals_full(
        "TCS", _TRANSCRIPT, anthropic_client=client
    )
    assert result.quality_flag == "ok"


def test_management_tone_field_is_scanned():
    # If somehow the model bypassed the enum constraint we'd want the
    # walker to catch directional language in the tone field too. We
    # use a non-enum value here; schema validation should catch it
    # first.
    bad = json.loads(json.dumps(_CLEAN_PAYLOAD))
    bad["management_tone"] = "strongly bullish"  # 'strong' is banned
    client = _mock_client(bad)
    with pytest.raises(ValueError, match="management_tone"):
        intel.extract_concall_signals_full(
            "TCS", _TRANSCRIPT, anthropic_client=client
        )


# ---------- schema validation ----------------------------------------------

def test_missing_required_key_raises():
    bad = json.loads(json.dumps(_CLEAN_PAYLOAD))
    del bad["key_quotes"]
    client = _mock_client(bad)
    with pytest.raises(ValueError, match="key_quotes"):
        intel.extract_concall_signals_full(
            "TCS", _TRANSCRIPT, anthropic_client=client
        )


def test_non_list_for_list_field_raises():
    bad = json.loads(json.dumps(_CLEAN_PAYLOAD))
    bad["capex_commitments"] = {"oops": "not a list"}
    client = _mock_client(bad)
    with pytest.raises(ValueError, match="capex_commitments"):
        intel.extract_concall_signals_full(
            "TCS", _TRANSCRIPT, anthropic_client=client
        )


# ---------- legacy contract ------------------------------------------------

def test_legacy_extract_returns_bare_dict():
    client = _mock_client(_CLEAN_PAYLOAD)
    out = intel.extract_concall_signals("TCS", _TRANSCRIPT, anthropic_client=client)
    assert isinstance(out, dict)
    assert out["management_tone"] == "bullish"
    # Extractor version is now the v1 string.
    assert out["extractor_version"] == intel.EXTRACTOR_VERSION
    assert "anthropic" in intel.EXTRACTOR_VERSION


def test_no_client_and_no_api_key_still_raises_not_implemented(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(NotImplementedError):
        intel.extract_concall_signals_full("TCS", _TRANSCRIPT)
