"""Day-35 (2026-05-20): regression guards for currency / number
formatting consolidation.

Day-27 audit flagged 5+ sites with local fmtNum / fmtPct / raw
.toLocaleString re-implementations. Day-35 centralises:
  - formatNumberWithSuffix in lib/utils.ts
  - formatPctSigned in lib/utils.ts
  - ESLint rule (warn) banning .toLocaleString in component files

Source-text grep — same pattern as Days 28-34.
"""
from __future__ import annotations
from pathlib import Path


_F = Path(__file__).resolve().parents[2] / "frontend" / "src"
_UTILS = _F / "lib" / "utils.ts"
_PEER_CARD = _F / "components" / "analysis" / "PeerComparisonCard.tsx"
_ADMIN_STORY_DCF = _F / "app" / "(app)" / "admin" / "story-dcf" / "page.tsx"
_ESLINT = Path(__file__).resolve().parents[2] / "frontend" / "eslint.config.mjs"


# ── New canonical helpers ────────────────────────────────────


def test_utils_exports_format_number_with_suffix():
    src = _UTILS.read_text(encoding="utf-8")
    assert "export function formatNumberWithSuffix(" in src, (
        "formatNumberWithSuffix() missing from lib/utils.ts. This is "
        "the canonical replacement for the local fmtNum() variants."
    )


def test_utils_exports_format_pct_signed():
    src = _UTILS.read_text(encoding="utf-8")
    assert "export function formatPctSigned(" in src


def test_format_number_with_suffix_uses_isfinite_not_isnan():
    """The local fmtNum() variants used `isNaN(v)` which lets +/-
    Infinity through. The canonical helper uses Number.isFinite
    so all non-finite values fall to the em-dash path."""
    src = _UTILS.read_text(encoding="utf-8")
    # Both new helpers should use Number.isFinite
    nf_count = src.count("!Number.isFinite(value)")
    assert nf_count >= 2, (
        f"Expected formatNumberWithSuffix + formatPctSigned to use "
        f"!Number.isFinite. Found {nf_count} matches."
    )


# ── Component dedup ──────────────────────────────────────────


def test_peer_comparison_imports_canonical_helpers():
    src = _PEER_CARD.read_text(encoding="utf-8")
    assert 'import { formatNumberWithSuffix, formatPctSigned } from "@/lib/utils"' in src
    # Local 3-line bodies should be replaced by single-line aliases
    # to the canonical helpers (not deleted — calling code keeps
    # the local names for diff hygiene).
    assert "const fmtPct = formatPctSigned" in src
    assert "const fmtNum = formatNumberWithSuffix" in src
    # The OLD body must be gone — flagged by the isNaN check that
    # got replaced.
    assert (
        'if (v == null || isNaN(v)) return "—"\n  return `${v >= 0 ? "+"'
        not in src
    )


def test_admin_story_dcf_uses_canonical_helpers():
    src = _ADMIN_STORY_DCF.read_text(encoding="utf-8")
    assert 'import { formatNumberWithSuffix, formatRateDecimal } from "@/lib/utils"' in src
    # Local helpers now delegate to canonical
    assert "const fmtPct = (n: number | null | undefined) => formatRateDecimal(n, 1)" in src
    assert "formatNumberWithSuffix(n, digits)" in src


# ── ESLint rule ──────────────────────────────────────────────


def test_eslint_bans_to_locale_string_in_components():
    src = _ESLINT.read_text(encoding="utf-8")
    assert "no-restricted-syntax" in src, (
        "ESLint no-restricted-syntax rule missing — needed to prevent "
        "future drift to ad-hoc .toLocaleString calls."
    )
    # Selector must catch .toLocaleString() calls
    assert "callee.property.name='toLocaleString'" in src
    # Allowlist must include lib/utils + lib/currency
    assert "src/lib/utils.ts" in src
    assert "src/lib/currency.ts" in src
    # Test files should be exempt
    assert "src/**/*.test.{ts,tsx}" in src
    # Suggested replacements named in the message
    assert "formatCurrency" in src
    assert "formatNumberWithSuffix" in src
