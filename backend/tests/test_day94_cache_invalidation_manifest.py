"""Day-94 (2026-05-22): granular cache invalidation manifest.

Replaces the single global CACHE_VERSION integer as the read-path
validity gate. Key invariants this suite locks in:

  1. Wildcard ticker scope ("*") invalidates everything
  2. Listed ticker scope invalidates only those tickers
  3. Wildcard field scope ("*") invalidates regardless of fields_needed
  4. Listed field scope invalidates only when fields_needed overlaps
  5. Dotted prefix ("a.*") matches any "a.X" field
  6. Rows computed AFTER an invalidation are still valid
  7. Rows computed BEFORE an invalidation that applies are invalid
  8. The .NS / .BO suffix is stripped when matching ticker scope
  9. Bare and canonical ticker forms are equivalent
 10. fields_needed=None defaults to "everything" (safe failure mode)
 11. Missing computed_at returns invalid (safe failure mode)
 12. CACHE_MANIFEST_DISABLED env var bypasses the matcher entirely

Source-text guards on the integration into analysis_cache_service.
"""
from __future__ import annotations

import importlib
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _fresh_manifest_module():
    """Re-import the module so CACHE_MANIFEST_DISABLED env changes take
    effect for individual tests."""
    import backend.services.cache_invalidation_manifest as mod
    return importlib.reload(mod)


