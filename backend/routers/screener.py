# backend/routers/screener.py
# Stock screener — queries Aiven pipeline DB for real-time ranked stocks.
#
# ─── market_metrics dedupe discipline (2026-04-21) ────────────────────
# The ``market_metrics`` table stores ONE ROW PER LISTING, not per
# ticker. Dual-listed tickers (NSE+BSE) therefore have TWO rows each,
# and ~70% of the table (2,652/3,780) is effectively duplicate when
# viewed through the stocks-master "one ticker, one company" lens.
# Any query that JOINs market_metrics directly against stocks (or does
# ``SELECT ... FROM market_metrics``) will inflate:
#   • COUNT(*) by up to 2×
#   • result lists (same ticker twice — BPCL regressed this way in prod)
#   • aggregate ORDER BY mm.market_cap_cr (same ticker appears twice)
# The cure is ALWAYS either (a) ``DISTINCT ON (ticker) ... ORDER BY
# ticker, trade_date DESC`` inside a CTE/subquery, or (b) ``GROUP BY
# ticker`` before JOINing. We do NOT add a unique constraint on
# market_metrics(ticker) because the duplicates have semantic meaning
# (NSE-listing row vs BSE-listing row carry different close_price,
# volume, etc.). Deduplicate at READ TIME.  See docs/ticker_format_audit.md.
# ─────────────────────────────────────────────────────────────────────
from __future__ import annotations
import logging
from typing import Any, Optional
from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from backend.models.responses import ScreenerResponse, ScreenerStock
from backend.middleware.auth import get_current_user, get_current_user_optional, require_tier

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/screener", tags=["screener"])


# ─────────────────────────────────────────────────────────────────
# Smart (composite criteria) screener — extends the existing single-
# filter endpoints with a multi-criterion builder.
#
# Why a NEW endpoint instead of overloading /run or /query:
#   - /run is the legacy two-knob (min_score, min_mos) form used by
#     /home Quant-Pick tiles; stable contract, anon-allowed.
#   - /query (in routers/public.py) is the DSL form used by the
#     existing /screener page; only exposes the ratio_history /
#     market_metrics / fair_value_history join (no payload JSONB
#     fields like dividend_streak_years or sbc_intensity_label).
#   - The new /smart endpoint reads the analysis_cache JSONB payload
#     directly so it can filter on the richer engine outputs that
#     never made it into a flat column (dividend streak, SBC
#     intensity label, fair_value_ratio). Trade-off: this is an
#     in-memory filter, not a SQL push-down. Universe is ~3k tickers
#     and each row is small after JSONB projection — well inside
#     the 200ms budget for a Railway worker. If we ever blow past
#     that we can promote the hot fields into a materialised view
#     and switch /smart to SQL. The contract here doesn't need to
#     change for that future migration.
#
# Fields are intentionally a curated allowlist (SMART_FIELDS below)
# rather than "anything in the payload". Letting the public POST
# arbitrary JSONB keys risks (a) leaking internal engine knobs and
# (b) loose schema drift — better to widen the list explicitly when
# the UI grows a new criterion.
# ─────────────────────────────────────────────────────────────────


# Each entry: (label, type, jsonb_path, sample-op-set). The path is
# the dotted route under `payload->` we read at filter time. Numeric
# fields support 6 comparators; string fields use only = / != / in
# (latter handled via the value being a comma list, see _match_string).
SMART_FIELDS: dict[str, dict[str, Any]] = {
    "mos": {
        "label": "Margin of Safety %",
        "type": "number",
        "path": "valuation.margin_of_safety",
    },
    "fair_value_ratio": {
        "label": "Fair Value / Price",
        "type": "number",
        "path": "valuation.fair_value_ratio",
    },
    "score": {
        "label": "YieldIQ Score",
        "type": "number",
        "path": "quality.yieldiq_score",
    },
    "roe": {
        "label": "ROE %",
        "type": "number",
        "path": "quality.roe",
    },
    "roce": {
        "label": "ROCE %",
        "type": "number",
        "path": "quality.roce",
    },
    "pe_ratio": {
        "label": "P/E",
        "type": "number",
        "path": "valuation.pe_ratio",
    },
    "pb_ratio": {
        "label": "P/B",
        "type": "number",
        "path": "valuation.pb_ratio",
    },
    "debt_to_equity": {
        "label": "Debt / Equity",
        "type": "number",
        "path": "quality.de_ratio",
    },
    "dividend_streak_years": {
        "label": "Dividend streak (years)",
        "type": "number",
        # The streak is sometimes mirrored under quality.* and
        # sometimes under dividend.consecutive_years. Provide both
        # so older cache rows still match — _read_path will probe in
        # order until something non-null comes back.
        "path": [
            "dividend.consecutive_years",
            "quality.dividend_streak_years",
        ],
    },
    "revenue_cagr_3y": {
        "label": "Revenue CAGR (3y)",
        "type": "number",
        "path": "quality.revenue_cagr_3y",
    },
    "moat": {
        "label": "Moat",
        "type": "string",
        "path": "quality.moat",
    },
    "sbc_intensity_label": {
        "label": "SBC intensity",
        "type": "string",
        # Lives under valuation.* in current payloads; the older
        # quality slot was deprecated but still exists in some
        # cached rows.
        "path": [
            "valuation.sbc_intensity_label",
            "quality.sbc_intensity_label",
        ],
    },
    "verdict": {
        "label": "Verdict band",
        "type": "string",
        "path": "valuation.verdict",
    },
}

