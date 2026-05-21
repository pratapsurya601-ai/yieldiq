"""Day-83 (2026-05-22): source-text guards for the /help section.

Day-83 ships an end-user documentation section at frontend/src/app/
(marketing)/help/ — seven topic pages plus an index, navigation
component, and shared shell. This guard pins:

  1. All seven topic pages exist at their expected slugs.
  2. The index page, HelpNav, and HelpPageShell components exist.
  3. The sitemap lists every help URL (index + seven topics).
  4. MarketingFooter links to /help.
  5. Each help page carries enough word-count to be real content
     (rough proxy of >= 200 words of body copy).
  6. No SEBI-banned vocabulary appears anywhere in the help pages.
     The banned list mirrors backend/services/analysis/sebi_filter.py
     plus the documentation-specific bans called out in the Day-83
     spec ("should", "hold" in plain text, raw <strong> tags).

These tests are source-text only — they read .tsx files as text and
match against regex. No Node, no build step. Keeps the guard cheap.
"""
from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_HELP = _ROOT / "frontend" / "src" / "app" / "(marketing)" / "help"
_SITEMAP = _ROOT / "frontend" / "src" / "app" / "sitemap.ts"
_FOOTER = _ROOT / "frontend" / "src" / "components" / "marketing" / "MarketingFooter.tsx"

_TOPIC_SLUGS = [
    "reading-an-analysis",
    "fair-value-and-mos",
    "using-the-screener",
    "portfolio-prism",
    "confidence-and-limits",
    "sectors-and-cohorts",
    "pricing-and-tiers",
]

# SEBI-banned vocabulary. Word-boundary matched, case-insensitive.
# "hold" is banned in plain text — "holding"/"holdings" are allowed
# because they are distinct nouns and the regex below uses \b.
_BANNED_WORDS = [
    "buy",
    "sell",
    "hold",
    "holds",
    "strong",
    "accumulate",
    "recommend",
    "recommendation",
    "outperform",
    "underperform",
    "should",
]


def _topic_file(slug: str) -> Path:
    return _HELP / slug / "page.tsx"


def _strip_jsx_to_text(src: str) -> str:
    """Best-effort strip of JSX tags and attributes to leave just the
    user-facing text. Good enough for word-count and vocabulary scans."""
    # Remove import/export/const blocks (anything outside JSX returns).
    src = re.sub(r"<[^>]+>", " ", src)
    # Collapse JSX entities.
    src = (
        src.replace("&rsquo;", "'")
        .replace("&ldquo;", '"')
        .replace("&rdquo;", '"')
        .replace("&mdash;", "-")
        .replace("&ndash;", "-")
        .replace("&larr;", "")
        .replace("&rarr;", "")
        .replace("&amp;", "&")
        .replace("&#8377;", "Rs")
    )
    return src


# ── 1. File existence ─────────────────────────────────────────────


def test_help_index_page_exists() -> None:
    assert (_HELP / "page.tsx").exists(), "/help index page must exist."


def test_help_nav_component_exists() -> None:
    assert (_HELP / "HelpNav.tsx").exists(), "HelpNav.tsx side-rail must exist."


def test_help_page_shell_exists() -> None:
    assert (
        _HELP / "HelpPageShell.tsx"
    ).exists(), "HelpPageShell.tsx wrapper must exist."


def test_all_seven_topic_pages_exist() -> None:
    missing = [s for s in _TOPIC_SLUGS if not _topic_file(s).exists()]
    assert not missing, f"Missing help topic pages: {missing}"


# ── 2. Sitemap + footer wiring ────────────────────────────────────


def test_sitemap_lists_help_index() -> None:
    body = _SITEMAP.read_text(encoding="utf-8")
    assert "https://yieldiq.in/help\"" in body or "yieldiq.in/help\"" in body, (
        "Sitemap must list the /help index URL."
    )


def test_sitemap_lists_every_help_topic() -> None:
    body = _SITEMAP.read_text(encoding="utf-8")
    missing = [s for s in _TOPIC_SLUGS if f"/help/{s}" not in body]
    assert not missing, f"Sitemap missing help topic URLs: {missing}"


def test_marketing_footer_links_to_help() -> None:
    body = _FOOTER.read_text(encoding="utf-8")
    assert 'href="/help"' in body, (
        "MarketingFooter must link to /help so users can discover the "
        "documentation section from any marketing page."
    )


# ── 3. Word-count floor (each topic has real content) ─────────────


def test_every_topic_page_has_at_least_200_words() -> None:
    too_short: list[tuple[str, int]] = []
    for slug in _TOPIC_SLUGS:
        text = _strip_jsx_to_text(_topic_file(slug).read_text(encoding="utf-8"))
        words = re.findall(r"[A-Za-z][A-Za-z'-]+", text)
        if len(words) < 200:
            too_short.append((slug, len(words)))
    assert not too_short, (
        f"Help pages below the 200-word floor: {too_short}. End-user "
        "documentation must be substantive, not a stub."
    )


# ── 4. SEBI vocabulary scan ───────────────────────────────────────


def _scan_banned(slug: str) -> list[str]:
    text = _strip_jsx_to_text(_topic_file(slug).read_text(encoding="utf-8"))
    hits: list[str] = []
    for word in _BANNED_WORDS:
        if re.search(rf"\b{re.escape(word)}\b", text, flags=re.IGNORECASE):
            hits.append(word)
    return hits


def test_no_banned_vocabulary_in_topic_pages() -> None:
    failures: dict[str, list[str]] = {}
    for slug in _TOPIC_SLUGS:
        hits = _scan_banned(slug)
        if hits:
            failures[slug] = hits
    assert not failures, (
        f"SEBI-banned vocabulary in help pages: {failures}. Replace "
        "with descriptive alternatives (consider / look at / compare / "
        "displays / renders / retain)."
    )


def test_no_banned_vocabulary_in_help_index_or_nav() -> None:
    failures: dict[str, list[str]] = {}
    for fname in ("page.tsx", "HelpNav.tsx", "HelpPageShell.tsx"):
        text = _strip_jsx_to_text((_HELP / fname).read_text(encoding="utf-8"))
        hits = [
            w
            for w in _BANNED_WORDS
            if re.search(rf"\b{re.escape(w)}\b", text, flags=re.IGNORECASE)
        ]
        if hits:
            failures[fname] = hits
    assert not failures, (
        f"SEBI-banned vocabulary in help shell files: {failures}."
    )


def test_no_raw_strong_tags_in_help_pages() -> None:
    """The Day-72 theme rollout replaced <strong> with
    <span className="font-bold">. Day-83 documentation must follow
    the same convention so the codemod doesn't have to revisit it."""
    failures: list[str] = []
    for path in [_HELP / "page.tsx", _HELP / "HelpNav.tsx", _HELP / "HelpPageShell.tsx"] + [
        _topic_file(s) for s in _TOPIC_SLUGS
    ]:
        if re.search(r"<strong[\s>]", path.read_text(encoding="utf-8")):
            failures.append(str(path.relative_to(_ROOT)))
    assert not failures, (
        f"Raw <strong> tags in help files: {failures}. Use "
        "<span className=\"font-bold\"> per the Day-72 theme convention."
    )
