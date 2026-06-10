# backend/services/revenue_segments_service.py
# ═══════════════════════════════════════════════════════════════
# Revenue-segment breakdown reader (task #176-followup, 2026-06-10).
#
# Reads the latest `ar_signals.segment_data` JSONB row for a ticker
# (populated by ar_intel_service.extract_ar_signals_full from the
# annual-report PDF) and reshapes it into two parallel lists for
# the frontend pie panel: business segments and geographic segments.
#
# The extracted shape (per ar_intel_service prompt) is::
#
#     [{"segment":      "Mobile Services",
#       "revenue_cr":   12345,
#       "ebit_cr":      678,
#       "fy":           "FY24",
#       "geography":    "India",        # optional
#       "kind":         "business",     # optional, one of business|geography
#       "quote":        "..."},
#      ...]
#
# The prompt schema doesn't formally split business vs geography
# rows, so this reader classifies each entry heuristically:
#
#   * Explicit `kind` field wins ("business" / "geography").
#   * Otherwise, names matching a geography vocabulary (India, USA,
#     Asia, Domestic, Exports, Rest of World, etc.) route to geo.
#   * Everything else is a business segment.
#
# Percentages are computed within each list so business + geography
# each sum to 100%. Empty lists are valid — frontend renders an
# honest "AR signals coming soon" empty state.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Iterable

logger = logging.getLogger("yieldiq.revenue_segments")


# Geography keyword vocabulary. Matched case-insensitively against
# the segment name. We err on the side of "geography" only when a
# clear hit exists — false-positive routing into business segments
# (the larger bucket) is the safer failure mode.
_GEO_KEYWORDS: tuple[str, ...] = (
    "india",
    "domestic",
    "indian",
    "exports",
    "export",
    "overseas",
    "international",
    "rest of world",
    "row",
    "rest of asia",
    "asia",
    "apac",
    "asia pacific",
    "americas",
    "north america",
    "south america",
    "latin america",
    "latam",
    "usa",
    "united states",
    "us ",
    "europe",
    "emea",
    "uk ",
    "united kingdom",
    "middle east",
    "africa",
    "anz",
    "australia",
    "japan",
    "china",
    "geography",
    "geographic",
    "region",
    "regional",
    "outside india",
    "within india",
)

_GEO_RE = re.compile(
    r"\b(" + "|".join(re.escape(k.strip()) for k in _GEO_KEYWORDS) + r")\b",
    re.IGNORECASE,
)


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            f = float(value)
        except (ValueError, TypeError, OverflowError):
            return None
        if f != f:  # NaN
            return None
        return f
    if isinstance(value, str):
        s = value.strip().replace(",", "")
        if not s:
            return None
        try:
            return float(s)
        except (ValueError, TypeError):
            return None
    return None


def _name_of(row: dict) -> str | None:
    for key in ("segment", "name", "segment_name", "region", "geography", "label"):
        v = row.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def _classify(row: dict, name: str) -> str:
    """Return 'business' or 'geography' for a single segment row.

    Explicit ``kind`` wins; otherwise we check the name against the
    geography vocabulary. Default is 'business' so a noisy AR
    doesn't accidentally drain the larger bucket.
    """
    kind = row.get("kind") or row.get("segment_type") or row.get("type")
    if isinstance(kind, str):
        k = kind.strip().lower()
        if k in ("geography", "geographic", "geo", "region", "regional"):
            return "geography"
        if k in ("business", "operating", "operational", "product"):
            return "business"

    if row.get("geography") and not row.get("segment"):
        return "geography"

    if _GEO_RE.search(name or ""):
        return "geography"
    return "business"


def _connect():
    """Open a psycopg2 connection. Returns None on missing
    DATABASE_URL or driver-import failure. Mirrors the degrade
    pattern in backend/routers/annual_reports.py — endpoints return
    an empty payload rather than 500-ing the analysis page.
    """
    url = os.environ.get("DATABASE_URL")
    if not url:
        return None
    try:
        import psycopg2  # type: ignore
        return psycopg2.connect(url)
    except Exception as exc:  # pragma: no cover - driver missing in some envs
        logger.debug("revenue_segments: psycopg2.connect failed (%s)", exc)
        return None


