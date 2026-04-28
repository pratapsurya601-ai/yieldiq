# Cache Layer Audit + Unification Proposal

**Date:** 2026-04-27
**Branch:** `wkt/fund-f-cache-audit`
**Trigger:** PR #138's `fair_value_source` field failed to surface on prod
despite Railway restart + CACHE_VERSION bump.

## TL;DR

YieldIQ has **three** independent cache surfaces:

1. **`backend.services.cache_service.cache`** — in-memory, per-worker.
   Tuple-stores `(value, expires_at, version)`. `get()` invalidates on
   `version != CACHE_VERSION`, BUT this only fires when a key is
   actually fetched. There is no global sweep on startup, and the
   pickled tuple still occupies memory until accessed. More importantly,
   the **storage key is NOT version-prefixed**, so any future migration
   to a shared backend (Redis, persistent KV) where keys are namespace-
   sensitive cannot rely on tuple introspection — a stale-version entry
   for `public:stock-summary:TCS.NS` would still be served if the
   external store does not enforce the embedded-version check.
2. **`backend.services.endpoint_cache_service`** — persistent (Postgres
   `endpoint_cache` table). Filters by `cache_version = :version` in
   the WHERE clause. Strictly version-keyed.
3. **`backend.services.analysis_cache_service`** — persistent
   `analysis_cache` table. Schema-versioned but content-versioned only
   at write time; read path filters by version.

The footgun PR #138 hit:

The public `/public/stock-summary/{ticker}` endpoint stores its rendered
summary under the key `public:stock-summary:{ticker}` via `cache.set()`.
Because the in-memory cache is per-worker and only does *lazy*
version-check on read, a Railway redeploy combined with stale workers
produced a window in which `_extract_analysis_summary(...)` payloads
that pre-dated PR #138 (no `fair_value_source` field) were re-served.
A CACHE_VERSION bump *should* have invalidated them on next read — but
because the public endpoint also short-circuits on `_cached_summary is
not None` *before* re-checking the underlying analysis cache, any
worker that had warmed the public summary key during the brief window
between deploy + version bump kept serving the v-stale rendering.

The fix: prefix the storage key itself with `v{CACHE_VERSION}:` for
caches that store derived analysis output. A version bump then makes
the old keys *unreachable* (different key namespace) rather than
relying on lazy invalidation.

## 1. Cache site catalogue

Locations searched: `backend/`. `dashboard/` and `frontend/` excluded
(those caches are user-session scoped via Streamlit / Next.js).

### 1.1 In-memory (`cache_service.cache`)

