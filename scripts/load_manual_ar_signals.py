#!/usr/bin/env python
"""Bulk-load manually-curated AR signal JSONs into the ar_signals table.

WHY THIS EXISTS
---------------
The Anthropic-API AR backfill (scripts/run_ar_intel_backfill.py) would
cost ~$500 for the full universe. While the operator has a small
credit balance, they can produce 10-20 high-traffic ARs by pasting
the AR text into the FREE claude.ai web interface using the same
SEBI-compliant system prompt that ar_intel_service uses, saving each
response as `<TICKER>_<FY>.json` under `manual_ar_signals/` at the
repo root. This script bulk-loads those files.

CONTRACT
--------
* Filename pattern: ``<TICKER>_<FY>.json`` (e.g. ``HDFCBANK_2025.json``).
  Ticker is uppercase, no .NS suffix. FY is the four-digit fiscal-
  year-end (FY25 -> 2025).
* JSON shape must match the six-section ar_intel schema documented
  in ``backend/services/ar_intel_service.py`` PLUS top-level
  ``ticker`` and ``fiscal_year`` keys for cross-checking against the
  filename:
      ticker, fiscal_year,
      segment_data, capex_commitments, related_party_transactions,
      auditor_flags, contingent_liabilities, management_outlook
* The annual_report_id is looked up from
  ``company_annual_reports`` by ``(ticker, fiscal_year)``. Missing
  row -> the file is reported as failed and the loader continues
  with the rest.
* SEBI sanitizer (``scan_for_banned_vocab``) runs over every string
  leaf. If the count of findings exceeds ``SANITIZER_SWAP_THRESHOLD``
  (5) the row is persisted with ``quality_flag='sebi_withheld'`` and
  the free-text fields blanked; otherwise the offending words are
  swapped for ``[redacted]`` and the row goes in as ``'ok'``.
* INSERT uses ``ON CONFLICT (annual_report_id, model_version,
  prompt_version) DO UPDATE`` so re-runs are idempotent.

DB WRITE METADATA
-----------------
* model_version = ``claude-ai-web-manual``
* prompt_version = 1
* input_tokens = NULL, output_tokens = NULL, cost_usd = 0

USAGE
-----
    python scripts/load_manual_ar_signals.py
    python scripts/load_manual_ar_signals.py --dry-run
    python scripts/load_manual_ar_signals.py --tickers RELIANCE,TCS
    python scripts/load_manual_ar_signals.py --folder ./alt_dir

Exits 0 on a clean run (even if some files failed -- inspect the
summary). Exits 2 only on a hard misconfiguration (no DATABASE_URL
when not in --dry-run, missing input folder).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any, Optional

# Allow ``python scripts/load_manual_ar_signals.py`` from the repo
# root without an editable install.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.services.ar_intel_service import (  # noqa: E402
    SEBI_BANNED_WORDS,
    _path_subject_to_sebi_check,
    scan_for_banned_vocab,
    validate_schema,
)

log = logging.getLogger("yieldiq.load_manual_ar_signals")

MODEL_VERSION = "claude-ai-web-manual"
PROMPT_VERSION = 1
SANITIZER_SWAP_THRESHOLD = 5  # > N findings -> withhold; <= N -> swap in-place

FILENAME_RE = re.compile(r"^([A-Z][A-Z0-9&\-]*)_([0-9]{4})\.json$")

_REQUIRED_TOP_KEYS = (
    "ticker", "fiscal_year",
    "segment_data", "capex_commitments", "related_party_transactions",
    "auditor_flags", "contingent_liabilities", "management_outlook",
)


# ---------------------------------------------------------------------------
# Sanitization helpers (built on ar_intel_service primitives)
# ---------------------------------------------------------------------------

def _swap_banned_in_string(value: str) -> tuple[str, int]:
    """Replace whole-word matches of SEBI_BANNED_WORDS with
    ``[redacted]``. Returns (new_string, n_swaps).
    Case-insensitive on the match; the swapped token is lowercase.
    """
    n = 0
    out = value
    for word in SEBI_BANNED_WORDS:
        pattern = re.compile(rf"\b{re.escape(word)}\b", re.IGNORECASE)
        out, count = pattern.subn("[redacted]", out)
        n += count
    return out, n


def _swap_inplace(node: Any, path: str = "") -> int:
    """Walk the dict in place, swapping banned words in the same
    free-text fields the ar_intel sanitizer inspects. Returns the
    total number of swaps performed.
    """
    if isinstance(node, dict):
        total = 0
        for k, v in list(node.items()):
            child_path = f"{path}.{k}" if path else k
            if isinstance(v, str):
                if _path_subject_to_sebi_check(child_path):
                    new_v, n = _swap_banned_in_string(v)
                    if n:
                        node[k] = new_v
                        total += n
            else:
                total += _swap_inplace(v, child_path)
        return total
    if isinstance(node, list):
        total = 0
        for i, v in enumerate(node):
            child_path = f"{path}[{i}]"
            if isinstance(v, str):
                # Lists of bare strings are rare in the AR schema but
                # the sanitizer's path test treats the parent key as
                # the trigger, so reuse the parent's path.
                if _path_subject_to_sebi_check(path):
                    new_v, n = _swap_banned_in_string(v)
                    if n:
                        node[i] = new_v
                        total += n
            else:
                total += _swap_inplace(v, child_path)
        return total
    return 0


# ---------------------------------------------------------------------------
# Filesystem + JSON parsing
# ---------------------------------------------------------------------------

def parse_filename(name: str) -> Optional[tuple[str, int]]:
    """Return (ticker, fiscal_year) on a valid filename, else None."""
    m = FILENAME_RE.match(name)
    if not m:
        return None
    return m.group(1), int(m.group(2))


def load_and_validate(path: Path) -> dict:
    """Read+parse a JSON file, validate keys + cross-check filename
    matches the embedded ticker/fiscal_year. Raises ValueError on
    any mismatch.
    """
    parsed = parse_filename(path.name)
    if parsed is None:
        raise ValueError(
            f"filename {path.name!r} does not match <TICKER>_<FY>.json"
        )
    fname_ticker, fname_fy = parsed

    with path.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)

    if not isinstance(payload, dict):
        raise ValueError(f"{path.name}: top-level JSON must be an object")

    missing = [k for k in _REQUIRED_TOP_KEYS if k not in payload]
    if missing:
        raise ValueError(f"{path.name}: missing top-level keys {missing}")

    if str(payload["ticker"]).upper() != fname_ticker:
        raise ValueError(
            f"{path.name}: filename ticker {fname_ticker!r} "
            f"!= json ticker {payload['ticker']!r}"
        )
    if int(payload["fiscal_year"]) != fname_fy:
        raise ValueError(
            f"{path.name}: filename FY {fname_fy} "
            f"!= json fiscal_year {payload['fiscal_year']}"
        )

    # Run the same shape validation the live extractor uses.
    validate_schema(payload)
    return payload


# ---------------------------------------------------------------------------
# DB operations
# ---------------------------------------------------------------------------

def _connect_required():
    """Open a psycopg2 connection. Hard-fails (exit 2) when
    DATABASE_URL is absent so we never silently drop the load.
    """
    url = os.environ.get("DATABASE_URL")
    if not url:
        log.error("DATABASE_URL not set; cannot load (use --dry-run to skip DB).")
        sys.exit(2)
    try:
        import psycopg2  # type: ignore
    except ImportError as exc:
        log.error("psycopg2 not installed: %s", exc)
        sys.exit(2)
    return psycopg2.connect(url)


def lookup_ar_id(cur, ticker: str, fiscal_year: int) -> Optional[int]:
    """Find ``company_annual_reports.id`` for (ticker, fiscal_year).
    Returns None when there is no row.
    """
    cur.execute(
        "SELECT id FROM company_annual_reports "
        "WHERE ticker = %s AND fiscal_year = %s "
        "ORDER BY id DESC LIMIT 1",
        (ticker, fiscal_year),
    )
    row = cur.fetchone()
    return int(row[0]) if row else None


def upsert_signals(
    cur,
    annual_report_id: int,
    signals: dict,
    quality_flag: str,
) -> None:
    """Mirrors ar_intel_service.save_signals but accepts a cursor
    (so the caller can batch multiple upserts in one transaction)
    and uses the manual model_version / prompt_version constants.
    """
    cur.execute(
        """
        INSERT INTO ar_signals (
            annual_report_id,
            segment_data, capex_commitments, related_party_transactions,
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
            MODEL_VERSION,
            PROMPT_VERSION,
            None,   # input_tokens
            None,   # output_tokens
            0,      # cost_usd
        ),
    )


