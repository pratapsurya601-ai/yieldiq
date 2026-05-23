# backend/services/ar_intel_service.py
# ===============================================================
# Annual Report INTELLIGENCE -- structured-signal extraction from
# annual-report PDFs using the Claude (Anthropic) API.
#
# Sibling to concall_intel_service. ARs are much larger (100-300
# pages vs 15-30 for concalls), so this service CHUNKS the
# transcript text by section heading (Items / Schedules / common
# AR sub-headings) and runs one Anthropic call per chunk, then
# merges the results into a single ar_signals row.
#
# Shape of an extracted ar_signals row (stored in migration 060):
#   * segment_data              JSONB list
#   * capex_commitments         JSONB list
#   * related_party_transactions JSONB list
#   * auditor_flags             JSONB list
#   * contingent_liabilities    JSONB list
#   * management_outlook        TEXT (short narrative, <=2000 chars)
#   * quality_flag              'ok' | 'sebi_withheld' | 'extraction_failed'
#   * model_version / prompt_version (versioning + retries)
#   * input_tokens / output_tokens / cost_usd
#
# SEBI discipline mirrors concall_intel: every string leaf of the
# parsed JSON is walked through the banned-vocab sanitizer; on a
# hit the row is persisted with quality_flag='sebi_withheld' and
# the public reader collapses the response to {signals: null,
# withheld: true}.
# ===============================================================
from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

logger = logging.getLogger("yieldiq.ar_intel")

# Version tags persisted to ar_signals on every write. Bump
# PROMPT_VERSION whenever _SYSTEM_PROMPT changes -- the
# (annual_report_id, model_version, prompt_version) UNIQUE keeps
# the previous extraction around for diffing.
EXTRACTOR_VERSION = "ar-intel-v1-anthropic-2026-05-26"
PROMPT_VERSION = 1

DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-5"
ANTHROPIC_PRICING_USD_PER_MTOKEN: dict[str, dict[str, float]] = {
    "claude-sonnet-4-5":  {"input": 3.0,  "output": 15.0},
    "claude-sonnet-4-7":  {"input": 3.0,  "output": 15.0},
    "claude-opus-4-7":    {"input": 15.0, "output": 75.0},
    "claude-haiku-4-5":   {"input": 1.0,  "output": 5.0},
}

# Banned vocabulary -- single source of truth in
# concall_intel_service; copied here so this module has no
# compile-time dep on the sibling.
SEBI_BANNED_WORDS: tuple[str, ...] = (
    "buy", "sell", "hold", "strong", "recommend", "accumulate",
    "should", "outperform", "underperform", "opportunity", "pick",
    "target", "rating", "downgrade", "upgrade",
)

# Free-text JSON paths where the SEBI walker fires. Structural
# tokens like "direction":"raised" or {"type":"going_concern"}
# are exempt -- the schema itself uses controlled vocabulary that
# can legitimately overlap.
_SEBI_CHECK_FIELD_BASES: frozenset[str] = frozenset({
    "quote", "drivers", "purpose", "description", "nature",
    "qualification", "outlook", "management_outlook",
    "commentary", "notes",
})

# Network / size caps. ARs are larger than concalls so the
# defaults are looser than concall_intel.
#
# Cap bumped from 8 MB -> 50 MB post-Phase H (PR #581 dry-run, 2026-05-23).
# Real Indian AR PDFs run 100-300 pages and routinely land at 10-30 MB
# (observed: TCS 17 MB, LT 30 MB, LTIM 11 MB). The previous 8 MB ceiling
# was inherited from concall_intel (concalls are 1-3 MB) and rejected
# 100% of the production AR sample. 50 MB covers >99% of Indian ARs
# while still bounding worst-case memory: raw bytes (50 MB) + pypdf
# page-by-page text extraction (~5-10 MB output) is well within the
# Railway worker envelope, and downstream LLM input is already capped
# per-chunk at CHUNK_MAX_CHARS (60k chars) so the Anthropic payload
# never balloons with PDF size.
PDF_MAX_BYTES = 50 * 1024 * 1024  # 50 MB hard cap
PDF_DOWNLOAD_TIMEOUT_S = 60
MIN_TEXT_CHARS = 2000            # bail if pypdf yields almost nothing
CHUNK_MAX_CHARS = 60_000         # ~15-17k tokens per chunk
MAX_CHUNKS_PER_AR = 10           # safety brake on runaway PDFs

