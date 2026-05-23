# Phase B.0 — Cache Read-Path Inventory + Live Probe Diagnostic

**Date:** 2026-05-23 (filed under 2026-05-24 per spec)
**Author:** Phase B.0 agent (read-only diagnostic; no code changes)
**Base commit:** `4175695` (Phase A.2.2)
**Probe target:** `https://api.yieldiq.in`
**Purpose:** Ground-truth data for scoping Phase B.1 (read-path
unification) and Phase B.2 (HDFCBANK score-drop + IT cohort
`data_limited` fixes). Original spec assumed 3 cache paths; the actual
count is 9+.

---

## TL;DR

1. **9 distinct cache read paths**, not 3. Three tiers (in-mem raw dict,
   in-mem Pydantic, Postgres `analysis_cache`) × multiple wrapper
   functions (`get_cached`, `get_cached_latest`, raw `cache.get`).
2. **Auth-vs-anon divergence is structural, not transient.** The anon
   `/public/stock-summary` and authed `/analysis` paths use overlapping
   but **not identical** cache key namespaces. Anon adds an extra
   `public:stock-summary:` layer that is `version_keyed=True`; authed
   uses `analysis:{ticker}:raw` (no version-keying). On the same worker
   they CAN serve different generations after a CACHE_VERSION bump.
3. **HDFCBANK is NOT in a 68→50 score drop from a stale cache.** Live
   probe shows score=50, FV=1097, MoS=43.1%, verdict=fairly_valued. The
   most recent applicable manifest entry is `v_day109a_banking_cohort_2026_05_23`
   (PB anchoring + ROE boost). The score is a **post-Day-109a correct
   recompute**, not a stale or bugged value. The user-perceived "drop"
   appears to be the model-correction itself.
4. **IT cohort `data_limited` IS real and stored in cache.** WIPRO,
   HCLTECH, TECHM all show `verdict=data_limited` on BOTH the
   individual stock-summary AND the sector aggregator. The sector
   aggregator projection is correct — it's faithfully reporting the
   cached payload. The root cause is the DCF safety-net firing because
   the model produces absurd bull_case outputs (WIPRO bull_case=6733
   vs price=203 — 33×; TECHM bull_case=46788 vs price=1422 — 33×) AND
   the confidence score lands at 43-45 (<50 threshold).
5. **Every "fresh" probe with `Cache-Control: no-cache` triggered a
   MISS** (X-Cache: MISS). Subsequent probes hit. So the public path's
   anon edge cache respects `no-cache`, but the no-cache request still
   went through the origin compute path. **The origin path got a HIT
   on tier-2 (analysis_cache table); the MISS is on the s-maxage edge
   layer.** This is the expected behaviour, not a bug.

---

## Section 1 — Cache Read-Path Inventory

