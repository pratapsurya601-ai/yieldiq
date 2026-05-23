"""Phase H-extract (2026-05-26) — ar_intel_service unit tests.

Mirrors backend/tests/test_phase_g_concall_intel_phase1.py for the
AR pipeline. Covers:

* Anthropic pricing math (compute_anthropic_cost_usd).
* JSON-walking SEBI sanitizer flags banned vocab in free-text
  fields (quote / description / outlook / management_outlook)
  but ignores structural enum tokens (type, direction, fy).
* Schema validation (missing keys, wrong list types).
* chunk_ar_text produces deterministic chunk_ids and respects
  the max-chars + max-chunks caps; handles the no-headings
  fallback.
* merge_chunk_results concatenates lists and dedupes outlook.
* extract_ar_signals_from_text returns a clean ARIntelResult
  with quality_flag='ok' on a happy path and 'sebi_withheld' on
  a banned-word path.
* extract_ar_signals_from_text returns quality_flag='extraction_failed'
  when every chunk call raises.

No live Anthropic / network — clients are mocked end-to-end.
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

from backend.services import ar_intel_service as ari  # noqa: E402


# Long enough to clear MIN_TEXT_CHARS (2000) without being huge.
_AR_TEXT = (
    "MANAGEMENT DISCUSSION AND ANALYSIS\n\n"
    "The company posted revenue of Rs 12345 Cr in FY24, up 18% YoY. "
    "EBIT was Rs 1500 Cr. Segment performance was led by Consumer "
    "(Rs 8000 Cr) and Industrial (Rs 4345 Cr).\n\n"
    "RELATED PARTY TRANSACTIONS\n\n"
    "Transactions with Acme Subsidiary (subsidiary): sales of "
    "Rs 12.3 Cr; loans Rs 5 Cr.\n\n"
    "CONTINGENT LIABILITIES\n\n"
    "Tax disputes Rs 234 Cr as at 2024-03-31.\n\n"
    "INDEPENDENT AUDITORS REPORT\n\n"
    "Unmodified opinion. No going-concern qualification.\n\n"
) * 20  # repeat to clear the size bar


_CLEAN_PAYLOAD = {
    "segment_data": [
        {"segment": "Consumer", "revenue_cr": 8000, "ebit_cr": 1100,
         "fy": "FY24", "quote": "Consumer segment revenue grew 18 percent."},
    ],
    "capex_commitments": [
        {"amount_cr": 800, "fy": "FY25", "project": "Sanand fab",
         "quote": "Capex of Rs 800 Cr planned over FY25."},
    ],
    "related_party_transactions": [
        {"counterparty": "Acme Subsidiary", "relationship": "subsidiary",
         "nature": "sales", "amount_cr": 12.3, "fy": "FY24",
         "quote": "Sales to Acme Subsidiary of Rs 12.3 Cr."},
    ],
    "auditor_flags": [
        {"type": "emphasis_of_matter",
         "description": "Pending tax matter.", "as_of": "2024-03-31"},
    ],
    "contingent_liabilities": [
        {"description": "Tax disputes.",
         "amount_cr": 234, "as_of": "2024-03-31"},
    ],
    "management_outlook": "Management commentary on the year ahead is constructive.",
}


def _mock_client(payload: dict, *, in_tok: int = 1500,
                 out_tok: int = 400, cache_read: int = 0) -> MagicMock:
    """Build a mock Anthropic client whose messages.create returns
    the given JSON payload, on every call.
    """
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

def test_compute_cost_sonnet_4_5_known_rates():
    # 1M input @ $3 + 1M output @ $15 = $18
    assert ari.compute_anthropic_cost_usd(
        "claude-sonnet-4-5", 1_000_000, 1_000_000,
    ) == 18.0


def test_compute_cost_unknown_model_zero():
    assert ari.compute_anthropic_cost_usd("not-a-model", 1000, 1000) == 0.0


# ---------- sanitizer -------------------------------------------------------

def test_sanitizer_clean_payload_no_hits():
    assert ari.scan_for_banned_vocab(_CLEAN_PAYLOAD) == []


def test_sanitizer_catches_banned_word_in_quote():
    payload = json.loads(json.dumps(_CLEAN_PAYLOAD))  # deepcopy
    payload["segment_data"][0]["quote"] = "We recommend you buy this name."
    hits = ari.scan_for_banned_vocab(payload)
    assert any("buy" in h for h in hits)
    assert any("recommend" in h for h in hits)


def test_sanitizer_catches_banned_word_in_outlook():
    payload = json.loads(json.dumps(_CLEAN_PAYLOAD))
    payload["management_outlook"] = "Investors should accumulate the stock."
    hits = ari.scan_for_banned_vocab(payload)
    assert any("should" in h for h in hits)
    assert any("accumulate" in h for h in hits)


def test_sanitizer_ignores_structural_enum_tokens():
    """`type`, `direction`, `relationship` are exempt — controlled
    vocabulary tokens like 'target' or 'rating' that legitimately
    appear in enum values must NOT trip the sanitizer.
    """
    payload = json.loads(json.dumps(_CLEAN_PAYLOAD))
    payload["auditor_flags"][0]["type"] = "rating_downgrade_disclosure"
    payload["related_party_transactions"][0]["relationship"] = "target_subsidiary"
    # These should NOT fire — they're on structural paths.
    assert ari.scan_for_banned_vocab(payload) == []


def test_sanitizer_word_boundary_no_false_positive():
    """'should' inside 'shoulder' must not fire."""
    payload = json.loads(json.dumps(_CLEAN_PAYLOAD))
    payload["segment_data"][0]["quote"] = "Production reached shoulder peaks."
    assert ari.scan_for_banned_vocab(payload) == []


# ---------- schema validation ----------------------------------------------

def test_validate_schema_clean_payload_passes():
    ari.validate_schema(_CLEAN_PAYLOAD)


def test_validate_schema_missing_key_raises():
    bad = json.loads(json.dumps(_CLEAN_PAYLOAD))
    del bad["segment_data"]
    with pytest.raises(ValueError, match="missing required keys"):
        ari.validate_schema(bad)


def test_validate_schema_list_field_must_be_list():
    bad = json.loads(json.dumps(_CLEAN_PAYLOAD))
    bad["capex_commitments"] = {"not": "a list"}
    with pytest.raises(ValueError, match="must be a list"):
        ari.validate_schema(bad)


def test_validate_schema_outlook_must_be_string():
    bad = json.loads(json.dumps(_CLEAN_PAYLOAD))
    bad["management_outlook"] = 12345
    with pytest.raises(ValueError, match="management_outlook must be a string"):
        ari.validate_schema(bad)


# ---------- PDF size cap (post-Phase H bump to 50 MB) ----------------------

def _fake_httpx_client(content: bytes) -> MagicMock:
    """Build a minimal httpx-like client whose .get(url) returns a
    response with .content and a no-op raise_for_status().
    """
    resp = MagicMock()
    resp.content = content
    resp.raise_for_status = MagicMock()
    client = MagicMock()
    client.get.return_value = resp
    return client


def test_pdf_cap_is_50_mb():
    """Regression guard: cap was bumped from 8 MB to 50 MB in PR #581
    after real Indian ARs (TCS 17 MB, LT 30 MB, LTIM 11 MB) all
    exceeded the inherited 8 MB ceiling and failed pre-flight.
    """
    assert ari.PDF_MAX_BYTES == 50 * 1024 * 1024


def test_download_ar_pdf_accepts_30mb_payload():
    """A 30 MB AR PDF (well within the observed real-world range)
    must be accepted under the post-bump 50 MB cap.
    """
    payload = b"%PDF-1.4\n" + b"x" * (30 * 1024 * 1024)
    client = _fake_httpx_client(payload)
    out = ari.download_ar_pdf("https://example.com/AR.pdf", client=client)
    assert out == payload


def test_download_ar_pdf_rejects_51mb_payload_gracefully():
    """A 51 MB PDF must be rejected with ValueError (not OOM / not
    swallowed silently). The batch script catches this as
    `extract failed` and bumps the pre-flight failure count.
    """
    payload = b"%PDF-1.4\n" + b"x" * (51 * 1024 * 1024)
    client = _fake_httpx_client(payload)
    with pytest.raises(ValueError, match="cap"):
        ari.download_ar_pdf("https://example.com/big.pdf", client=client)


# ---------- chunking -------------------------------------------------------

def test_chunk_ar_text_empty_returns_empty():
    assert ari.chunk_ar_text("") == []


def test_chunk_ar_text_no_headings_fixed_slice():
    # 200k chars of body, no headings -> 4 chunks at default 60k cap.
    body = "x" * 200_000
    chunks = ari.chunk_ar_text(body)
    assert 3 <= len(chunks) <= 4
    # chunk_ids are deterministic ck001, ck002, ...
    assert chunks[0]["chunk_id"] == "ck001"
    assert chunks[1]["chunk_id"] == "ck002"
    # Heading is None on the fallback path.
    assert chunks[0]["heading"] is None
    # Sequential, non-overlapping, covers the whole text.
    assert chunks[0]["start"] == 0
    for i in range(len(chunks) - 1):
        assert chunks[i]["end"] == chunks[i + 1]["start"]


def test_chunk_ar_text_respects_max_chunks_cap():
    body = "y" * 5_000_000  # 5M chars; 5000_000/60000 ~ 84 chunks
    chunks = ari.chunk_ar_text(body)
    assert len(chunks) <= ari.MAX_CHUNKS_PER_AR


def test_chunk_ar_text_finds_headings():
    text = (
        "MANAGEMENT DISCUSSION AND ANALYSIS\n"
        + ("a" * 100) + "\n"
        "RELATED PARTY TRANSACTIONS\n"
        + ("b" * 100) + "\n"
        "INDEPENDENT AUDITORS REPORT\n"
        + ("c" * 100)
    )
    chunks = ari.chunk_ar_text(text, max_chars=200)
    # We expect multiple chunks; first chunk's heading should be 'intro'
    # (prefix before first match) or a matched heading.
    assert len(chunks) >= 1
    headings = [c.get("heading") for c in chunks]
    assert any(h for h in headings)


def test_chunk_fingerprint_stable():
    chunk = {"chunk_id": "ck001", "text": "hello world" * 100}
    a = ari.chunk_fingerprint(chunk)
    b = ari.chunk_fingerprint(chunk)
    assert a == b
    assert len(a) == 64  # sha256 hex


# ---------- merge ----------------------------------------------------------

def test_merge_chunk_results_concatenates_lists():
    c1 = {
        "segment_data": [{"segment": "A"}],
        "capex_commitments": [],
        "related_party_transactions": [],
        "auditor_flags": [],
        "contingent_liabilities": [],
        "management_outlook": "First chunk outlook.",
    }
    c2 = {
        "segment_data": [{"segment": "B"}, {"segment": "C"}],
        "capex_commitments": [{"amount_cr": 100}],
        "related_party_transactions": [],
        "auditor_flags": [],
        "contingent_liabilities": [],
        "management_outlook": "Second chunk outlook.",
    }
    merged = ari.merge_chunk_results([c1, c2])
    assert [s["segment"] for s in merged["segment_data"]] == ["A", "B", "C"]
    assert len(merged["capex_commitments"]) == 1
    assert "First chunk outlook" in merged["management_outlook"]
    assert "Second chunk outlook" in merged["management_outlook"]


def test_merge_chunk_results_dedupes_outlook():
    c1 = {"segment_data": [], "capex_commitments": [],
          "related_party_transactions": [], "auditor_flags": [],
          "contingent_liabilities": [],
          "management_outlook": "Same outlook here."}
    c2 = {"segment_data": [], "capex_commitments": [],
          "related_party_transactions": [], "auditor_flags": [],
          "contingent_liabilities": [],
          "management_outlook": "Same outlook here."}
    merged = ari.merge_chunk_results([c1, c2])
    # Deduped — appears once, not twice.
    assert merged["management_outlook"].count("Same outlook here.") == 1


def test_merge_chunk_results_caps_outlook_length():
    big = "x" * 5000
    c = {"segment_data": [], "capex_commitments": [],
         "related_party_transactions": [], "auditor_flags": [],
         "contingent_liabilities": [],
         "management_outlook": big}
    merged = ari.merge_chunk_results([c])
    assert len(merged["management_outlook"]) <= 2000


# ---------- end-to-end extract_ar_signals_from_text ------------------------

def test_extract_ar_signals_from_text_happy_path_ok():
    client = _mock_client(_CLEAN_PAYLOAD, in_tok=1500, out_tok=400)
    result = ari.extract_ar_signals_from_text(
        "RELIANCE", _AR_TEXT, anthropic_client=client,
    )
    assert result.quality_flag == "ok"
    assert result.model == "claude-sonnet-4-5"
    assert result.n_chunks >= 1
    assert result.input_tokens > 0
    assert result.output_tokens > 0
    assert result.cost_usd > 0
    # Merged shape sane.
    assert len(result.signals["segment_data"]) >= 1
    assert result.signals["management_outlook"]
    # Prompt-cache marker present in the first call's system block.
    first_call_kwargs = client.messages.create.call_args_list[0].kwargs
    sys_block = first_call_kwargs["system"][0]
    assert sys_block["cache_control"] == {"type": "ephemeral"}


def test_extract_ar_signals_from_text_sebi_withheld_on_banned_word():
    dirty = json.loads(json.dumps(_CLEAN_PAYLOAD))
    dirty["management_outlook"] = "We recommend you buy this stock."
    client = _mock_client(dirty)
    result = ari.extract_ar_signals_from_text(
        "RELIANCE", _AR_TEXT, anthropic_client=client,
    )
    assert result.quality_flag == "sebi_withheld"
    assert any("buy" in h or "recommend" in h for h in result.sanitizer_hits)


def test_extract_ar_signals_from_text_extraction_failed_when_all_chunks_fail():
    client = MagicMock()
    client.messages.create.side_effect = RuntimeError("API down")
    result = ari.extract_ar_signals_from_text(
        "RELIANCE", _AR_TEXT, anthropic_client=client,
    )
    assert result.quality_flag == "extraction_failed"
    # Schema is the empty-signals fallback.
    assert result.signals["segment_data"] == []
    assert result.signals["management_outlook"] == ""


def test_extract_ar_signals_from_text_rejects_short_text():
    client = _mock_client(_CLEAN_PAYLOAD)
    with pytest.raises(ValueError, match="too short"):
        ari.extract_ar_signals_from_text(
            "RELIANCE", "too short", anthropic_client=client,
        )


def test_extract_ar_signals_from_text_requires_client():
    """No client + no ANTHROPIC_API_KEY -> NotImplementedError."""
    import os
    saved = os.environ.pop("ANTHROPIC_API_KEY", None)
    try:
        with pytest.raises(NotImplementedError):
            ari.extract_ar_signals_from_text("RELIANCE", _AR_TEXT)
    finally:
        if saved is not None:
            os.environ["ANTHROPIC_API_KEY"] = saved


# ---------- cost tracking is summed across chunks --------------------------

def test_cost_tracking_sums_across_chunks():
    """Token + cost fields sum across chunks. Drive multiple chunks by
    feeding text > CHUNK_MAX_CHARS so the chunker naturally splits it.
    """
    # 3x the chunker's cap guarantees >=2 chunks (likely 3).
    big_text = _AR_TEXT * 30
    n_chunks = len(ari.chunk_ar_text(big_text))
    assert n_chunks >= 2

    client = _mock_client(_CLEAN_PAYLOAD, in_tok=1000, out_tok=200)
    result = ari.extract_ar_signals_from_text(
        "RELIANCE", big_text, anthropic_client=client,
    )
    expected_n = min(n_chunks, ari.MAX_CHUNKS_PER_AR)
    assert result.n_chunks == expected_n
    assert result.input_tokens == 1000 * expected_n
    assert result.output_tokens == 200 * expected_n
    # Cost = sum across chunks.
    expected_cost = ari.compute_anthropic_cost_usd(
        "claude-sonnet-4-5", 1000 * expected_n, 200 * expected_n,
    )
    assert result.cost_usd == expected_cost