# Long, stable system prompt -- candidate for Anthropic prompt
# caching. We split the response into the SIX persisted columns
# (segment_data, capex_commitments, related_party_transactions,
# auditor_flags, contingent_liabilities, management_outlook).
_SYSTEM_PROMPT = (
    "You are an equity-research analyst extracting STRUCTURED SIGNALS "
    "from an Indian annual report (AR) chunk.\n\n"
    "You MUST respond with a single JSON object matching this schema:\n"
    "{\n"
    '  "segment_data":               [\n'
    '    {"segment":"Food Delivery","revenue_cr":12345,"ebit_cr":678,\n'
    '     "fy":"FY24","quote":"..."}\n'
    '  ],\n'
    '  "capex_commitments":          [\n'
    '    {"amount_cr":800,"fy":"FY25","project":"Sanand fab","quote":"..."}\n'
    '  ],\n'
    '  "related_party_transactions": [\n'
    '    {"counterparty":"Acme Subs","relationship":"subsidiary",\n'
    '     "nature":"sales","amount_cr":12.3,"fy":"FY24","quote":"..."}\n'
    '  ],\n'
    '  "auditor_flags":              [\n'
    '    {"type":"going_concern|emphasis_of_matter|qualified_opinion|adverse",\n'
    '     "description":"...","as_of":"YYYY-MM-DD"}\n'
    '  ],\n'
    '  "contingent_liabilities":     [\n'
    '    {"description":"...","amount_cr":234,"as_of":"YYYY-MM-DD"}\n'
    '  ],\n'
    '  "management_outlook":         "free-text MD&A summary (<= 1500 chars)"\n'
    "}\n\n"
    "SEBI-COMPLIANCE RULES (HARD CONSTRAINTS):\n"
    "* You are NOT a SEBI-registered research analyst. You MUST NOT use any of:\n"
    "  buy, sell, hold, strong, recommend, accumulate, should, outperform,\n"
    "  underperform, opportunity, pick, target, rating, downgrade, upgrade.\n"
    "* Quote management VERBATIM. Do not paraphrase to add a directional bias.\n"
    "* Empty arrays are valid. Do not fabricate segments / capex / RPT entries\n"
    "  if the chunk does not contain them.\n"
    "* `management_outlook` may be an empty string when the chunk has no MD&A.\n\n"
    "OUTPUT FORMAT:\n"
    "* Return ONLY the JSON object. No markdown, no preamble, no closing line.\n"
    "* All amounts in INR Cr (crore = 10M). Convert if the AR used Rs Mn / Rs Lakh.\n"
)

_REQUIRED_KEYS = (
    "segment_data",
    "capex_commitments",
    "related_party_transactions",
    "auditor_flags",
    "contingent_liabilities",
    "management_outlook",
)
_LIST_KEYS = _REQUIRED_KEYS[:-1]  # all except management_outlook


@dataclass
class ARIntelResult:
    """Return shape of extract_ar_signals_full.

    `signals` is the merged six-section dict ready to UPSERT into
    ar_signals. `quality_flag` is 'ok' on a clean walk,
    'sebi_withheld' if the JSON sanitizer caught a banned word in
    any free-text field, 'extraction_failed' on schema / LLM
    failures. Cost fields are summed across all chunks.
    """
    signals: dict
    quality_flag: str = "ok"
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    model: str = ""
    n_chunks: int = 0
    sanitizer_hits: list[str] = field(default_factory=list)


# ---------- pricing ---------------------------------------------------------

def compute_anthropic_cost_usd(
    model: str, input_tokens: int, output_tokens: int
) -> float:
    """Return USD cost for an Anthropic call given the model + tokens.

    Pure function so tests can call it directly. Returns 0.0 for
    unknown models -- caller decides whether to treat that as an
    error.
    """
    rates = ANTHROPIC_PRICING_USD_PER_MTOKEN.get(model)
    if not rates:
        return 0.0
    return round(
        (input_tokens / 1_000_000.0) * rates["input"]
        + (output_tokens / 1_000_000.0) * rates["output"],
        4,
    )


