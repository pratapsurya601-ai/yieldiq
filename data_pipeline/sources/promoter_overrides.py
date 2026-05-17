# data_pipeline/sources/promoter_overrides.py
# Read-only loader for `data_pipeline/data/promoter_overrides.json`.
#
# Why this exists:
#   The NSE corporate-share-holdings master API returns a single
#   `pr_and_prgrp` (promoter & promoter-group) percentage. For Indian
#   subsidiaries of foreign parents (ITC/BAT, HUL/Unilever, MARUTI/
#   Suzuki, NESTLEIND/Nestle SA, BOSCHLTD/Bosch GmbH) the economic
#   promoter is filed under "Public" / "FPI" categories, so the API
#   reports 0.0% and the analysis page shows "Low stake" — wrong.
#   Indian private banks (HDFCBANK, ICICIBANK, AXISBANK) legitimately
#   have no designated promoter under RBI norms, but the same 0.0%
#   surfaces as "Low stake" rather than "No promoter (RBI norms)".
#
# This loader is the source of truth for those special cases. It
# returns a typed record that callers can merge into the shareholding
# dict before it leaves the analysis service. The JSON file lives
# under data_pipeline/data/ so it ships with the package and needs no
# DB migration (data field only — see CLAUDE.md discipline rules).
from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Literal, TypedDict

logger = logging.getLogger(__name__)

OverrideType = Literal[
    "foreign_promoter",
    "no_promoter_bank",
    "govt_promoter",
    "domestic_promoter",
]


class PromoterOverride(TypedDict, total=False):
    promoter_pct: float | None
    type: OverrideType
    entity: str | None
    source: str


_OVERRIDES_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "promoter_overrides.json"
)


@lru_cache(maxsize=1)
def _load_table() -> dict[str, PromoterOverride]:
    """Load the override table once per process. Returns an empty
    dict if the file is missing or malformed — overrides are purely
    additive, never raise."""
    try:
        with _OVERRIDES_PATH.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        logger.warning(
            "promoter_overrides.json not found at %s; overrides disabled.",
            _OVERRIDES_PATH,
        )
        return {}
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("Failed to load promoter overrides: %s", exc)
        return {}
    # Drop schema/comment keys (anything starting with "_").
    return {
        k.upper(): v
        for k, v in data.items()
        if not k.startswith("_") and isinstance(v, dict)
    }


def _clean(ticker: str | None) -> str:
    if not ticker:
        return ""
    upper = ticker.strip().upper()
    for suffix in (".NS", ".BO"):
        if upper.endswith(suffix):
            upper = upper[: -len(suffix)]
            break
    return upper


def get_promoter_override(ticker: str | None) -> PromoterOverride | None:
    """Return the manual override record for `ticker`, or None.

    Caller is expected to prefer the override over the extractor when
    present. The record is a copy — mutate freely."""
    key = _clean(ticker)
    if not key:
        return None
    table = _load_table()
    row = table.get(key)
    if row is None:
        return None
    return dict(row)  # type: ignore[return-value]


def apply_promoter_override(
    ticker: str | None,
    shareholding: dict,
) -> dict:
    """Merge any override into a shareholding dict (returned from
    `_query_shareholding`). Mutates and returns the same dict for
    convenience.

    Adds three keys when an override applies:
      * `promoter_pct`        — overwritten (or set None for banks)
      * `promoter_holding_type` — one of the OverrideType strings
      * `promoter_entity`     — display string for foreign/govt promoter
    """
    if shareholding is None:
        shareholding = {}
    override = get_promoter_override(ticker)
    if override is None:
        return shareholding
    o_type = override.get("type")
    shareholding["promoter_holding_type"] = o_type
    shareholding["promoter_entity"] = override.get("entity")
    shareholding["promoter_override_source"] = override.get("source")
    if o_type == "no_promoter_bank":
        # RBI banks: pct is meaningless, force None so the frontend
        # renders the dedicated "No promoter (RBI norms)" label rather
        # than a 0.0% "Low stake" tag.
        shareholding["promoter_pct"] = None
    else:
        pct = override.get("promoter_pct")
        if pct is not None:
            shareholding["promoter_pct"] = float(pct)
    return shareholding


def is_no_promoter_bank(ticker: str | None) -> bool:
    """Convenience used by the display layer when only the bank-flag
    matters and the pct/entity are not needed."""
    o = get_promoter_override(ticker)
    return bool(o and o.get("type") == "no_promoter_bank")


def list_overrides() -> dict[str, PromoterOverride]:
    """Return a shallow copy of the entire override table (for tests
    and admin tooling). The cached underlying dict is not exposed."""
    return dict(_load_table())
