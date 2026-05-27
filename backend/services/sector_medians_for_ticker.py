# backend/services/sector_medians_for_ticker.py
# ═══════════════════════════════════════════════════════════════
# Per-ticker sector-median lookup.
#
# Tickertape-density-trick #2 (2026-05-27, audit
# .audit/tickertape-deep-walk-2026-05-27.md): every primary ratio
# on the analysis page should sit next to a "Sector X" reference
# number, not float standalone. This service produces the 5 medians
# that the frontend chips read.
#
# Output shape (per the AnalysisResponse contract):
#     {
#         "pe":         float | None,
#         "pb":         float | None,
#         "roe":        float | None,
#         "div_yield":  float | None,
#         "op_margin":  float | None,
#     }
#
# Cohort definition is reused from `sector_pages.SECTOR_PAGES` — the
# same slug-keyed cohorts that back the /sector/{slug} landing page.
# Cohort medians are computed from the latest `analysis_cache` row of
# each cohort member (NOT freshly recomputed) and the result is cached
# in-process for 15 min keyed by slug, so the analysis hot path pays a
# single dict lookup after the first warm-up.
#
# When the ticker doesn't belong to any Day-108c cohort (ADR-cohort
# names like TCS-via-ADR, data_limited tickers, fresh listings) every
# value is None — the frontend chips self-hide per metric in that case.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import logging
import statistics
import threading
import time
from typing import Any, Optional

logger = logging.getLogger("yieldiq.sector_medians_for_ticker")


# Empty shell returned when the ticker is out-of-cohort or all
# downstream lookups fail. The frontend treats each None as "hide
# this chip", so the panel degrades cleanly to no-chips.
_EMPTY: dict[str, Optional[float]] = {
    "pe": None,
    "pb": None,
    "roe": None,
    "div_yield": None,
    "op_margin": None,
}


# Per-slug median cache. The cohort itself is small (<= ~15 tickers)
# and the underlying analysis_cache moves on a daily cadence, so a
# 15-min in-process TTL is well within tolerance — same TTL the
# hex sector-median cache uses (see hex_service._SECTOR_MEDIAN_TTL).
_TTL_SECONDS = 15 * 60
_cache_lock = threading.Lock()
_cache: dict[str, tuple[float, dict[str, Optional[float]]]] = {}


def _median_or_none(values: list[Any]) -> Optional[float]:
    """Median over the non-None projection. ``[]`` and all-None → None.

    Values are coerced through ``float()``; coercion failures (strings,
    NaN-likes from upstream cache writers) are dropped silently —
    poisoning the median with a default would be worse than omitting
    the chip.
    """
    clean: list[float] = []
    for v in values or []:
        if v is None:
            continue
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        # statistics.median rejects NaN by accepting it as a "value" and
        # producing meaningless output — filter explicitly.
        if f != f:  # NaN check without importing math
            continue
        clean.append(f)
    if not clean:
        return None
    return float(statistics.median(clean))


def _bare(ticker: str) -> str:
    """Strip the .NS / .BO exchange suffix to match cohort symbols.

    The Day-108c cohort table (sector_pages.SECTOR_PAGES) stores bare
    symbols; analysis routes accept either form. Normalize so the
    reverse lookup is a single dict compare.
    """
    if not ticker:
        return ""
    s = str(ticker).upper().strip()
    for suf in (".NS", ".BO", ".BSE", ".NSE"):
        if s.endswith(suf):
            return s[: -len(suf)]
    return s


def _find_cohort_slug(bare_ticker: str) -> Optional[str]:
    """Reverse-lookup the Day-108c cohort slug for a bare ticker.

    Returns None when the ticker is in no cohort — the typical case
    for small/mid-caps outside the curated landing-page set. The
    `sector_pages` import is local so callers that never invoke this
    helper (e.g. test environments without the cohort registry) don't
    pay the import cost.
    """
    try:
        from backend.services.sector_pages import SECTOR_PAGES
    except Exception as exc:
        logger.warning("sector_medians_for_ticker: SECTOR_PAGES import failed: %s", exc)
        return None
    if not bare_ticker:
        return None
    for slug, cohort in SECTOR_PAGES.items():
        if bare_ticker in cohort.get("tickers", ()):  # tuple of bare symbols
            return slug
    return None


def _extract_op_margin(payload: dict) -> Optional[float]:
    """Best-effort operating margin in percent from a cached payload.

    The analysis payload doesn't expose op-margin at a single canonical
    key, so we walk a small list of likely homes and accept the first
    that parses as a number. Returns None when none of the slots are
    populated — better than a fabricated zero.
    """
    if not isinstance(payload, dict):
        return None
    # Common slots ordered by likelihood / authoritativeness.
    candidates = [
        (payload.get("quality") or {}).get("operating_margin"),
        (payload.get("quality") or {}).get("op_margin"),
        (payload.get("insights") or {}).get("operating_margin"),
        (payload.get("valuation") or {}).get("operating_margin"),
    ]
    for v in candidates:
        if v is None:
            continue
        try:
            return float(v)
        except (TypeError, ValueError):
            continue
    return None


