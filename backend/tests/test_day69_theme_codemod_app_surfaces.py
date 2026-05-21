"""Day-69 (PR-1/4 of theme rollout): regression guards for the
mechanical token codemod across (app)/ and (stocks)/ route pages.

The Day-69 audit found 1,230 hardcoded color tokens across 99 .tsx
files. PR-1 (this one) handles the SAFE SURFACES — pure 1:1 swaps of
neutral grays / white to design tokens (bg-bg / bg-surface / text-ink /
text-caption / border-border) on the route-page level only.

What we guard:
  - Previously-broken pages now contain at least one design token.
  - Hardcoded neutral tokens we swapped no longer appear OUTSIDE
    ternary branches tied to a semantic conditional (those stay
    branded — see scripts/day69_theme_codemod.py for the rules).
  - The known semantic ternaries that MUST stay branded are still
    present byte-for-byte (regression guard against an over-eager
    later codemod stripping them).

PR-2 covers (marketing)/ pages, PR-3 covers components/, PR-4 covers
the semantic chips (ValueBand, VerdictPill, RedFlag, MoSChip,
ScorePill, Sentiment) — those each keep their branded palette.
"""
from __future__ import annotations

import re
from pathlib import Path

_F = Path(__file__).resolve().parents[2] / "frontend" / "src"

# Subset of files PR-1 modified. We don't pin all 30 here — the codemod
# script is the source of truth for that list. These are the highest-
# traffic surfaces a regression would hurt the most.
_FAIR_VALUE = _F / "app" / "(stocks)" / "stocks" / "[ticker]" / "fair-value" / "page.tsx"
_PORTFOLIO = _F / "app" / "(app)" / "portfolio" / "page.tsx"
_REVERSE_DCF = _F / "app" / "(stocks)" / "stocks" / "[ticker]" / "reverse-dcf" / "ReverseDCFClient.tsx"
_RISK = _F / "app" / "(stocks)" / "stocks" / "[ticker]" / "risk-analysis" / "page.tsx"
_DUPONT = _F / "app" / "(stocks)" / "stocks" / "[ticker]" / "dupont" / "page.tsx"
_COMPARE_CLIENT = _F / "app" / "(stocks)" / "compare" / "[slug]" / "CompareClient.tsx"
_ACCOUNT = _F / "app" / "(app)" / "account" / "page.tsx"

# Class-token boundary matcher. Tailwind class tokens never have a
# trailing `-` or word char and never a leading word char or `:` (the
# `:` would make it a variant prefix like `hover:bg-white`, not a
# bare `bg-white`).
_BOUNDARY = r"(?<![\w:-])({tok})(?![\w-])"


def _count_token(src: str, token: str) -> int:
    return len(re.findall(_BOUNDARY.format(tok=re.escape(token)), src))


# ── Negative assertions: the codemod stripped the bare hardcoded
# neutrals from high-traffic pages. Anything that remains must be a
# semantic-ternary branch and is whitelisted explicitly per file.


def test_fair_value_no_bare_bg_white():
    src = _FAIR_VALUE.read_text(encoding="utf-8")
    # 0 expected — no semantic ternary branches reference bg-white here.
    assert _count_token(src, "bg-white") == 0, (
        "fair-value/page.tsx still has bare `bg-white`. PR-1 should "
        "have swapped these to `bg-bg dark:bg-surface`."
    )


def test_portfolio_no_bare_text_gray_700():
    src = _PORTFOLIO.read_text(encoding="utf-8")
    assert _count_token(src, "text-gray-700") == 0


def test_reverse_dcf_no_bare_border_gray_200():
    src = _REVERSE_DCF.read_text(encoding="utf-8")
    assert _count_token(src, "border-gray-200") == 0


def test_risk_analysis_no_bare_bg_gray_50():
    src = _RISK.read_text(encoding="utf-8")
    assert _count_token(src, "bg-gray-50") == 0


def test_dupont_no_bare_text_gray_500():
    src = _DUPONT.read_text(encoding="utf-8")
    assert _count_token(src, "text-gray-500") == 0


# ── Positive assertions: the new design tokens now appear in the
# previously-broken pages. Sanity check that we actually swapped IN
# something, not just deleted hardcoded grays.


def test_fair_value_has_design_tokens():
    src = _FAIR_VALUE.read_text(encoding="utf-8")
    assert "bg-bg dark:bg-surface" in src
    assert "text-caption" in src
    assert "border-border" in src


def test_portfolio_has_design_tokens():
    src = _PORTFOLIO.read_text(encoding="utf-8")
    assert "text-ink" in src or "text-caption" in src
    assert "border-border" in src


# ── Branded-ternary preservation: these specific verdict / status
# ternaries MUST keep their gray-as-neutral branch unmodified. If a
# later codemod ever strips them, this test fires immediately.


def test_compare_client_semantic_ternary_preserved():
    """The CompareClient win/loss tile uses the neutral gray branch as
    the "not winning" state, paired with `border-green-300 bg-green-50`
    for the winning state. The pairing is the visual language — both
    halves must stay literal so the contrast reads correctly."""
    src = _COMPARE_CLIENT.read_text(encoding="utf-8")
    assert 'isWin ? "border-green-300 bg-green-50/40" : "border-gray-200 bg-white"' in src


def test_fair_value_moat_ternary_preserved():
    """The Economic Moat tile colour cascades Wide -> green, Narrow ->
    blue, else gray. The trailing `text-gray-600` is the neutral branch
    and must not be swapped to text-caption (that would desync from the
    green/blue siblings)."""
    src = _FAIR_VALUE.read_text(encoding="utf-8")
    assert 'data.moat === "Wide" ? "text-green-600" : data.moat === "Narrow" ? "text-blue-600" : "text-gray-600"' in src


def test_account_toast_ternary_preserved():
    src = _ACCOUNT.read_text(encoding="utf-8")
    assert 'toast.tone === "err" ? "bg-red-600" : "bg-gray-900"' in src
