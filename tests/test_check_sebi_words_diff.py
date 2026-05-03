"""Tests for the --diff-only mode of scripts/check_sebi_words.py.

The lesson behind these tests: in a parallel-PR world, a banned word
that already lives in main is "inherited debt". If the lint flags it
on every open PR, the lint stops being a useful signal — it's just
noise that PR authors learn to ignore. --diff-only restricts checking
to the lines a PR ACTUALLY added.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import check_sebi_words as csw  # noqa: E402


REPO_ROOT = _SCRIPTS.parent


def _diff(file: str, *, added: list[str] = (), removed: list[str] = (), context: list[str] = ()) -> str:
    """Build a tiny synthetic unified diff. Hunk header line numbers are
    not load-bearing for the scanner — only the +/- lines matter."""
    parts = [
        f"diff --git a/{file} b/{file}",
        f"--- a/{file}",
        f"+++ b/{file}",
        "@@ -1,1 +1,1 @@",
    ]
    for c in context:
        parts.append(f" {c}")
    for r in removed:
        parts.append(f"-{r}")
    for a in added:
        parts.append(f"+{a}")
    return "\n".join(parts) + "\n"


def test_inherited_banned_line_not_flagged():
    """The whole point: an existing line containing 'undervalued' that
    the PR did NOT touch must not be flagged."""
    diff = _diff(
        "frontend/src/components/MetricCard.tsx",
        context=['  <span>This is a strong business</span>'],  # inherited
        added=['  <span>Cash flow remained steady this quarter</span>'],  # safe
    )
    hits = csw._scan_diff_added_lines(diff, repo_root=REPO_ROOT)
    assert hits == [], f"expected no hits, got {hits}"


def test_added_banned_line_is_flagged():
    diff = _diff(
        "frontend/src/components/MetricCard.tsx",
        added=['  <span>This stock is undervalued today</span>'],
    )
    hits = csw._scan_diff_added_lines(diff, repo_root=REPO_ROOT)
    assert len(hits) == 1
    f, ln, word, excerpt, _blame = hits[0]
    assert f.endswith("MetricCard.tsx")
    assert word.lower() == "undervalued"


def test_removed_banned_line_not_flagged():
    """If a PR REMOVES inherited banned vocab, that's a good thing —
    don't fail the PR for the deletion."""
    diff = _diff(
        "frontend/src/components/MetricCard.tsx",
        removed=['  <span>This stock is undervalued today</span>'],
        added=['  <span>Trading at 0.7x fair value</span>'],
    )
    hits = csw._scan_diff_added_lines(diff, repo_root=REPO_ROOT)
    assert hits == []


def test_wire_format_literal_not_flagged_on_added_line():
    diff = _diff(
        "frontend/src/lib/verdict.ts",
        added=['  return "undervalued";'],
    )
    # The literal "undervalued" is in WIRE_FORMAT_LITERALS — code-level
    # comparisons against the backend Pydantic enum are exempt.
    hits = csw._scan_diff_added_lines(diff, repo_root=REPO_ROOT)
    assert hits == [], f"wire-format literal should be exempt, got {hits}"


def test_sebi_allow_annotation_on_added_line():
    diff = _diff(
        "frontend/src/components/Foo.tsx",
        added=['  const label = "buy"; // sebi-allow: buy'],
    )
    hits = csw._scan_diff_added_lines(diff, repo_root=REPO_ROOT)
    assert hits == []


def test_non_scanned_extension_ignored():
    diff = _diff(
        "README.md",
        added=['This stock is undervalued.'],
    )
    hits = csw._scan_diff_added_lines(diff, repo_root=REPO_ROOT)
    assert hits == []


def test_exempt_file_ignored():
    diff = _diff(
        "frontend/src/types/api.ts",
        added=['export type Verdict = "undervalued" | "overvalued";'],
    )
    hits = csw._scan_diff_added_lines(diff, repo_root=REPO_ROOT)
    assert hits == []


def test_hunk_line_numbers_track_correctly():
    """Two added lines in a hunk starting at line 50 should be reported
    at lines 50 and 51 of the new file."""
    diff = (
        "diff --git a/frontend/src/x.tsx b/frontend/src/x.tsx\n"
        "--- a/frontend/src/x.tsx\n"
        "+++ b/frontend/src/x.tsx\n"
        "@@ -50,0 +50,2 @@\n"
        "+const a = \"this is undervalued\";\n"
        "+const b = \"this is overvalued\";\n"
    )
    hits = csw._scan_diff_added_lines(diff, repo_root=REPO_ROOT)
    assert len(hits) == 2
    line_nos = sorted(h[1] for h in hits)
    assert line_nos == [50, 51]