# ---------- sanitizer -------------------------------------------------------

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
    """True when the JSON path ends in a free-text field.

    Structural enum-typed fields like `direction`, `type`,
    `relationship`, `nature` (when used as a category) are exempt
    -- their controlled vocabulary legitimately includes words
    that also appear in the SEBI ban list (e.g. `type:'rating_action'`).
    """
    last = path.rsplit(".", 1)[-1]
    base = last.split("[", 1)[0]
    return base in _SEBI_CHECK_FIELD_BASES


def scan_for_banned_vocab(signals: dict) -> list[str]:
    """Walk every string leaf in the signals dict; return
    "<path>: <banned_word>" findings, empty when clean.
    """
    findings: list[str] = []
    lowered_bans = [w.lower() for w in SEBI_BANNED_WORDS]
    for path, value in _iter_string_leaves(signals):
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

def validate_schema(signals: dict) -> None:
    """Raise ValueError if `signals` is missing keys or has wrong types.

    Soft validation -- list-typed fields must be lists,
    management_outlook must be a string (or None which we
    coerce). Nested dict shapes are not enforced so a partial AR
    chunk doesn't tank the whole row.
    """
    missing = [k for k in _REQUIRED_KEYS if k not in signals]
    if missing:
        raise ValueError(f"signals missing required keys: {missing}")
    for k in _LIST_KEYS:
        if not isinstance(signals[k], list):
            raise ValueError(f"signals.{k} must be a list")
    outlook = signals.get("management_outlook")
    if outlook is not None and not isinstance(outlook, str):
        raise ValueError("management_outlook must be a string or None")


# ---------- PDF extraction --------------------------------------------------

def download_ar_pdf(url: str, client: Optional[Any] = None) -> bytes:
    """Download an AR PDF with the size cap and timeout. Returns
    raw bytes. Raises on HTTP error / oversize / missing httpx.
    """
    if client is None:
        try:
            import httpx
        except ImportError as exc:
            raise RuntimeError(f"httpx not installed: {exc}") from exc
        with httpx.Client(
            timeout=PDF_DOWNLOAD_TIMEOUT_S,
            follow_redirects=True,
            headers={"User-Agent": "YieldIQ-AR-Extract/1.0"},
        ) as c:
            resp = c.get(url)
            resp.raise_for_status()
            content = resp.content
    else:
        # Test injection: client must be httpx-like with .get().
        resp = client.get(url)
        resp.raise_for_status()
        content = resp.content
    if len(content) > PDF_MAX_BYTES:
        raise ValueError(
            f"AR PDF {url} is {len(content)} bytes; cap {PDF_MAX_BYTES}"
        )
    return content


def extract_text_from_pdf_bytes(pdf_bytes: bytes) -> str:
    """Run pypdf over the bytes and return the concatenated text.

    Best-effort: per-page errors are swallowed (some AR pages are
    image-only and pypdf yields nothing -- that's fine, downstream
    chunker just sees less text).
    """
    try:
        import pypdf
    except ImportError as exc:
        raise RuntimeError(f"pypdf not installed: {exc}") from exc
    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    pages: list[str] = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text() or "")
        except Exception:
            pages.append("")
    return "\n".join(pages)


# Regex for AR section / item headings. Matches common Indian AR
# structure: "Note 1", "Schedule 1", "Item 1", "(a) ... ", uppercase
# section titles like "MANAGEMENT DISCUSSION AND ANALYSIS", etc.
# We use this as a SECONDARY chunker -- the primary chunker just
# slices on CHUNK_MAX_CHARS boundaries.
_SECTION_HEADING_RX = re.compile(
    r"(?m)^(?:"
    r"Note\s+\d+|"
    r"Schedule\s+\d+|"
    r"Item\s+\d+|"
    r"MANAGEMENT\s+DISCUSSION|"
    r"DIRECTORS'?\s+REPORT|"
    r"INDEPENDENT\s+AUDITORS?'?\s+REPORT|"
    r"AUDITORS?'?\s+REPORT|"
    r"RELATED\s+PARTY|"
    r"CONTINGENT\s+LIABILITIES|"
    r"SEGMENT\s+REPORTING|"
    r"CORPORATE\s+GOVERNANCE"
    r")\b"
)


