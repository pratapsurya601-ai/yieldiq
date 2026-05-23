"""Tests for the full-tree JSX text-node scanner in check_sebi_words.py.

Background
==========
The original ``_JSX_TEXT_RE`` was ``>([^<{}\\n]*[A-Za-z][^<{}]*)<`` which
required the FIRST character after ``>`` to be a letter on the SAME line.
That silently missed banned vocab inside multi-line JSX bodies like::

    <p className="...">
      No SEBI-regulated buy/sell signals
    </p>

while still catching the single-line variant. PR #571 (Task #134) fixed
a real production miss matching this exact shape. The fixture file
``scripts/_sebi_test_fixtures/multiline_banned.tsx.fixture`` encodes the
miss so we never regress.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import check_sebi_words as csw  # noqa: E402


FIXTURE = (
    _SCRIPTS
    / "_sebi_test_fixtures"
    / "multiline_banned.tsx.fixture"
)


def _scan_text(src: str) -> list[tuple[int, str, str]]:
    """Run the same JSX-text scan path used in production on a literal
    string, without needing to materialise a real file on disk."""
    stripped = csw._strip_comments(src)
    hits: list[tuple[int, str, str]] = []
    for m in csw._JSX_TEXT_RE.finditer(stripped):
        body = m.group(1)
        hit = csw._BANNED_RE.search(body)
        if not hit:
            continue
        ln = stripped.count("\n", 0, m.start()) + 1
        hits.append((ln, hit.group(0), body.strip()))
    return hits


def test_fixture_exists():
    assert FIXTURE.is_file(), f"missing fixture: {FIXTURE}"


def test_multiline_jsx_banned_word_is_caught():
    """The exact shape that PR #571 fixed: banned word on its own line
    inside a JSX body. The pre-fix regex missed this entirely."""
    src = (
        "function Card() {\n"
        "  return (\n"
        "    <p className=\"advisory\">\n"
        "      No SEBI-regulated signals\n"
        "    </p>\n"
        "  );\n"
        "}\n"
    )
    # Replace marker with a banned word inline to keep the Python source
    # SEBI-clean. The fixture file owns the canonical example.
    src = src.replace("signals", "investable signals")
    hits = _scan_text(src)
    assert any(h[1].lower() == "investable" for h in hits), (
        f"multi-line JSX banned word not caught: hits={hits}"
    )


def test_single_line_jsx_still_caught():
    """Regression guard: the new regex must not lose the single-line case."""
    src = '<p>This is an investable business</p>\n'
    hits = _scan_text(src)
    assert len(hits) == 1
    assert hits[0][1].lower() == "investable"


def test_jsx_expression_not_treated_as_text():
    """``{expr}`` should be skipped — the regex must not match across
    braces, otherwise it would false-positive on code identifiers."""
    src = '<p>{getLabel("recommend")}</p>\n'
    hits = _scan_text(src)
    # The string literal inside the expression is checked by the
    # string-literal path, not by the JSX-text path. The JSX-text path
    # here should NOT report a hit.
    assert hits == [], f"JSX expression body should not be matched: {hits}"


def test_attribute_values_not_matched_as_jsx_text():
    """Attribute strings are inside quotes and inside the tag — the
    JSX-text regex starts at ``>`` so they should be skipped here."""
    src = '<div className="recommend-card">plain text only</div>\n'
    hits = _scan_text(src)
    # "plain text only" has no banned word; "recommend" is inside an
    # attribute value, which lives between < and >, not > and <.
    assert hits == []


def test_fixture_file_full_scan_catches_multiline_misses(tmp_path):
    """End-to-end: run _scan_file against the on-disk fixture and assert
    we catch the multi-line banned bodies that motivated this change."""
    # Copy fixture into a temp tree shaped like ``<root>/src/fixture.tsx``
    # so the relative-path logic inside _scan_file is happy. We use a
    # ``.tsx`` extension here (rather than ``.fixture``) so the file
    # qualifies as a scanned extension; the on-disk fixture keeps the
    # neutral ``.fixture`` extension so production lint ignores it.
    root = tmp_path
    src_dir = root / "src"
    src_dir.mkdir()
    target = src_dir / "MultiLineBanned.tsx"
    target.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")

    hits = csw._scan_file(target, root)
    words = {w.lower() for _ln, w, _ex in hits}
    # The fixture contains three JSX text bodies with banned vocab. The
    # scanner reports the FIRST banned hit per body (_BANNED_RE.search,
    # not findall), so we assert one representative word from each:
    #   - multi-line "buy/sell" body  -> "buy" (sell shares the body)
    #   - multi-line "recommend ... accumulate" body -> "recommend"
    #   - single-line "strong" body   -> "strong"
    # The point of this test is that the multi-line bodies are seen at
    # all by the scanner, which the pre-fix regex failed to do.
    for expected in ("buy", "recommend", "strong"):
        assert expected in words, (
            f"expected '{expected}' to be caught by full-file scan, "
            f"got {sorted(words)}"
        )
