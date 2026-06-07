"""Unit tests for the sector rotation lens (2026-06-07).

The aggregator is pure-Python over a stub per-sector aggregator —
no FastAPI, no DB. Each test builds a small set of fake sector
landing-page payloads and asserts:

    1. Ranking: median_mos_pct desc, with None sectors sorted to the
       end in original slug order.
    2. pct_undervalued is computed against the full verdict denominator
       (incl. 'other'), and is None for empty cohorts.
    3. top_discounts surfaces only positive-MoS tickers, sorted desc,
       capped at 3 per sector.
    4. universe_ticker_count sums across all sectors.
    5. Disclosure string is present and SEBI-safe (no banned vocab).
    6. Per-sector aggregator failures don't break the whole response.
    7. Unknown slug arguments are skipped, not raised.
"""
from __future__ import annotations

from typing import Optional

import pytest

from backend.services.sector_rotation import (
    ROTATION_DISCLOSURE,
    _pct_undervalued,
    _rank_sectors,
    _top_discounts,
    build_sector_rotation,
)


# ── Fixtures ─────────────────────────────────────────────────────


def _ticker(
    sym: str,
    *,
    mos: Optional[float] = None,
    verdict: Optional[str] = None,
    name: Optional[str] = None,
) -> dict:
    return {
        "ticker": sym,
        "name": name or sym.split(".")[0],
        "mos_pct": mos,
        "verdict": verdict,
        "score": 70,
        "fv": 100.0,
        "price": 90.0,
        "fv_to_price": 1.1,
    }


def _sector_payload(
    slug: str,
    display_name: str,
    *,
    median_mos: Optional[float],
    distribution: dict[str, int],
    tickers: list[dict],
) -> dict:
    """Mimic the shape returned by _sector_page_aggregate."""
    return {
        "slug": slug,
        "display_name": display_name,
        "cohort_tickers": [t["ticker"] for t in tickers],
        "cohort_notes": "Test cohort notes.",
        "aggregates": {
            "ticker_count": len(tickers),
            "median_fair_value_to_price_ratio": 1.1,
            "median_score": 65.0,
            "median_mos_pct": median_mos,
            "median_pe": 22.0,
            "median_roe": 18.0,
            "verdict_distribution": distribution,
        },
        "tickers": tickers,
    }


# ── _pct_undervalued ─────────────────────────────────────────────


def test_pct_undervalued_simple():
    """2 undervalued out of 4 total → 50.0."""
    d = {"undervalued": 2, "fairly_valued": 1, "overvalued": 1}
    assert _pct_undervalued(d) == 50.0


def test_pct_undervalued_includes_other_in_denominator():
    """'other' counts toward the denominator — honest cohort size."""
    d = {"undervalued": 1, "fairly_valued": 1, "overvalued": 1, "other": 1}
    assert _pct_undervalued(d) == 25.0


def test_pct_undervalued_empty_distribution_is_none():
    """Empty cohort → None (distinguishes from 0% undervalued)."""
    assert _pct_undervalued({"undervalued": 0, "fairly_valued": 0, "overvalued": 0}) is None
    assert _pct_undervalued({}) is None


def test_pct_undervalued_handles_bad_input():
    """Non-dict input must not raise."""
    assert _pct_undervalued(None) is None  # type: ignore[arg-type]
    assert _pct_undervalued("nope") is None  # type: ignore[arg-type]


# ── _top_discounts ───────────────────────────────────────────────


def test_top_discounts_picks_largest_positive_mos():
    tickers = [
        _ticker("A.NS", mos=5.0),
        _ticker("B.NS", mos=20.0),
        _ticker("C.NS", mos=15.0),
    ]
    out = _top_discounts(tickers, 3)
    assert [t["ticker"] for t in out] == ["B.NS", "C.NS", "A.NS"]
    assert all(t["mos_pct"] > 0 for t in out)


def test_top_discounts_filters_non_positive_and_none():
    """MoS <= 0 and MoS None must not surface as 'most discounted'."""
    tickers = [
        _ticker("A.NS", mos=10.0),
        _ticker("B.NS", mos=-5.0),   # overvalued — excluded
        _ticker("C.NS", mos=0.0),    # at FV — excluded
        _ticker("D.NS", mos=None),   # no data — excluded
        _ticker("E.NS", mos=8.0),
    ]
    out = _top_discounts(tickers, 3)
    assert [t["ticker"] for t in out] == ["A.NS", "E.NS"]


def test_top_discounts_cap_respected():
    """At most k entries even when many positive-MoS candidates exist."""
    tickers = [_ticker(f"T{i}.NS", mos=float(i)) for i in range(1, 10)]
    out = _top_discounts(tickers, 3)
    assert len(out) == 3
    assert [t["ticker"] for t in out] == ["T9.NS", "T8.NS", "T7.NS"]