def _utc(year, month, day, hour=0, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


# ── Wildcard ticker + wildcard field ─────────────────────────


def test_global_wildcard_invalidates_old_rows():
    m = _fresh_manifest_module()
    test_manifest = [
        {
            "version_id": "v_test_global",
            "applied_at": _utc(2026, 5, 22, 12),
            "scope": {"tickers": "*", "fields": "*"},
            "rationale": "test",
        },
    ]
    row_old = _utc(2026, 5, 21, 8)  # before applied_at
    assert m.is_row_valid_per_manifest(
        "ANYTHING.NS", row_old, fields_needed=None,
        manifest=test_manifest,
    ) is False


def test_global_wildcard_accepts_newer_rows():
    m = _fresh_manifest_module()
    test_manifest = [
        {
            "version_id": "v_test_global",
            "applied_at": _utc(2026, 5, 22, 12),
            "scope": {"tickers": "*", "fields": "*"},
            "rationale": "test",
        },
    ]
    row_new = _utc(2026, 5, 23, 8)  # after applied_at
    assert m.is_row_valid_per_manifest(
        "ANYTHING.NS", row_new, fields_needed=None,
        manifest=test_manifest,
    ) is True


# ── Scoped ticker invalidation ───────────────────────────────


def test_scoped_invalidation_hits_listed_tickers():
    m = _fresh_manifest_module()
    test_manifest = [
        {
            "version_id": "v_test_utility",
            "applied_at": _utc(2026, 5, 22, 18),
            "scope": {"tickers": ["NTPC", "POWERGRID"], "fields": "*"},
            "rationale": "regulated utility bear floor",
        },
    ]
    row_old = _utc(2026, 5, 22, 12)
    assert m.is_row_valid_per_manifest(
        "NTPC.NS", row_old, manifest=test_manifest,
    ) is False
    assert m.is_row_valid_per_manifest(
        "POWERGRID.NS", row_old, manifest=test_manifest,
    ) is False


def test_scoped_invalidation_spares_other_tickers():
    """The key cost-saving invariant: a scoped invalidation must NOT
    invalidate cached rows for tickers outside the scope."""
    m = _fresh_manifest_module()
    test_manifest = [
        {
            "version_id": "v_test_utility",
            "applied_at": _utc(2026, 5, 22, 18),
            "scope": {"tickers": ["NTPC", "POWERGRID"], "fields": "*"},
            "rationale": "regulated utility bear floor",
        },
    ]
    row_old = _utc(2026, 5, 22, 12)
    # These should ALL stay valid despite being older than the entry
    for ticker in ("HDFCBANK.NS", "RELIANCE.NS", "TCS.NS", "ITC.NS"):
        assert m.is_row_valid_per_manifest(
            ticker, row_old, manifest=test_manifest,
        ) is True, f"{ticker} false-invalidated by scoped entry"


def test_bare_ticker_form_works_too():
    m = _fresh_manifest_module()
    test_manifest = [
        {
            "version_id": "v_test_bare",
            "applied_at": _utc(2026, 5, 22, 18),
            "scope": {"tickers": ["NTPC"], "fields": "*"},
            "rationale": "test",
        },
    ]
    row_old = _utc(2026, 5, 22, 12)
    # Both bare and canonical forms should match
    assert m.is_row_valid_per_manifest("NTPC", row_old, manifest=test_manifest) is False
    assert m.is_row_valid_per_manifest("NTPC.NS", row_old, manifest=test_manifest) is False
    assert m.is_row_valid_per_manifest("NTPC.BO", row_old, manifest=test_manifest) is False


# ── Field-level invalidation ─────────────────────────────────


def test_field_scoped_invalidation_only_matters_for_overlapping_fields():
    m = _fresh_manifest_module()
    test_manifest = [
        {
            "version_id": "v_test_bear_only",
            "applied_at": _utc(2026, 5, 22, 18),
            "scope": {
                "tickers": ["NTPC"],
                "fields": ["scenarios.bear"],
            },
            "rationale": "bear-only fix",
        },
    ]
    row_old = _utc(2026, 5, 22, 12)
    # Reading ONLY fair_value: this fix doesn't affect that field → valid
    assert m.is_row_valid_per_manifest(
        "NTPC", row_old,
        fields_needed=["fair_value"], manifest=test_manifest,
    ) is True
    # Reading scenarios.bear: affected → invalid
    assert m.is_row_valid_per_manifest(
        "NTPC", row_old,
        fields_needed=["scenarios.bear"], manifest=test_manifest,
    ) is False
    # Reading both: affected → invalid
    assert m.is_row_valid_per_manifest(
        "NTPC", row_old,
        fields_needed=["fair_value", "scenarios.bear"],
        manifest=test_manifest,
    ) is False


def test_dotted_prefix_matches_subpaths():
    m = _fresh_manifest_module()
    test_manifest = [
        {
            "version_id": "v_test_scenarios_all",
            "applied_at": _utc(2026, 5, 22, 18),
            "scope": {
                "tickers": ["NTPC"],
                "fields": ["scenarios.*"],
            },
            "rationale": "rebuild all scenarios",
        },
    ]
    row_old = _utc(2026, 5, 22, 12)
    for field in ("scenarios.bear", "scenarios.base", "scenarios.bull"):
        assert m.is_row_valid_per_manifest(
            "NTPC", row_old,
            fields_needed=[field], manifest=test_manifest,
        ) is False, f"{field} not invalidated by scenarios.*"
    # Unrelated field stays valid
    assert m.is_row_valid_per_manifest(
        "NTPC", row_old,
        fields_needed=["fair_value"], manifest=test_manifest,
    ) is True


def test_fields_needed_none_treats_as_all():
    """Defensive default: a caller that doesn't declare what fields
    it reads gets the worst-case treatment (invalidate if any entry
    applies to the ticker)."""
    m = _fresh_manifest_module()
    test_manifest = [
        {
            "version_id": "v_test_bear_only",
            "applied_at": _utc(2026, 5, 22, 18),
            "scope": {
                "tickers": ["NTPC"],
                "fields": ["scenarios.bear"],
            },
            "rationale": "bear-only fix",
        },
    ]
    row_old = _utc(2026, 5, 22, 12)
    # fields_needed=None → assumes caller reads everything → invalid
    assert m.is_row_valid_per_manifest(
        "NTPC", row_old, fields_needed=None, manifest=test_manifest,
    ) is False


# ── Edge cases ───────────────────────────────────────────────


def test_missing_computed_at_invalidates_safely():
    m = _fresh_manifest_module()
    assert m.is_row_valid_per_manifest("ANY", None) is False


def test_string_computed_at_is_parsed():
    m = _fresh_manifest_module()
    test_manifest = [
        {
            "version_id": "v_test",
            "applied_at": _utc(2026, 5, 22, 12),
            "scope": {"tickers": "*", "fields": "*"},
            "rationale": "test",
        },
    ]
    # ISO string after the entry → valid
    assert m.is_row_valid_per_manifest(
        "ITC.NS", "2026-05-23T08:00:00+00:00",
        manifest=test_manifest,
    ) is True
    # ISO string before the entry → invalid
    assert m.is_row_valid_per_manifest(
        "ITC.NS", "2026-05-21T08:00:00+00:00",
        manifest=test_manifest,
    ) is False


def test_naive_datetime_is_treated_as_utc():
    m = _fresh_manifest_module()
    test_manifest = [
        {
            "version_id": "v_test",
            "applied_at": _utc(2026, 5, 22, 12),
            "scope": {"tickers": "*", "fields": "*"},
            "rationale": "test",
        },
    ]
    naive_old = datetime(2026, 5, 21, 8)  # no tzinfo
    assert m.is_row_valid_per_manifest(
        "ITC", naive_old, manifest=test_manifest,
    ) is False


def test_multiple_entries_any_can_invalidate():
    """A row must be valid against EVERY applicable entry; ANY single
    failed match invalidates it."""
    m = _fresh_manifest_module()
    test_manifest = [
        {
            "version_id": "v_a",
            "applied_at": _utc(2026, 5, 20, 12),
            "scope": {"tickers": ["NTPC"], "fields": "*"},
            "rationale": "test a",
        },
        {
            "version_id": "v_b",
            "applied_at": _utc(2026, 5, 22, 12),
            "scope": {"tickers": ["TCS"], "fields": "*"},
            "rationale": "test b",
        },
    ]
    row_mid = _utc(2026, 5, 21, 8)  # between v_a and v_b
    # NTPC: v_a applies (entry < row), v_b doesn't (TCS scope) → valid
    assert m.is_row_valid_per_manifest("NTPC.NS", row_mid, manifest=test_manifest) is True
    # TCS: v_a doesn't (NTPC scope), v_b applies (row < v_b) → invalid
    assert m.is_row_valid_per_manifest("TCS.NS", row_mid, manifest=test_manifest) is False


# ── Panic switch ─────────────────────────────────────────────


def test_disabled_env_var_bypasses_manifest(monkeypatch):
    """CACHE_MANIFEST_DISABLED=1 makes the matcher always return True
    so legacy callers can fall back to strict cache_version equality."""
    monkeypatch.setenv("CACHE_MANIFEST_DISABLED", "1")
    m = _fresh_manifest_module()
    test_manifest = [
        {
            "version_id": "v_test",
            "applied_at": _utc(2026, 5, 22, 12),
            "scope": {"tickers": "*", "fields": "*"},
            "rationale": "test",
        },
    ]
    row_old = _utc(2026, 5, 21, 8)
    # Without disable: would be invalid. With disable: always valid.
    assert m.is_row_valid_per_manifest(
        "ITC.NS", row_old, manifest=test_manifest,
    ) is True
    # Reset for other tests
    monkeypatch.delenv("CACHE_MANIFEST_DISABLED", raising=False)
    _fresh_manifest_module()


# ── Summary helper ──────────────────────────────────────────


def test_summarise_manifest_counts_correctly():
    m = _fresh_manifest_module()
    test_manifest = [
        {
            "version_id": "v_a",
            "applied_at": _utc(2026, 5, 20, 12),
            "scope": {"tickers": "*", "fields": "*"},
            "rationale": "global",
        },
        {
            "version_id": "v_b",
            "applied_at": _utc(2026, 5, 22, 12),
            "scope": {"tickers": ["NTPC"], "fields": ["scenarios.bear"]},
            "rationale": "scoped",
        },
    ]
    s = m.summarise_manifest(manifest=test_manifest)
    assert s.total_entries == 2
    assert s.global_entries_count == 1
    assert s.scoped_entries_count == 1
    assert s.most_recent_entry_id == "v_b"  # newest applied_at


# ── Real manifest sanity ────────────────────────────────────


def test_real_manifest_has_init_anchor():
    m = _fresh_manifest_module()
    ids = [e.get("version_id") for e in m.MANIFEST]
    assert "v_init_2026_05_22" in ids
    init = next(e for e in m.MANIFEST if e["version_id"] == "v_init_2026_05_22")
    assert init["scope"]["tickers"] == "*"
    assert init["scope"]["fields"] == "*"


# ── Integration: analysis_cache_service wired correctly ─────


def test_analysis_cache_get_cached_calls_manifest():
    """Source-text guard that get_cached() invokes the manifest."""
    src = (
        ROOT / "backend" / "services" / "analysis_cache_service.py"
    ).read_text(encoding="utf-8")
    assert "is_row_valid_per_manifest" in src
    assert "from backend.services.cache_invalidation_manifest import" in src
    # Has the fallback to strict cache_version equality on manifest failure
    assert "manifest check failed" in src
    # New signature accepts fields_needed kwarg
    assert "fields_needed=None" in src


# ── v_244 scope-typo regression guards (2026-06-07) ─────────
#
# History: v_244_cagr_clamp_loosened_2026_05_29 originally shipped
# with scope.tickers = ["WIPRO", "*"]. The matcher treats a list as
# literal-membership ({"WIPRO", "*"}), so only WIPRO invalidated;
# the literal "*" element was effectively a hypothetical ticker
# named asterisk. Every other ticker affected by the engine's
# widened ±50%→±80% _sanitize_cagr clamp (PR #697) kept serving
# stale pre-2026-05-29 cache rows. The fix replaced the list with
# the bare-string wildcard "*". These tests lock in:
#
#  1. Bare-string "*" really does wildcard-match a non-WIPRO ticker.
#  2. The list-with-literal-"*" shape does NOT wildcard-match
#     (regression test — the exact bug we just fixed).
#  3. The real v_244 entry currently in MANIFEST is wildcard-scoped,
#     not the broken list form.


def test_v244_wildcard_string_matches_non_wipro_ticker():
    """Bare-string '*' invalidates AMBUJACEM (and every other ticker)."""
    m = _fresh_manifest_module()
    assert m._ticker_in_scope("AMBUJACEM", "*") is True
    assert m._ticker_in_scope("AMBUJACEM.NS", "*") is True
    assert m._ticker_in_scope("JSWSTEEL", "*") is True


def test_v244_list_with_literal_asterisk_does_not_wildcard():
    """Regression: ['WIPRO', '*'] is literal membership, NOT wildcard.

    This is the exact shape the v_244 entry had before the 2026-06-07
    typo fix. Locks the matcher's documented behaviour in so a future
    refactor cannot silently start treating '*' inside a list as a
    wildcard (which would mask manifest authoring mistakes).
    """
    m = _fresh_manifest_module()
    broken_scope = ["WIPRO", "*"]
    assert m._ticker_in_scope("WIPRO", broken_scope) is True
    assert m._ticker_in_scope("AMBUJACEM", broken_scope) is False
    assert m._ticker_in_scope("JSWSTEEL", broken_scope) is False
    assert m._ticker_in_scope("IOC.NS", broken_scope) is False


def test_v244_entry_in_real_manifest_is_wildcard_scoped():
    """The shipped v_244 entry must be bare-string '*' wildcard.

    If anyone re-introduces the ['WIPRO', '*'] form (or any other
    list shape that includes a literal '*' element) this test
    catches it before merge.
    """
    m = _fresh_manifest_module()
    v244 = next(
        (e for e in m.MANIFEST
         if e.get("version_id") == "v_244_cagr_clamp_loosened_2026_05_29"),
        None,
    )
    assert v244 is not None, "v_244 entry missing from manifest"
    assert v244["scope"]["tickers"] == "*", (
        "v_244 scope.tickers must be the bare-string wildcard '*'; "
        f"got {v244['scope']['tickers']!r}"
    )


def test_no_manifest_entry_has_list_with_literal_asterisk():
    """Lint-style guard: no entry should have ['X', '*', ...] shape.

    Any list containing a literal '*' is almost certainly a typo —
    the matcher will treat it as a literal-ticker named asterisk and
    silently fail to wildcard. If a genuine wildcard is intended, use
    the bare string '*' instead.
    """
    m = _fresh_manifest_module()
    offenders = []
    for entry in m.MANIFEST:
        scope = entry.get("scope") or {}
        tickers = scope.get("tickers")
        if isinstance(tickers, (list, tuple, set)) and "*" in tickers:
            offenders.append(entry.get("version_id"))
    assert not offenders, (
        "These manifest entries have a literal '*' inside a list, which "
        "the matcher treats as a literal ticker, not a wildcard. Replace "
        f"with bare-string '*': {offenders}"
    )
