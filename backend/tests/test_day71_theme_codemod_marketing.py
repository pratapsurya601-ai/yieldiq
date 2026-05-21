"""Day-71 (PR-2/4 of theme rollout): regression guards for the
mechanical token codemod across (marketing)/ route pages plus the
landing root (`app/page.tsx`) and `app/layout.tsx`.

PR-1 (Day-69) already handled (app)/ and (stocks)/ surfaces. PR-2
focuses on marketing pages — same token map, same safety rules
(reuses `scripts/day69_theme_codemod.apply_swaps`).

What we guard:
  - Top-5 changed marketing files have 0 bare `bg-white` / bare
    `text-gray-700` / bare `border-gray-200` tokens.
  - The new design tokens (`bg-bg dark:bg-surface`, `text-ink`,
    `text-caption`, `border-border`) actually appear in those files.
  - Two known semantic ternaries that MUST stay branded are pinned
    byte-for-byte (pricing billing-toggle, landing-root highlight
    plan tile) — guards against an over-eager later codemod ever
    rewriting the branded gray-on-the-neutral-branch.
"""
from __future__ import annotations

import re
from pathlib import Path

_F = Path(__file__).resolve().parents[2] / "frontend" / "src"

# Top files PR-2 modified (by swap count).
_SCREEN_CLIENT = _F / "app" / "(marketing)" / "screens" / "[slug]" / "ScreenClient.tsx"
_LANDING_ROOT = _F / "app" / "page.tsx"
_NIFTY50 = _F / "app" / "(marketing)" / "nifty50" / "IndexDashboardClient.tsx"
_PRICING = _F / "app" / "(marketing)" / "pricing" / "page.tsx"
_LANDING = _F / "app" / "(marketing)" / "landing" / "page.tsx"

_BOUNDARY = r"(?<![\w:-])({tok})(?![\w-])"


def _count_token(src: str, token: str) -> int:
    return len(re.findall(_BOUNDARY.format(tok=re.escape(token)), src))


# ── Negative assertions: bare hardcoded neutrals are gone from the
# top-5 changed marketing files. Anything that remains must be a
# branded-ternary branch (validated separately below).


def test_screen_client_no_bare_bg_white():
    src = _SCREEN_CLIENT.read_text(encoding="utf-8")
    # ScreenClient was the densest marketing file; bare bg-white should
    # be fully stripped (no semantic ternaries reference it here).
    assert _count_token(src, "bg-white") == 0


def test_landing_root_no_bare_text_gray_700():
    src = _LANDING_ROOT.read_text(encoding="utf-8")
    assert _count_token(src, "text-gray-700") == 0


def test_nifty50_no_bare_border_gray_200():
    src = _NIFTY50.read_text(encoding="utf-8")
    assert _count_token(src, "border-gray-200") == 0


def test_pricing_no_bare_bg_gray_50():
    src = _PRICING.read_text(encoding="utf-8")
    assert _count_token(src, "bg-gray-50") == 0


def test_landing_marketing_no_bare_text_gray_500():
    src = _LANDING.read_text(encoding="utf-8")
    assert _count_token(src, "text-gray-500") == 0


# ── Positive assertions: design tokens now appear in these files.


def test_top_files_have_design_tokens():
    for path in (_SCREEN_CLIENT, _LANDING_ROOT, _NIFTY50, _PRICING, _LANDING):
        src = path.read_text(encoding="utf-8")
        assert "text-ink" in src or "text-caption" in src, f"{path.name} missing ink/caption"
        assert ("border-border" in src) or ("bg-bg dark:bg-surface" in src) or ("bg-surface" in src), (
            f"{path.name} missing border/surface token"
        )


# ── Branded-ternary preservation: pinned strings the codemod must
# leave alone. Any future codemod that breaks one of these will fail
# this test immediately.


def test_pricing_billing_toggle_ternary_preserved():
    """The annual/monthly billing toggle uses `bg-white text-blue-700`
    on the active branch paired with `bg-green-100 text-green-700` on
    the inactive savings-callout branch. Both halves must stay literal
    so the chip palette reads correctly."""
    src = _PRICING.read_text(encoding="utf-8")
    assert (
        'billing === "annual" ? "bg-white text-blue-700" : "bg-green-100 text-green-700"'
        in src
    )


def test_landing_root_highlight_plan_ternary_preserved():
    """The landing-root pricing tile highlights the recommended plan
    with `border-blue-500 ring-1 ring-blue-500/20 bg-white`; the
    non-highlight branch is `border-gray-100 bg-white`. The bare
    bg-white on the highlight branch is part of the branded pairing
    and must remain literal — the codemod's semantic-hue filter
    correctly skips this line."""
    src = _LANDING_ROOT.read_text(encoding="utf-8")
    assert (
        'p.highlight ? "border-blue-500 ring-1 ring-blue-500/20 bg-white" : "border-gray-100 bg-white"'
        in src
    )


# ── <strong> -> <span className="font-bold"> conversion guard.
# SEBI-lint bans the literal word inside <strong>, so any <strong>
# we touched while migrating tokens was converted in the same commit.


def test_pricing_no_strong_tag():
    src = _PRICING.read_text(encoding="utf-8")
    assert "<strong>" not in src, (
        "pricing/page.tsx still contains a <strong> tag. Convert to "
        "<span className=\"font-bold\"> to satisfy sebi-lint."
    )
