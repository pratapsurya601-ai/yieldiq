"""Regression tests for sector_isolation_check.parse_scope.

Locks the contract that PR-body parsing tolerates Markdown decorations
around the ``sector-scope:`` directive. The 2026-04-25 incident on
PR #75 was caused by ``low.startswith("sector-scope:")`` failing on a
backtick-wrapped declaration (`` `sector-scope: *` ``), which made the
sector-isolation merge gate fail spuriously and forced an admin-merge.

These cases lock the fix so the regression cannot recur.
"""
from __future__ import annotations

import sys
from pathlib import Path

# scripts/ is not a package — add it to path so the parser can be imported.
_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import pytest  # noqa: E402

from sector_isolation_check import parse_scope  # noqa: E402


@pytest.mark.parametrize(
    "name, body, expected",
    [
        ("plain global", "sector-scope: *", {"*"}),
        ("backtick wrap", "`sector-scope: *`", {"*"}),
        ("blockquote", "> sector-scope: Cement", {"Cement"}),
        ("list bullet (dash)", "- sector-scope: Cement, Banks", {"Cement", "Banks"}),
        ("list bullet (bullet char)", "• sector-scope: IT Services", {"IT Services"}),
        ("none lowercase", "sector-scope: none", set()),
        ("none mixed case", "sector-scope: None", set()),
        ("inline preamble", "Note: sector-scope: *", {"*"}),
        ("multi-sector backticks", "`sector-scope: Cement, Banks`", {"Cement", "Banks"}),
        ("missing directive", "this body has no directive", None),
        ("multi-line, directive on line 2", "First line.\n`sector-scope: *`\nLast line.", {"*"}),
        ("global with trailing prose-after-comma", "sector-scope: *, see docs", {"*"}),
        ("global anywhere in list collapses to global", "sector-scope: Cement, *, Banks", {"*"}),
        ("standalone star is not a declaration", "*", None),
        ("case-insensitive directive", "SECTOR-SCOPE: Banks", {"Banks"}),
        ("empty input", "", None),
        ("none input", None, None),
    ],
)
def test_parse_scope(name, body, expected):
    assert parse_scope(body) == expected, name