def test_top_discounts_deterministic_tie_break():
    """When two tickers share MoS, ticker symbol is the tie-break."""
    tickers = [
        _ticker("ZZZ.NS", mos=10.0),
        _ticker("AAA.NS", mos=10.0),
        _ticker("MMM.NS", mos=10.0),
    ]
    out = _top_discounts(tickers, 3)
    assert [t["ticker"] for t in out] == ["AAA.NS", "MMM.NS", "ZZZ.NS"]


def test_top_discounts_handles_garbage_input():
    """Bad rows are silently dropped, not raised."""
    tickers = [
        _ticker("A.NS", mos=10.0),
        "not-a-dict",                            # type: ignore[list-item]
        {"ticker": "B.NS", "mos_pct": "garbage"},
        {"ticker": "C.NS"},                       # missing mos_pct
    ]
    out = _top_discounts(tickers, 3)  # type: ignore[arg-type]
    assert [t["ticker"] for t in out] == ["A.NS"]


# ── _rank_sectors ────────────────────────────────────────────────


def test_rank_sectors_by_median_mos_desc():
    sectors = [
        {"slug": "a", "median_mos_pct": 5.0},
        {"slug": "b", "median_mos_pct": 20.0},
        {"slug": "c", "median_mos_pct": 10.0},
    ]
    assert _rank_sectors(sectors) == ["b", "c", "a"]


def test_rank_sectors_none_sorts_to_end_in_input_order():
    """Sectors with median_mos_pct == None go last, in original order
    — distinguishes 'no data' from 'fair value'."""
    sectors = [
        {"slug": "a", "median_mos_pct": None},
        {"slug": "b", "median_mos_pct": 20.0},
        {"slug": "c", "median_mos_pct": None},
        {"slug": "d", "median_mos_pct": 5.0},
    ]
    assert _rank_sectors(sectors) == ["b", "d", "a", "c"]


def test_rank_sectors_stable_on_tied_mos():
    """Equal MoS sectors sort by slug asc — deterministic across runs."""
    sectors = [
        {"slug": "zebra", "median_mos_pct": 10.0},
        {"slug": "apple", "median_mos_pct": 10.0},
        {"slug": "mango", "median_mos_pct": 10.0},
    ]
    assert _rank_sectors(sectors) == ["apple", "mango", "zebra"]


# ── build_sector_rotation ────────────────────────────────────────


def test_build_rotation_orders_by_median_mos_and_attaches_top_picks():
    """End-to-end happy path: aggregator hit for 3 cohort slugs."""
    fake_data = {
        "fmcg": _sector_payload(
            "fmcg", "FMCG",
            median_mos=-5.0,
            distribution={"undervalued": 1, "fairly_valued": 3, "overvalued": 6},
            tickers=[
                _ticker("HUL.NS", mos=2.0, verdict="undervalued"),
                _ticker("ITC.NS", mos=-15.0, verdict="overvalued"),
            ],
        ),
        "auto": _sector_payload(
            "auto", "Auto",
            median_mos=25.0,
            distribution={"undervalued": 8, "fairly_valued": 2, "overvalued": 2},
            tickers=[
                _ticker("MARUTI.NS", mos=30.0, verdict="undervalued"),
                _ticker("TVS.NS",    mos=20.0, verdict="undervalued"),
                _ticker("M&M.NS",    mos=15.0, verdict="undervalued"),
                _ticker("EICH.NS",   mos=10.0, verdict="undervalued"),
            ],
        ),
        "it-services": _sector_payload(
            "it-services", "IT Services",
            median_mos=8.0,
            distribution={"undervalued": 3, "fairly_valued": 2, "overvalued": 0},
            tickers=[
                _ticker("TCS.NS",  mos=10.0, verdict="undervalued"),
                _ticker("INFY.NS", mos=8.0,  verdict="undervalued"),
            ],
        ),
    }

    def _aggregator(slug: str) -> Optional[dict]:
        return fake_data.get(slug)

    payload = build_sector_rotation(
        _aggregator, slugs=("it-services", "fmcg", "auto"),
    )

    # 1. ranked_slugs is by median MoS desc.
    assert payload["ranked_slugs"] == ["auto", "it-services", "fmcg"]

    # 2. All 3 sectors are present in `sectors`.
    by_slug = {s["slug"]: s for s in payload["sectors"]}
    assert set(by_slug) == {"it-services", "fmcg", "auto"}

    # 3. pct_undervalued is computed against the verdict total.
    assert by_slug["auto"]["pct_undervalued"] == round(8/12 * 100, 1)
    assert by_slug["fmcg"]["pct_undervalued"] == round(1/10 * 100, 1)

    # 4. top_discounts: only positive MoS, sorted desc.
    auto_top = [t["ticker"] for t in by_slug["auto"]["top_discounts"]]
    assert auto_top == ["MARUTI.NS", "TVS.NS", "M&M.NS"]  # 3-cap
    fmcg_top = [t["ticker"] for t in by_slug["fmcg"]["top_discounts"]]
    assert fmcg_top == ["HUL.NS"]  # ITC excluded — negative MoS

    # 5. universe count sums.
    assert payload["universe_ticker_count"] == 2 + 4 + 2  # 8

    # 6. Disclosure string is in the payload.
    assert payload["notes"] == ROTATION_DISCLOSURE


