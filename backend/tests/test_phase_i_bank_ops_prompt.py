"""Phase I-ingest-b (2026-05-26) -- bank_ops_prompt unit tests.

Covers:
* scan_for_banned_vocab catches banned words in free-text fields
  (notes, source_section) but ignores numeric / structural fields.
* validate_schema accepts clean payloads and rejects bad types.
* merge_chunk_results picks last non-null operational values and
  prefers source_section / notes from the most-populated chunk.
* call_anthropic_for_chunk drives a mocked client through the
  system-prompt cache_control path and returns parsed + usage.
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

from backend.services import bank_ops_prompt as bop  # noqa: E402


_FULL_PAYLOAD = {
    "branches_total": 7821,
    "branches_tier1": 3100,
    "branches_tier2": 2700,
    "branches_tier3": 2021,
    "atms_total": 19500,
    "customers_millions": 92.0,
    "period_end": "2024-03-31",
    "period_type": "annual",
    "source_section": "Performance Highlights",
    "notes": "Branches include all domestic and overseas offices.",
}


# ---------- sanitizer -------------------------------------------------------

def test_sanitizer_clean_payload_no_hits():
    assert bop.scan_for_banned_vocab(_FULL_PAYLOAD) == []


def test_sanitizer_catches_banned_word_in_notes():
    bad = json.loads(json.dumps(_FULL_PAYLOAD))
    bad["notes"] = "Investors should accumulate this name."
    hits = bop.scan_for_banned_vocab(bad)
    assert any("should" in h for h in hits)
    assert any("accumulate" in h for h in hits)


def test_sanitizer_catches_banned_word_in_source_section():
    bad = json.loads(json.dumps(_FULL_PAYLOAD))
    bad["source_section"] = "We strongly recommend the buy list."
    hits = bop.scan_for_banned_vocab(bad)
    assert any("recommend" in h for h in hits)
    assert any("buy" in h for h in hits)


def test_sanitizer_ignores_numeric_fields():
    """Numeric fields can never carry banned-word text."""
    bad = json.loads(json.dumps(_FULL_PAYLOAD))
    bad["branches_total"] = 9999  # ignored anyway -- not a string
    assert bop.scan_for_banned_vocab(bad) == []


def test_sanitizer_word_boundary_no_false_positive():
    """'should' in 'shoulder' must not fire."""
    bad = json.loads(json.dumps(_FULL_PAYLOAD))
    bad["notes"] = "Branch network at shoulder peaks."
    assert bop.scan_for_banned_vocab(bad) == []


# ---------- schema validation ----------------------------------------------

def test_validate_schema_clean_payload_passes():
    bop.validate_schema(_FULL_PAYLOAD)


def test_validate_schema_missing_fields_ok():
    """All fields are optional / nullable -- a payload with
    nothing but period_end is still valid (the merge step
    handles cross-chunk fill-in)."""
    bop.validate_schema({"period_end": "2024-03-31"})


def test_validate_schema_rejects_bad_int_type():
    bad = json.loads(json.dumps(_FULL_PAYLOAD))
    bad["branches_total"] = "lots"
    with pytest.raises(ValueError, match="branches_total"):
        bop.validate_schema(bad)


def test_validate_schema_rejects_bad_period_type():
    bad = json.loads(json.dumps(_FULL_PAYLOAD))
    bad["period_type"] = "semiannual"
    with pytest.raises(ValueError, match="period_type"):
        bop.validate_schema(bad)


def test_validate_schema_rejects_bad_customers_type():
    bad = json.loads(json.dumps(_FULL_PAYLOAD))
    bad["customers_millions"] = "ninety-two"
    with pytest.raises(ValueError, match="customers_millions"):
        bop.validate_schema(bad)


# ---------- merge -----------------------------------------------------------

def test_merge_last_non_null_wins_for_operational_fields():
    # Chunk 1 has branches only; chunk 2 has ATMs and a different
    # branches count. Merge should take chunk 2's branches (last
    # non-null wins) and chunk 2's ATMs.
    c1 = {
        "branches_total": 100, "branches_tier1": 50,
        "atms_total": None, "customers_millions": None,
        "source_section": "Pre-table",
    }
    c2 = {
        "branches_total": 200, "branches_tier1": None,
        "atms_total": 800, "customers_millions": 12.5,
        "source_section": "Performance Highlights",
    }
    merged = bop.merge_chunk_results([c1, c2])
    assert merged["branches_total"] == 200
    # tier1 only appeared in c1 -- preserved.
    assert merged["branches_tier1"] == 50
    assert merged["atms_total"] == 800
    assert merged["customers_millions"] == 12.5
    # source_section comes from chunk with most populated fields
    # (c2 has 3, c1 has 2) -> "Performance Highlights".
    assert merged["source_section"] == "Performance Highlights"


def test_merge_period_end_first_non_null_wins():
    c1 = {"period_end": None, "period_type": None}
    c2 = {"period_end": "2024-03-31", "period_type": "annual"}
    c3 = {"period_end": "2023-03-31", "period_type": "annual"}
    merged = bop.merge_chunk_results([c1, c2, c3])
    # First non-null is c2's date.
    assert merged["period_end"] == "2024-03-31"
    assert merged["period_type"] == "annual"


def test_merge_handles_non_dict_chunks_gracefully():
    merged = bop.merge_chunk_results([None, "garbage", _FULL_PAYLOAD])
    assert merged["branches_total"] == 7821
    assert merged["source_section"] == "Performance Highlights"


def test_merge_empty_input_returns_all_null():
    merged = bop.merge_chunk_results([])
    for f in (
        "branches_total", "branches_tier1", "branches_tier2",
        "branches_tier3", "atms_total", "customers_millions",
        "period_end", "period_type", "source_section", "notes",
    ):
        assert merged[f] is None


# ---------- call_anthropic_for_chunk ---------------------------------------

def _mock_client(payload: dict, *, in_tok: int = 1200,
                 out_tok: int = 300, cache_read: int = 0) -> MagicMock:
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


def test_call_anthropic_returns_parsed_and_usage():
    client = _mock_client(_FULL_PAYLOAD, in_tok=1500, out_tok=400)
    parsed, in_tok, out_tok, cache_read = bop.call_anthropic_for_chunk(
        client, "HDFCBANK", "AR chunk text body.", chunk_id="ck001",
    )
    assert parsed["branches_total"] == 7821
    assert in_tok == 1500
    assert out_tok == 400
    assert cache_read == 0
    # Verify the system prompt was sent with cache_control.
    call_kwargs = client.messages.create.call_args.kwargs
    assert call_kwargs["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert call_kwargs["model"] == bop.DEFAULT_ANTHROPIC_MODEL


def test_call_anthropic_raises_on_non_dict_root():
    client = _mock_client(_FULL_PAYLOAD)
    # Replace the text with a JSON array (root is a list).
    client.messages.create.return_value.content[0].text = json.dumps([1, 2, 3])
    with pytest.raises(ValueError, match="root must be an object"):
        bop.call_anthropic_for_chunk(client, "HDFCBANK", "text")


# ---------- BankOpsResult ---------------------------------------------------

def test_populated_field_count_full():
    r = bop.BankOpsResult(
        branches_total=10, branches_tier1=5, branches_tier2=3,
        branches_tier3=2, atms_total=200, customers_millions=1.5,
    )
    assert r.populated_field_count() == 6


def test_populated_field_count_empty():
    assert bop.BankOpsResult().populated_field_count() == 0
