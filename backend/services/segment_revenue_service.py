# backend/services/segment_revenue_service.py
# ═══════════════════════════════════════════════════════════════
# Segment-revenue extractor.
#
# Many Indian listed companies file segment-level revenue in their
# XBRL filings (e.g. Bharti Airtel: Mobile Services / Home / Enterprise;
# Bajaj Auto: 2-Wheeler / Commercial; Reliance: O2C / Digital / Retail).
#
# These land in `Financials.raw_data` (TEXT column, JSON-encoded). The
# XBRL key naming is *not* uniform across filings, so this extractor
# tries a list of common keys and normalises the result to a uniform
# shape.  Returns an empty list if nothing matches — callers must
# handle the "no segments" case gracefully.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger("yieldiq.segments")


# Sample shapes we have observed in real BSE/NSE XBRL filings:
#
#   1. Flat list under one of these keys:
#        {"segment_revenue": [{"name": "Mobile Services",
#                              "revenue": 4521.0}, ...]}
#
#   2. Nested under "segments" with mixed key names:
#        {"segments": [{"segment_name": "O2C",
#                       "segment_revenue_cr": 152340}, ...]}
#
#   3. Geographic split:
#        {"geographic_segment_revenue": [{"region": "India",
#                                         "revenue": 12000}, ...]}
#
#   4. Dict-of-name->amount:
#        {"business_segment_revenue": {"Digital": 102, "Retail": 250}}

_LIST_KEYS = (
    "segment_revenue",
    "business_segment_revenue",
    "geographic_segment_revenue",
    "segments",
    "business_segments",
    "operating_segments",
)

_NAME_KEYS = ("name", "segment_name", "segment", "region", "label")
_REVENUE_KEYS = (
    "revenue",
    "revenue_cr",
    "segment_revenue",
    "segment_revenue_cr",
    "amount",
    "value",
)


def _coerce_number(v: Any) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        s = str(v).replace(",", "").strip()
        if not s:
            return None
        return float(s)
    except (ValueError, TypeError):
        return None


def _pick(d: dict, keys: tuple[str, ...]) -> Any:
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return None


def _from_list(items: list, period_end: str | None, period_type: str | None) -> list[dict]:
    out: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = _pick(item, _NAME_KEYS)
        rev = _coerce_number(_pick(item, _REVENUE_KEYS))
        if not name or rev is None:
            continue
        out.append({
            "name": str(name).strip(),
            "revenue_cr": round(rev, 2),
            "period_end": period_end,
            "period_type": period_type,
        })
    return out


def _from_mapping(mapping: dict, period_end: str | None, period_type: str | None) -> list[dict]:
    out: list[dict] = []
    for name, value in mapping.items():
        rev = _coerce_number(value)
        if rev is None:
            continue
        out.append({
            "name": str(name).strip(),
            "revenue_cr": round(rev, 2),
            "period_end": period_end,
            "period_type": period_type,
        })
    return out


def extract_segments(
    raw_data_json: str | dict | None,
    period_end: str | None = None,
    period_type: str | None = None,
) -> list[dict]:
    """Parse segment revenue out of a Financials.raw_data JSON blob.

    Returns a list of dicts shaped:
        {"name": str, "revenue_cr": float,
         "period_end": str|None, "period_type": str|None}

    Returns [] when no segment data is found (the common case).
    """
    if raw_data_json is None:
        return []

    data: Any = raw_data_json
    if isinstance(raw_data_json, (str, bytes)):
        try:
            data = json.loads(raw_data_json)
        except (ValueError, TypeError):
            return []

    if not isinstance(data, dict):
        return []

    for key in _LIST_KEYS:
        if key not in data:
            continue
        node = data[key]
        if isinstance(node, list):
            result = _from_list(node, period_end, period_type)
            if result:
                return result
        elif isinstance(node, dict):
            # Could be either {"items": [...]} OR a name->amount mapping.
            if "items" in node and isinstance(node["items"], list):
                result = _from_list(node["items"], period_end, period_type)
                if result:
                    return result
            result = _from_mapping(node, period_end, period_type)
            if result:
                return result

    return []
