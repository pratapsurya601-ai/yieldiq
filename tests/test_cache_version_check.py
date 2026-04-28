"""Tests for scripts/cache_version_check.py.

Covers the four scenarios spelled out in the spec:

  1. backend/services touched + bump present                  -> PASS
  2. backend/services touched + no bump + no skip declaration -> FAIL
  3. only frontend/docs touched                               -> PASS
  4. backend/services touched + skip declaration              -> PASS

Plus a couple of regression locks (skip token tolerates Markdown
decorations; bump-to-same-value is NOT counted as a bump).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# scripts/ is not a package — extend sys.path the same way
# tests/test_sector_isolation_parser.py does.
_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import cache_version_check as cvc  # noqa: E402


# ---- Synthetic diff builders ----------------------------------------------
def _diff_chunk(path: str, added: str = "+x = 1\n", removed: str = "-x = 0\n") -> str:
    return (
        f"diff --git a/{path} b/{path}\n"
        f"--- a/{path}\n"
        f"+++ b/{path}\n"
        f"@@ -1,1 +1,1 @@\n"
        f"{removed}{added}"
    )


def _bump_chunk(old: int = 64, new: int = 65) -> str:
    return (
        "diff --git a/backend/services/cache_service.py b/backend/services/cache_service.py\n"
        "--- a/backend/services/cache_service.py\n"
        "+++ b/backend/services/cache_service.py\n"
        "@@ -34,1 +34,1 @@\n"
        f"-CACHE_VERSION = {old}\n"
        f"+CACHE_VERSION = {new}\n"
    )


# ---- Scenario 1: backend touched + bump present ---------------------------
def test_backend_services_with_bump_passes():
    diff = _diff_chunk("backend/services/analysis_service.py") + _bump_chunk(64, 65)
    touched, matched = cvc.diff_touches_trigger(diff)
    assert touched
    assert "backend/services/analysis_service.py" in matched
    assert cvc.diff_has_cache_bump(diff) is True


# ---- Scenario 2: backend touched + no bump + no skip ----------------------
def test_backend_services_without_bump_or_skip_fails():
    diff = _diff_chunk("backend/services/analysis_service.py")
    touched, matched = cvc.diff_touches_trigger(diff)
    assert touched
    assert cvc.diff_has_cache_bump(diff) is False
    assert cvc.body_has_skip_declaration("Just a routine refactor.") is False


# ---- Scenario 3: only frontend / docs ------------------------------------
@pytest.mark.parametrize(
    "path",
    [
        "frontend/components/ui/Button.tsx",
        "frontend/app/page.tsx",
        "docs/cache_version_discipline.md",
        "README.md",
        "tests/test_something.py",
    ],
)
def test_non_trigger_paths_dont_require_bump(path):
    diff = _diff_chunk(path)
    touched, matched = cvc.diff_touches_trigger(diff)
    assert not touched, f"{path} should not be a trigger"
    assert matched == []


# ---- Scenario 4: backend touched + skip declaration ----------------------
@pytest.mark.parametrize(
    "body",
    [
        "cache-version: skip",
        "cache-version: not-needed",
        "cache-version: not-needed - frontend-wiring only",
        "Some preamble.\n\ncache-version: skip - logging additions",
        "`cache-version: not-needed - docs only`",
        "> cache-version: skip",
        "- cache-version: not-needed - test refactor",
        "CACHE-VERSION: SKIP",  # case-insensitive
    ],
)
def test_skip_declaration_recognised(body):
    assert cvc.body_has_skip_declaration(body) is True


@pytest.mark.parametrize(
    "body",
    [
        "",
        None,
        "cache version: skip",  # missing hyphen
        "cache-version skip",   # missing colon
        "I forgot to add the skip token.",
    ],
)
def test_skip_declaration_rejected(body):
    assert cvc.body_has_skip_declaration(body) is False


# ---- Regression locks -----------------------------------------------------
def test_bump_to_same_value_not_counted():
    """If someone edits the line but keeps the same integer, that's not a bump."""
    diff = (
        "diff --git a/backend/services/cache_service.py b/backend/services/cache_service.py\n"
        "--- a/backend/services/cache_service.py\n"
        "+++ b/backend/services/cache_service.py\n"
        "@@ -34,1 +34,1 @@\n"
        "-CACHE_VERSION = 65  # old comment\n"
        "+CACHE_VERSION = 65  # new comment\n"
    )
    assert cvc.diff_has_cache_bump(diff) is False


def test_each_trigger_prefix_fires():
    for prefix in cvc.TRIGGER_PREFIXES:
        path = prefix + "x.py"
        touched, matched = cvc.diff_touches_trigger(_diff_chunk(path))
        assert touched, f"prefix {prefix} should trigger"
        assert path in matched


def test_exact_trigger_files_fire():
    for path in cvc.TRIGGER_EXACT:
        touched, matched = cvc.diff_touches_trigger(_diff_chunk(path))
        assert touched, f"{path} should trigger"
        assert path in matched


def test_models_subdir_not_in_trigger_exact_does_not_fire():
    """models/ is NOT a blanket trigger — only forecaster.py + industry_wacc.py."""
    diff = _diff_chunk("models/some_other_thing.py")
    touched, _ = cvc.diff_touches_trigger(diff)
    assert not touched


def test_full_main_pass_path(tmp_path):
    """End-to-end: main() returns 0 when bump + trigger both present."""
    diff = _diff_chunk("backend/services/analysis_service.py") + _bump_chunk(64, 65)
    diff_file = tmp_path / "pr.diff"
    body_file = tmp_path / "pr_body.txt"
    diff_file.write_text(diff, encoding="utf-8")
    body_file.write_text("Routine fix.", encoding="utf-8")
    rc = cvc.main([
        "--diff-file", str(diff_file),
        "--pr-body-file", str(body_file),
        "--require-bump",
    ])
    assert rc == 0


def test_full_main_fail_path(tmp_path, capsys):
    diff = _diff_chunk("backend/services/analysis_service.py")
    diff_file = tmp_path / "pr.diff"
    body_file = tmp_path / "pr_body.txt"
    diff_file.write_text(diff, encoding="utf-8")
    body_file.write_text("Just a refactor.", encoding="utf-8")
    rc = cvc.main([
        "--diff-file", str(diff_file),
        "--pr-body-file", str(body_file),
        "--require-bump",
    ])
    assert rc == 1
    err = capsys.readouterr().err
    assert "CACHE_VERSION-bump check FAILED" in err


def test_full_main_skip_path(tmp_path):
    diff = _diff_chunk("backend/routers/analysis.py")
    diff_file = tmp_path / "pr.diff"
    body_file = tmp_path / "pr_body.txt"
    diff_file.write_text(diff, encoding="utf-8")
    body_file.write_text(
        "Adds a logging line. cache-version: not-needed - logging-only\n",
        encoding="utf-8",
    )
    rc = cvc.main([
        "--diff-file", str(diff_file),
        "--pr-body-file", str(body_file),
        "--require-bump",
    ])
    assert rc == 0


def test_full_main_no_trigger_path(tmp_path):
    diff = _diff_chunk("frontend/components/ui/Button.tsx")
    diff_file = tmp_path / "pr.diff"
    diff_file.write_text(diff, encoding="utf-8")
    rc = cvc.main([
        "--diff-file", str(diff_file),
        "--require-bump",
    ])
    assert rc == 0
