"""
Day-79 — news source-quality tiering (Tier-3 issue #33, news/sentiment).

Audit observation (2026-05-20):
    "News item from GuruFocus (US site for an Indian smallcap) —
     relevance ranking still weak for small-caps"

Fix: tag every news item with a coarse A/B/C source-quality tier and
drop Tier C (downranked US aggregator) sources for Indian-only
listings (no US ADR). Dual-listed names keep Tier C.

Tests below cover:
  - the source-text guards (Tier A / B / downranked sets exist,
    _classify_source helper exists)
  - the pure math of _classify_source on canonical inputs
  - the ADR-aware filter behaviour on a mixed list
  - integration with filter_and_rank for an Indian-only .NS ticker
"""
from __future__ import annotations

import pytest

from backend.services import news_filters
from backend.services.news_filters import (
    _classify_source,
    _has_us_listing,
    _is_indian_only_ticker,
    _INDIAN_SOURCES_TIER_A,
    _INDIAN_SOURCES_TIER_B,
    _DOWNRANKED_SOURCES,
    annotate,
    filter_and_rank,
    filter_low_quality_sources,
)


# ── Source-text guards ─────────────────────────────────────────

def test_tier_a_set_contains_canonical_indian_media():
    # Sanity guards on the constant — if someone renames these
    # the tier mapping silently breaks.
    for host in ("moneycontrol.com", "economictimes.indiatimes.com",
                 "business-standard.com", "livemint.com"):
        assert host in _INDIAN_SOURCES_TIER_A


def test_tier_b_set_contains_global_wires():
    for host in ("reuters.com", "bloomberg.com", "ft.com"):
        assert host in _INDIAN_SOURCES_TIER_B


def test_downranked_set_contains_us_aggregators():
    for host in ("gurufocus.com", "seekingalpha.com", "fool.com",
                 "simplywall.st"):
        assert host in _DOWNRANKED_SOURCES


def test_classify_source_helper_is_exported():
    assert callable(news_filters._classify_source)


# ── _classify_source math ──────────────────────────────────────

@pytest.mark.parametrize("inp,expected", [
    ("moneycontrol.com", "A"),
    ("https://www.moneycontrol.com/news/x", "A"),
    ("livemint.com", "A"),
    ("https://economictimes.indiatimes.com/x", "A"),
    ("reuters.com", "B"),
    ("https://bloomberg.com/news/y", "B"),
    ("gurufocus.com", "C"),
    ("https://gurufocus.com/stock/PARADEEP", "C"),
    ("seekingalpha.com", "C"),
    ("simplywall.st", "C"),
])
def test_classify_source_known_hosts(inp, expected):
    assert _classify_source(inp) == expected


@pytest.mark.parametrize("inp", ["", None, "not a url", "ftp://broken"])
def test_classify_source_malformed_defaults_to_b(inp):
    assert _classify_source(inp) == "B"


def test_classify_source_unknown_host_defaults_to_b():
    assert _classify_source("https://example.com/news") == "B"


# ── ADR / dual-listing helpers ─────────────────────────────────

def test_has_us_listing_dual_listed_names():
    assert _has_us_listing("TCS")
    assert _has_us_listing("INFY.NS")
    assert _has_us_listing("WIPRO")


def test_has_us_listing_smallcap_false():
    assert not _has_us_listing("PARADEEP")
    assert not _has_us_listing("MANKIND.NS")


def test_is_indian_only_ticker_smallcap_with_ns_suffix():
    assert _is_indian_only_ticker("PARADEEP.NS")
    assert _is_indian_only_ticker("MANKIND.BO")


def test_is_indian_only_ticker_dual_listed_false():
    # TCS has a US ADR; we keep Tier C for it.
    assert not _is_indian_only_ticker("TCS.NS")
    assert not _is_indian_only_ticker("INFY.NS")


def test_is_indian_only_ticker_us_only_false():
    # No .NS/.BO suffix → not Indian
    assert not _is_indian_only_ticker("AAPL")
    assert not _is_indian_only_ticker(None)
    assert not _is_indian_only_ticker("")


# ── filter_low_quality_sources ─────────────────────────────────

def _mk(url: str, source: str = "x") -> dict:
    return {
        "headline": f"Story from {source}",
        "summary": "",
        "source": source,
        "url": url,
        "published_at": "2026-05-20T10:00:00Z",
    }


def test_filter_low_quality_drops_gurufocus_for_indian_smallcap():
    items = [
        _mk("https://moneycontrol.com/a", "Moneycontrol"),
        _mk("https://gurufocus.com/b", "GuruFocus"),
        _mk("https://gurufocus.com/c", "GuruFocus"),
        _mk("https://livemint.com/d", "Livemint"),
        _mk("https://reuters.com/e", "Reuters"),
    ]
    out = filter_low_quality_sources(items, "PARADEEP.NS")
    assert len(out) == 3
    urls = [it["url"] for it in out]
    assert all("gurufocus.com" not in u for u in urls)