# ---------------------------------------------------------------------------
# Per-file pipeline
# ---------------------------------------------------------------------------

def sanitize(payload: dict) -> tuple[dict, str, int]:
    """Run the SEBI sanitizer over ``payload``. Mutates ``payload``
    in place when swapping. Returns (payload, quality_flag, n_findings).

    * <= SANITIZER_SWAP_THRESHOLD findings -> swap each in place,
      flag = 'ok'.
    * >  SANITIZER_SWAP_THRESHOLD findings -> blank free-text fields,
      flag = 'sebi_withheld'.
    """
    findings = scan_for_banned_vocab(payload)
    n = len(findings)
    if n == 0:
        return payload, "ok", 0
    if n <= SANITIZER_SWAP_THRESHOLD:
        _swap_inplace(payload)
        return payload, "ok", n
    # Over threshold -- withhold: blank management_outlook and all
    # free-text 'quote' / 'description' fields, keep numeric scaffolding.
    payload["management_outlook"] = ""
    for key in ("segment_data", "capex_commitments",
                "related_party_transactions", "auditor_flags",
                "contingent_liabilities"):
        items = payload.get(key) or []
        for item in items:
            if isinstance(item, dict):
                for fld in ("quote", "description", "purpose",
                            "drivers", "nature", "outlook",
                            "commentary", "notes", "qualification"):
                    if fld in item and isinstance(item[fld], str):
                        item[fld] = ""
    return payload, "sebi_withheld", n


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Bulk-load manual AR signal JSONs into ar_signals.",
    )
    p.add_argument(
        "--folder",
        default="manual_ar_signals",
        help="Folder containing <TICKER>_<FY>.json files (default: manual_ar_signals).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse / validate / sanitize but do not write to the DB.",
    )
    p.add_argument(
        "--tickers",
        default="",
        help="Comma-separated subset of tickers to load (default: all in folder).",
    )
    p.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose logging.",
    )
    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = _build_argparser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    folder = Path(args.folder)
    if not folder.is_dir():
        log.error("folder %s does not exist", folder)
        return 2

    subset: Optional[set[str]] = None
    if args.tickers.strip():
        subset = {t.strip().upper() for t in args.tickers.split(",") if t.strip()}

    files = sorted(folder.glob("*.json"))
    if subset is not None:
        files = [f for f in files if (parse_filename(f.name) or ("",))[0] in subset]
    if not files:
        log.warning("no JSON files matched in %s (subset=%s)", folder, subset)
        print("loaded=0 withheld=0 failed=0")
        return 0

    conn = None if args.dry_run else _connect_required()
    loaded = withheld = failed = 0

    try:
        for path in files:
            try:
                payload = load_and_validate(path)
                payload, flag, n_hits = sanitize(payload)
                ticker = str(payload["ticker"]).upper()
                fy = int(payload["fiscal_year"])

                if args.dry_run:
                    log.info(
                        "DRY-RUN %s/%s: flag=%s sanitizer_hits=%d",
                        ticker, fy, flag, n_hits,
                    )
                    if flag == "sebi_withheld":
                        withheld += 1
                    else:
                        loaded += 1
                    continue

                with conn:  # transaction per file
                    with conn.cursor() as cur:
                        ar_id = lookup_ar_id(cur, ticker, fy)
                        if ar_id is None:
                            raise RuntimeError(
                                f"no company_annual_reports row for "
                                f"({ticker}, {fy}) -- run the AR-index "
                                f"backfill first."
                            )
                        upsert_signals(cur, ar_id, payload, flag)

                log.info(
                    "loaded %s/%s -> ar_id=%s flag=%s hits=%d",
                    ticker, fy, ar_id, flag, n_hits,
                )
                if flag == "sebi_withheld":
                    withheld += 1
                else:
                    loaded += 1
            except Exception as exc:  # noqa: BLE001 -- per-file isolation
                log.error("FAILED %s: %s", path.name, exc)
                failed += 1
    finally:
        if conn is not None:
            conn.close()

    print(f"loaded={loaded} withheld={withheld} failed={failed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
