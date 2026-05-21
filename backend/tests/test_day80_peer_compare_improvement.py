"""Day-80 (2026-05-22): peer-cohort transparency captions.

Tier-3 #34 (peer comparison UX): the public /peers endpoint already
returns enough per-peer signal (`sector`, `sub_sector`, `mcap_ratio`)
to explain WHY each peer is in the cohort — but the frontend was
showing peers with zero rationale, same as Tickertape and Screener.

Day-80 adds:

  * `cohort_criteria` object on the `/api/v1/public/peers/{ticker}`
    response — sub_sector, sector, mcap_band_pct, peer_count, caption,
    mixed_sub_sector. Plain-English caption is ready to render.

  * Compare-page caption block (`data-testid="peer-cohort-caption"`)
    rendered above the suggestion chips when present.

  * Frontend type `PeerCohortCriteria` in `frontend/src/lib/api.ts`
    plus an optional `cohort_criteria` field on `PublicPeersResponse`.

These guards are source-text based — no Redis / no DB / no FastAPI
bootstrap. The endpoint itself is exercised by the wider integration
suite; this file's job is to lock in the shape and the wiring so a
future cleanup can't quietly delete the caption.
"""
from __future__ import annotations

from pathlib import Path


_ROOT = Path(__file__).resolve().parents[2]
_BACKEND_PUBLIC = _ROOT / "backend" / "routers" / "public.py"
_FRONTEND_API = _ROOT / "frontend" / "src" / "lib" / "api.ts"
_FRONTEND_COMPARE = _ROOT / "frontend" / "src" / "app" / "(app)" / "compare" / "page.tsx"


def _read(p: Path) -> str:
    assert p.exists(), f"required source file missing: {p}"
    return p.read_text(encoding="utf-8")


# ---------------------------------------------------------------------
# Backend: cohort_criteria synthesis lives in routers/public.py
# ---------------------------------------------------------------------


def test_public_peers_response_carries_cohort_criteria_key() -> None:
    src = _read(_BACKEND_PUBLIC)
    assert '"cohort_criteria": cohort_criteria,' in src, (
        "public /peers response must include the cohort_criteria field — "
        "compare-page caption depends on it."
    )


def test_cohort_criteria_caption_uses_sub_sector_phrasing() -> None:
    src = _read(_BACKEND_PUBLIC)
    # Caption phrasing is part of the user-visible contract; lock it.
    assert 'f"Same sub-sector ({primary_sub})"' in src, (
        "Cohort caption must use 'Same sub-sector (...)' phrasing."
    )
    assert 'f"Same sector ({primary_sector})"' in src, (
        "Cohort caption must fall back to 'Same sector (...)' when "
        "sub-sectors disagree."
    )


def test_cohort_criteria_caption_includes_mcap_band() -> None:
    src = _read(_BACKEND_PUBLIC)
    assert 'peers span {lo:g}%-{hi:g}% of {clean} mcap' in src, (
        "Cohort caption must surface the mcap band so users see relative "
        "size — this is the actual cohort signal Tickertape hides."
    )


def test_cohort_criteria_exposes_structured_band() -> None:
    src = _read(_BACKEND_PUBLIC)
    assert '"mcap_band_pct": mcap_band,' in src
    assert '"peer_count": len(peers_out),' in src
    assert '"mixed_sub_sector": len(sub_sectors) > 1,' in src, (
        "mixed_sub_sector flag lets the UI disclaim mixed cohorts."
    )


def test_cohort_criteria_synth_is_exception_safe() -> None:
    src = _read(_BACKEND_PUBLIC)
    assert 'cohort_criteria: dict[str, object] | None = None' in src
    assert 'cohort_criteria = None' in src, (
        "Cohort synthesis must degrade to None on failure — peer list "
        "is the critical path; caption is enhancement."
    )


# ---------------------------------------------------------------------
# Frontend: typed contract + UI render path
# ---------------------------------------------------------------------


def test_frontend_api_exports_peer_cohort_criteria_interface() -> None:
    src = _read(_FRONTEND_API)
    assert "export interface PeerCohortCriteria" in src
    assert "mcap_band_pct: [number, number] | null" in src
    assert "caption: string | null" in src
    assert "mixed_sub_sector: boolean" in src


def test_public_peers_response_type_has_optional_cohort_criteria() -> None:
    src = _read(_FRONTEND_API)
    # Optional because older cached responses (pre-Day-80) won't have it.
    assert "cohort_criteria?: PeerCohortCriteria | null" in src


def test_compare_page_renders_cohort_caption_block() -> None:
    src = _read(_FRONTEND_COMPARE)
    assert 'data-testid="peer-cohort-caption"' in src, (
        "Compare page must expose the cohort caption with a stable "
        "test id so the frontend smoke test can assert on it."
    )
    assert "peersData?.cohort_criteria?.caption" in src
    assert "mixed_sub_sector" in src, (
        "Compare page must surface the mixed-cohort disclaimer when "
        "the cohort spans more than one sub-sector."
    )


def test_compare_page_avoids_sebi_banned_vocab_in_cohort_block() -> None:
    """No buy/sell/retain language should leak into the cohort caption UI."""
    src = _read(_FRONTEND_COMPARE)
    # Slice around the cohort block so unrelated copy doesn't trigger.
    start = src.find('data-testid="peer-cohort-caption"')
    assert start > 0
    window = src[max(0, start - 200): start + 800]
    banned = ("buy", "sell", " hold", "accumulate", "recommend",
              "outperform", "underperform", "strong")
    lowered = window.lower()
    for word in banned:
        assert word not in lowered, (
            f"SEBI-banned vocabulary '{word.strip()}' leaked into the "
            f"cohort caption block."
        )