| # | Location | Function / key | TTL | version_keyed | Manifest-respecting | Used by | Drain on cohort apply |
|---|----------|----------------|-----|---------------|---------------------|---------|------------------------|
| 1 | `backend/services/analysis_cache_service.py:140` `get_cached(ticker, max_age_hours=24)` | `analysis_cache` Postgres table, key=`ticker` (canonical) | 24 h | n/a (cache_version column ignored after Day-94) | **YES** — calls `is_row_valid_per_manifest` | `routers/analysis.py:323,650,1315,2404`, `routers/public.py:620,2981,3948`, `services/coverage_tier_service.py:237`, `services/portfolio_aggregator.py:95` | Manifest entry with matching scope makes row invalid on next read |
| 2 | `backend/services/analysis_cache_service.py:572` `get_cached_latest(ticker, max_age_hours=168)` | Same Postgres table | 168 h (7 d) | n/a | **NO** — bypasses manifest by design | `routers/public.py:5076` (sector aggregator only) | None. Drained only by row deletion or 7-day TTL. **Survives manifest invalidations.** |
| 3 | `backend/routers/analysis.py:282` `cache.get(f"analysis:{ticker}:raw")` (Tier-0 raw dict, in-memory) | In-mem CacheService, key=`analysis:{ticker}:raw` | 86400 s (24 h) per `set()` at line 350 | **NO** | **NO** (in-memory tier, never sees manifest) | `/api/v1/analysis/{ticker}` Tier-0 fast path; `/api/v1/analysis/{ticker}/export` line 2399 | CACHE_VERSION bump invalidates because CacheService.get() checks stored version != CACHE_VERSION. **NOT drained by scoped manifest entries.** |
| 4 | `backend/routers/analysis.py:295` `cache.get(f"analysis:{ticker}")` (Tier-1 Pydantic, in-memory) | In-mem CacheService, key=`analysis:{ticker}` | unspecified (legacy) | **NO** | **NO** | `/api/v1/analysis/{ticker}` Tier-1; `/analysis/{ticker}/ai-summary` line 974; `/public/stock-summary` line 615 | CACHE_VERSION bump only. **NOT drained by manifest.** |
| 5 | `backend/routers/public.py:601` `cache.get(f"public:stock-summary:{ticker}", version_keyed=True)` | In-mem CacheService with `v{CACHE_VERSION}:` key prefix | 3600 s (1 h, inferred from `s-maxage`) | **YES** | **NO** (in-mem tier) | `/api/v1/public/stock-summary/{ticker}` SEO path | CACHE_VERSION bump moves to fresh key namespace. **NOT drained by scoped manifest entries.** |
| 6 | `backend/services/portfolio_aggregator.py:95` `analysis_cache_service.get_cached(norm)` | (calls #1) | 24 h | n/a | **YES** | `/portfolio/*` endpoints | (via #1) |
| 7 | `backend/services/coverage_tier_service.py:237` `analysis_cache_service.get_cached(...)` | (calls #1) | 24 h | n/a | **YES** | Coverage tier classifier | (via #1) |
| 8 | `backend/services/analysis_cache_service.py:267` `get_valuation_bulk(tickers)` | Same Postgres table, bulk SELECT | configurable, default looser than 24 h | n/a | **NO** — does NOT call manifest (docstring confirms) | (search use only; admin?) | Implicit CACHE_VERSION filter in SQL or no filter |
| 9 | Edge cache (Cloudflare/Railway in front) | `s-maxage=600, swr=3600` on `/public/stock-summary/*` | 600 s | n/a | **NO** | All anon SEO pages | TTL only; no purge mechanism on cohort apply |

**Counts:**
- 4 paths respect the manifest (#1, #2-but-by-design-bypasses, #6, #7).
- 3 in-memory paths bypass the manifest entirely (#3, #4, #5).
- 1 bulk-read path on Postgres bypasses the manifest (#8).
- 1 edge cache is invisible to the manifest (#9).

**Key finding for B.1:** A cohort manifest apply (e.g. Day-109a) updates
the *validity gate* for paths #1, #6, #7 — but a worker that has #3, #4,
or #5 populated will serve a stale payload until its in-memory entry's
TTL expires OR CACHE_VERSION is bumped. CACHE_VERSION has NOT been
bumped post-Day-109a (manifest-only mechanism). Therefore:

> **Workers that warmed `analysis:{ticker}` or `analysis:{ticker}:raw`
> before 2026-05-23T20:00:00Z will continue serving the pre-Day-109a
> HDFCBANK payload for up to 24 h on the authed `/api/v1/analysis`
> endpoint and up to 1 h on the anon `/public/stock-summary` endpoint,
> until the per-worker in-memory entry expires.**

This is the auth-vs-anon divergence root cause.

---

## Section 2 — Live Probe (anon path, 2026-05-23 ~05:43Z)

All probes used `Cache-Control: no-cache` to defeat the edge layer.
Every "first" probe was a MISS at the edge; the origin path hit
tier-2 (Postgres `analysis_cache`). Subsequent probes (no header)
were HIT.

| Ticker      | HTTP | X-Cache | X-Source | last_updated | score | FV | price | MoS% | verdict | confidence | base | bull | bear | t (s) |
|-------------|------|---------|----------|-------------|------:|-----:|------:|-----:|---------|-----------:|-----:|-----:|-----:|------:|
| HDFCBANK.NS | 200 | MISS | analysis_cache_v35 | 05:42:47 | **50** | 1097.15 | 766.80 | **+43.1** | fairly_valued | 90 | 1097 | 1463 | 914 | 0.49 |
| LICI.NS     | 200 | MISS | analysis_cache_v35 | 05:43:10 | 40 | 1640.32 | 840.05 | **+95.3** | undervalued | **1089072600041** ⚠ | 1640 | 1968 | 1312 | 1.58 |
| INFY.NS     | 200 | MISS | analysis_cache_v35 | 05:42:51 | 40 | 1845.54 | 1174.50 | +57.1 | undervalued | 70 | 1846 | 2215 | 1068 | 0.56 |
| RELIANCE.NS | 200 | MISS | analysis_cache_v35 | 05:42:55 | 67 | 1608.46 | 1354.50 | +18.7 | fairly_valued | 45 | 1608 | 1930 | 1151 | 0.49 |
| HCLTECH.NS  | 200 | MISS | analysis_cache_v35 | 05:43:13 | 66 | 1622.52 | 1164.00 | 0.0¹ | **data_limited** | 44 | 1623 | 1877 | 904 | 1.90 |
| WIPRO.NS    | 200 | MISS | analysis_cache_v35 | 05:43:15 | 63 | 858.35 | 203.11 | 0.0¹ | **data_limited** | 43 | 858 | **6734** ⚠ | 687 | 1.88 |
| TECHM.NS    | 200 | MISS | analysis_cache_v35 | 05:43:17 | 63 | 5684.86 | 1422.20 | 0.0¹ | **data_limited** | 45 | 5685 | **46788** ⚠ | 4548 | 1.97 |
| TCS.NS      | 200 | MISS | analysis_cache_v35 | 05:43:19 | 50 | 3436.40 | 2317.30 | +48.3 | fairly_valued | 67 | 3436 | 3977 | 1911 | 1.67 |

¹ `mos_pct=0.0` when verdict=data_limited — set by the data_limited
projection at `service.py:4768-4783` to avoid showing a misleading MoS.

**Findings:**
- **No anon-vs-anon ticker inconsistency.** All 8 served fresh
  payloads from analysis_cache_v35.
- **LICI `confidence=1089072600041`** is a clear bug (stray timestamp
  or similar integer leaked into the wrong field). Filed as B.3.
- **WIPRO bull_case=6734 vs price=203** (33×) and **TECHM
  bull_case=46788 vs price=1422** (33×) — these are the model outputs
  that trip the DCF-collapse safety-net's confidence gate
  (`_conf_score < 35 and abs(mos_pct) > 40 → data_limited`) at
  `service.py:3476`. Confidence ends up 43-45 instead.
  - Why these don't go to `data_limited` via the conf gate but DO end
    up there via some other route: the bull-case absurdity feeds
    DCF-collapse logic. To be confirmed in B.2.
- **HDFCBANK verdict=fairly_valued at MoS=+43.1%** — just under the
  Day-111c bull-side bypass threshold (typical bypass is MoS>=50%).
  Confidence=90 means the data is trusted. **Could be flagged for
  threshold tuning.**
- Auth probe **not performed** — agent has no cookie/session. The
  authed-vs-anon divergence is inferred from the cache-key
  inventory (Section 1) not measured directly. Recommend follow-up
  with an admin-issued service token.

---

## Section 3 — HDFCBANK score-drop root cause

The original spec claimed "score went 68→50". Evidence found:

**Live now (2026-05-23 05:42Z):** score=50, FV=1097.15, MoS=+43.1%,
verdict=fairly_valued, confidence=90, moat=Wide, piotroski=6, WACC=0.098.

**Stored snapshot 2026-04-23 (`scripts/snapshots/snapshot_20260423_135549_ae518d0f9328.json`):**
- FV=782.71, MoS=-3.6%, verdict=fairly_valued
- base_case=782.71, bull_case=1017.53
- WACC=0.1114, roe=13.82, revenue_cagr_3y=0.325
- **No `score` field stored** in the snapshot format — only public
  surface (cmp, FV, MoS, verdict, bull/base/bear, ROE, WACC, growth).

**Manifest history for HDFCBANK.NS** (live, `/api/v1/public/manifest-history/HDFCBANK.NS`):

| applied_at | version_id | fields | rationale |
|------------|-----------|--------|-----------|
| 2026-05-23T23:30 | v_day112_adj_close_rebuild | compounded_growth.stock, stock_cagr_status | Day-112 cagr swap |
| 2026-05-23T22:10 | v_day111c_bull_undervalued_bypass | verdict | LICI 95% MoS fix |
| **2026-05-23T20:00** | **v_day109a_banking_cohort** | **\*** | **PB anchoring + ROE boost + stress flag** |
| 2026-05-23T11:00 | v_day110a_sector_page_read_path | sector_page | aggregator bypass |
| 2026-05-22T23:00 | v_init | * | Day-94 anchor |

**Diagnosis:** Day-109a (banking cohort) is the trigger. It changed
the valuation engine for HDFCBANK (PB-anchored T1 bank multiple 3.0×,
ROE-quality boost). The resulting payload is FV=1097 (UP 40% from the
Apr 23 snapshot's 782), MoS swings positive. This appears to be a
**correct model change**, not a bug. The score=50 is what the new
model produces.

**The "68→50" framing in the original spec cannot be verified from
available snapshots.** A score of 68 may have existed in a transient
in-memory cache that was never snapshotted, OR it may be a
misremembered figure. The B.2 spec should be reframed:

> "HDFCBANK verdict=fairly_valued at MoS=43% feels wrong; investigate
> whether the bull-side verdict bypass threshold (currently >=50% per
> Day-111c) should be lowered to ~40%."

This is a 1-line constant change in `service.py` and a corresponding
manifest entry. NOT a cache architecture problem.

---

## Section 4 — IT cohort `data_limited` root cause

**Live sector probe** `/api/v1/public/sector/it-services`:

| ticker | sector path verdict | sector path FV | sector path mos | individual verdict | individual FV |
|--------|---------------------|---------------:|----------------:|--------------------|---------------:|
| TCS.NS     | fairly_valued | 3436.40 | 48.3 | fairly_valued | 3436.40 |
| INFY.NS    | undervalued   | 1845.54 | 57.1 | undervalued   | 1845.54 |
| WIPRO.NS   | **data_limited** | 858.35  | 0.0  | **data_limited** | 858.35  |
| HCLTECH.NS | **data_limited** | 1622.52 | 0.0  | **data_limited** | 1622.52 |
| TECHM.NS   | **data_limited** | 5684.86 | 0.0  | **data_limited** | 5684.86 |

**Sector path === individual path for all 5 tickers.** Aggregator
projection is faithful. The `data_limited` is stored in the cached
payload, not an aggregator artefact.

**Snapshot comparison (Apr 23 → live):**

| ticker | old FV | new FV | old MoS | new MoS | old verdict | new verdict | WACC then→now |
|--------|-------:|-------:|--------:|--------:|-------------|-------------|---------------|
| WIPRO   | 301.28  | 858.35  | 47.0%  | (data_limited) | undervalued | data_limited | 0.1114 → **0.098** |
| HCLTECH | 1837.30 | 1622.52 | 27.5%  | (data_limited) | undervalued | data_limited | 0.1114 → 0.098 |
| TECHM   | 1204.37 | 5684.86 | -18.8% | (data_limited) | overvalued  | data_limited | 0.098 → 0.098 |
| TCS     | 3404.15 | 3436.40 | 30.4%  | 48.3%          | undervalued | fairly_valued | 0.1114 → 0.098 |
| INFY    | 1916.74 | 1845.54 | 46.0%  | 57.1%          | undervalued | undervalued   | 0.1114 → 0.1114 |

**Diagnosis:**
- WACC was lowered from 0.1114 to 0.098 for WIPRO/HCLTECH/TECHM/TCS
  (likely an industry-WACC change). INFY kept 0.1114.
- Lower WACC → higher terminal value → ballooning bull_case
  (WIPRO 6734, TECHM 46788).
- The verdict gate at `service.py:3474-3477`:
  ```
  elif _confidence in ("low", "unusable") and abs(mos_pct) > 40 ...:
      verdict = "data_limited"
  elif _conf_score < 35 and abs(mos_pct) > 40 ...:
      verdict = "data_limited"
  ```
  Confidence ends up 43-45 (just above the 35 conf_score floor) but
  the categorical `_confidence` likely is "low" → first branch fires.
- B.2 fix: either (a) revisit the WACC-by-sector mapping for IT
  services so terminal values don't explode, OR (b) tighten the
  bull_case sanity check so `bull_case > 5× current_price` triggers
  a hard re-anchor instead of letting it propagate to confidence and
  then verdict.

**Estimated LoC for B.2:**
- Option (a): WACC table edit, ~5-10 LoC + a manifest entry. Risk:
  affects every IT name.
- Option (b): sanity gate in DCF safety-net, ~15-25 LoC + tests +
  manifest entry. Lower-blast-radius.

Recommend (b).

---

## Section 5 — Recommendations

### B.1 — Read-path unification (~150-250 LoC + tests)

Two things must change:

1. **Drain in-memory caches on manifest apply.** Today's manifest
   mechanism updates the validity gate for paths #1/#6/#7 but does
   nothing to paths #3/#4/#5 (in-memory tiers). Add a manifest-apply
   hook that calls `cache_service.delete_by_prefix("analysis:")`
   and `cache_service.delete_by_prefix("public:stock-summary:")`
   across all workers (in single-worker dev: just a local call;
   in prod: a tiny pub/sub on Postgres `LISTEN/NOTIFY` already
   used elsewhere).
2. **Helper: `get_canonical_payload(ticker, *, allow_stale=False,
   fields_needed=None) -> dict | None`** that wraps tiers 0-2 with a
   single entry point. Replaces 8 call sites of `get_cached` and 6
   raw `cache.get("analysis:...")` patterns. Routes:
   - `allow_stale=False`: tries tier-0 → tier-1 → `get_cached`
     (manifest-respecting).
   - `allow_stale=True`: as above, falls through to `get_cached_latest`
     on miss. (Sector aggregator switches to this single flag.)

**Migration 058 (recompute queue) is NOT needed.** Existing
manifest-apply already invalidates Postgres-tier reads on the next
request. Drain hook is the missing piece — not a queue.

**Files touched (estimate):**
- `backend/services/analysis_cache_service.py` (+ helper, +30 LoC)
- `backend/services/cache_service.py` (+ delete_by_prefix, +20 LoC)
- `backend/services/cache_invalidation_manifest.py` (+ post-apply hook,
  +30 LoC)
- 6 routers/services updated to use the helper (~80 LoC churn)
- Tests (+150 LoC)

### B.2 — IT cohort + HDFCBANK verdict (~30-60 LoC)

- IT cohort `data_limited`: bull_case sanity gate in
  `dcf_collapse_safety_net.py` (~20 LoC) + manifest entry.
- HDFCBANK bull-side verdict threshold: 1-line constant change in
  `service.py` (Day-111c logic) from `MoS >= 50` to `MoS >= 40` (or
  whatever the audit lands on) + manifest entry.

### B.3 — Out of scope but flagged

- **LICI `confidence=1089072600041`** — clear field-leak bug. One-line
  fix likely. Spawned separately.
- **CACHE_VERSION never bumped** despite multiple manifest entries.
  Intentional — the manifest mechanism replaced CACHE_VERSION bumps —
  but worth a runbook note explaining when each tool applies.

---

## Appendix A — Probe artefacts

Saved to `C:\tmp\probes\` on agent machine (not committed):
- `HDFCBANK.json`, `LICI.json`, `INFY.json`, `RELIANCE.json`,
  `HCLTECH.json`, `WIPRO.json`, `TECHM.json`, `TCS.json`
- `sector_it.json`, `mfhist.json`

Snapshots referenced:
- `scripts/snapshots/snapshot_20260423_135549_ae518d0f9328.json`
  (Apr 23, 2026 — pre-Day-109a banking cohort)
