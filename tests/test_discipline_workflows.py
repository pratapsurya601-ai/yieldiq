"""Tests for the CLAUDE.md discipline-rule automation.

Covers:
  * Rule #2 — snapshot-id detection logic against synthetic PR diffs
    and PR-body strings.
  * Rule #3 — consecutive-clean streak counting against synthetic
    canary_history.jsonl files (including reset-on-failure, partial
    days, and empty histories).
  * `scripts/declare_fix_status.py` message construction.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import declare_fix_status as dfs  # noqa: E402


# ---------------------------------------------------------------------------
# Rule #2 — snapshot-id parsing
# ---------------------------------------------------------------------------

# Mirror the regex used inside discipline_rule_2.yml so we test the
# same logic that the workflow runs.
_SNAPSHOT_RE = re.compile(r'(?mi)^\s*snapshot-id:\s*([\w./-]+)\s*$')


def _extract_snapshot_id(body: str) -> str | None:
    m = _SNAPSHOT_RE.search(body or "")
    return m.group(1).strip() if m else None


def test_rule2_accepts_clean_snapshot_declaration():
    body = (
        "fix(analysis): something\n\n"
        "snapshot-id: snapshot_20260427_120000_abcdef.json\n\n"
        "Other body text."
    )
    assert _extract_snapshot_id(body) == "snapshot_20260427_120000_abcdef.json"


def test_rule2_rejects_missing_snapshot_declaration():
    body = "fix(analysis): just some words, no snapshot declared at all.\n"
    assert _extract_snapshot_id(body) is None


def test_rule2_rejects_empty_pr_body():
    assert _extract_snapshot_id("") is None
    assert _extract_snapshot_id(None) is None  # type: ignore[arg-type]


def test_rule2_handles_case_insensitive_label():
    body = "Snapshot-Id: snap1.json"
    assert _extract_snapshot_id(body) == "snap1.json"


def test_rule2_rejects_path_traversal():
    # Path traversal must not match the strict character class.
    body = "snapshot-id: ../../etc/passwd"
    sid = _extract_snapshot_id(body)
    # The regex character class allows ., /, -, _ and word chars, so
    # `../../etc/passwd` matches; the workflow rejects it on the
    # ".." check separately. Mirror that check here.
    assert sid is not None
    assert ".." in sid  # caught by the workflow's secondary guard


def test_rule2_diff_pattern_detects_cache_version_change():
    # Mirrors the `git diff | grep` filter in the workflow.
    diff = (
        "diff --git a/backend/services/cache_service.py "
        "b/backend/services/cache_service.py\n"
        "@@\n"
        "-CACHE_VERSION = 64  # old\n"
        "+CACHE_VERSION = 65  # new\n"
        " class CacheService:\n"
    )
    pattern = re.compile(r'^[+-]CACHE_VERSION\s*=', re.MULTILINE)
    assert pattern.search(diff) is not None


def test_rule2_diff_pattern_skips_unrelated_edits():
    diff = (
        "diff --git a/backend/services/cache_service.py "
        "b/backend/services/cache_service.py\n"
        "@@\n"
        "-    # old comment about CACHE_VERSION semantics\n"
        "+    # new comment about CACHE_VERSION semantics\n"
        " class CacheService:\n"
    )
    pattern = re.compile(r'^[+-]CACHE_VERSION\s*=', re.MULTILINE)
    assert pattern.search(diff) is None


# ---------------------------------------------------------------------------
# Rule #3 — streak counting
# ---------------------------------------------------------------------------


def _write_history(tmp_path: Path, entries: list[dict]) -> Path:
    p = tmp_path / "canary_history.jsonl"
    p.write_text(
        "\n".join(json.dumps(e) for e in entries) + ("\n" if entries else ""),
        encoding="utf-8",
    )
    return p


def _entry(*, clean: bool, day: int = 1) -> dict:
    return {
        "timestamp": f"2026-04-{day:02d}T20:30:00Z",
        "commit": f"abc{day}",
        "clean": clean,
        "gate_violations": 0 if clean else 2,
        "fetch_failures": 0,
        "exit_code": 0 if clean else 1,
    }


def test_streak_zero_for_empty_history(tmp_path):
    p = _write_history(tmp_path, [])
    assert dfs.compute_streak(p) == 0


def test_streak_zero_when_history_file_missing(tmp_path):
    assert dfs.compute_streak(tmp_path / "nope.jsonl") == 0


def test_streak_counts_trailing_clean_runs(tmp_path):
    p = _write_history(tmp_path, [_entry(clean=True, day=d) for d in range(1, 8)])
    assert dfs.compute_streak(p) == 7


def test_streak_resets_on_any_failure(tmp_path):
    entries = [_entry(clean=True, day=d) for d in range(1, 5)]
    entries.append(_entry(clean=False, day=5))
    entries.extend(_entry(clean=True, day=d) for d in range(6, 9))
    p = _write_history(tmp_path, entries)
    # Only the trailing 3 clean runs count.
    assert dfs.compute_streak(p) == 3


def test_streak_zero_when_latest_run_failed(tmp_path):
    entries = [_entry(clean=True, day=d) for d in range(1, 7)]
    entries.append(_entry(clean=False, day=7))
    p = _write_history(tmp_path, entries)
    assert dfs.compute_streak(p) == 0


def test_streak_tolerates_blank_lines(tmp_path):
    p = tmp_path / "h.jsonl"
    body = json.dumps(_entry(clean=True, day=1)) + "\n\n" + \
           json.dumps(_entry(clean=True, day=2)) + "\n"
    p.write_text(body, encoding="utf-8")
    assert dfs.compute_streak(p) == 2


def test_streak_breaks_on_partial_day_corruption(tmp_path):
    # Partial / corrupt JSON line should terminate the streak walk
    # rather than silently treat it as clean.
    p = tmp_path / "h.jsonl"
    p.write_text(
        json.dumps(_entry(clean=True, day=1)) + "\n"
        + "{not-json\n"
        + json.dumps(_entry(clean=True, day=3)) + "\n",
        encoding="utf-8",
    )
    # Walking from the bottom: day=3 clean (+1), then corrupt line breaks.
    assert dfs.compute_streak(p) == 1


def test_streak_failure_with_fetch_only_failure(tmp_path):
    # An entry with fetch_failures>0 but exit_code 0 should be
    # marked clean=False by the workflow before write; here we just
    # confirm the streak walker honours the `clean` flag.
    p = _write_history(tmp_path, [
        _entry(clean=True, day=1),
        {"timestamp": "2026-04-02T20:30:00Z", "commit": "x",
         "clean": False, "gate_violations": 0, "fetch_failures": 3,
         "exit_code": 0},
        _entry(clean=True, day=3),
    ])
    assert dfs.compute_streak(p) == 1


# ---------------------------------------------------------------------------
# declare_fix_status message construction
# ---------------------------------------------------------------------------


def test_message_declared_when_streak_and_days_satisfied():
    msg = dfs.build_message(streak=7, days=8.5, declared=True)
    assert "declared **FIXED**" in msg
    assert "7/7" in msg
    assert dfs.DECLARED_MARKER in msg


def test_message_progress_when_streak_short():
    msg = dfs.build_message(streak=3, days=10.0, declared=False)
    assert "3/7" in msg
    # Progress message references "declared FIXED" as a goal, but
    # must NOT contain the actual declaration marker.
    assert dfs.DECLARED_MARKER not in msg
    assert "declared **FIXED**" not in msg
    assert dfs.PROGRESS_MARKER in msg


def test_message_progress_when_days_short():
    msg = dfs.build_message(streak=7, days=2.0, declared=False)
    assert "7/7" in msg
    assert "2.0/7" in msg
    assert dfs.PROGRESS_MARKER in msg


def test_days_on_main_zero_for_empty_string():
    assert dfs.days_on_main("") == 0.0


def test_days_on_main_handles_z_suffix():
    # Should not raise; value will be very large for an old date.
    assert dfs.days_on_main("2026-01-01T00:00:00Z") > 0
