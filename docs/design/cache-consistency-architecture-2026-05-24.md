# Cache consistency architecture (Phase B.1, 2026-05-24)

**Companion to** `docs/diagnostics/phase-b-cache-paths-2026-05-24.md`
(Phase B.0 audit).
**Status:** in-memory drain hook landed; legacy call-site refactor
deferred.

---

## TL;DR

YieldIQ has 9 cache read paths. Pre-Phase-B.1, four of them
(`#3` in-mem raw dict, `#4` in-mem Pydantic, `#5` in-mem version-keyed
SEO, `#8` bulk valuation SELECT) bypassed the Day-94 manifest entirely.
A worker that warmed those tiers BEFORE a cohort applied kept serving
the pre-cohort payload for up to 24 hours.

Phase B.1 closes the in-memory drift window (tiers 3-5) by registering
a drain hook at module import time. Tier 8 stays as-is (bulk read,
search-only, not on the auth-vs-anon hot path). Tier 9 (edge cache)
is by definition outside the manifest's reach.

---

## The 9 paths after B.1

| # | Path | Manifest gate | In-mem drained on apply |
|---|------|---------------|--------------------------|
| 1 | `analysis_cache_service.get_cached`           | Yes (Day-94)  | n/a (DB tier) |
| 2 | `analysis_cache_service.get_cached_latest`    | No (by design) | n/a |
| 3 | `cache.get("analysis:{ticker}:raw")`          | No            | **Yes (B.1)** |
| 4 | `cache.get("analysis:{ticker}")`              | No            | **Yes (B.1)** |
| 5 | `cache.get("public:stock-summary:{ticker}", version_keyed=True)` | No | **Yes (B.1)** |
| 6 | `portfolio_aggregator → get_cached`           | Yes (via #1)  | n/a |
| 7 | `coverage_tier_service → get_cached`          | Yes (via #1)  | n/a |
| 8 | `get_valuation_bulk`                           | No            | n/a (DB tier, looser TTL) |
| 9 | Edge cache (Cloudflare/Railway)                | No            | TTL only |

---

## The drain hook (Phase B.1)

### Mechanism

`backend/services/cache_invalidation_manifest.py` exposes:

* `MANIFEST_APPLIED_HOOKS: list[Callable[[dict], None]]`
* `register_manifest_applied_hook(hook)`
* `notify_manifest_entry_applied(entry)` — manual fire
* `sweep_recent_entries(...)` — import-time sweep

At import the module:

1. Registers a default hook that calls
   `cache.delete_by_prefix("analysis:")` and
   `cache.delete_by_prefix("public:stock-summary:")`.
2. Sweeps every manifest entry whose `applied_at` is within
   `DRAIN_LOOKBACK_HOURS` (= 24 h, matching the longest in-memory
   TTL) and fires every hook for each.

`CacheService.delete_by_prefix` peels the `v{N}:` version-key prefix
in addition to literal-prefix matching, so version-keyed tier 5 and
non-version-keyed tiers 3/4 both drop in one call.

### Why module-import time

Each Railway worker is its own Python process with its own in-memory
cache. The manifest module is imported during app boot (every router
imports `analysis_cache_service`, which transitively imports the
manifest). So:

* Fresh worker on deploy → fresh in-memory cache → sweep is a no-op
  (cheap).
* Worker that survives a deploy AND was warmed before a recent
  cohort's `applied_at` → sweep at re-import drains the stale
  entries on first request to the new code.
* Cron / warmer / Celery worker that imports the manifest → same
  drain semantics for free.

### Limitations

* **Per-worker scope.** Each Railway worker has its OWN in-memory
  cache. The hook drains the local process only. Cross-process
  invalidation would require Postgres `LISTEN/NOTIFY` or Redis
  pub/sub; deferred until a concrete need.
* **Worst-case window.** If a worker survives a deploy AND was
  warmed before a cohort apply AND is never re-imported (long-lived
  request loop), the natural in-memory TTL (24 h tier 3/4, 1 h
  tier 5) is still the upper bound per worker.
* **Tier 8 untouched.** `get_valuation_bulk` is search/admin-only,
  not on the auth-vs-anon hot path. Its 168 h TTL is intentional
  for inline-list UX.
* **Tier 9 untouched.** Edge cache invalidation needs a deploy hook
  on Cloudflare/Railway, out of scope here.

---

## `get_canonical_payload` helper

```python
def get_canonical_payload(
    ticker: str,
    fields_needed: list | None = None,
    allow_stale: bool = False,
) -> dict | None:
    ...
```

* `allow_stale=False` (default) → `get_cached` (manifest gate).
* `allow_stale=True` → falls through to `get_cached_latest` on miss
  (sector aggregator's intentional bypass).
* `fields_needed` is forwarded so a scoped invalidation
  (`["scenarios.bear"]`) doesn't invalidate a caller that only reads
  `["fair_value"]`.

Existing call sites are NOT rewritten in B.1 — the in-memory drift
window (the actual auth-vs-anon bug) is closed by the drain hook,
not by the helper. The 15+ legacy `cache.get("analysis:...")` sites
will migrate to this helper opportunistically; until then they remain
correct because each worker now drains its `analysis:*` keys on every
recent manifest entry.

---

## Worked example: Day-109a banking cohort

Pre-B.1 timeline:

1. Worker A boots at 19:00, warms `analysis:HDFCBANK.NS:raw`
   (score=68, FV=782 from pre-cohort engine). Tier-1 in-mem.
2. Cohort PR merges 20:00 → manifest gains `v_day109a_banking_cohort`
   → Postgres `analysis_cache` row written with new payload (score=50,
   FV=1097).
3. Worker A handles a request at 20:30. Tier-0/1 hits the warmed
   in-mem entry → serves the OLD score=68. Postgres-tier manifest
   gate never consulted.
4. Anon request hits worker B at 20:30. Worker B has empty in-mem
   cache → falls through to Postgres → manifest gate accepts new row
   → serves new score=50.
5. Auth vs anon disagree for up to 24 h (worker A's in-mem TTL).

Post-B.1 timeline:

1. Worker A boots at 19:00, warms in-mem as above.
2. Cohort PR merges 20:00. Deploy restarts workers OR worker A's
   manifest module re-imports → `sweep_recent_entries` finds
   `v_day109a` (applied 20:00, within 24 h) → fires drain hook →
   `delete_by_prefix("analysis:")` clears worker A's warmed entry.
3. Next auth request on worker A: tier-0/1 miss → tier-2 hit on
   fresh row → score=50. Auth and anon agree within seconds.

The drain is cheap (a dict-key iteration) and happens at most once
per process per import — so the only "cost" is the recompute on the
next request, which would have happened anyway on natural TTL expiry.

---

## Day-113 manifest entry

Added to mark this deploy. Scope is intentionally narrow
(`fields = ["score", "verdict", "fair_value", "mos_pct"]`) so the
tier-2 Postgres rows are not invalidated wholesale; the drain hook
itself sweeps the in-memory prefixes regardless of `scope.fields`.