def chunk_ar_text(text: str, *, max_chars: int = CHUNK_MAX_CHARS,
                  max_chunks: int = MAX_CHUNKS_PER_AR) -> list[dict[str, Any]]:
    """Split `text` into deterministic chunks for per-chunk LLM calls.

    Strategy: find all section-heading offsets; greedily pack
    sections together until the next one would push us over
    `max_chars`. Fall back to fixed-width slicing if there are
    no headings (e.g. a scanned image-only AR yielded little
    text but enough to bypass MIN_TEXT_CHARS).

    Returns a list of dicts:
        {"chunk_id": "ck001", "start": int, "end": int,
         "text": str, "heading": str | None}

    chunk_id is deterministic from offset so retries land on the
    same id -- important for idempotent re-runs.
    """
    chunks: list[dict[str, Any]] = []
    text_len = len(text)
    if text_len == 0:
        return chunks

    # Find heading offsets.
    heads: list[tuple[int, str]] = [
        (m.start(), m.group(0)) for m in _SECTION_HEADING_RX.finditer(text)
    ]
    if not heads:
        # No headings; fixed slice.
        offset = 0
        idx = 1
        while offset < text_len and idx <= max_chunks:
            end = min(offset + max_chars, text_len)
            chunks.append({
                "chunk_id": f"ck{idx:03d}",
                "start": offset,
                "end": end,
                "text": text[offset:end],
                "heading": None,
            })
            offset = end
            idx += 1
        return chunks

    # Greedy pack between headings. Treat (0, "intro") as the
    # implicit start so any pre-Heading prefix is captured.
    boundaries: list[tuple[int, str]] = [(0, "intro")] + heads + [(text_len, "end")]
    cur_start = boundaries[0][0]
    cur_heading = boundaries[0][1]
    idx = 1
    for i in range(1, len(boundaries)):
        next_start, next_heading = boundaries[i]
        if next_start - cur_start >= max_chars:
            end = min(next_start, cur_start + max_chars)
            chunks.append({
                "chunk_id": f"ck{idx:03d}",
                "start": cur_start,
                "end": end,
                "text": text[cur_start:end],
                "heading": cur_heading,
            })
            idx += 1
            if idx > max_chunks:
                break
            cur_start = end
            cur_heading = next_heading
        # else: keep packing this chunk until the size bound trips.

    # Tail.
    if idx <= max_chunks and cur_start < text_len:
        chunks.append({
            "chunk_id": f"ck{idx:03d}",
            "start": cur_start,
            "end": text_len,
            "text": text[cur_start:text_len],
            "heading": cur_heading,
        })

    return chunks


# ---------- merge -----------------------------------------------------------

def _empty_signals() -> dict:
    return {k: [] for k in _LIST_KEYS} | {"management_outlook": ""}


def _dedupe_outlook(outlook_parts: list[str]) -> str:
    """Concatenate chunk-level outlook strings, trim duplicates,
    cap to 2000 chars (DB-friendly, also keeps the panel readable).
    """
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in outlook_parts:
        s = (raw or "").strip()
        if not s:
            continue
        key = s[:160].lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(s)
    joined = " ".join(cleaned).strip()
    if len(joined) > 2000:
        joined = joined[:1997].rstrip() + "..."
    return joined


def merge_chunk_results(chunk_signals: list[dict]) -> dict:
    """Combine per-chunk signal dicts into one row-ready dict.

    Lists are concatenated in chunk order; management_outlook
    strings are deduped + capped. Schema validation happens after
    this so a single missing key in one chunk is tolerated.
    """
    out = _empty_signals()
    outlook_parts: list[str] = []
    for cs in chunk_signals:
        if not isinstance(cs, dict):
            continue
        for k in _LIST_KEYS:
            v = cs.get(k)
            if isinstance(v, list):
                out[k].extend(v)
        ml = cs.get("management_outlook")
        if isinstance(ml, str):
            outlook_parts.append(ml)
    out["management_outlook"] = _dedupe_outlook(outlook_parts)
    return out


# ---------- client factory --------------------------------------------------

def _build_anthropic_client() -> Optional[Any]:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        from anthropic import Anthropic
        return Anthropic(api_key=api_key)
    except Exception as exc:
        logger.warning("anthropic client init failed: %s", exc)
        return None