SMART_NUMERIC_OPS = {"<", ">", "<=", ">=", "=", "!="}
SMART_STRING_OPS = {"=", "!=", "in", "not_in"}


class SmartCriterion(BaseModel):
    """One composite-screener clause.

    Numeric `value` can be sent as a number or string — both forms
    end up float()-cast at match time so the JSON wire format is
    forgiving. String fields accept a single literal or, for the
    `in` / `not_in` ops, a comma-separated list.
    """
    field: str = Field(..., description="One of SMART_FIELDS keys")
    op: str = Field(..., description="<, >, <=, >=, =, !=, in, not_in")
    value: Any = Field(..., description="Numeric or string value")


class SmartScreenerRequest(BaseModel):
    """POST body for /api/v1/screener/smart.

    `sector` is optional and applies as an implicit equality filter
    on top of `criteria` — kept separate from the criteria list so
    the frontend's sector dropdown maps to a single dedicated knob
    and the URL share-link stays short ("?sector=FMCG&c=…" instead
    of folding sector into the criteria array).
    """
    sector: Optional[str] = None
    criteria: list[SmartCriterion] = Field(default_factory=list)
    sort: Optional[str] = Field(
        default="mos",
        description="Sort field — any SMART_FIELDS key. Prefix '-' for desc.",
    )
    limit: int = Field(default=50, ge=1, le=500)


def _read_path(payload: dict, path: Any) -> Any:
    """Walk a dotted JSONB path, returning None on any miss.

    Accepts either a single dotted string ('valuation.margin_of_safety')
    or a list of fallback paths (first non-null wins). Returning None
    on any segment miss is intentional: filter logic below treats None
    as "row doesn't match" rather than raising — that way a partially
    populated cache row doesn't blow up the whole screener.
    """
    if isinstance(path, list):
        for p in path:
            v = _read_path(payload, p)
            if v is not None:
                return v
        return None
    if not isinstance(payload, dict):
        return None
    cur: Any = payload
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
        if cur is None:
            return None
    return cur