| # | File:line | Key shape | TTL | Stores | Honors CACHE_VERSION? |
|---|-----------|-----------|-----|--------|-----------------------|
| 1 | `routers/analysis.py:227,240,295` | `analysis:{ticker}` (+`:raw`) | 86400 | Full `AnalysisResponse` | Y (stored-version) |
| 2 | `routers/analysis.py:455,462` | `analysis:{ticker}` (+`:raw`) | 86400 | AnalysisResponse | Y (stored-version) |
| 3 | `routers/analysis.py:544,560` | `verdict:{ticker}` | 86400 | Verdict subset | Y |
| 4 | `routers/analysis.py:634` | `og:{ticker}` | 3600 | OG-card payload | Y |
| 5 | `routers/analysis.py:676,726` | `preview:{ticker}` | 3600 | Preview payload | Y |
| 6 | `routers/analysis.py:771,830` | `ai_summary:{ticker}` | `_AI_SUMMARY_CACHE_TTL_S` | LLM narrative | Y |
| 7 | `routers/analysis.py:912,916,1108,1110,1136` | per-endpoint ticker keys | 300-86400 | analysis variants | Y |
| 8 | `routers/analysis.py:1304,1478` | `screener:*` | 21600 | Screener result | Y |
| 9 | `routers/analysis.py:1513-1577` | `fvh:{ticker}` | 3600 | FairValueHistory | Y |
| 10 | `routers/analysis.py:1615,1644,1671,1699,1719,1733` | per-ticker | 86400 | History rows | Y |
| 11 | `routers/analysis.py:1848,1861` | `reverse_dcf:{ticker}:{wacc}:{terminal_g}:{years}` | 3600 | Reverse-DCF payload | Y (stored-version) |
| 12 | `routers/hex.py:206,211` | `hex:{ticker}` | `_CACHE_TTL` | HEX axes | Y |
| 13 | `routers/market.py:48,70,95,100,119` | `macro:*` | 60-86400 | Macro snapshot/AI summary | Y |
| 14 | `routers/prism.py:97,113,157,188,209,223` | `prism:*` | 3600-`_HISTORY_TTL` | Prism payloads | Y |
| 15 | `routers/public.py:359,418` | `public:recent-activity` | 300 | Activity list | Y |
| 16 | `routers/public.py:431,463` | `public:demo-cards` | 120 | Demo cards | Y |
| 17 | **`routers/public.py:501,638`** | **`public:stock-summary:{ticker}`** | **3600** | **Rendered SEO summary** | **Y (stored-version) — see footgun** |
| 18 | `routers/public.py:516,526,587` | `analysis:{ticker}` | 86400 | AnalysisResponse | Y |
| 19 | `routers/public.py:657,755` | `public:all-tickers` | 86400 | Sitemap list | Y |
| 20 | `routers/public.py:810,894` | `public:index-dashboard:*` | 900 | Index dashboard | Y |
| 21 | `routers/public.py:928,1021` | `public:compare:*` | 3600 | Comparison | Y |
| 22 | `routers/public.py:1038,1084` | `public:earnings-calendar` | 3600 | Calendar | Y |
| 23 | `routers/public.py:1184,1248` | `public:screens:*` | 7200 | Screen results | Y |
| 24 | `routers/public.py:1276,1354` | `public:dupont:*` | 86400 | Dupont | Y |
| 25 | `routers/public.py:1419,1434` | `public:news:*` | 3600 | News | Y |
| 26 | `routers/public.py:1448,1462` | `public:backtest:*` | 7200 | Backtest | Y |
| 27 | `routers/public.py:1491,1520` | `public:technicals:*` | 86400 | Technicals | Y |
| 28 | `routers/public.py:1540,1550` | `public:risk-stats:*` | 3600 | Risk stats | Y |
| 29 | `routers/public.py:1570,1587` | `public:price-history:*` | 86400 | Price history | Y |
| 30 | `routers/public.py:1623,1654` | `public:screener-query:*` | 3600 | Screener query | Y |
| 31 | `routers/public.py:1691,1922` | `public:top-tickers:*` | 300 | Top-tickers | Y |
| 32 | `routers/public.py:1960,1986` | `public:near-52w-lows` | 3600 | Lists | Y |
| 33 | `routers/public.py:2012,2090` | `public:lowest-pe` | 3600 | Lists | Y |
| 34 | `routers/public.py:2107,2161` | `public:financials:*` | 3600 | Financials | Y |
| 35 | `routers/public.py:2218,2284` | `public:ratios-history:*` | 3600 | Ratios | Y |
| 36 | `routers/public.py:2307,2367` | `public:peers:*` | 3600 | Peers | Y |
| 37 | `routers/public.py:2393,2508` | `public:peers-detail:*` | 1800 | Peer detail | Y |
| 38 | `routers/public.py:2613,2630,2639,2647` | `public:ipos*` | 3600 | IPO list | Y |
| 39 | `routers/public.py:2669,2715` | `public:segments:*` | 3600 | Segments | Y |
| 40 | `routers/public.py:2767,2821` | `public:dividends:*` | 3600 | Dividends | Y |
| 41 | `services/macro_service.py:33,39,43,49,88,91` | `macro:*` | 4h-7d | Macro | Y |
| 42 | `services/newsletter_service.py:27,49,69` | `newsletter:*` | varied | Newsletter sections | Y |
| 43 | `services/peers_service.py:197` | `analysis:{t}` (read-through) | n/a | (re-uses analysis) | Y |
| 44 | `services/prism_narration_service.py:73,97` | `prism_narration:*` | `_CACHE_TTL` | Prism narration | Y |
| 45 | `services/prism_service.py:531,549` | `prism:*` | `_CACHE_TTL` | Prism core | Y |
| 46 | `services/analysis/narrative.py:434,465` | `ai_summary:{ticker}` | varied | AI summary | Y |
| 47 | `main.py:625-662` | warmup keys | 86400 | Pre-warm | Y |

### 1.2 Postgres-backed (`endpoint_cache_service`)

| # | File | Key shape | TTL | Stores | Honors CACHE_VERSION? |
|---|------|-----------|-----|--------|-----------------------|
| 48 | `services/endpoint_cache_service.py:48-121` | `{endpoint}:{ticker}:{params}` | 24h default | Slow authed-endpoint payloads | Y (WHERE filter) |

### 1.3 Persistent analysis cache (`analysis_cache_service`)

| # | File | Key shape | TTL | Stores | Honors CACHE_VERSION? |
|---|------|-----------|-----|--------|-----------------------|
| 49 | `services/analysis_cache_service.py` | ticker | n/a (DB row) | Full AnalysisResponse | Y |

### 1.4 Operational / non-derived

| # | File:line | Purpose | TTL | Should version-key? |
|---|-----------|---------|-----|---------------------|
| 50 | `middleware/auth.py:149` (`_tier_cache`) | Per-user tier 60s lookup | 60s | NO — pure operational |

