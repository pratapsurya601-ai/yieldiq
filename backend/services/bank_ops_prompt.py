"""bank_ops_prompt.py -- Anthropic prompt + result helpers for the
bank operational-stats extractor (Phase I-ingest-b, Block II).

Sibling to ``backend.services.ar_intel_service``. Where ar_intel
extracts the cross-sector AR signal bundle (segments / capex /
RPT / auditor flags / etc.), this module's prompt focuses
NARROWLY on the three bank operational stats that are NOT in
XBRL:

    branches_total   + branches_tier1 / tier2 / tier3
    atms_total
    customers_millions

GNPA / NNPA / PCR / CASA / cost-to-income / credit-deposit are
out of scope here -- they come from
``scripts/ingest_bank_kpis_from_xbrl.py`` (I-ingest-a) via
``data_pipeline/sources/bse_bank_xbrl.py``. Having two ingest
paths populate the same ``bank_operational_kpis`` row keyed by
(ticker, period_end, period_type, source) lets each side
incrementally fill its half without clobbering the other.

Discipline (matches concall_intel / ar_intel)::

    * Banned-vocab list in-prompt + post-call JSON sanitizer.
    * Versioned PROMPT_VERSION + EXTRACTOR_VERSION written to
      bank_operational_kpis_extractions (audit-trail, scoped to
      this script -- not a new persistent table for v1).
    * Single-quoted here-doc for the prompt so a $ in a fund
      name doesn't get expanded.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

logger = logging.getLogger("yieldiq.bank_ops_prompt")

EXTRACTOR_VERSION = "bank-ops-v1-anthropic-2026-05-26"
PROMPT_VERSION = 1

DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-5"

# Mirrored from ar_intel_service so this module has no compile-time
# dep on the sibling. Keep in sync if/when the canonical list moves.
SEBI_BANNED_WORDS: tuple[str, ...] = (
    "buy", "sell", "hold", "strong", "recommend", "accumulate",
    "should", "outperform", "underperform", "opportunity", "pick",
    "target", "rating", "downgrade", "upgrade",
)

# Free-text JSON paths where the SEBI walker fires. Structural
# enum tokens like "period_type":"annual" are exempt.
_SEBI_CHECK_FIELD_BASES: frozenset[str] = frozenset({
    "quote", "notes", "source_section",
})


_SYSTEM_PROMPT = (
    "You are a financial-data extractor reading a chunk of an Indian "
    "BANK annual report. Extract the following OPERATIONAL STATISTICS "
    "if (and only if) they are explicitly disclosed in this chunk:\n\n"
    "  * branches_total          -- total branch count as of FY-end\n"
    "  * branches_tier1          -- branches in metro / urban (Tier 1)\n"
    "  * branches_tier2          -- branches in semi-urban (Tier 2)\n"
    "  * branches_tier3          -- branches in rural (Tier 3)\n"
    "  * atms_total              -- total ATMs (own ATMs; exclude white-label)\n"
    "  * customers_millions      -- total customer base in MILLIONS (convert if disclosed in lakh / crore)\n"
    "  * period_end              -- FY-end date in YYYY-MM-DD (almost\n"
    "                               always YYYY-03-31 for Indian banks)\n"
    "  * period_type             -- 'annual' or 'quarterly'\n"
    "  * source_section          -- short label for the AR section\n"
    "                               the values came from (e.g.\n"
    "                               'Performance Highlights', 'Branch\n"
    "                               Network', 'Bank at a Glance').\n"
    "  * notes                   -- one-line explanation if a value\n"
    "                               required conversion or aggregation.\n\n"
    "Respond with a SINGLE JSON object matching this schema:\n"
    "{\n"
    '  "branches_total":     <int or null>,\n'
    '  "branches_tier1":     <int or null>,\n'
    '  "branches_tier2":     <int or null>,\n'
    '  "branches_tier3":     <int or null>,\n'
    '  "atms_total":         <int or null>,\n'
    '  "customers_millions": <number or null>,\n'
    '  "period_end":         "YYYY-MM-DD" or null,\n'
    '  "period_type":        "annual" | "quarterly" | null,\n'
    '  "source_section":     <string or null>,\n'
    '  "notes":              <string or null>\n'
    "}\n\n"
    "SEBI-COMPLIANCE RULES (HARD CONSTRAINTS):\n"
    "* You are NOT a SEBI-registered research analyst. You MUST NOT use any of:\n"
    "  buy, sell, hold, strong, recommend, accumulate, should, outperform,\n"
    "  underperform, opportunity, pick, target, rating, downgrade, upgrade.\n"
    "* Numerics only -- no editorial commentary in 'notes'.\n"
    "* If a field is not disclosed in this chunk, return null. Do NOT\n"
    "  estimate, extrapolate, or carry values from prior periods.\n"
    "* If the chunk has no relevant operational stats at all, return\n"
    "  the object with every field null.\n\n"
    "OUTPUT FORMAT:\n"
    "* Return ONLY the JSON object. No markdown, no preamble, no closing line.\n"
)

# Fields the extractor produces. Mirror the bank_operational_kpis
# columns so persistence is a 1:1 map.
_OPERATIONAL_FIELDS: tuple[str, ...] = (
    "branches_total",
    "branches_tier1",
    "branches_tier2",
    "branches_tier3",
    "atms_total",
    "customers_millions",
)

_INT_FIELDS: frozenset[str] = frozenset({
    "branches_total", "branches_tier1", "branches_tier2",
    "branches_tier3", "atms_total",
})


@dataclass
class BankOpsResult:
    """One AR chunk's worth of bank-ops fields.

    Mirrors the persistence shape so the caller can pass us
    straight to the UPSERT without a translation layer.
    `period_end` is a YYYY-MM-DD string; the CLI converts to a
    Python date before writing.
    """
    branches_total: Optional[int] = None
    branches_tier1: Optional[int] = None
    branches_tier2: Optional[int] = None
    branches_tier3: Optional[int] = None
    atms_total: Optional[int] = None
    customers_millions: Optional[float] = None
    period_end: Optional[str] = None
    period_type: Optional[str] = None
    source_section: Optional[str] = None
    notes: Optional[str] = None

    quality_flag: str = "ok"
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    model: str = ""
    sanitizer_hits: list[str] = field(default_factory=list)

    def populated_field_count(self) -> int:
        return sum(
            1 for f in _OPERATIONAL_FIELDS if getattr(self, f) is not None
        )


# ---------- sanitizer (mirrors ar_intel_service) ----------------------------

def _iter_string_leaves(node: Any, path: str = "") -> Iterable[tuple[str, str]]:
    if isinstance(node, str):
        yield path or "$", node
    elif isinstance(node, dict):
        for k, v in node.items():
            yield from _iter_string_leaves(v, f"{path}.{k}" if path else k)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _iter_string_leaves(v, f"{path}[{i}]")


def _path_subject_to_sebi_check(path: str) -> bool:
    last = path.rsplit(".", 1)[-1]
    base = last.split("[", 1)[0]
    return base in _SEBI_CHECK_FIELD_BASES


def scan_for_banned_vocab(payload: dict) -> list[str]:
    """Return "<path>: <banned_word>" findings, empty when clean."""
    findings: list[str] = []
    lowered_bans = [w.lower() for w in SEBI_BANNED_WORDS]
    for path, value in _iter_string_leaves(payload):
        if not _path_subject_to_sebi_check(path):
            continue
        lowered = value.lower()
        for word in lowered_bans:
            idx = 0
            while True:
                pos = lowered.find(word, idx)
                if pos < 0:
                    break
                left_ok = pos == 0 or not lowered[pos - 1].isalpha()
                end = pos + len(word)
                right_ok = end == len(lowered) or not lowered[end].isalpha()
                if left_ok and right_ok:
                    findings.append(f"{path}: {word}")
                    break
                idx = pos + 1
    return findings


# ---------- schema validation -----------------------------------------------

def validate_schema(payload: dict) -> None:
    """Raise ValueError on wrong types. Missing fields are OK
    (they're optional / nullable by design)."""
    for f in _INT_FIELDS:
        v = payload.get(f)
        if v is not None and not isinstance(v, (int, float)):
            raise ValueError(f"{f} must be a number or null, got {type(v).__name__}")
    cm = payload.get("customers_millions")
    if cm is not None and not isinstance(cm, (int, float)):
        raise ValueError("customers_millions must be a number or null")
    pe = payload.get("period_end")
    if pe is not None and not isinstance(pe, str):
        raise ValueError("period_end must be a string or null")
    pt = payload.get("period_type")
    if pt is not None and pt not in ("annual", "quarterly"):
        raise ValueError(f"period_type must be 'annual' / 'quarterly' / null, got {pt!r}")


# ---------- merge -----------------------------------------------------------

def merge_chunk_results(chunk_payloads: list[dict]) -> dict:
    """Pick the best populated values across chunks.

    Strategy: for each operational field, prefer the LAST non-null
    value seen across chunks (later sections of the AR -- like
    'Performance Highlights' near the back -- usually have the
    summary table). For period_end / period_type we prefer the
    first non-null. For source_section / notes we keep the entry
    that came alongside the most populated row.
    """
    out: dict[str, Any] = {f: None for f in _OPERATIONAL_FIELDS}
    out.update({
        "period_end": None,
        "period_type": None,
        "source_section": None,
        "notes": None,
    })
    best_populated = -1
    best_meta: dict[str, Any] = {}
    for cp in chunk_payloads:
        if not isinstance(cp, dict):
            continue
        # Per-field "last non-null wins" for numerics.
        for f in _OPERATIONAL_FIELDS:
            v = cp.get(f)
            if v is not None:
                out[f] = v
        if out["period_end"] is None and cp.get("period_end"):
            out["period_end"] = cp["period_end"]
        if out["period_type"] is None and cp.get("period_type"):
            out["period_type"] = cp["period_type"]
        # Attach source_section / notes from the chunk with the
        # most populated operational fields.
        chunk_populated = sum(
            1 for f in _OPERATIONAL_FIELDS if cp.get(f) is not None
        )
        if chunk_populated > best_populated:
            best_populated = chunk_populated
            best_meta = {
                "source_section": cp.get("source_section"),
                "notes": cp.get("notes"),
            }
    out["source_section"] = best_meta.get("source_section")
    out["notes"] = best_meta.get("notes")
    return out


# ---------- LLM call helper -------------------------------------------------

def call_anthropic_for_chunk(
    client: Any, ticker: str, chunk_text: str, *,
    chunk_id: str = "ck001", heading: Optional[str] = None,
    model: str = DEFAULT_ANTHROPIC_MODEL, max_tokens: int = 800,
) -> tuple[dict, int, int, int]:
    """One Anthropic call returning (parsed_dict, in_tok, out_tok, cache_read).

    Caller is responsible for chunking + cost accumulation. The
    system prompt is marked ``cache_control: ephemeral`` so
    repeated bank ARs in the same batch share the prompt cache.
    """
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=[
            {
                "type": "text",
                "text": _SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            },
        ],
        messages=[
            {
                "role": "user",
                "content": (
                    f"Ticker: {ticker}\n"
                    f"Chunk: {chunk_id} (heading={heading or 'none'})\n\n"
                    f"AR chunk text:\n{chunk_text}\n\n"
                    "Respond with the JSON object only."
                ),
            }
        ],
    )
    try:
        raw_text = response.content[0].text
    except (AttributeError, IndexError) as exc:
        raise ValueError(f"unexpected anthropic response shape: {exc}") from exc
    usage = getattr(response, "usage", None)
    in_tok = int(getattr(usage, "input_tokens", 0) or 0) if usage else 0
    out_tok = int(getattr(usage, "output_tokens", 0) or 0) if usage else 0
    cache_read = int(getattr(usage, "cache_read_input_tokens", 0) or 0) if usage else 0
    parsed = json.loads(raw_text)
    if not isinstance(parsed, dict):
        raise ValueError("LLM JSON root must be an object")
    return parsed, in_tok, out_tok, cache_read


__all__ = [
    "EXTRACTOR_VERSION",
    "PROMPT_VERSION",
    "DEFAULT_ANTHROPIC_MODEL",
    "BankOpsResult",
    "scan_for_banned_vocab",
    "validate_schema",
    "merge_chunk_results",
    "call_anthropic_for_chunk",
]