def test_build_rotation_empty_cohorts_sort_to_end():
    """A sector with no cohort cache hits surfaces with median None and
    sorts to the end of ranked_slugs."""

    def _aggregator(slug: str) -> Optional[dict]:
        if slug == "auto":
            return _sector_payload(
                "auto", "Auto",
                median_mos=12.0,
                distribution={"undervalued": 3, "fairly_valued": 1, "overvalued": 1},
                tickers=[_ticker("MARUTI.NS", mos=12.0, verdict="undervalued")],
            )
        # All other cohorts: empty
        return _sector_payload(
            slug, slug,
            median_mos=None,
            distribution={"undervalued": 0, "fairly_valued": 0, "overvalued": 0},
            tickers=[],
        )

    payload = build_sector_rotation(
        _aggregator, slugs=("fmcg", "auto", "it-services"),
    )
    # auto first (has data), then fmcg+it-services in original input order.
    assert payload["ranked_slugs"][0] == "auto"
    assert set(payload["ranked_slugs"][1:]) == {"fmcg", "it-services"}
    assert payload["ranked_slugs"][1:] == ["fmcg", "it-services"]


def test_build_rotation_aggregator_exception_does_not_break_overall():
    """If one cohort's aggregator throws, the others still render."""
    def _aggregator(slug: str) -> Optional[dict]:
        if slug == "auto":
            raise RuntimeError("simulated DB blip")
        return _sector_payload(
            slug, slug,
            median_mos=5.0,
            distribution={"undervalued": 1, "fairly_valued": 1, "overvalued": 1},
            tickers=[_ticker(f"{slug.upper()}1.NS", mos=5.0, verdict="undervalued")],
        )

    payload = build_sector_rotation(
        _aggregator, slugs=("fmcg", "auto", "it-services"),
    )

    by_slug = {s["slug"]: s for s in payload["sectors"]}
    # The throwing sector still appears as a placeholder card.
    assert "auto" in by_slug
    assert by_slug["auto"]["median_mos_pct"] is None
    assert by_slug["auto"]["ticker_count"] == 0
    # Others rendered normally.
    assert by_slug["fmcg"]["median_mos_pct"] == 5.0


def test_build_rotation_aggregator_returns_none_renders_empty_card():
    """When the aggregator returns None (e.g. cache miss + DB down)
    for a sector, the rotation lens still surfaces a card with
    ticker_count=0 / median None."""
    def _aggregator(slug: str) -> Optional[dict]:
        return None

    payload = build_sector_rotation(
        _aggregator, slugs=("fmcg", "auto"),
    )
    assert len(payload["sectors"]) == 2
    for s in payload["sectors"]:
        assert s["median_mos_pct"] is None
        assert s["ticker_count"] == 0
        assert s["top_discounts"] == []


def test_build_rotation_unknown_slug_is_skipped_not_raised():
    """An unknown slug (not in SECTOR_PAGES) is skipped silently."""
    def _aggregator(slug: str) -> Optional[dict]:
        return _sector_payload(
            slug, slug, median_mos=5.0,
            distribution={"undervalued": 1, "fairly_valued": 1, "overvalued": 1},
            tickers=[_ticker(f"{slug.upper()}1.NS", mos=5.0)],
        )

    payload = build_sector_rotation(
        _aggregator, slugs=("fmcg", "this-slug-does-not-exist"),
    )
    slugs = [s["slug"] for s in payload["sectors"]]
    assert slugs == ["fmcg"]


def test_disclosure_string_is_sebi_safe():
    """Disclosure must not contain SEBI-banned vocabulary."""
    banned = ["buy now", "sell now", "guaranteed", "risk-free", "sure shot"]
    lowered = ROTATION_DISCLOSURE.lower()
    for word in banned:
        assert word not in lowered, f"banned vocab in disclosure: {word}"
    # Must be descriptive, mentioning model output.
    assert "model" in lowered or "yieldiq" in lowered
    assert "not a recommendation" in lowered


def test_payload_has_iso8601_computed_at():
    """computed_at must be present and parseable as ISO-8601."""
    from datetime import datetime

    def _aggregator(slug: str) -> Optional[dict]:
        return _sector_payload(
            slug, slug, median_mos=5.0,
            distribution={"undervalued": 1, "fairly_valued": 1, "overvalued": 1},
            tickers=[_ticker(f"{slug.upper()}1.NS", mos=5.0)],
        )

    payload = build_sector_rotation(_aggregator, slugs=("fmcg",))
    # Doesn't raise.
    datetime.fromisoformat(payload["computed_at"])