def _coerce_number(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _match_numeric(actual: Optional[float], op: str, target: float) -> bool:
    if actual is None:
        return False
    if op == "<":
        return actual < target
    if op == ">":
        return actual > target
    if op == "<=":
        return actual <= target
    if op == ">=":
        return actual >= target
    if op == "=":
        return actual == target
    if op == "!=":
        return actual != target
    return False


def _match_string(actual: Optional[str], op: str, target: Any) -> bool:
    # Compare case-insensitive and tolerate missing values — string
    # filters are typically labels (moat="Wide", sector="FMCG") so a
    # null payload slot should fail-closed, not crash.
    a = (actual or "").strip().lower()
    if op in ("=", "!="):
        t = str(target).strip().lower()
        return (a == t) if op == "=" else (a != t)
    if op in ("in", "not_in"):
        # Accept either an array or comma-separated string.
        if isinstance(target, (list, tuple)):
            options = [str(x).strip().lower() for x in target]
        else:
            options = [s.strip().lower() for s in str(target).split(",") if s.strip()]
        return (a in options) if op == "in" else (a not in options)
    return False


def _row_matches(payload: dict, sector_value: Optional[str], criteria: list[SmartCriterion]) -> bool:
    if sector_value:
        # Sector comparison is case-insensitive and looks at the
        # canonical `stocks.sector` mirror inside the payload. Some
        # rows nest it under `peer.sector` instead; check both.
        row_sector = _read_path(payload, "sector") or _read_path(payload, "peer.sector")
        if not row_sector or str(row_sector).strip().lower() != sector_value.strip().lower():
            return False

    for crit in criteria:
        spec = SMART_FIELDS.get(crit.field)
        if not spec:
            # Unknown field — fail-closed so a stale frontend can't
            # silently match the universe.
            return False
        raw = _read_path(payload, spec["path"])
        if spec["type"] == "number":
            num = _coerce_number(raw)
            target = _coerce_number(crit.value)
            if target is None:
                return False
            if not _match_numeric(num, crit.op, target):
                return False
        else:
            if not _match_string(raw if isinstance(raw, str) else None, crit.op, crit.value):
                return False
    return True


def _validate_criteria(criteria: list[SmartCriterion]) -> None:
    """Raise HTTPException(400) on any malformed criterion before scan."""
    for c in criteria:
        if c.field not in SMART_FIELDS:
            raise HTTPException(
                status_code=400,
                detail=f"unknown field {c.field!r}; allowed: {sorted(SMART_FIELDS)}",
            )
        spec = SMART_FIELDS[c.field]
        if spec["type"] == "number":
            if c.op not in SMART_NUMERIC_OPS:
                raise HTTPException(
                    status_code=400,
                    detail=f"{c.field} is numeric; op {c.op!r} not in {sorted(SMART_NUMERIC_OPS)}",
                )
            if _coerce_number(c.value) is None:
                raise HTTPException(
                    status_code=400,
                    detail=f"{c.field} needs a numeric value; got {c.value!r}",
                )
        else:
            if c.op not in SMART_STRING_OPS:
                raise HTTPException(
                    status_code=400,
                    detail=f"{c.field} is string; op {c.op!r} not in {sorted(SMART_STRING_OPS)}",
                )


def _scan_smart_universe(
    sector: Optional[str],
    criteria: list[SmartCriterion],
) -> list[dict]:
    """Walk analysis_cache (last 48h) + in-memory tier-2 and collect
    matching rows. Returns a list of small dicts (ticker, score, mos,
    sector, mcap_cr, fair_value_ratio) ready for sorting & truncation.

    Dedupes by bare ticker (strip .NS/.BO) — same fix pattern as
    _query_preset_from_db above. Cross-listing rows would otherwise
    inflate the count preview by ~30%.
    """
    out: list[dict] = []
    seen: set[str] = set()

    # Tier 1: persistent analysis_cache.
    try:
        from data_pipeline.db import Session as _Session
        from sqlalchemy import text as _sql_text
        sess = _Session()
        try:
            rows = sess.execute(_sql_text(
                """
                SELECT ticker, payload
                FROM analysis_cache
                WHERE computed_at > now() - interval '48 hours'
                """
            )).fetchall()
        finally:
            sess.close()
        for ticker, payload in rows:
            if not isinstance(payload, dict):
                continue
            dedup = (ticker or "").split(".")[0].upper()
            if not dedup or dedup in seen:
                continue
            if not _row_matches(payload, sector, criteria):
                continue
            seen.add(dedup)
            out.append(_summarize_match(ticker, payload))
    except Exception as exc:
        logger.info("smart-screener: analysis_cache scan skipped: %s", exc)

    # Tier 2: in-memory cache (recently-computed but not yet flushed).
    try:
        from backend.services.cache_service import cache as _c
        for key in list(_c._store.keys()):
            if not key.startswith("analysis:") or ".NS" not in key:
                continue
            val = _c.get(key)
            if not val:
                continue
            # ScreenerResponse objects come through dict-ish; coerce to
            # a plain dict using model_dump if it's a pydantic model.
            payload = val.model_dump() if hasattr(val, "model_dump") else val
            if not isinstance(payload, dict):
                continue
            ticker = payload.get("ticker") or ""
            dedup = ticker.split(".")[0].upper()
            if not dedup or dedup in seen:
                continue
            if not _row_matches(payload, sector, criteria):
                continue
            seen.add(dedup)
            out.append(_summarize_match(ticker, payload))
    except Exception as exc:
        logger.info("smart-screener: in-memory scan skipped: %s", exc)

    return out


def _summarize_match(ticker: str, payload: dict) -> dict:
    """Pluck the small set of fields we render in the result list +
    use for sorting. Keep the payload itself out of the response —
    it can be 100KB+ per row, and the builder UI only needs the
    summary chips."""
    full = ticker if "." in ticker else f"{ticker}.NS"
    return {
        "ticker": full,
        "score": _coerce_number(_read_path(payload, "quality.yieldiq_score")),
        "mos": _coerce_number(_read_path(payload, "valuation.margin_of_safety")),
        "fair_value_ratio": _coerce_number(_read_path(payload, "valuation.fair_value_ratio")),
        "pe_ratio": _coerce_number(_read_path(payload, "valuation.pe_ratio")),
        "roe": _coerce_number(_read_path(payload, "quality.roe")),
        "sector": _read_path(payload, "sector") or _read_path(payload, "peer.sector"),
        "verdict": _read_path(payload, "valuation.verdict"),
    }


def _sort_matches(matches: list[dict], sort: Optional[str]) -> list[dict]:
    key = (sort or "mos").lstrip("-")
    desc = (sort or "mos").startswith("-") or key in {"mos", "score", "fair_value_ratio", "roe", "roce"}
    # None must sink to the bottom regardless of direction. We can't
    # rely on `(v is None, v)` because `reverse=True` flips the
    # None-flag too. Sort in two passes instead: first by value asc/
    # desc with None-as-sentinel, then stable-partition None to the
    # back. This costs one extra O(N) scan and keeps the semantics
    # obvious in code review.
    nulls = [r for r in matches if r.get(key) is None]
    real = [r for r in matches if r.get(key) is not None]
    real.sort(key=lambda r: r.get(key), reverse=desc)
    matches[:] = real + nulls
    return matches


def _summary_stats(matches: list[dict]) -> dict:
    """Aggregate the summary footer the UI shows above the result
    table ("47 names · median MoS 18% · median score 62"). Median is
    cheap on a list of ~50–500 floats."""
    def _median(vs: list[float]) -> Optional[float]:
        clean = sorted(v for v in vs if v is not None)
        if not clean:
            return None
        n = len(clean)
        if n % 2:
            return clean[n // 2]
        return (clean[n // 2 - 1] + clean[n // 2]) / 2

    return {
        "count": len(matches),
        "median_mos": _median([m["mos"] for m in matches]),
        "median_score": _median([m["score"] for m in matches]),
        "median_roe": _median([m["roe"] for m in matches]),
    }


@router.get("/smart/fields")
async def smart_screener_fields():
    """Metadata for the smart-criteria builder UI.

    Returned in the same shape as /screener/fields so the existing
    frontend type can be reused. The `meta` block carries op sets
    per field type so the UI can render the operator picker without
    a second round-trip.
    """
    return {
        "fields": [
            {
                "key": k,
                "label": v["label"],
                "type": v["type"],
            }
            for k, v in SMART_FIELDS.items()
        ],
        "ops": {
            "number": sorted(SMART_NUMERIC_OPS),
            "string": sorted(SMART_STRING_OPS),
        },
        "sort_keys": [
            k for k, v in SMART_FIELDS.items() if v["type"] == "number"
        ],
    }


@router.post("/smart")
async def run_smart_screener(
    body: SmartScreenerRequest = Body(...),
    user: dict | None = Depends(get_current_user_optional),
):
    """Composite-criteria screener.

    Filters applied as a logical AND across `sector` + every
    criterion. The composite engine is intentionally an in-process
    scan over the analysis_cache JSONB payloads rather than SQL
    push-down — see the module-level note above /smart for why.

    Returns:
      {
        "matches": [...],     # truncated to body.limit
        "count": int,         # total before truncation
        "summary": {...},     # median MoS/score/ROE over matches
        "criteria_echo": [...]  # what the server actually applied
      }
    """
    _validate_criteria(body.criteria)
    matches = _scan_smart_universe(body.sector, body.criteria)
    total = len(matches)
    matches = _sort_matches(matches, body.sort)
    summary = _summary_stats(matches)
    page = matches[: body.limit]
    return {
        "matches": page,
        "count": total,
        "summary": summary,
        "criteria_echo": [c.model_dump() for c in body.criteria],
        "sector": body.sector,
        "sort": body.sort or "mos",
        "limit": body.limit,
    }


@router.post("/smart/count")
async def smart_screener_count(
    body: SmartScreenerRequest = Body(...),
    user: dict | None = Depends(get_current_user_optional),
):
    """Cheap count-only endpoint for the builder's live preview.

    The builder calls this on every criterion edit (debounced) to
    populate the "47 names match" chip. Skipping the sort + summary
    + per-row projection cuts ~30% of the work vs /smart for the
    same scan and keeps keystroke-latency under 100ms on the
    Railway worker even when nothing is cached.
    """
    _validate_criteria(body.criteria)
    matches = _scan_smart_universe(body.sector, body.criteria)
    return {"count": len(matches), "sector": body.sector}


def _query_stocks_from_db(min_score: int = 0, min_mos: float = -100,
                          page: int = 1, page_size: int = 25) -> tuple[list[ScreenerStock], int]:
    """Query stocks from Aiven pipeline database."""
    try:
        from data_pipeline.db import Session
        if Session is None:
            return [], 0

        from sqlalchemy import text
        db = Session()
        try:
            # Get stocks with market metrics — rank by PE (lower = more undervalued)
            # Only show quality stocks: market cap > 2000 Cr, PE between 3-50
            #
            # DISTINCT ON (mm.ticker) dedupes cross-listing rows in
            # market_metrics (NSE+BSE). See the module-level design note
            # at the top of this file. Without it, "2,907 stocks" in the
            # UI was ~1,700 real tickers counted twice.
            # PR #218 read-path fallback: skip NULL-mcap rows + prefer high-trust source.
            # Prevents 2026-04-30 yfinance-NULL incident class.
            query = text("""
                WITH mm_dedup AS (
                    SELECT DISTINCT ON (ticker)
                        ticker, pe_ratio, pb_ratio, beta_1yr,
                        market_cap_cr, dividend_yield
                    FROM market_metrics
                    WHERE market_cap_cr IS NOT NULL AND market_cap_cr > 0
                    ORDER BY ticker, COALESCE(data_quality_rank, 50) ASC, trade_date DESC
                )
                SELECT
                    s.ticker,
                    s.company_name,
                    mm.pe_ratio,
                    mm.pb_ratio,
                    mm.beta_1yr,
                    mm.market_cap_cr,
                    mm.dividend_yield
                FROM stocks s
                JOIN mm_dedup mm ON mm.ticker = s.ticker
                WHERE s.is_active = true
                  AND mm.pe_ratio BETWEEN 3 AND 50
                  AND mm.market_cap_cr > 2000
                ORDER BY mm.pe_ratio ASC
                LIMIT :lim OFFSET :off
            """)
            offset = (page - 1) * page_size
            rows = db.execute(query, {"lim": page_size, "off": offset}).fetchall()

            # Count must ALSO dedupe — pre-fix this was returning ~2,900
            # for a true universe of ~1,700.
            # PR #218 read-path fallback: skip NULL-mcap rows + prefer high-trust source.
            # Prevents 2026-04-30 yfinance-NULL incident class.
            count_q = text("""
                WITH mm_dedup AS (
                    SELECT DISTINCT ON (ticker) ticker, pe_ratio, market_cap_cr
                    FROM market_metrics
                    WHERE market_cap_cr IS NOT NULL AND market_cap_cr > 0
                    ORDER BY ticker, COALESCE(data_quality_rank, 50) ASC, trade_date DESC
                )
                SELECT COUNT(*) FROM stocks s
                JOIN mm_dedup mm ON mm.ticker = s.ticker
                WHERE s.is_active = true
                  AND mm.pe_ratio BETWEEN 3 AND 50
                  AND mm.market_cap_cr > 2000
            """)
            total = db.execute(count_q).scalar() or 0

            # PR-SCREENER-DEDUP: market_metrics can have duplicate ticker
            # rows (multi-listing on NSE+BSE, or pipeline write conflicts).
            # The JOIN above multiplies them. Dedupe in Python so the
            # output has exactly one row per ticker (first hit wins —
            # already ordered by pe_ratio so that's the cheapest).
            stocks = []
            seen: set[str] = set()
            for row in rows:
                ticker = row[0]
                if not ticker or ticker in seen:
                    continue
                seen.add(ticker)
                name = row[1] or ticker
                pe = row[2] or 0
                pb = row[3] or 0
                beta = row[4] or 1.0
                mcap = row[5] or 0

                # Simple score: lower PE + lower PB = higher score
                pe_score = max(0, min(40, int((30 - pe) / 30 * 40))) if pe > 0 else 0
                pb_score = max(0, min(30, int((5 - pb) / 5 * 30))) if pb > 0 else 0
                simple_score = pe_score + pb_score + 20  # base 20

                # Simple MoS estimate from PE (sector median ~20)
                mos = round((20 - pe) / 20 * 100, 1) if pe > 0 else 0

                stocks.append(ScreenerStock(
                    ticker=f"{ticker}.NS" if "." not in ticker else ticker,
                    score=max(0, min(100, simple_score)),
                    margin_of_safety=mos,
                ))

            return stocks, total
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"Screener DB query failed: {e}")
        return [], 0


def _query_preset_from_db(preset: str, page: int = 1,
                          page_size: int = 25) -> tuple[list[ScreenerStock], int]:
    """
    Run preset screener against the in-memory analysis cache.

    Replaces the previous market_metrics DB query (which returned empty
    because that table isn't populated yet). The analysis cache has
    hundreds of stocks with real DCF data — much more useful.

    2026-06-11 (P0 home Quant-Picks zero-matches fix): when the strict
    filter returns 0 candidates, an automatic relaxation pass kicks in
    so the home tile is never wholly empty. Strict-pass thresholds are
    preserved (they're what /screener?preset=… still shows); the relax
    pass only runs as a last-resort widening so /home shows at least a
    handful of "closest matches" instead of "0".

    The relaxation pass is signaled to the caller via the
    `_query_preset_from_db.last_relaxed` module-level flag —
    intentionally side-channelled rather than threaded through the
    return tuple so the public signature stays compatible with the
    /export tier's existing caller. The caller copies the flag into
    filter_applied so the frontend can show "Showing closest matches"
    when relaxed=True.
    """
    stocks, total = _run_preset_pass(preset, page, page_size, relaxed=False)
    if total > 0:
        _query_preset_from_db.last_relaxed = False  # type: ignore[attr-defined]
        return stocks, total
    # Strict pass returned 0 — try the relaxed pass so /home never shows
    # all four Quant-Pick tiles at 0/0/0/0. This is a "closest matches"
    # widening, not a re-definition of the preset — the strict thresholds
    # are still the canonical filter on the /screener?preset=… page.
    stocks2, total2 = _run_preset_pass(preset, page, page_size, relaxed=True)
    _query_preset_from_db.last_relaxed = total2 > 0  # type: ignore[attr-defined]
    return stocks2, total2


# Module-level flag — see docstring above for why side-channel.
_query_preset_from_db.last_relaxed = False  # type: ignore[attr-defined]


def _run_preset_pass(preset: str, page: int, page_size: int,
                     relaxed: bool) -> tuple[list[ScreenerStock], int]:
    """Single pass of the preset query. `relaxed=True` widens every
    threshold by a uniform step so 0-match cohorts still surface
    "closest" candidates on /home tiles.

    Why uniform widening rather than per-preset tuning: keeps the relax
    pass auditable in one place. The strict gates remain authoritative
    for the /screener?preset=… page (relaxed=False is the default).
    """
    try:
        from backend.services.cache_service import cache as _c

        # Filter functions per preset.
        #
        # Day-63 (2026-05-21): each filter now takes (score, mos, moat,
        # pe, revenue_cagr_3y) so growth_quality can enforce a genuine
        # growth requirement instead of just being "top score." Audit
        # 2026-05-20 caught all three Discover screens (Wide-Moat / Deep
        # Value / High-Margin Growers) leading with the SAME 3 tickers
        # (WAAREEINDO/EIEL/WEBELSOLAR at +0%) --- root cause was a
        # too-loose growth filter combined with an identical sort
        # across presets. Sort is now preset-specific (see below).
        #
        # 2026-06-11 (P0 fix): moat compare is now case-insensitive.
        # Pre-fix, `moat == "Wide"` (strict CAP-W) skipped rows where
        # the cache wrote "wide" / "WIDE" / "Wide moat" — which on the
        # current analysis_cache snapshot was MOST rows. That's why
        # the buffett tile showed 0/0 on yieldiq.in despite hundreds of
        # wide-moat names in the universe.
        def _moat_is_wide(moat: str | None) -> bool:
            return bool(moat) and "wide" in moat.lower()

        # Relax step: when `relaxed=True` each threshold is widened by
        # one notch. Values calibrated from the 2026-05-21 audit so the
        # relax pass returns ~5-30 candidates per preset on the current
        # universe (vs. 0 strict). When `relaxed=False` the step is 0
        # and the original strict thresholds apply unchanged.
        score_step = 10 if relaxed else 0
        mos_step = 10 if relaxed else 0

        def _is_buffett(score, mos, moat, pe, rev_cagr):
            # Quality + reasonable price + wide moat.
            # Strict: score>=60, mos>=0, wide-moat.
            # Relaxed (closest-matches): score>=50, mos>=-10, wide-moat
            # OR narrow-moat (we'd rather show 5 narrow-moat names than
            # an empty tile).
            score_floor = 60 - score_step
            mos_floor = 0 - mos_step
            if relaxed:
                moat_ok = _moat_is_wide(moat) or (bool(moat) and "narrow" in moat.lower())
            else:
                moat_ok = _moat_is_wide(moat)
            return score >= score_floor and mos >= mos_floor and moat_ok

        def _is_deep_value(score, mos, moat, pe, rev_cagr):
            # Big margin of safety + decent quality.
            # Strict: mos>=30, score>=50. Relaxed: mos>=20, score>=40.
            return mos >= (30 - mos_step) and score >= (50 - score_step)

        def _is_growth_quality(score, mos, moat, pe, rev_cagr):
            # Score >= 70 AND positive 3y revenue growth. The growth
            # threshold (8%) is calibrated to "genuinely growing"
            # rather than "barely keeping up with inflation" --- India
            # nominal GDP is ~6-7%, so 8%+ revenue CAGR means real
            # growth net of macro. Falls open (no growth gate) only
            # when rev_cagr is missing entirely; the score>=70 floor
            # still applies.
            #
            # Relaxed: score>=60 and growth>=4% (or score>=65 when
            # rev_cagr missing). The looser gate is acceptable for the
            # "closest matches" tile on /home — it never replaces the
            # canonical /screener preset.
            score_floor = 70 - score_step
            growth_floor = 0.08 if not relaxed else 0.04
            missing_floor = 75 if not relaxed else 65
            if score < score_floor:
                return False
            if rev_cagr is None:
                # Missing-data fallback — apply a score-only gate so we
                # never starve the screen completely on cohorts where
                # revenue_cagr_3y didn't backfill.
                return score >= missing_floor
            return rev_cagr >= growth_floor

        def _is_custom(score, mos, moat, pe, rev_cagr):
            return score >= 30  # almost everything

        filter_fn = {
            "buffett": _is_buffett,
            "deep_value": _is_deep_value,
            "growth_quality": _is_growth_quality,
            "custom": _is_custom,
        }.get(preset, _is_custom)

        # Day-63 (2026-05-21): preset-specific sort key. With one
        # universal sort by (score, mos) the top-3 of every preset
        # collapsed to the same handful of high-score names. Now each
        # preset's leaderboard ranks by its OWN primary signal so the
        # screens look meaningfully different even when filter
        # universes overlap.
        #
        # candidate tuple is (ticker, score, mos, rev_cagr) — keep
        # this ordering in sync with the (ticker, ..., ...) push
        # statements below.
        _PRESET_SORT_KEYS = {
            "buffett":        lambda c: (c[2], c[1]),           # MoS desc, then score
            "deep_value":     lambda c: (c[2], c[1]),           # MoS desc, then score
            "growth_quality": lambda c: ((c[3] or 0), c[1]),    # revenue CAGR desc, then score
        }
        sort_key = _PRESET_SORT_KEYS.get(preset, lambda c: (c[1], c[2]))  # default: score, mos

        # Three opinionated presets exclude clamped rows; see block
        # comment lower in this function for full reasoning.
        #
        # 2026-06-11 — on the relaxed pass we widen the MoS clamp guard
        # from 50 → 80 so micro-caps with MoS in the 50-80 band (which
        # are common in deep-value and growth-quality screens) make the
        # cut on /home tiles even though they'd still be filtered out
        # of the canonical /screener?preset page. data_limited rows are
        # still dropped — those have known FV-clamp artefacts.
        _PRESET_EXCLUDE_CLAMPED = {"buffett", "deep_value", "growth_quality"}
        _exclude_clamped = preset in _PRESET_EXCLUDE_CLAMPED
        _mos_clamp_guard = 50 if not relaxed else 80

        candidates = []
        seen_tickers: set[str] = set()

        # Tier 1 — persistent analysis_cache DB table. This survives
        # Railway redeploys, which wipe the in-memory cache below.
        # Before this was wired, the screener always returned "No stocks
        # match" for a few minutes after every deploy because the
        # in-memory cache hadn't rehydrated yet.
        try:
            from data_pipeline.db import Session as _Session
            from sqlalchemy import text as _sql_text
            _sess = _Session()
            try:
                # PERF (egress): pull only the 5 JSON fields we need via
                # JSONB path operators instead of the whole payload (which
                # can be 100KB+ per row x ~500-3000 rows = tens of MB on a
                # cold scan). Same field semantics as the prior dict-walk.
                # FIX-SCREENER-CLAMPED (2026-04-27): exclude rows where
                # the router clamped FV/MoS to its sanity bounds (FV outside
                # [0.1×price, 3×price] OR |MoS| >= 95%) for the three named
                # presets. Pre-fix, buffett/deep-value/growth-quality were
                # full of micro-caps where MoS got pinned at the ~±95-200%
                # boundary because of FCF/EPS data-quality issues
                # (AMJLAND +215%, NILAINFRA +198%, CAPITALSFB +289%, etc.).
                # The custom screener intentionally still includes these so
                # power users can see everything.
                #
                # Primary signal: payload->valuation->data_limited = true
                # (router sets this whenever it clamps; see
                # backend/routers/analysis.py around the FV-clamp block and
                # backend/models/responses.py ValuationOutput.data_limited).
                # Fallback: |mos| < 50 (tightened from 95 to 50 — wide-moat
                # preset shouldn't show MoS that high; real wide-moat names
                # rarely sit in the 50–95% range, so values there are almost
                # always DCF-calibration artifacts rather than genuine bargains).
                # This also catches any pre-flag legacy cache rows that were
                # clamped before the data_limited flag was wired but still
                # carry the boundary-pinned MoS value.
                # `_exclude_clamped` itself is hoisted to function scope so
                # the tier-2 in-memory path below sees the same gate.
                _rows = _sess.execute(_sql_text(
                    """
                    SELECT
                      ticker,
                      (payload->'quality'->>'yieldiq_score')::float    AS score,
                      (payload->'valuation'->>'margin_of_safety')::float AS mos,
                      (payload->'quality'->>'moat')                    AS moat,
                      (payload->'valuation'->>'eps_ttm')::float        AS eps_ttm,
                      (payload->'valuation'->>'current_price')::float  AS current_price,
                      COALESCE((payload->'valuation'->>'data_limited')::boolean, false) AS data_limited,
                      (payload->'quality'->>'revenue_cagr_3y')::float  AS revenue_cagr_3y
                    FROM analysis_cache
                    WHERE computed_at > now() - interval '48 hours'
                    """
                )).fetchall()
            finally:
                _sess.close()
            for _r in _rows:
                _ticker = _r[0]
                score = _r[1] or 0
                mos = _r[2] or 0
                moat = _r[3] or "None"
                pe = None
                try:
                    eps = _r[4] or 0
                    cp = _r[5] or 0
                    if eps > 0 and cp > 0:
                        pe = cp / eps
                except Exception:
                    pass
                _data_limited = bool(_r[6]) if len(_r) > 6 else False
                _rev_cagr = _r[7] if len(_r) > 7 else None  # Day-63
                # Skip rows where MoS got clamped (data-quality issues)
                # for the three opinionated presets. See block comment above.
                # 2026-06-11 — _mos_clamp_guard is 50 on the strict pass
                # and 80 on the relaxed pass (the home-tile relaxation).
                if _exclude_clamped and (_data_limited or abs(mos) >= _mos_clamp_guard):
                    continue
                full_ticker = _ticker if "." in _ticker else f"{_ticker}.NS"
                # Dedup by bare ticker (strip .NS/.BO) so NSE+BSE listings
                # of the same company and raw-vs-suffixed cache entries
                # can't both be counted. Pre-fix this was producing
                # 899 > 550-Nifty-500-universe in prod.
                _dedup_key = full_ticker.split(".")[0]
                if filter_fn(score, mos, moat, pe, _rev_cagr) and _dedup_key not in seen_tickers:
                    candidates.append((full_ticker, score, mos, _rev_cagr))
                    seen_tickers.add(_dedup_key)
        except Exception as _exc:
            logger.info("analysis_cache scan skipped: %s", _exc)

        # Tier 2 — in-memory cache. Catches anything freshly computed
        # on this worker but not yet in the persistent table.
        for key in list(_c._store.keys()):
            if not key.startswith("analysis:") or ".NS" not in key:
                continue
            val = _c.get(key)
            if not val or not hasattr(val, "valuation"):
                continue
            v = val.valuation
            q = val.quality
            score = q.yieldiq_score or 0
            mos = v.margin_of_safety or 0
            moat = q.moat or "None"
            pe = None
            try:
                eps = getattr(v, "eps_ttm", None)
                if eps and eps > 0 and v.current_price > 0:
                    pe = v.current_price / eps
            except Exception:
                pe = None

            # Mirror the tier-1 clamp-exclusion for the named presets.
            # See block comment in the analysis_cache scan above. The
            # _mos_clamp_guard widens to 80 on the relaxed pass.
            _dl = bool(getattr(v, "data_limited", False))
            if _exclude_clamped and (_dl or abs(mos) >= _mos_clamp_guard):
                continue
            _rev_cagr2 = getattr(q, "revenue_cagr_3y", None)  # Day-63

            _dedup_key2 = val.ticker.split(".")[0]
            if filter_fn(score, mos, moat, pe, _rev_cagr2) and _dedup_key2 not in seen_tickers:
                candidates.append((val.ticker, score, mos, _rev_cagr2))
                seen_tickers.add(_dedup_key2)

        # Day-63 (2026-05-21): preset-specific sort. Default is the
        # legacy (score, mos) desc; named presets get their own
        # primary signal so leaderboards differ structurally across
        # screens. See _PRESET_SORT_KEYS above.
        candidates.sort(key=sort_key, reverse=True)

        # Pagination
        total = len(candidates)
        start = (page - 1) * page_size
        end = start + page_size
        page_items = candidates[start:end]

        stocks = [
            ScreenerStock(
                ticker=ticker,
                score=int(round(score)),
                margin_of_safety=round(mos, 1),
            )
            for ticker, score, mos, _rev_cagr_ignored in page_items
        ]
        return stocks, total
    except Exception as e:
        logger.warning(f"Screener preset query failed: {e}", exc_info=True)
        return [], 0


@router.get("/run", response_model=ScreenerResponse)
async def run_screener(
    min_score: int = Query(0, ge=0, le=100),
    min_mos: float = Query(-100),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    # task #180 (2026-05-24): switched from get_current_user → optional.
    # This endpoint feeds the "Quant picks > Quality at a Discount" tile
    # on /home, which is rendered inside the (app) route group but has
    # NO auth wall — anonymous visitors land on /home (logo click, OAuth
    # callback race, deep-link). With the required-auth dep, anon hits
    # got 401, react-query retried once, and the tile was stuck in its
    # loading skeleton showing "…" forever instead of the picked
    # tickers. The handler doesn't reference `user`, so dropping the
    # 401 floor is a no-op for behaviour — just makes the public path
    # render data instead of a frozen placeholder.
    user: dict | None = Depends(get_current_user_optional),
):
    """Run custom screener. Available to all users (anon allowed)."""
    stocks, total = _query_stocks_from_db(min_score, min_mos, page, page_size)

    # Filter by min_score and min_mos
    if min_score > 0:
        stocks = [s for s in stocks if s.score >= min_score]
    if min_mos > -100:
        stocks = [s for s in stocks if s.margin_of_safety >= min_mos]

    return ScreenerResponse(
        results=stocks, total=total, page=page, page_size=page_size,
        filter_applied={"min_score": min_score, "min_mos": min_mos},
    )


@router.get("/preset/{preset_name}", response_model=ScreenerResponse)
async def run_preset(
    preset_name: str,
    # task #180 (2026-05-24): see /run for the full rationale. The three
    # named presets (buffett / deep-value / growth-quality) back the
    # first three Quant-Pick tiles on /home, which is reachable by
    # logged-out users. Required auth here is what produced the
    # "literal '…' placeholder" symptom on yieldiq.in — the tiles 401'd,
    # never resolved, and the loading skeleton stayed up indefinitely.
    user: dict | None = Depends(get_current_user_optional),
):
    """Run a pre-built screener preset. Available to all users.

    Frontend sends slug-style preset names with dashes
    (``deep-value``, ``growth-quality``) — the in-memory filter dispatch
    below keys on underscores (``deep_value``, ``growth_quality``).
    Without this normalisation, BOTH slugs fell through to ``_is_custom``
    (``score >= 30``) and returned an identical, over-inflated count
    (899/899 in prod on 2026-04-22). Fixes P0-#5 on the Day-1 audit.
    """
    api_preset = preset_name.replace("-", "_")
    stocks, total = _query_preset_from_db(api_preset)
    # 2026-06-11 — surface the relaxation flag so the frontend can show
    # "Showing closest matches" copy on /home tiles that fell back to
    # the relaxed pass. See _query_preset_from_db docstring.
    relaxed = getattr(_query_preset_from_db, "last_relaxed", False)

    return ScreenerResponse(
        results=stocks, total=total, page=1, page_size=25,
        filter_applied={"preset": preset_name, "relaxed": relaxed},
    )


@router.get("/export", response_model=ScreenerResponse)
async def export_screener(
    preset: str = Query("custom"),
    min_score: int = Query(0, ge=0, le=100),
    min_mos: float = Query(-100),
    user: dict = Depends(require_tier("starter")),
):
    """Export screener results (up to 500 stocks). Starter+ only."""
    if preset != "custom":
        api_preset = preset.replace("-", "_")
        stocks, total = _query_preset_from_db(api_preset, page=1, page_size=500)
    else:
        stocks, total = _query_stocks_from_db(min_score, min_mos, page=1, page_size=500)

    # Apply filters
    if min_score > 0:
        stocks = [s for s in stocks if s.score >= min_score]
    if min_mos > -100:
        stocks = [s for s in stocks if s.margin_of_safety >= min_mos]

    return ScreenerResponse(
        results=stocks[:500], total=len(stocks), page=1, page_size=500,
        filter_applied={"preset": preset, "min_score": min_score, "min_mos": min_mos, "export": True},
    )
