"""Day-70 (2026-05-21): "Quality at a Discount" filter tightening.

The 2026-05-20 audit said:

  > "Quality at a Discount: 702 stocks" — Same broken count.
  > Filter too loose.

The 4th tile of the Discover-page QuantPicks grid was fetching
`/api/v1/screener/run?min_score=50&min_mos=15`, which returned ~702
names — basically the entire mid-cap universe, not an opinionated
"quality at a discount" shortlist.

Day-70 tightens the thresholds to `min_score=65 · min_mos=20`, which
in canary testing yields ~30–80 names — small enough that the tile
title is honest, large enough that the list isn't empty on a bad
market day.

This test is a source-text regression on QuantPicksGrid.tsx: it
fails loudly if someone reverts the thresholds, drops the blurb
update, or removes the tightened filter.
"""
from __future__ import annotations
from pathlib import Path


_GRID = (
    Path(__file__).resolve().parents[2]
    / "frontend" / "src" / "components" / "home" / "v2"
    / "QuantPicksGrid.tsx"
)


def _src() -> str:
    assert _GRID.exists(), f"QuantPicksGrid not found at {_GRID}"
    return _GRID.read_text(encoding="utf-8")


# ── Old (too-loose) thresholds are gone ─────────────────────────

def test_old_min_score_50_is_gone() -> None:
    """The old min_score: 50 fetcher param must not survive."""
    src = _src()
    assert "min_score: 50" not in src, (
        "Found old `min_score: 50` in QuantPicksGrid.tsx — the Day-70 "
        "tightening was reverted. The 2026-05-20 audit explicitly "
        "flagged this as 'filter too loose, 702 stocks'."
    )


def test_old_min_mos_15_is_gone() -> None:
    """The old min_mos: 15 fetcher param must not survive."""
    src = _src()
    assert "min_mos: 15" not in src, (
        "Found old `min_mos: 15` in QuantPicksGrid.tsx — Day-70 "
        "raised the margin-of-safety floor to 20% so the tile shows "
        "a real shortlist, not the whole universe."
    )


def test_old_blurb_is_gone() -> None:
    src = _src()
    assert "Score ≥ 50 · MoS ≥ 15%" not in src, (
        "Old blurb 'Score ≥ 50 · MoS ≥ 15%' still in the tile — "
        "blurb must reflect the tightened thresholds."
    )


# ── New (tightened) thresholds are present ──────────────────────

def test_new_min_score_65_present() -> None:
    src = _src()
    assert "min_score: 65" in src, (
        "Expected `min_score: 65` in the quality_discount tile "
        "fetcher. Day-70 set this to reduce 702 → ~30-80 results."
    )


def test_new_min_mos_20_present() -> None:
    src = _src()
    assert "min_mos: 20" in src, (
        "Expected `min_mos: 20` in the quality_discount tile fetcher."
    )


def test_new_blurb_present() -> None:
    src = _src()
    assert "Score ≥ 65 · MoS ≥ 20%" in src, (
        "Expected blurb 'Score ≥ 65 · MoS ≥ 20%' on the "
        "quality_discount tile so the displayed thresholds match "
        "the actual fetcher params."
    )


# ── Tile identity unchanged ─────────────────────────────────────

def test_tile_title_unchanged() -> None:
    """The user-facing title 'Quality at a Discount' is the brand
    name of this tile and must not drift."""
    src = _src()
    assert '"Quality at a Discount"' in src


def test_tile_key_unchanged() -> None:
    src = _src()
    assert '"quality_discount"' in src


# ── Deep link query string matches fetcher ──────────────────────

def test_href_query_string_matches_fetcher() -> None:
    """The 'See all →' deep link must use the same thresholds as
    the fetcher, otherwise the count on the tile won't match the
    full screener page the user lands on."""
    src = _src()
    assert "min_score=65" in src and "min_mos=20" in src, (
        "Deep-link href for quality_discount tile must use the same "
        "tightened thresholds as the fetcher."
    )