def test_filter_low_quality_keeps_gurufocus_for_dual_listed():
    items = [
        _mk("https://moneycontrol.com/a", "Moneycontrol"),
        _mk("https://gurufocus.com/b", "GuruFocus"),
    ]
    # TCS has a US ADR — keep Tier C.
    out = filter_low_quality_sources(items, "TCS.NS")
    assert len(out) == 2


def test_filter_low_quality_passthrough_for_unknown_ticker():
    items = [_mk("https://gurufocus.com/x", "GuruFocus")]
    out = filter_low_quality_sources(items, None)
    assert len(out) == 1


# ── Integration with filter_and_rank ───────────────────────────

def test_annotate_attaches_source_quality_tier():
    out = annotate(_mk("https://moneycontrol.com/p", "Moneycontrol"))
    assert out["source_quality_tier"] == "A"
    assert out["source_tier_label"] == "India-native"


def test_annotate_attaches_downranked_quality():
    out = annotate(_mk("https://gurufocus.com/p", "GuruFocus"))
    assert out["source_quality_tier"] == "C"
    assert out["source_tier_label"] == "US aggregator"


def test_filter_and_rank_drops_gurufocus_for_indian_smallcap_integration():
    # Mix of 5 articles, 2 from gurufocus, on an Indian-only .NS
    # ticker (PARADEEP) — should return 3 articles.
    items = [
        {
            "headline": "Paradeep Phosphates Q4 results beat estimates",
            "summary": "Paradeep Phosphates Limited reported strong Q4 numbers",
            "source": "Moneycontrol",
            "url": "https://moneycontrol.com/paradeep-q4",
            "published_at": "2026-05-19T10:00:00Z",
        },
        {
            "headline": "Paradeep Phosphates: deep value or value trap?",
            "summary": "Paradeep Phosphates analysis",
            "source": "GuruFocus",
            "url": "https://gurufocus.com/paradeep-1",
            "published_at": "2026-05-18T10:00:00Z",
        },
        {
            "headline": "Paradeep Phosphates capacity expansion update",
            "summary": "Paradeep Phosphates new plant",
            "source": "Livemint",
            "url": "https://livemint.com/paradeep-x",
            "published_at": "2026-05-17T10:00:00Z",
        },
        {
            "headline": "Paradeep Phosphates: contrarian thesis",
            "summary": "Paradeep Phosphates piece",
            "source": "Seeking Alpha — via GuruFocus",
            "url": "https://gurufocus.com/paradeep-2",
            "published_at": "2026-05-16T10:00:00Z",
        },
        {
            "headline": "Paradeep Phosphates wins fertilizer subsidy claim",
            "summary": "Paradeep Phosphates Limited received",
            "source": "Business Standard",
            "url": "https://business-standard.com/paradeep-y",
            "published_at": "2026-05-15T10:00:00Z",
        },
    ]
    out = filter_and_rank(items, ticker="PARADEEP.NS")
    assert len(out) == 3
    urls = [it["url"] for it in out]
    assert all("gurufocus.com" not in u for u in urls)
    # All survivors carry the new quality fields.
    for it in out:
        assert "source_quality_tier" in it
        assert it["source_quality_tier"] in ("A", "B")
        assert "source_tier_label" in it


def test_filter_and_rank_keeps_gurufocus_for_tcs():
    # TCS has a US ADR; Tier C survives.
    items = [
        {
            "headline": "TCS Q4 results beat estimates",
            "summary": "Tata Consultancy Services reported",
            "source": "Moneycontrol",
            "url": "https://moneycontrol.com/tcs-q4",
            "published_at": "2026-05-19T10:00:00Z",
        },
        {
            "headline": "TCS: contrarian ADR view",
            "summary": "Tata Consultancy Services ADR analysis",
            "source": "GuruFocus",
            "url": "https://gurufocus.com/tcs-1",
            "published_at": "2026-05-18T10:00:00Z",
        },
    ]
    out = filter_and_rank(items, ticker="TCS.NS")
    assert len(out) == 2


def test_filter_and_rank_aggregate_feed_passthrough_for_tier_c():
    # No ticker (aggregate feed) — Tier C survives because we don't
    # know which listings the user cares about.
    items = [
        {
            "headline": "Markets edge higher in late trade",
            "summary": "Nifty rose",
            "source": "GuruFocus",
            "url": "https://gurufocus.com/markets",
            "published_at": "2026-05-19T10:00:00Z",
        },
    ]
    out = filter_and_rank(items, ticker=None)
    # Aggregate has no ticker gate, so Tier-3 numeric tier survives
    # (it's not boilerplate, no ticker filter, and Tier 3 < 4).
    assert len(out) == 1
    assert out[0]["source_quality_tier"] == "C"