def _call_anthropic_for_chunk(
    client: Any, ticker: str, chunk: dict, model: str,
) -> tuple[dict, int, int, int]:
    """Run one Anthropic call for a single AR chunk. Returns
    (parsed_dict, input_tokens, output_tokens, cache_read_tokens).
    """
    response = client.messages.create(
        model=model,
        max_tokens=3000,
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
                    f"Chunk: {chunk['chunk_id']}"
                    f" (heading={chunk.get('heading') or 'none'})\n\n"
                    f"AR text:\n{chunk['text']}\n\n"
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


# ---------- main entry points ----------------------------------------------

def extract_ar_signals_from_text(
    ticker: str,
    ar_text: str,
    *,
    anthropic_client: Optional[Any] = None,
    model: str = DEFAULT_ANTHROPIC_MODEL,
) -> ARIntelResult:
    """Extract structured AR signals from already-extracted text.

    Used by tests and by the batch script's resume path (where
    we've cached pypdf output). Chunks the text, calls Anthropic
    per chunk, merges, validates, sanitizes.
    """
    if not ticker or not isinstance(ticker, str):
        raise ValueError("ticker must be a non-empty string")
    if not ar_text or len(ar_text.strip()) < MIN_TEXT_CHARS:
        raise ValueError(
            f"ar_text too short ({len(ar_text or '')} chars) -- "
            f"need at least {MIN_TEXT_CHARS}"
        )

    if anthropic_client is None:
        anthropic_client = _build_anthropic_client()
    if anthropic_client is None:
        raise NotImplementedError(
            "ar_intel_service.extract_ar_signals_from_text: no anthropic "
            "client supplied and ANTHROPIC_API_KEY is unset."
        )

    chunks = chunk_ar_text(ar_text)
    if not chunks:
        raise ValueError("chunker returned 0 chunks (ar_text empty?)")

    chunk_results: list[dict] = []
    total_in = total_out = total_cache = 0
    schema_failures = 0

    for chunk in chunks:
        try:
            parsed, in_tok, out_tok, cache_read = _call_anthropic_for_chunk(
                anthropic_client, ticker, chunk, model,
            )
        except Exception as exc:
            # One chunk failed -- count it but continue. If ALL
            # chunks fail we mark quality_flag='extraction_failed'.
            logger.warning(
                "ar_intel: chunk %s (%s) failed: %s",
                chunk["chunk_id"], ticker, exc,
            )
            schema_failures += 1
            continue
        chunk_results.append(parsed)
        total_in += in_tok
        total_out += out_tok
        total_cache += cache_read

    in_tok_total = total_in + total_cache

    if not chunk_results:
        # Every chunk failed. Return a placeholder result so the
        # batch script can persist a cost-accounting row with
        # quality_flag='extraction_failed'.
        return ARIntelResult(
            signals=_empty_signals(),
            quality_flag="extraction_failed",
            input_tokens=in_tok_total,
            output_tokens=total_out,
            cost_usd=compute_anthropic_cost_usd(model, in_tok_total, total_out),
            model=model,
            n_chunks=len(chunks),
            sanitizer_hits=[],
        )

    merged = merge_chunk_results(chunk_results)
    try:
        validate_schema(merged)
    except ValueError as exc:
        logger.warning("ar_intel schema validation failed: %s", exc)
        return ARIntelResult(
            signals=_empty_signals(),
            quality_flag="extraction_failed",
            input_tokens=in_tok_total,
            output_tokens=total_out,
            cost_usd=compute_anthropic_cost_usd(model, in_tok_total, total_out),
            model=model,
            n_chunks=len(chunks),
            sanitizer_hits=[],
        )

    hits = scan_for_banned_vocab(merged)
    quality = "ok"
    if hits:
        logger.warning(
            "ar_intel: SEBI banned vocab in %s output for %s: %s",
            model, ticker, hits[:5],
        )
        quality = "sebi_withheld"

    cost = compute_anthropic_cost_usd(model, in_tok_total, total_out)
    return ARIntelResult(
        signals=merged,
        quality_flag=quality,
        input_tokens=in_tok_total,
        output_tokens=total_out,
        cost_usd=cost,
        model=model,
        n_chunks=len(chunks),
        sanitizer_hits=hits,
    )


def extract_ar_signals_from_url(
    ticker: str,
    ar_url: str,
    *,
    http_client: Optional[Any] = None,
    anthropic_client: Optional[Any] = None,
    model: str = DEFAULT_ANTHROPIC_MODEL,
) -> ARIntelResult:
    """End-to-end: download PDF, pypdf-extract, chunk + extract.

    Wraps `download_ar_pdf` + `extract_text_from_pdf_bytes` +
    `extract_ar_signals_from_text`. Used by the batch script.
    """
    pdf_bytes = download_ar_pdf(ar_url, client=http_client)
    text = extract_text_from_pdf_bytes(pdf_bytes)
    if len(text.strip()) < MIN_TEXT_CHARS:
        # Image-only / scanned AR -- no point calling LLM.
        return ARIntelResult(
            signals=_empty_signals(),
            quality_flag="extraction_failed",
            input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
            model=model,
            n_chunks=0,
            sanitizer_hits=[],
        )
    return extract_ar_signals_from_text(
        ticker, text, anthropic_client=anthropic_client, model=model,
    )


# ---------- DB persistence --------------------------------------------------

def _connect():
    url = os.environ.get("DATABASE_URL")
    if not url:
        return None
    try:
        import psycopg2  # type: ignore
        return psycopg2.connect(url)
    except Exception as exc:
        logger.debug("ar_intel: psycopg2.connect failed (%s)", exc)
        return None


def save_signals(
    annual_report_id: int,
    signals: dict,
    *,
    quality_flag: str = "ok",
    model_version: str = EXTRACTOR_VERSION,
    prompt_version: int = PROMPT_VERSION,
    input_tokens: Optional[int] = None,
    output_tokens: Optional[int] = None,
    cost_usd: Optional[float] = None,
) -> bool:
    """UPSERT a row into ar_signals keyed by
    (annual_report_id, model_version, prompt_version).

    Returns True on success, False on DB unreachable / write
    failure. Does not raise -- callers can decide whether to
    retry.
    """
    if not isinstance(annual_report_id, int) or annual_report_id <= 0:
        raise ValueError("annual_report_id must be a positive int")
    if not isinstance(signals, dict):
        raise ValueError("signals must be a dict")
    if quality_flag not in ("ok", "sebi_withheld", "extraction_failed"):
        raise ValueError(f"bad quality_flag: {quality_flag!r}")

    conn = _connect()
    if conn is None:
        logger.info(
            "save_signals: no DATABASE_URL -- skipping persist for ar_id=%s",
            annual_report_id,
        )
        return False

    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO ar_signals (
                        annual_report_id,
                        segment_data, capex_commitments,
                        related_party_transactions,
                        auditor_flags, contingent_liabilities,
                        management_outlook,
                        quality_flag,
                        model_version, prompt_version,
                        input_tokens, output_tokens, cost_usd
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    ON CONFLICT (annual_report_id, model_version, prompt_version)
                    DO UPDATE SET
                        segment_data               = EXCLUDED.segment_data,
                        capex_commitments          = EXCLUDED.capex_commitments,
                        related_party_transactions = EXCLUDED.related_party_transactions,
                        auditor_flags              = EXCLUDED.auditor_flags,
                        contingent_liabilities     = EXCLUDED.contingent_liabilities,
                        management_outlook         = EXCLUDED.management_outlook,
                        quality_flag               = EXCLUDED.quality_flag,
                        input_tokens               = EXCLUDED.input_tokens,
                        output_tokens              = EXCLUDED.output_tokens,
                        cost_usd                   = EXCLUDED.cost_usd,
                        extracted_at               = now()
                    """,
                    (
                        annual_report_id,
                        json.dumps(signals.get("segment_data") or []),
                        json.dumps(signals.get("capex_commitments") or []),
                        json.dumps(signals.get("related_party_transactions") or []),
                        json.dumps(signals.get("auditor_flags") or []),
                        json.dumps(signals.get("contingent_liabilities") or []),
                        signals.get("management_outlook") or None,
                        quality_flag,
                        model_version,
                        prompt_version,
                        input_tokens,
                        output_tokens,
                        cost_usd,
                    ),
                )
        return True
    except Exception as exc:
        logger.warning("save_signals UPSERT failed for ar_id=%s: %s",
                       annual_report_id, exc)
        return False
    finally:
        try:
            conn.close()
        except Exception:
            pass


# Helper for deterministic chunk-id checksums (callers may
# persist a chunk fingerprint alongside the cost record for
# replay).
def chunk_fingerprint(chunk: dict) -> str:
    """SHA256 of (chunk_id + first 256 chars of text). Stable
    across runs against the same PDF; lets the batch script
    detect whether the chunk has shifted between re-extractions.
    """
    raw = f"{chunk.get('chunk_id', '')}|{chunk.get('text', '')[:256]}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
