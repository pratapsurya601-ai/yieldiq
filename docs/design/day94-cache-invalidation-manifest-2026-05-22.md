# Day-94 — Granular Cache Invalidation Manifest

**Date**: 2026-05-22
**Trigger**: 21 CACHE_VERSION bumps in 12 hours caused real Railway
latency spikes (per `cache_service.py` header). Need an architectural
fix, not just discipline.

---

## The problem

Before Day-94:

- `CACHE_VERSION` is a single global integer in `cache_service.py`
- Bumping it invalidates EVERY cached row across EVERY ticker in
  `analysis_cache`
- 2,400 tickers × ~20s cold yfinance recompute = **~13 hours of
  compute per bump**
- The Day-25 warm-cache job runs top-500 in background but users
  hitting tickers 501-2400 wait for cold computes
- A 4-line bear-floor fix affecting 6 utility tickers costs the
  same as a 400-line engine rewrite

This is a cost-amplification design bug. Today's Railway memory
chart shows spikes that line up exactly with each CACHE_VERSION
bump.

---

## The fix

Replace the integer with a structured **invalidation manifest** —
an append-only list of entries declaring:

- WHICH version (a human-readable id like `v137_day95_xyz`)
- WHEN it was applied (UTC datetime)
- WHAT it affects (`scope.tickers` + `scope.fields`)
- WHY (free-text rationale)

Read path: a cached row is valid IFF its `computed_at` postdates
every manifest entry that applies to (this ticker, the fields the
caller is reading).

### Architecture

```
┌────────────────────────────────────────────────────────────────┐
│  Engineer ships an engine fix                                  │
│  └─ Appends ONE entry to MANIFEST in                           │
│     backend/services/cache_invalidation_manifest.py            │
│     {                                                          │
│       version_id: "v137_day95_xyz",                            │
│       applied_at: <now UTC>,                                   │
│       scope: {tickers: ["NTPC", ...], fields: ["scenarios.*"]},│
│       rationale: "fix bear scenario for utilities",            │
│     }                                                          │
└────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────────┐
│  Railway deploys                                               │
│  └─ Cached rows are NOT touched                                │
└────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────────┐
│  User hits /api/v1/public/stock-summary/NTPC.NS                │
│  └─ analysis_cache_service.get_cached("NTPC.NS")               │
│      ├─ SELECT payload, computed_at FROM analysis_cache        │
│      │  WHERE ticker = "NTPC.NS" ORDER BY computed_at DESC     │
│      │  → row exists, computed_at = yesterday                  │
│      └─ is_row_valid_per_manifest("NTPC.NS", computed_at):     │
│          ├─ Iterates MANIFEST                                  │
│          ├─ Finds v137_day95_xyz with applied_at = TODAY       │
│          ├─ NTPC matches scope.tickers ✓                       │
│          ├─ "scenarios.*" matches fields_needed ✓              │
│          ├─ applied_at > computed_at → INVALID                 │
│          └─ Returns False                                      │
│      └─ get_cached returns None → cache miss → recompute       │
└────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────────┐
│  User hits /api/v1/public/stock-summary/HDFCBANK.NS            │
│  └─ Same flow, but:                                            │
│      ├─ MANIFEST entry v137 has scope.tickers = [NTPC, ...]    │
│      ├─ HDFCBANK not in scope → entry doesn't apply            │
│      ├─ No other applicable entries → row VALID                │
│      └─ get_cached returns the cached payload → fast path      │
└────────────────────────────────────────────────────────────────┘
```

### Cost reduction

Estimated impact at current Railway tier:

| Bump scenario | Pre-Day-94 cold recomputes | Post-Day-94 |
|---|---|---|
| Day-92 (regulated utility bear floor) | 2,400 | 6 |
| Day-93 (metals/mining sector pins) | 2,400 | 17 |
| Day-84 (pharma quality cohort) | 2,400 | 13 |
| Day-66 (moat off-by-5 fix) | 2,400 | ~50 (score-band overlap) |
| Day-58 (price sanity gates) | 2,400 | 0 (no FV change) |

Average reduction: **~95%** of post-deploy cold recompute load.

---

## Implementation

### Files (this PR)

| File | Change |
|---|---|
| `backend/services/cache_invalidation_manifest.py` | NEW. Manifest + matcher + summary helper. |
| `backend/services/analysis_cache_service.py` | MODIFIED. `get_cached()` now uses the matcher; legacy strict-equality kept as fallback when manifest import fails. |
| `backend/routers/admin.py` | NEW endpoint. `/admin/cache-manifest` returns the full manifest + summary. |
| `backend/tests/test_day94_cache_invalidation_manifest.py` | NEW. 16 tests covering all matcher invariants. |
| `docs/design/day94-cache-invalidation-manifest-2026-05-22.md` | This file. |

### Migration

The first manifest entry is `v_init_2026_05_22` with global wildcard
scope. This forces a one-time wipe of every row predating the Day-94
deploy, then the manifest takes over from there.

**No backfill** of historical CACHE_VERSION bumps as manifest entries.
Reason: most of those bumps had global impact (we didn't track scope
at the time), so backfilling adds no precision. The v_init entry is
the clean break.

### Panic switch

Set `CACHE_MANIFEST_DISABLED=1` in Railway env to bypass the matcher.
`is_row_valid_per_manifest` returns True for everything; the legacy
strict `cache_version = :version` check (still in `get_cached` as
fallback) becomes the only gate. Use only if the manifest produces
obviously-wrong cache hits in prod.

### CACHE_VERSION integer — kept

The integer in `cache_service.py` is NOT removed. It's now
informational:
- Still written to every new `analysis_cache` row (the column exists
  and the writer still uses it)
- Still read by `/admin/health-stats` for the cache distribution
  panel
- Still the legacy fallback in `get_cached` if the manifest import
  fails

But for new bumps, do NOT increment the integer. Append a manifest
entry instead.

---

## Risk + rollback

**Risk: medium.** The matcher logic is well-tested (16 unit tests
covering wildcard, scoped, field-level, prefix, panic switch). The
real risk is:

1. **Field-name drift**: if engineers use field paths that don't
   match the actual payload (`scenarios.bear` vs
   `valuation.scenarios.bear`), the matcher passes them through. We
   chose to make `fields_needed=None` the safe default (assumes
   "all fields") so callers don't accidentally serve stale data.

2. **Forgotten entries**: an engineer ships a fix without adding a
   manifest entry → cached rows for affected tickers stay stale.
   Mitigation: code review + an `/admin/cache-manifest` check on PR
   describing what entry was added.

3. **Time-zone bugs**: all `applied_at` and `computed_at` should be
   UTC. The matcher coerces naive datetimes to UTC, but a bug there
   could cause off-by-hours invalidation.

**Rollback**: `CACHE_MANIFEST_DISABLED=1` in Railway env restores
strict cache_version equality immediately. No code revert needed.

---

## Future work (NOT in this PR)

- **Manifest GC**: as MANIFEST grows past ~200 entries, add a
  "compact" job that merges entries older than 90 days into a
  single "v_compact_<date>" with combined scope (or simply drops
  them, since by that point all rows older than 90 days are
  already TTL-expired in `analysis_cache`).
- **Migration helper**: a CLI script that takes a "bump description"
  and emits the right manifest dict. Reduces the chance of
  forgotten entries.
- **Frontend "stale data" indicator**: when a cached row IS served
  to a user, optionally surface "Last computed 4h ago" so the user
  knows the data freshness vs the most recent invalidation that
  applies.