def _extract_div_yield(payload: dict) -> Optional[float]:
    """Best-effort dividend yield in percent from a cached payload.

    Mirrors the DividendData contract — ``insights.dividend
    .current_yield_pct`` is the canonical surface; fall back to a
    quality-level ``dividend_yield`` for legacy payloads.
    """
    if not isinstance(payload, dict):
        return None
    div_block = (payload.get("insights") or {}).get("dividend") or {}
    val = div_block.get("current_yield_pct")
    if val is None:
        # Legacy / alternative payloads keep the yield on quality.
        val = (payload.get("quality") or {}).get("dividend_yield")
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _compute_medians_for_slug(slug: str) -> dict[str, Optional[float]]:
    """Cold compute path. Walks the cohort's latest cached payloads
    and medians the 5 metric slots.

    Never raises — any per-ticker fetch error is logged and that ticker
    is skipped. An empty cohort (e.g. analysis_cache wiped) collapses
    every metric to None so the frontend hides every chip.
    """
    try:
        from backend.services.sector_pages import get_cohort
        from backend.services import analysis_cache_service
    except Exception as exc:
        logger.warning("sector_medians_for_ticker: import failed: %s", exc)
        return dict(_EMPTY)

    cohort = get_cohort(slug)
    if not cohort:
        return dict(_EMPTY)

    pes: list[Any] = []
    pbs: list[Any] = []
    roes: list[Any] = []
    yields: list[Any] = []
    op_margins: list[Any] = []

    for bare in cohort.get("tickers", ()):
        symbol = f"{bare}.NS"
        try:
            # Same get_cached_latest the sector landing page uses — it
            # bypasses the manifest's wildcard invalidation so cohorts
            # don't collapse to zero entries right after a global bump.
            payload = analysis_cache_service.get_cached_latest(symbol)
        except Exception as exc:
            logger.debug(
                "sector_medians_for_ticker: cache miss for %s in %s: %s",
                symbol, slug, exc,
            )
            continue
        if not isinstance(payload, dict):
            continue
        qual = payload.get("quality") or {}
        pes.append(qual.get("pe_ratio"))
        pbs.append(qual.get("pb_ratio"))
        roes.append(qual.get("roe"))
        yields.append(_extract_div_yield(payload))
        op_margins.append(_extract_op_margin(payload))

    return {
        "pe": _median_or_none(pes),
        "pb": _median_or_none(pbs),
        "roe": _median_or_none(roes),
        "div_yield": _median_or_none(yields),
        "op_margin": _median_or_none(op_margins),
    }


def _get_cached_medians(slug: str) -> dict[str, Optional[float]]:
    """TTL-bounded cache wrapper around `_compute_medians_for_slug`.

    The cache is per-process. Cross-worker consistency is not required
    here — sector medians shift slowly (daily nightly recompute) and
    even a 15-min skew between workers is well within UX tolerance.
    """
    now = time.monotonic()
    with _cache_lock:
        entry = _cache.get(slug)
        if entry is not None:
            ts, payload = entry
            if (now - ts) < _TTL_SECONDS:
                return payload
    # Compute outside the lock so concurrent requests don't serialize
    # on the cohort walk. A small thundering-herd on cold start is fine
    # — the cohort lookup is < 50 ms wall time.
    payload = _compute_medians_for_slug(slug)
    with _cache_lock:
        _cache[slug] = (now, payload)
    return payload


def get_sector_medians_for_ticker(ticker: str) -> dict[str, Optional[float]]:
    """Public entry point. Returns the 5-key median dict for a ticker.

    Always returns a dict with all 5 keys present (None when unknown
    / out-of-cohort / cache empty) so the frontend can write a stable
    selector without optional-chain noise. Never raises.
    """
    try:
        bare = _bare(ticker)
        if not bare:
            return dict(_EMPTY)
        slug = _find_cohort_slug(bare)
        if slug is None:
            # Out-of-cohort ticker (ADR-cohort, data_limited, fresh
            # listing). Return shell so frontend chips hide.
            return dict(_EMPTY)
        return _get_cached_medians(slug)
    except Exception as exc:
        # The chip surface is purely descriptive — it must never break
        # the analysis response. Swallow + log, return empty shell.
        logger.warning(
            "sector_medians_for_ticker: get failed for %s: %s", ticker, exc,
        )
        return dict(_EMPTY)


def _reset_cache_for_tests() -> None:
    """Test hook — clears the in-process TTL cache."""
    with _cache_lock:
        _cache.clear()
