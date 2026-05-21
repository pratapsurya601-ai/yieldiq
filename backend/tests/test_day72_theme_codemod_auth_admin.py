"""Day-72 PR-4 guard: verify auth + legal + terms/privacy surfaces have
been migrated from hardcoded gray/white classes to design tokens, and
that no in-scope file leaks the SEBI-banned `<strong>` HTML tag (which
Sebi-lint flags as banned vocabulary on added diff lines).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend" / "src"

IN_SCOPE = [
    "app/auth/login/page.tsx",
    "app/auth/callback/page.tsx",
    "app/auth/signup/page.tsx",
    "app/auth/reset-password/page.tsx",
    "app/auth/forgot-password/page.tsx",
    "app/legal/sla/page.tsx",
    "app/(marketing)/terms/page.tsx",
    "app/(marketing)/privacy/page.tsx",
]

# Tailwind class-token boundary (matches codemod).
_PRE = r"(?<![\w:-])"
_POST = r"(?![\w-])"


def _read(rel: str) -> str:
    p = FRONTEND / rel
    assert p.exists(), f"missing in-scope file: {rel}"
    return p.read_text(encoding="utf-8")


@pytest.mark.parametrize("rel", IN_SCOPE)
def test_no_bare_bg_white(rel: str) -> None:
    """No bare `bg-white` class token outside a `dark:` variant prefix."""
    src = _read(rel)
    for i, line in enumerate(src.splitlines(), 1):
        if re.search(_PRE + r"bg-white" + _POST, line):
            assert False, f"{rel}:{i} still uses bare `bg-white`: {line.strip()}"


@pytest.mark.parametrize("rel", IN_SCOPE)
def test_no_bare_gray_text(rel: str) -> None:
    """No bare `text-gray-[4-9]00` class tokens (should be ink/caption)."""
    src = _read(rel)
    pat = re.compile(_PRE + r"text-gray-[4-9]00" + _POST)
    for i, line in enumerate(src.splitlines(), 1):
        if pat.search(line):
            assert False, f"{rel}:{i} still uses `text-gray-*`: {line.strip()}"


@pytest.mark.parametrize("rel", IN_SCOPE)
def test_no_bare_gray_border(rel: str) -> None:
    """No bare `border-gray-200|300` tokens (should be `border-border`)."""
    src = _read(rel)
    pat = re.compile(_PRE + r"border-gray-[23]00" + _POST)
    for i, line in enumerate(src.splitlines(), 1):
        if pat.search(line):
            assert False, f"{rel}:{i} still uses `border-gray-*`: {line.strip()}"


@pytest.mark.parametrize("rel", IN_SCOPE)
def test_no_bare_gray_surface(rel: str) -> None:
    """No bare `bg-gray-50` / `bg-gray-100` (should be `bg-bg` / `bg-surface`)."""
    src = _read(rel)
    pat = re.compile(_PRE + r"bg-gray-(?:50|100)" + _POST)
    for i, line in enumerate(src.splitlines(), 1):
        if pat.search(line):
            assert False, f"{rel}:{i} still uses `bg-gray-50/100`: {line.strip()}"


@pytest.mark.parametrize("rel", IN_SCOPE)
def test_no_html_strong_tag(rel: str) -> None:
    """Sebi-lint hazard: `<strong>` is banned vocabulary in added diff lines.
    Use `<span className=\"font-bold\">` instead.
    """
    src = _read(rel)
    assert "<strong" not in src, f"{rel} still has a `<strong` HTML tag"
    assert "</strong>" not in src, f"{rel} still has a `</strong>` close tag"


def test_scope_files_all_present() -> None:
    """Sanity: every file listed in IN_SCOPE exists on disk."""
    missing = [rel for rel in IN_SCOPE if not (FRONTEND / rel).exists()]
    assert not missing, f"missing in-scope files: {missing}"


def test_tokens_actually_used() -> None:
    """At least one in-scope file must contain `text-ink` and `text-caption`
    and `bg-bg dark:bg-surface` — proving the codemod actually ran rather
    than us shipping an empty diff."""
    joined = "\n".join(_read(rel) for rel in IN_SCOPE)
    assert "text-ink" in joined, "no `text-ink` token found across in-scope files"
    assert "text-caption" in joined, "no `text-caption` token found across in-scope files"
    assert "bg-bg dark:bg-surface" in joined, "no `bg-bg dark:bg-surface` swap found"
    assert "border-border" in joined, "no `border-border` token found"