def _bare_ticker(ticker: str) -> str:
    bare = (ticker or "").strip().upper()
    for suffix in (".NS", ".BO"):
        if bare.endswith(suffix):
            bare = bare[: -len(suffix)]
            break
    return bare


_SEGMENTS_SQL = (
    "SELECT s.segment_data, s.quality_flag, "
    "       car.fiscal_year, car.published_at "
    "FROM ar_signals s "
    "JOIN company_annual_reports car ON car.id = s.annual_report_id "
    "WHERE car.ticker IN (%s, %s, %s) "
    "ORDER BY car.published_at DESC NULLS LAST, "
    "         car.fiscal_year DESC, "
    "         s.extracted_at DESC "
    "LIMIT 5"
)


def _normalise_segments(raw: Any) -> list[dict]:
    """psycopg2 returns JSONB as either dict/list or raw JSON string.
    Normalise to a list of row dicts. Returns [] on parse failure
    so the caller can render an honest empty state."""
    if raw is None:
        return []
    if isinstance(raw, (dict, list)):
        data: Any = raw
    elif isinstance(raw, (str, bytes)):
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            return []
    else:
        return []
    if isinstance(data, dict):
        # Defensive — the schema is a list but a single dict could
        # show up if a hand-written backfill row used the wrong shape.
        data = [data]
    if not isinstance(data, list):
        return []
    return [row for row in data if isinstance(row, dict)]


def _build_buckets(rows: Iterable[dict]) -> tuple[list[dict], list[dict]]:
    """Split rows into (business, geography) lists, dedup-by-name."""
    business: dict[str, dict] = {}
    geography: dict[str, dict] = {}

    for raw in rows:
        name = _name_of(raw)
        if not name:
            continue
        revenue = _coerce_float(
            raw.get("revenue_cr")
            if raw.get("revenue_cr") is not None
            else raw.get("revenue")
        )
        if revenue is None or revenue <= 0:
            continue
        ebit = _coerce_float(raw.get("ebit_cr"))
        yoy = _coerce_float(raw.get("yoy_growth_pct"))
        fy = raw.get("fy") if isinstance(raw.get("fy"), str) else None
        bucket_name = _classify(raw, name)
        bucket = business if bucket_name == "business" else geography
        # De-dup on case-insensitive name — sum revenue if the same
        # segment name appears twice in a single AR chunk extraction.
        key = name.casefold()
        prior = bucket.get(key)
        if prior is None:
            bucket[key] = {
                "name": name,
                "revenue_cr": round(revenue, 2),
                "ebit_cr": round(ebit, 2) if ebit is not None else None,
                "yoy_growth_pct": round(yoy, 2) if yoy is not None else None,
                "fy": fy,
            }
        else:
            prior["revenue_cr"] = round((prior["revenue_cr"] or 0) + revenue, 2)
            if prior["ebit_cr"] is None and ebit is not None:
                prior["ebit_cr"] = round(ebit, 2)
            if prior["yoy_growth_pct"] is None and yoy is not None:
                prior["yoy_growth_pct"] = round(yoy, 2)
            if not prior.get("fy") and fy:
                prior["fy"] = fy

    def _finalise(bucket: dict[str, dict]) -> list[dict]:
        items = list(bucket.values())
        items.sort(key=lambda r: r["revenue_cr"] or 0.0, reverse=True)
        total = sum(r["revenue_cr"] or 0.0 for r in items)
        if total <= 0:
            return []
        for r in items:
            r["pct"] = round(100.0 * (r["revenue_cr"] or 0.0) / total, 2)
        return items

    return _finalise(business), _finalise(geography)