### Total cache sites audited: **50**

## 2. Architectural footgun

The in-memory `cache_service.cache` does an *implicit* version check at
read time (`if version != CACHE_VERSION: del`), which is correct in
isolation. But the storage key for the public stock-summary cache —
`public:stock-summary:{ticker}` — is *the same* before and after a
CACHE_VERSION bump. Three failure modes follow:

1. **Lazy invalidation only:** entries linger in memory until next
   `get()`. No proactive sweep on bump.
2. **Tuple introspection is non-portable:** if `cache_service` is later
   swapped for a Redis backend, the embedded `(value, exp, version)`
   tuple has to round-trip through pickle — meanwhile the *key* is
   ambiguous between versions, which creates collision risk.
3. **Render-layer caches are doubly stale:** the public endpoint caches
   `_extract_analysis_summary(analysis_cached)` (a v-specific
   *projection* of the analysis payload). Even when the underlying
   `analysis:{ticker}` is invalidated correctly, the rendered summary
   under `public:stock-summary:{ticker}` is shielded by its own TTL
   and re-served until `time.time() >= expires_at`.

PR #138's `fair_value_source` field made it onto fresh
`AnalysisResponse` objects but the projection cached under
`public:stock-summary:*` was a python `dict` snapshot (no schema
upgrade on cache hit). Bumping CACHE_VERSION killed the underlying
`analysis:*` entries on read but the `public:stock-summary:*` entries
expired only on TTL.

## 3. Unification proposal

**Rule of thumb**

* Caches that store **derived analysis output** (FV, MoS, ratios,
  scores, axes, summaries, projections) → MUST be **version-keyed**.
* Caches that store **transient operational state** (rate-limit
  counters, request idempotency, per-user 60s tier lookup) → MAY stay
  TTL-only.

**Mechanism**

Add a `version_keyed=True` parameter to `cache.get()` / `cache.set()`.
When set, the actual storage key is `f"v{CACHE_VERSION}:{key}"`. A
CACHE_VERSION bump then naturally retires the old keys: the new
generation reads/writes a new namespace. Old entries live out their
TTL in irrelevance and `cleanup()` reaps them.

Default value `version_keyed=False` preserves existing semantics.

**Migrations (this PR)**

| Site | Decision |
|------|----------|
| `public:stock-summary:{ticker}` | **migrate → version-keyed** (PR #138 footgun) |
| `reverse_dcf:{ticker}:...` | **migrate → version-keyed** (FV-derived) |
| `_tier_cache` (auth) | **leave TTL-only** (operational) |
| `macro:fii_dii_last` | **leave TTL-only** (operational fallback) |

The remaining ~46 sites continue to rely on the existing
stored-version tuple check. They are not migrated in this PR
because:

* They are all served by the same in-memory `CacheService`, where
  stored-version *does* invalidate on read. The footgun specifically
  bit `public:stock-summary:*` because it is the most-accessed public
  endpoint right after a deploy — the entries are warmed by edge
  prefetch within seconds, before workers see CACHE_VERSION change.
* A wholesale migration would be a separate PR with a far larger
  surface area to review.

Future PR: opt every analysis-derived cache site into `version_keyed=True`
once this wrapper has soaked. Tracker: the comment block in
`cache_service.py` lists which categories should migrate next.

## 4. Dependency graph (logical)

```
            ┌──────────────────────────┐
            │   AnalysisService.get_   │
            │   full_analysis(ticker)  │
            └──────────┬───────────────┘
                       │
                       ▼
            ┌──────────────────────────┐
            │   analysis_cache (PG)    │  ← persistent, version-keyed
            └──────────┬───────────────┘
                       │ on warm read
                       ▼
            ┌──────────────────────────┐
            │   cache (in-memory)      │  ← per-worker, stored-version
            │   key: analysis:{ticker} │
            └──────────┬───────────────┘
                       │
              ┌────────┴────────┬──────────────────┐
              ▼                 ▼                  ▼
   public:stock-summary   reverse_dcf:*       hex:{ticker}
   ⮕ projection cache     ⮕ params cache      ⮕ derived cache
   (now version-keyed)    (now version-keyed)
```

## 5. Test coverage added

`tests/test_cache_versioning.py`:

* `test_version_keyed_get_set_roundtrip` — happy path
* `test_version_keyed_invalidates_on_version_bump` — simulated bump
  invalidates new-style entries
* `test_ttl_only_unchanged_by_version_bump` — backward-compat:
  TTL-only entries persist across a bump (until TTL expires)
* `test_version_keyed_is_isolated_from_ttl_only` — same logical key
  under both flags does not collide
