"""Day-95b (2026-05-22): production proof that the Day-94 manifest
scopes invalidation correctly.

Context: Day-94 (2026-05-22) shipped the granular cache invalidation
manifest, replacing global CACHE_VERSION bumps with scoped entries.
Day-95 was the first production proof — it appended a manifest entry
for 17 metals/mining sector tickers (HINDZINC + 16 others).

Pre-Day-94 this would have invalidated all ~2,400 cached rows.
Post-Day-94 it should invalidate only those 17.

This suite locks that invariant in against the REAL production
MANIFEST (not a synthetic one). It constructs ~30 synthetic
analysis_cache rows — a mix of metals tickers + non-metals — feeds
them into ``is_row_valid_per_manifest`` one by one, and asserts:

  * Every metals row predating the Day-95 entry → invalid (miss)
  * Every non-metals row predating the Day-95 entry → valid (hit)
  * Every row computed AFTER the Day-95 entry's applied_at → valid

The same logic that powers the read-path gate and the new
``/admin/cache-manifest-impact`` diagnostic endpoint. If this test
ever fails, the manifest has stopped scoping correctly and we are
back to global-wipe behavior.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# Mirror of the production Day-95 metals/mining cohort. Kept inline so
# the test is self-documenting: if someone changes the manifest entry,
# this list must change in lockstep and the diff is obvious.
DAY95_METALS_TICKERS = [
    "HINDZINC", "HINDCOPPER", "HINDALCO", "VEDL", "NATIONALUM",
    "TATASTEEL", "JSWSTEEL", "JINDALSTEL", "SAIL", "NMDC",
    "MOIL", "GMDCLTD", "COALINDIA", "WELCORP", "RATNAMANI",
    "APLAPOLLO", "JINDALSAW",
]

# Non-metals representatives spanning banking, IT, pharma, FMCG,
# auto, utilities, telecom — the sectors the Day-95 entry must NOT
# touch. 13 names so the total fixture is ~30 rows.
NON_METALS_TICKERS = [
    "HDFCBANK", "ICICIBANK", "SBIN",
    "TCS", "INFY", "WIPRO",
    "SUNPHARMA", "CIPLA",
    "HINDUNILVR", "ITC",
    "MARUTI", "NTPC", "BHARTIARTL",
]


def _utc(year, month, day, hour=0, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def _load_production_manifest():
    """Return the live MANIFEST list from the services module.

    Imported lazily so a parse-time failure in the module surfaces as
    a real test failure, not a collection error.
    """
    from backend.services.cache_invalidation_manifest import MANIFEST
    return MANIFEST


def _find_entry(manifest, version_id):
    for entry in manifest:
        if entry.get("version_id") == version_id:
            return entry
    return None


# ── Manifest shape guards ─────────────────────────────────────────


def test_day95_metals_entry_is_present_and_scoped():
    """The Day-95 metals entry must exist in MANIFEST and must list
    exactly the 17 known tickers — no more, no less. Catches accidental
    edits that would change production invalidation behavior.
    """
    manifest = _load_production_manifest()
    entry = _find_entry(manifest, "v_day95_metals_sector_pins")
    assert entry is not None, "Day-95 metals entry missing from MANIFEST"
    scope_tickers = entry["scope"]["tickers"]
    assert isinstance(scope_tickers, list), "scope.tickers must be a list"
    assert set(scope_tickers) == set(DAY95_METALS_TICKERS), (
        f"Day-95 metals cohort drift: expected {sorted(DAY95_METALS_TICKERS)}, "
        f"got {sorted(scope_tickers)}"
    )
    assert len(scope_tickers) == 17, (
        f"Day-95 metals cohort size changed: got {len(scope_tickers)}"
    )


# ── End-to-end matcher proof on synthetic cache rows ──────────────


def test_day95_metals_entry_invalidates_only_metals_rows():
    """Construct ~30 synthetic cache rows all computed BEFORE the
    Day-95 entry's applied_at, run them through the matcher against
    a one-entry manifest containing ONLY the production Day-95 entry,
    and verify scoping.

    Why a one-entry manifest: the production MANIFEST also contains
    the ``v_init_2026_05_22`` global-wildcard anchor (applied 23:00
    UTC on the same calendar day). If we ran the full manifest, the
    anchor would invalidate every row alongside the Day-95 entry and
    we couldn't isolate Day-95's scoping behavior. We pull the live
    Day-95 entry dict straight out of production MANIFEST so we're
    still testing the real scope.tickers list, just without the
    confounding anchor.

    Expected outcome:
      * All 17 metals rows → invalid (Day-95 entry matches)
      * All 13 non-metals rows → valid (Day-95 entry's scope excludes
        them — exactly the Day-94 promise)
    """
    from backend.services.cache_invalidation_manifest import (
        is_row_valid_per_manifest,
    )

    full_manifest = _load_production_manifest()
    metals = _find_entry(full_manifest, "v_day95_metals_sector_pins")
    assert metals is not None
    # One-entry manifest containing only the production Day-95 entry.
    iso_manifest = [metals]

    # Row computed one hour BEFORE the Day-95 entry's applied_at, so
    # the entry fires for every metals ticker in scope.
    row_before = metals["applied_at"] - timedelta(hours=1)

    invalidated = []
    served = []
    for ticker in DAY95_METALS_TICKERS + NON_METALS_TICKERS:
        valid = is_row_valid_per_manifest(
            ticker=ticker,
            computed_at=row_before,
            fields_needed=None,
            manifest=iso_manifest,
        )
        if valid:
            served.append(ticker)
        else:
            invalidated.append(ticker)

    # The 17 metals tickers must all be invalidated by the Day-95 entry.
    assert set(invalidated) == set(DAY95_METALS_TICKERS), (
        f"Day-95 scoping drift. Expected exactly the metals cohort to be "
        f"invalidated. Unexpectedly invalidated: "
        f"{sorted(set(invalidated) - set(DAY95_METALS_TICKERS))}. "
        f"Unexpectedly served: "
        f"{sorted(set(DAY95_METALS_TICKERS) - set(invalidated))}."
    )
    # The 13 non-metals tickers must all be served (no applicable entry).
    assert set(served) == set(NON_METALS_TICKERS), (
        f"Non-metals tickers should be served as valid cache hits. "
        f"Mismatch: served={sorted(served)}, "
        f"expected={sorted(NON_METALS_TICKERS)}"
    )
    # Quantitative invariant: 17 invalidated, 13 served, 30 total.
    assert len(invalidated) == 17
    assert len(served) == 13


def test_day95_metals_entry_accepts_canonical_ns_suffix():
    """The metals scope is stored as bare tickers (no .NS), but the
    read path passes canonical .NS-suffixed forms. Suffix stripping
    must keep the scoping correct.
    """
    from backend.services.cache_invalidation_manifest import (
        is_row_valid_per_manifest,
    )

    full_manifest = _load_production_manifest()
    metals = _find_entry(full_manifest, "v_day95_metals_sector_pins")
    iso_manifest = [metals]
    row_before = metals["applied_at"] - timedelta(hours=1)

    for bare in DAY95_METALS_TICKERS:
        canonical = f"{bare}.NS"
        assert is_row_valid_per_manifest(
            ticker=canonical,
            computed_at=row_before,
            fields_needed=None,
            manifest=iso_manifest,
        ) is False, f"{canonical} should be invalidated by Day-95 entry"


def test_day95_does_not_invalidate_rows_computed_after_it():
    """A row computed AFTER the Day-95 entry's applied_at must be
    served — the fix is already baked into that row.
    """
    from backend.services.cache_invalidation_manifest import (
        is_row_valid_per_manifest,
    )

    manifest = _load_production_manifest()
    # After the LATEST entry in the manifest → no applicable
    # invalidation for any ticker. (The original draft hard-coded
    # max(metals, v_init); that bit-rotted as later cohort entries
    # such as Day-107c added MARUTI/etc. to scope. Always pick the
    # true tail so the invariant survives future additions.)
    row_after_all = max(e["applied_at"] for e in manifest) + timedelta(hours=1)

    for ticker in DAY95_METALS_TICKERS + NON_METALS_TICKERS:
        assert is_row_valid_per_manifest(
            ticker=ticker,
            computed_at=row_after_all,
            fields_needed=None,
            manifest=manifest,
        ) is True, f"{ticker} computed post-fix should be served as valid"


# ── Headline scoping metric ───────────────────────────────────────


def test_day95_scoping_ratio_is_better_than_global_wipe():
    """The headline Day-94 promise: a scoped entry must invalidate
    dramatically fewer rows than a global wipe.

    With a representative 30-row fixture, the Day-95 entry should hit
    17 / 30 = 56.7% — but that's an artifact of the metals-heavy
    fixture. In production the same entry against ~2,400 rows is
    17 / 2,400 = 0.7%. What we lock in here is the structural fact:
    invalidation count == cohort size, NOT total row count.
    """
    from backend.services.cache_invalidation_manifest import (
        is_row_valid_per_manifest,
    )

    full_manifest = _load_production_manifest()
    metals = _find_entry(full_manifest, "v_day95_metals_sector_pins")
    iso_manifest = [metals]
    row_before = metals["applied_at"] - timedelta(hours=1)

    # Scale up the non-metals side to simulate a more realistic ratio.
    big_fixture = list(DAY95_METALS_TICKERS) + (NON_METALS_TICKERS * 20)
    invalidated_count = sum(
        1 for t in big_fixture
        if not is_row_valid_per_manifest(
            ticker=t,
            computed_at=row_before,
            fields_needed=None,
            manifest=iso_manifest,
        )
    )
    total = len(big_fixture)
    # 17 metals + (13 non-metals * 20) = 277 total rows.
    # Pre-Day-94 a global bump would invalidate all 277.
    # Post-Day-94 only the 17 metals should be hit.
    assert invalidated_count == 17, (
        f"Expected scoped invalidation of exactly 17 rows out of {total}; "
        f"got {invalidated_count}. Manifest is no longer scoping correctly."
    )
    pct = invalidated_count / total * 100
    assert pct < 10.0, (
        f"Scoping ratio regressed: {pct:.1f}% of rows invalidated "
        f"(expected << global-wipe baseline of 100%)."
    )
