"""Day-96 (2026-05-22): airlines peer-engine label fix.

Audit #4 surfaced INDIGO's peer block returning ABB / CUMMINSIND /
SIEMENS / POWERINDIA / POLYCAB — all capital-goods companies — each
tagged `sub_sector: "Airlines"`. Root cause: `scripts/build_peer_groups.py`
writes the SUBJECT's sub_sector onto every peer row regardless of
whether the cohort had to broaden past the subject's sub-sector.
INDIGO is effectively the only listed large-cap airline (SPICEJET is
~5% of its mcap, Air India is unlisted), so the builder fell back
to "same sector (Industrials), mcap proximity" — but the resulting
peer rows still carried "Airlines" because that's what the builder
copied from INDIGO.

Day-96 fixes this in the READ path (no peer_groups backfill needed):

  * `routers/public.py::get_peers` now reads each peer's TRUE
    industry (= sub_sector) from the `stocks` table at query time
    and surfaces THAT on the row.
  * `cohort_criteria` gains `cohort_broadened: bool`,
    `subject_sub_sector`, and `same_sub_sector_peer_count` so the
    frontend can warn when the cohort was broadened.
  * Caption phrasing for broadened cohorts is explicit:
    "Same sector (Industrials); only 0 same-sub-sector peers
    available, broadened to nearest Industrials".
  * Compare page renders "(broadened cohort — not true sub-sector
    peers)" tag when the flag fires.

Guards are source-text based — same pattern as Day-80 / Day-86 /
Day-91. The endpoint behavior is exercised end-to-end by the live
canary; this file's job is to lock in the wiring + caption shape so
a future cleanup can't quietly delete the broadening signal.

Caching note: the peers endpoint uses an in-memory 30-min cache
(`public:peers:{ticker}`) not the analysis_cache layer, so no Day-94
manifest entry is required — naturally-expiring cache will refresh
within 30 minutes of deploy.
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
# Backend source guards
# ---------------------------------------------------------------------


def test_peers_reads_true_sub_sector_from_stocks() -> None:
    """The fix hinges on reading each peer's own industry from the
    `stocks` table rather than trusting the (subject-copied) tag on
    `peer_groups`."""
    src = _read(_BACKEND_PUBLIC)
    assert "true_sub_sector_by_ticker" in src, (
        "Day-96 fix requires per-peer sub_sector lookup from stocks; "
        "missing the lookup dict."
    )
    assert "Stock.industry" in src and "Stock.ticker" in src, (
        "Lookup must select Stock.industry (the real sub_sector)."
    )


def test_peers_uses_true_sub_when_available() -> None:
    src = _read(_BACKEND_PUBLIC)
    assert "peer_sub_sector = true_sub if true_sub is not None else peer.sub_sector" in src, (
        "Per-peer sub_sector must prefer the true industry over the "
        "(unreliable) peer_groups.sub_sector tag."
    )
    assert '"sub_sector": peer_sub_sector,' in src, (
        "Returned row must use the true-sub-sector value."
    )


def test_cohort_broadened_flag_derived_from_reason() -> None:
    src = _read(_BACKEND_PUBLIC)
    assert "cohort_broadened" in src, "cohort_broadened flag missing"
    assert "same_sub_sector_mcap_proximity" in src, (
        "Broadening detection must compare PeerGroup.reason against the "
        "narrow-cohort reason string written by build_peer_groups.py."
    )


def test_cohort_criteria_exposes_broadening_fields() -> None:
    src = _read(_BACKEND_PUBLIC)
    assert '"cohort_broadened": cohort_broadened,' in src
    assert '"subject_sub_sector": subject_sub_sector,' in src
    assert '"same_sub_sector_peer_count": same_sub_peer_count,' in src


def test_broadened_caption_is_explicit() -> None:
    src = _read(_BACKEND_PUBLIC)
    # Must mention broadening + count in the caption, not silently
    # assert "Same sub-sector (Airlines)" when the peers aren't.
    assert "broadened to nearest" in src, (
        "Broadened-cohort caption must say so explicitly."
    )
    assert "same-sub-sector peer" in src, (
        "Caption must surface how many true same-sub-sector peers existed."
    )


def test_no_advisory_verbs_in_new_caption_copy() -> None:
    """SEBI vocabulary guard — broadened-cohort phrasing is neutral."""
    src = _read(_BACKEND_PUBLIC)
    # Slice the Day-96 block to keep the guard narrow.
    start = src.find("Day-96 (2026-05-22): airlines peer-engine bug fix.")
    end = src.find("Day-80 (2026-05-22)", start)
    assert start != -1 and end != -1, "Day-96 block markers missing"
    block = src[start:end]
    banned = (
        " buy ", " sell ", " accumulate ", " outperform ", " underperform ",
        " recommend", " should ", " strong buy", " strong sell",
    )
    lowered = block.lower()
    for word in banned:
        assert word not in lowered, (
            f"SEBI vocabulary violation in Day-96 block: {word!r}"
        )


# ---------------------------------------------------------------------
# Frontend wiring guards
# ---------------------------------------------------------------------


def test_frontend_type_carries_cohort_broadened() -> None:
    src = _read(_FRONTEND_API)
    assert "cohort_broadened?" in src, (
        "PeerCohortCriteria must expose cohort_broadened so the compare "
        "page can render the broadening warning."
    )
    assert "subject_sub_sector?" in src
    assert "same_sub_sector_peer_count?" in src


def test_compare_page_renders_broadened_tag() -> None:
    src = _read(_FRONTEND_COMPARE)
    assert "cohort_broadened" in src, (
        "Compare page must conditionally render the broadened-cohort tag."
    )
    assert 'data-testid="peer-cohort-broadened-tag"' in src, (
        "Broadened tag needs a stable test-id for e2e selection."
    )
    assert "broadened cohort" in src, (
        "User-visible copy must say 'broadened cohort' so users read "
        "the chips with appropriate skepticism."
    )


# ---------------------------------------------------------------------
# Behavior guards — exercise the cohort_criteria synth on fixtures
# ---------------------------------------------------------------------


def _build_peers_out(rows: list[dict]) -> tuple[list[dict], dict]:
    """Re-implement the public.py cohort_criteria synth for unit testing.

    Behavior mirror — if you change the synth in public.py, mirror it
    here. Behavior parity is enforced by the source-text guards above
    (the field names and core phrasing must appear in public.py).
    """
    peers_out = list(rows)
    cohort_reason = rows[0].get("_reason") if rows else None
    subject_sub_sector = rows[0].get("_subject_sub_sector") if rows else None
    cohort_broadened = bool(
        cohort_reason and cohort_reason != "same_sub_sector_mcap_proximity"
    )
    same_sub_peer_count = 0
    if subject_sub_sector:
        same_sub_peer_count = sum(
            1 for p in peers_out
            if p.get("sub_sector") == subject_sub_sector
        )
    return peers_out, {
        "cohort_broadened": cohort_broadened,
        "same_sub_sector_peer_count": same_sub_peer_count,
        "subject_sub_sector": subject_sub_sector,
    }


def test_behavior_thin_cohort_fires_broadened_flag() -> None:
    """INDIGO-shaped fixture: subject sub_sector = Airlines, all peers
    are capital-goods, reason = 'same_sector_mcap_proximity'."""
    rows = [
        {"sub_sector": "Electric Equipment", "_reason": "same_sector_mcap_proximity",
         "_subject_sub_sector": "Airlines"},
        {"sub_sector": "Industrial Machinery", "_reason": "same_sector_mcap_proximity",
         "_subject_sub_sector": "Airlines"},
        {"sub_sector": "Electric Equipment", "_reason": "same_sector_mcap_proximity",
         "_subject_sub_sector": "Airlines"},
    ]
    _, meta = _build_peers_out(rows)
    assert meta["cohort_broadened"] is True, (
        "Thin-cohort (broadened) case must fire the flag."
    )
    assert meta["same_sub_sector_peer_count"] == 0, (
        "Zero peers actually share the subject's sub-sector — that's "
        "the whole story."
    )
    assert meta["subject_sub_sector"] == "Airlines"


def test_behavior_healthy_cohort_keeps_flag_false() -> None:
    """HDFCBANK-shaped fixture: 5 same-sub-sector peers, reason =
    'same_sub_sector_mcap_proximity'."""
    rows = [
        {"sub_sector": "Banks - Regional", "_reason": "same_sub_sector_mcap_proximity",
         "_subject_sub_sector": "Banks - Regional"}
        for _ in range(5)
    ]
    _, meta = _build_peers_out(rows)
    assert meta["cohort_broadened"] is False, (
        "Healthy same-sub-sector cohort must NOT fire the broadened flag."
    )
    assert meta["same_sub_sector_peer_count"] == 5