def _fastest_growing(items: list[dict]) -> dict | None:
    """Pick the segment with the largest positive yoy_growth_pct.
    Returns None when no row carries a YoY value."""
    candidates = [r for r in items if r.get("yoy_growth_pct") is not None]
    if not candidates:
        return None
    top = max(candidates, key=lambda r: r["yoy_growth_pct"] or 0.0)
    if (top.get("yoy_growth_pct") or 0.0) <= 0:
        return None
    return top


def empty_payload(ticker: str | None = None) -> dict:
    """Honest "no extraction yet" payload."""
    return {
        "ticker": (ticker or "").strip().upper() or None,
        "fiscal_year": None,
        "published_at": None,
        "business_segments": [],
        "geo_segments": [],
        "trend": None,
        "withheld": False,
        "source": "annual_report",
    }


def get_segments_for_ticker(ticker: str, *, conn=None) -> dict:
    """Return the latest segment breakdown for ``ticker``.

    Shape::

        {"ticker":            "RELIANCE",
         "fiscal_year":       2024,
         "published_at":      "2024-08-15",
         "business_segments": [{"name", "revenue_cr", "pct",
                                "ebit_cr", "yoy_growth_pct", "fy"}, ...],
         "geo_segments":      [...same shape...],
         "trend":             {"name", "yoy_growth_pct"} | null,
         "withheld":          false,
         "source":            "annual_report"}

    Always returns 200-shaped payload — never raises on missing
    data. The frontend renders an honest "AR signals coming soon"
    empty state when both lists are empty.
    """
    bare = _bare_ticker(ticker)
    if not bare:
        return empty_payload(ticker)

    own_conn = False
    if conn is None:
        conn = _connect()
        own_conn = True
    if conn is None:
        return empty_payload(bare)

    try:
        cur = conn.cursor()
        try:
            cur.execute(_SEGMENTS_SQL, (bare, f"{bare}.NS", f"{bare}.BO"))
            rows = cur.fetchall()
        finally:
            try:
                cur.close()
            except Exception:
                pass
    except Exception as exc:
        logger.warning("get_segments_for_ticker(%s) failed: %s", bare, exc)
        return empty_payload(bare)
    finally:
        if own_conn:
            try:
                conn.close()
            except Exception:
                pass

    if not rows:
        return empty_payload(bare)

    # Walk newest-first; if the most-recent AR yields no usable
    # rows (e.g. all entries lack revenue_cr) fall back to the next
    # year. Caps at 5 ARs via the LIMIT in _SEGMENTS_SQL.
    fy_used: int | None = None
    published_used = None
    business: list[dict] = []
    geography: list[dict] = []

    for raw_blob, quality_flag, fy, published in rows:
        if (quality_flag or "").lower() == "sebi_withheld":
            # Withheld envelope — return empty + flag so the panel
            # can show a neutral "quality review pending" state.
            payload = empty_payload(bare)
            payload["withheld"] = True
            payload["fiscal_year"] = int(fy) if fy is not None else None
            payload["published_at"] = published.isoformat() if hasattr(published, "isoformat") else published
            return payload
        normalised = _normalise_segments(raw_blob)
        b, g = _build_buckets(normalised)
        if b or g:
            business, geography = b, g
            fy_used = int(fy) if fy is not None else None
            published_used = published.isoformat() if hasattr(published, "isoformat") else published
            break

    payload = empty_payload(bare)
    payload["business_segments"] = business
    payload["geo_segments"] = geography
    payload["fiscal_year"] = fy_used
    payload["published_at"] = published_used

    # Trend chip: prefer the largest positive YoY across either bucket.
    candidates: list[dict] = []
    biz_trend = _fastest_growing(business)
    geo_trend = _fastest_growing(geography)
    if biz_trend:
        candidates.append(biz_trend)
    if geo_trend:
        candidates.append(geo_trend)
    if candidates:
        top = max(candidates, key=lambda r: r["yoy_growth_pct"] or 0.0)
        payload["trend"] = {
            "name": top["name"],
            "yoy_growth_pct": top["yoy_growth_pct"],
        }
    return payload
