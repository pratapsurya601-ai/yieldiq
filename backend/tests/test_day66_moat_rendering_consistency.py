"""Day-66 (2026-05-21): moat rendering consistency.

Audit 2026-05-20: Reliance's analysis page rendered Moat card
"Moderate" while the Strengths card listed "Wide Economic Moat" ---
contradiction on one screen.

Root cause
----------
The Wide Moat strength in backend/services/analysis/utils.py fired
at `m_score > 65 OR m_grade == "Wide"`. But the moat label
threshold (screener/moat_engine.py: _MOAT_BAND_WIDE = 70) is the
SSOT. Scores 66-69 lit up the strength as Wide while the label
said Moderate.

Fix
---
Drop the `m_score > 65` fallback. The grade ("Wide" label) is now
the single source of truth for the Wide Moat strength. Any score
66-69 will keep the Moderate label AND no longer emit a Wide
strength.
"""
from __future__ import annotations
from pathlib import Path


_UTILS = (
    Path(__file__).resolve().parents[2]
    / "backend" / "services" / "analysis" / "utils.py"
)
_MOAT_ENGINE = (
    Path(__file__).resolve().parents[2]
    / "screener" / "moat_engine.py"
)
_CACHE = (
    Path(__file__).resolve().parents[2]
    / "backend" / "services" / "cache_service.py"
)


def test_wide_moat_strength_uses_grade_only():
    """The strength gate must be `m_grade == "Wide"` --- no score-
    based alt-gate that could disagree with the label."""
    src = _UTILS.read_text(encoding="utf-8")
    # The new condition
    assert 'if m_grade == "Wide":' in src
    # The old off-by-5 condition must NOT be in the same block
    assert 'if m_score > 65 or m_grade == "Wide":' not in src


def test_day66_marker_present():
    src = _UTILS.read_text(encoding="utf-8")
    assert "Day-66 (2026-05-21):" in src


def test_moat_engine_band_wide_unchanged():
    """The moat engine's Wide threshold (70) is the SSOT --- if this
    ever drifts to a different number, the strength condition above
    needs to follow."""
    src = _MOAT_ENGINE.read_text(encoding="utf-8")
    assert "_MOAT_BAND_WIDE = 70" in src


def test_cache_version_bumped_for_engine_change():
    src = _CACHE.read_text(encoding="utf-8")
    # Day-73 (Bug D, 2026-05-21): CACHE_VERSION bumped 130 -> 131 for
    # the post-demerger detect-and-route fix. This Day-66 guard now
    # checks the changelog entry survived in the cache_service.py
    # changelog rather than pinning the version number.
    assert "fix/day66-moat-rendering-consistency" in src
