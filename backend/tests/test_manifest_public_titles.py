"""ROOT-CAUSE #11 (2026-06-10) — manifest title_public guard.

Background
----------
Three previous sanitisation fixes (#123, #175, #188) hardened the
RATIONALE sanitiser for Day-/Phase/Audit#/PR#/Task#/#NNN tokens.
Each time the leak recurred with a NEW vocabulary form the previous
patterns did not anticipate — T-numbers, internal slug strings
(``v_t6_2_ai_chat_phase_a_2026_06_10``), raw field names
(``composite_intrinsic_value``), and engineer-speak
(``byte-identical`` / ``bridge contract``).

The structural fix is a second author-supplied string,
``title_public``, on every manifest entry. This file is the pytest
half of a three-gate defense:

    Gate 1: load-time validator (this test) — every entry MUST carry a
            ``title_public`` that survives the banned-pattern guard.
    Gate 2: runtime serializer sanitiser
            (``public_manifest_entry`` → ``title``) — if the entry
            somehow slips past gate 1 in production, the serializer
            substitutes the humanised rationale fallback.
    Gate 3: standalone CI script
            (``scripts/check_manifest_public_title.py``) — wired into
            the SEBI-lint GitHub Actions workflow so a PR that touches
            the manifest fails the check before merge.

Contract
--------
* Every entry in ``MANIFEST`` carries a non-empty ``title_public``
  string.
* No ``title_public`` matches any pattern in
  ``_TITLE_PUBLIC_BANNED_PATTERNS``.
* The public serializer's ``title`` field equals the entry's
  ``title_public`` when present and passes the guard.
* A synthetic entry whose ``title_public`` IS jargon-laden is
  scrubbed at the serializer boundary (defense-in-depth runtime
  fallback).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.services.cache_invalidation_manifest import (  # noqa: E402
    MANIFEST,
    _matches_banned_title_pattern,
    _public_title,
    _TITLE_PUBLIC_BANNED_PATTERNS,
    public_manifest_entry,
)


# ─────────────────────────────────────────────────────────────────
# Independent banned-pattern set. Re-derived here so a regression in
# `_TITLE_PUBLIC_BANNED_PATTERNS` cannot hide a leak from the assertions
# below (the helper is the system under test; the test should not be
# its own oracle).
# ─────────────────────────────────────────────────────────────────
_INDEPENDENT_BANNED = re.compile(
    r"\bT\d+(?:\.\d+)+\b"
    r"|\bPhase\s+[A-Z](?:[-.][a-zA-Z0-9]+)*\b"
    r"|\bDay-\d+[a-z]?\b"
    r"|\bAudit\s*#\s*\d+"
    r"|\bPR\s*#?\s*\d+\b"
    r"|\bTask\s*#\s*\d+\b"
    r"|#\d+\b"
    r"|\bv_[a-z0-9_]+_\d{4}_\d{2}_\d{2}\b"
    r"|\b[a-z][a-z0-9_]*_\d{4}_\d{2}_\d{2}\b"
    r"|\bbyte-identical\b"
    r"|\bbridge contract\b"
    r"|\bcomposite_intrinsic_value\b"
    r"|\bcomposite_iv\b"
    r"|\bfair_value\b"
    r"|\bscope\.fields\b"
    r"|\bscope\.tickers\b",
    re.IGNORECASE,
)


def _assert_no_banned(text: str, ctx: str = "") -> None:
    hit = _INDEPENDENT_BANNED.search(text or "")
    assert hit is None, (
        f"banned jargon token surfaced ({ctx}): "
        f"{hit.group(0)!r} in {text!r}"
    )


# ─────────────────────────────────────────────────────────────────
# Gate 1 — load-time invariants on every manifest entry.
# ─────────────────────────────────────────────────────────────────

def test_every_entry_has_title_public() -> None:
    """Every manifest entry MUST carry a non-empty ``title_public``."""
    missing: list[str] = []
    for entry in MANIFEST:
        vid = (entry or {}).get("version_id") or "<unknown>"
        title = (entry or {}).get("title_public")
        if not isinstance(title, str) or not title.strip():
            missing.append(vid)
    assert not missing, (
        f"{len(missing)} entr"
        f"{'y' if len(missing) == 1 else 'ies'} missing title_public: "
        f"{missing[:10]}"
    )


def test_no_title_public_matches_banned_pattern() -> None:
    """No entry's ``title_public`` may contain T-numbers, internal
    slug strings, raw field names, or engineer-speak."""
    failures: list[tuple[str, str]] = []
    for entry in MANIFEST:
        vid = (entry or {}).get("version_id") or "<unknown>"
        title = (entry or {}).get("title_public") or ""
        # Independent regex first so a regression in the helper is
        # caught even if the helper passes.
        hit = _INDEPENDENT_BANNED.search(title)
        if hit is not None:
            failures.append((vid, hit.group(0)))
            continue
        # Sanity-check the helper agrees.
        assert _matches_banned_title_pattern(title) is None, (
            f"helper missed banned token in {vid}: {title!r}"
        )
    assert not failures, (
        f"{len(failures)} entr"
        f"{'y' if len(failures) == 1 else 'ies'} contain banned tokens "
        f"in title_public: {failures[:10]}"
    )


def test_title_public_within_length_budget() -> None:
    """Timeline cards stay one line — enforce a 140-char ceiling."""
    too_long: list[tuple[str, int]] = []
    for entry in MANIFEST:
        vid = (entry or {}).get("version_id") or "<unknown>"
        title = (entry or {}).get("title_public") or ""
        if len(title) > 140:
            too_long.append((vid, len(title)))
    assert not too_long, (
        f"{len(too_long)} entries exceed 140 chars: {too_long[:10]}"
    )


# ─────────────────────────────────────────────────────────────────
# Gate 2 — serializer-boundary defense in depth.
# ─────────────────────────────────────────────────────────────────

def test_serializer_emits_title_field_from_title_public() -> None:
    """The public_manifest_entry shape MUST include the new ``title``
    field, sourced from ``title_public``."""
    entry = {
        "version_id": "v_test_synthetic_2026_06_10",
        "title_public": "Composite Intrinsic Value updated for IT cohort",
        "applied_at": None,
        "scope": {"tickers": "*", "fields": ["score"]},
        "rationale": "T1.1 composite refinement",
    }
    public = public_manifest_entry(entry)
    assert public["title"] == "Composite Intrinsic Value updated for IT cohort"
    # Description still present for back-compat readers.
    assert "description" in public


def test_serializer_substitutes_when_title_public_is_jargon() -> None:
    """If an entry's title_public somehow contains banned tokens (a bug
    that slipped past gate 1 + gate 3), the serializer logs a warning
    and falls back to the humanised rationale."""
    entry = {
        "version_id": "v_test_leaky_2026_06_10",
        # Engineer accidentally pasted the rationale into title_public.
        "title_public": "T4.5 + T4.6 — five accounting normalizations added",
        "applied_at": None,
        "scope": {"tickers": "*", "fields": []},
        "rationale": (
            "Five accounting normalizations added (minority interest, "
            "working capital, effective tax rate, pension, FX translation)."
        ),
    }
    public = public_manifest_entry(entry)
    _assert_no_banned(public["title"], ctx="leaky-title fallback")
    # The fallback should still convey the substance, not blank out.
    assert "accounting normalizations" in public["title"].lower() or (
        public["title"] == "Model updated."
    )


def test_serializer_falls_through_to_model_updated_when_all_jargon() -> None:
    """Belt-and-braces: a title_public AND a rationale both made
    entirely of banned tokens degrade to the generic string."""
    entry = {
        "version_id": "v_test_pure_jargon_2026_06_10",
        "title_public": "T4.5 + Phase C.2",
        "applied_at": None,
        "scope": {"tickers": "*", "fields": []},
        "rationale": "T4.5 + T4.6 + Phase C.2 — composite_intrinsic_value",
    }
    public = public_manifest_entry(entry)
    _assert_no_banned(public["title"], ctx="pure-jargon fallback")


def test_serializer_handles_missing_title_public() -> None:
    """An entry that does NOT carry title_public (legacy or
    pre-migration) should fall through to the humanised rationale
    without raising."""
    entry = {
        "version_id": "v_test_legacy_2026_05_22",
        "applied_at": None,
        "scope": {"tickers": "*", "fields": []},
        "rationale": "Initial migration anchor — manifest started.",
    }
    public = public_manifest_entry(entry)
    assert public["title"]  # non-empty
    _assert_no_banned(public["title"], ctx="legacy entry fallback")


# ─────────────────────────────────────────────────────────────────
# Spec-example regression guards — these are the exact strings the
# brief flagged on yieldiq.in/analysis/HDFCBANK History tab.
# ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "jargon",
    [
        "T4.5 + T4.6 + T4.7 + T4.8 + T4.10 — five accounting normalizations",
        "T4.2 + T4.3 + T4.4 + T4.9 — four accounting normalizations",
        "T3.1 — bank residual-income engine deepened with NIM decomposition",
        "v_t6_2_ai_chat_phase_a_2026_06_10",
        "Verdict gate now reads composite_intrinsic_value when present "
        "(fallback to fair_value). DCF fair_value field byte-identical.",
    ],
)
def test_brief_example_jargon_rejected_by_guard(jargon: str) -> None:
    """The five exact strings that surfaced on the HDFCBANK timeline
    must each trigger the banned-pattern guard."""
    assert _matches_banned_title_pattern(jargon) is not None, (
        f"guard MISSED brief-example jargon: {jargon!r}"
    )


def test_t_number_pattern_isolated() -> None:
    """Specific T-number forms — make sure the regex catches each."""
    for sample in ["T1.1", "T3.1", "T4.5", "T4.10", "T2.5", "T3.14"]:
        assert _matches_banned_title_pattern(
            f"{sample} engine refinement"
        ) is not None, f"missed T-number {sample}"


def test_internal_slug_pattern_isolated() -> None:
    """Internal slug pattern must catch the v_<snake_case>_<date>
    form."""
    samples = [
        "v_t6_2_ai_chat_phase_a_2026_06_10",
        "v_init_2026_05_22",
        "v_phase_c_2_verdict_gate_2026_06_10",
    ]
    for s in samples:
        assert _matches_banned_title_pattern(
            f"See {s} for details"
        ) is not None, f"missed slug {s}"


def test_engineer_speak_caught() -> None:
    """`byte-identical` and `bridge contract` must trigger the guard."""
    assert _matches_banned_title_pattern(
        "DCF fair value byte-identical pre/post"
    ) is not None
    assert _matches_banned_title_pattern(
        "Bridge contract test #813 pinned the behavior"
    ) is not None


def test_raw_field_names_caught() -> None:
    """`composite_intrinsic_value` / `composite_iv` / `fair_value` /
    `scope.fields` should not appear in a user-facing title."""
    samples = [
        "Verdict now reads composite_intrinsic_value",
        "Composite_iv refinement",
        "DCF fair_value field is now richer",
        "scope.fields = [verdict, mos]",
    ]
    for s in samples:
        assert _matches_banned_title_pattern(s) is not None, (
            f"missed raw field name in {s!r}"
        )


def test_clean_titles_pass() -> None:
    """Negative control: well-written user-facing titles must NOT
    trip the guard."""
    clean = [
        "Sector heatmap added — tile grid sized by market cap",
        "Bank residual-income engine deepened — NIM, CASA, ROE",
        "Composite Intrinsic Value — weighted blend of DCF, multiples, "
        "and Wall-St consensus",
        "Verdict now consumes the Composite Intrinsic Value",
        "Multi-turn AI chat panel on the analysis page",
        "Free tier financials cap raised from 3 to 5 years",
        "Five accounting normalizations added (minority interest, working "
        "capital, tax rate, pension, FX translation)",
    ]
    for c in clean:
        assert _matches_banned_title_pattern(c) is None, (
            f"clean title {c!r} tripped the guard: "
            f"{_matches_banned_title_pattern(c)!r}"
        )


# ─────────────────────────────────────────────────────────────────
# Pattern definition sanity — make sure the banned-pattern tuple
# itself stays comprehensive (regression if a future refactor
# accidentally drops a pattern).
# ─────────────────────────────────────────────────────────────────

def test_banned_patterns_cover_known_categories() -> None:
    """We expect at least one pattern for each of the categories
    enumerated in the brief: T-numbers, Phase X.Y, Day-NNN, Audit/PR/
    Task/#NNN, slugs, engineer-speak, raw field names. Light sanity
    check — count of patterns should not drop below the expected
    minimum (we have ~16 patterns; floor at 12 to allow consolidation)."""
    assert len(_TITLE_PUBLIC_BANNED_PATTERNS) >= 12, (
        f"banned-pattern tuple shrunk to "
        f"{len(_TITLE_PUBLIC_BANNED_PATTERNS)} — possible regression"
    )
