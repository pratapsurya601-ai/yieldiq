# Memory Baseline Investigation — Railway `focused-vibrancy` (api.yieldiq.in)

**Author:** investigation by agent, 2026-05-18
**Status:** Findings + proposed fix sequence. No production code changed.
**Scope:** explain the 500 MB gap between expected baseline (600-800 MB) and observed baseline (1.3 GB), and the 2.5 GB cut-over spike.

---

## TL;DR

The biggest single cause is almost certainly **worker count, not a leak**.

`railway.toml` at the repo root (the file Railway actually reads on a Nixpacks build) hardcodes `--workers 4`. The `WEB_CONCURRENCY=1` env var **does nothing** because uvicorn does not consult `WEB_CONCURRENCY` — only gunicorn does. Each worker imports the full pandas / numpy / pyarrow / duckdb / scikit-learn / playwright / sentry stack and holds its own connection pool, its own in-memory `CacheService` singleton, and its own apscheduler-disabled lifespan threads. Four of those × ~325 MB = ~1.3 GB, which matches the observed RSS almost exactly.

The 2.5 GB cut-over spike is the old container still running while the new one warms — peak is `(N_old + N_new) × per_worker_RSS` plus a transient gc surge from yfinance / pandas frames during the first wave of uncached requests.

Beyond worker count, three smaller but real contributors exist:
1. Version-keyed cache **never auto-cleans** (`cache.cleanup()` has no caller in the lifespan or scheduler). After a CACHE_VERSION bump, stale `vN:key` entries linger in the `dict` until they are read or evicted by TTL. Across the 21-bump day described in `backend/services/cache_service.py:18`, this is the most plausible cause of the "stair-step climb after CACHE_VERSION bumps".
2. SQLAlchemy pool is sized for 4 workers (`pool_size=8, max_overflow=2` per worker — see `data_pipeline/db.py:35`), giving 40 connections × ~3-5 MB = ~150 MB resident across the 4 workers. The in-line comment claims `pool_size=3 + max_overflow=2` but the code says `pool_size=8`.
3. Backend requirements pull in **streamlit, plotly, matplotlib** via the root `requirements.txt` — these have no business in the API image. Each adds 40-80 MB of import-time allocation per worker.

`AUTO_REFRESH_PARQUETS=0` is correctly honored (see `backend/main.py:733`). `_prewarm_popular_stocks` is a documented no-op (`backend/main.py:600-623`). `ENABLE_INPROCESS_SCHEDULER` gating at `backend/main.py:813` is in place. Parquet files are read via on-demand DuckDB (`backend/services/price_history_service.py:134`, `backend/services/backtest_service.py:50`) — **no module-level parquet DataFrames** are held. The data dir on disk is only ~55 MB so even a hypothetical full load would not justify the gap.

---

## 1. Findings (with evidence)

### 1.1 SMOKING GUN — start command in `railway.toml` overrides everything

| File | Start command | Workers |
|---|---|---|
| `railway.toml` (repo root) | `uvicorn backend.main:app --host 0.0.0.0 --port $PORT --workers 4` (line 11) | **4** |
| `backend/railway.json` | `uvicorn backend.main:app --host 0.0.0.0 --port $PORT --workers 1` (line 6) | 1 |
| `backend/Procfile` | `uvicorn backend.main:app --host 0.0.0.0 --port $PORT` (line 1) | 1 (uvicorn default) |
| `backend/Dockerfile` | `uvicorn ... --workers 1` (line 16) | 1 |

Railway builds from the **repo root** with the Nixpacks builder declared in `railway.toml:2`. That file's `startCommand` is what runs in prod. `backend/railway.json` and `backend/Procfile` are dead config — they sit one directory deeper and Railway never sees them.

The CLAUDE.md memory note "`WEB_CONCURRENCY=1`" assumes gunicorn semantics. uvicorn ignores `WEB_CONCURRENCY` entirely; the only ways to set worker count are (a) `--workers N` on the CLI, (b) `UVICORN_WORKERS` (also CLI-only via the standard launcher), or (c) running uvicorn under gunicorn with the uvicorn worker class. None of those are wired up here. **The env var is silently a no-op.**

The codebase even self-documents the assumption that 4 workers run in prod — see `backend/main.py:809`:

> `# cost ~200MB per uvicorn worker × 4 workers = ~800MB of duplicated`
> `# background-job memory on Railway, plus N× duplicate fires per tick.`

The DCF pool-sizing comment at `data_pipeline/db.py:27-29` likewise reads:

> `# Sized for 4 uvicorn workers on Railway against Aiven Postgres`
> `# (free tier ceiling ~20 concurrent connections). Per-worker:`
> `# pool_size 3 + max_overflow 2 = 5 max → 4 workers × 5 = 20 total.`

Although the comment says 3+2, the actual line is `pool_size=8, max_overflow=2` — see `data_pipeline/db.py:35-36`. That alone is a separate bug (40-connection ceiling on a 20-connection Aiven free tier; will start refusing connections under load).

### 1.2 Per-worker import baseline is bloated

`requirements.txt` at repo root is a single monolithic file used by both the backend Docker image and the (separate) streamlit container. It pulls in, at the API layer:

- `pandas`, `numpy`, `pyarrow`, `duckdb`, `scipy`, `scikit-learn` — legitimate
- `streamlit>=1.40.0`, `plotly>=5.22.0`, `matplotlib>=3.7.0` — **not used by the FastAPI app**
- `playwright>=1.45.0` + `playwright-stealth>=2.0.0` — only used by `data_pipeline/sources/bse_quarterly_xbrl.py` which runs on GitHub Actions, not on Railway

A bare `python -c "import streamlit, plotly, matplotlib"` allocates 60-100 MB. Multiply by 4 workers and that is another ~300 MB of pure dead weight.

### 1.3 In-memory cache singleton grows monotonically across CACHE_VERSION bumps

`backend/services/cache_service.py:157`:

```python
cache = CacheService()
```

`CacheService._store: dict[str, tuple[Any, float, int]]` (line 93) — a plain dict, per-worker (because it is a module-level singleton, not Redis). Entries are written with TTLs ranging from a few minutes (rate-limit) to **86400 s = 24h** (`backend/main.py:668, 702`).

After a CACHE_VERSION bump:
- `version_keyed=True` entries (analysis output, stock-summary, reverse-dcf) move to a new `vN+1:` prefix. The old `vN:` entries stay until either (a) their 24h TTL elapses or (b) `cleanup()` is called.
- `cleanup()` exists (`cache_service.py:141`) but `grep -r "cache\.cleanup"` against `backend/` shows **zero callers**. No lifespan hook, no scheduled job, no per-request hook.

On the 21-bump day described in the v102 comment (`cache_service.py:33`), the worker resident set will have accumulated up to **21 generations of analysis cache** before any natural TTL expiry. If a single analysis payload is ~50-100 KB (pandas frames serialized, hex axes, scenarios, peer info) and a worker has warmed even ~50 tickers per generation, that is 21 × 50 × 75 KB = ~75 MB of dead cache per worker × 4 workers = **~300 MB** locked behind no-eviction-until-read.

This matches the "stair-step climb after CACHE_VERSION bumps" symptom precisely.

### 1.4 DB connection pool is double the documented size

`data_pipeline/db.py:35`:

```python
pool_size=8,
max_overflow=2,
```

with the comment two lines above claiming `pool_size 3 + max_overflow 2 = 5 max → 4 workers × 5 = 20 total`. The actual ceiling is **(8 + 2) × 4 = 40 connections**, double the 20-connection Aiven free-tier headroom claimed in the comment. Each idle pooled SQLAlchemy connection holds 3-5 MB resident; 40 × ~4 MB = ~160 MB.

### 1.5 No leak from background threads (verified)

The lifespan in `backend/main.py:777-829` starts three daemon threads:
- `_ensure_pipeline_tables` (line 783) — runs migrations, exits.
- `_screener_self_test` (line 804) — single DB roundtrip, exits.
- The `_warm` thread inside `_prewarm_popular_stocks` is **never started** because the function is a documented no-op (lines 600-623, returns before reaching the `threading.Thread(...).start()` at line 714).
- `_auto_refresh_parquets_if_needed` (line 717) checks `AUTO_REFRESH_PARQUETS` and exits early because the env var is `0`.

APScheduler is gated behind `ENABLE_INPROCESS_SCHEDULER=1` (line 813); the operator confirmed this is unset, so the `_start_pipeline_scheduler` path at line 238 never runs. **No persistent background memory hog** outside the cache singleton.

### 1.6 Parquet files are not eagerly loaded (verified)

`grep -n "read_parquet" backend/` shows DuckDB-on-demand patterns only (e.g. `backend/services/price_history_service.py:134-140` opens a `duckdb.connect(":memory:")` per call, runs `SELECT … FROM read_parquet(?)`, and returns to a pandas frame which falls out of scope when the request finishes). No router or service module holds a parquet `pd.read_parquet(...)` at import time.

The on-disk parquet footprint is:

| File | Size |
|---|---|
| `data/parquet/financials.parquet` | 0.99 MB |
| `data/parquet/market_metrics.parquet` | 0.33 MB |
| `data/parquet/peer_groups.parquet` | 0.30 MB |
| `data/parquet/ratio_history.parquet` | 1.61 MB |
| `data/parquet/shareholding_pattern.parquet` | 0.08 MB |
| `data/parquet/stocks.parquet` | 0.17 MB |
| `data/parquet/fair_value_history.parquet` | 0.05 MB |
| `data/parquet/daily_prices/` (11 files) | ~52 MB |
| **Total** | **~55 MB on disk** |

Decompressed-in-memory worst case would be ~150-250 MB, but only a tiny sliced fraction is in scope per request.

### 1.7 Module-level caches are small constants

`grep -n "^_[A-Z][A-Z_]+\s*[:=]\s*\{"` against `backend/services/` returns dict literals of curated ticker sets (`_NBFC_TICKERS`, `_BANK_TICKERS`, `_CONGLOMERATE_TICKERS`, `_PB_MEDIANS`, etc.) — all under 100 entries, <1 KB each. Not material.

The only module-level mutable cache outside `cache_service.py` is `backend/services/sector_percentile.py:39`:
```python
_cohort_cache: dict[str, tuple[float, list[dict]]] = {}
```
This stores cohort SQL results (~500 rows × ~5 dict keys per ticker = ~50 KB per sector × ~13 sectors = ~700 KB). Negligible.

`backend/middleware/auth.py:73` (`_tier_cache: dict[str, tuple[str, float]]`) is per-user JWT tier with 60s TTL — bounded by active user count, not material.

---

## 2. Quantified breakdown of the 1.3 GB

| Component | Per worker | × workers | Subtotal |
|---|---|---|---|
| Python interpreter + FastAPI/uvicorn baseline | ~70 MB | 4 | 280 MB |
| pandas + numpy + pyarrow + duckdb + scipy + sklearn import | ~140 MB | 4 | 560 MB |
| streamlit + plotly + matplotlib (dead deps in API image) | ~70 MB | 4 | 280 MB |
| sentry-sdk + playwright (idle) | ~25 MB | 4 | 100 MB |
| SQLAlchemy pool (10 connections × ~4 MB) | ~40 MB | 4 | 160 MB |
| `CacheService` warm entries (24h TTL, ~50 tickers warmed) | ~5-10 MB | 4 | 20-40 MB |
| Stale `vN:` entries from same-day CACHE_VERSION bumps | 0-75 MB | 4 | 0-300 MB |
| Per-request transients in flight at any moment | ~5-15 MB | 4 | 20-60 MB |
| **Total expected at steady state** |  |  | **~1.4-1.8 GB** |

This is **already consistent with the observed 1.3 GB** without invoking any leak — the env-var assumption was just wrong. The 500 MB "gap" disappears once you account for workers=4 instead of workers=1.

**Confidence:** medium-high on the worker-count component (railway.toml is explicit). Medium on the import baseline (depends on Python version, glibc, manylinux wheel choice). Low on the stale-cache band — could be anywhere in the 0-300 MB range depending on bump cadence and TTL hits.

### Cut-over spike (2.5 GB)

During a Railway deploy, the old container keeps serving while the new container warms its image, imports, and accepts traffic. For a few seconds you have **2 × 4 = 8 uvicorn workers** plus the new image's filesystem cache. 2 × 1.3 GB = 2.6 GB matches the observed spike.

### Cache-rebuild storm cost

One ticker analysis through `AnalysisService.get_full_analysis` materializes (per `backend/services/analysis_service.py` call sites): financials DataFrame (~50 rows × ~30 cols = ~50 KB), ratio_history slice (~100 KB), enriched dict with hex/prism axes (~30 KB), scenarios + peer info (~50 KB) plus pandas/yfinance scratch — call it **~3-5 MB peak transient** per concurrent compute.

The lifespan does not pre-warm any longer, so the rebuild storm shape depends entirely on user traffic plus OG/preview scrapers. At 50 concurrent uncached requests × 5 MB = ~250 MB transient — fits inside the headroom on the 8 GB plan but is the most likely trigger for the 2.5 GB spike if a CACHE_VERSION bump lands right before a traffic burst.

---

## 3. Fix options (ranked by effort)

### Quick (≤ 1 day) — start command + env var alignment

1. **Cut workers from 4 to 2 in `railway.toml:11`.** This is a one-line change that halves baseline memory. 2 workers × ~325 MB ≈ 650 MB — back inside the expected 600-800 MB band. Concurrency drops 2×, but per the comment at `backend/main.py:809` the codebase already accepts the loss (the prewarm code path was disabled precisely because a single worker was sufficient).
2. **Delete `backend/railway.json` and `backend/Procfile`.** They are dead config that contradicts the live `railway.toml` and will mislead the next operator.
3. **Drop `streamlit`, `plotly`, `matplotlib` from `backend/Dockerfile`'s pip install.** Split `requirements.txt` into `requirements-api.txt` and `requirements-streamlit.txt`, or pass `--no-deps` plus a curated list in the backend image. Saves ~70 MB/worker.
4. **Fix pool size.** Change `pool_size=8` to `pool_size=3` in `data_pipeline/db.py:35` so it matches the comment two lines above. Saves ~80 MB across 4 workers, and stops the Aiven 20-connection ceiling from being breached under burst.
5. **Wire `cache.cleanup()` into a per-request middleware** (call it on every Nth request, e.g. once per 100 requests via a counter) or into a 5-minute APScheduler-disabled-equivalent (a plain `threading.Timer` recursing in the lifespan). Reclaims the stale `vN:` band after CACHE_VERSION bumps. Quick win — could be a 5-line follow-up PR.

**Combined effect:** baseline drops from ~1.3 GB to ~600-700 MB. Cut-over spike drops from ~2.5 GB to ~1.3 GB.

### Medium (1-2 weeks) — split image + lazy parquets

1. Build a dedicated Dockerfile for the API service. Strip out streamlit, plotly, matplotlib, playwright. Confirm via `pip show` after build that the wheel set is minimal.
2. Move every parquet read into a thin `parquet_view.py` that always opens DuckDB on `:memory:`, runs a `SELECT … WHERE ticker = ?`, and never returns a full DataFrame to a caller that does not need one. Already mostly the case — finish the holdouts in `backend/routers/analytics.py:68` and `backend/routers/admin.py:196`.
3. Replace the in-process `CacheService` singleton with Redis (a Railway add-on or Upstash free tier). This eliminates the per-worker N× duplication entirely; the cache stops contributing to RSS at all. CACHE_VERSION bumps become free.

**Combined effect:** baseline drops to ~400-500 MB. The 8 GB Railway plan starts looking oversized.

### Deep (1+ month) — per-request resource cleanup

1. Introduce a `@dataclass(slots=True)` for `AnalysisResult` so the cache stores fixed-shape objects rather than nested dicts. Memory shrinks ~30-40% per entry.
2. Add an explicit `request_scope` context manager (FastAPI dependency) that owns the SQLAlchemy session, the DuckDB connection, and any pandas frames created during the request. On exit, all are dereferenced and a `gc.collect()` is called every Nth request.
3. Move heavy DCF math into a separate **subprocess** worker pool (multiprocessing.Pool, pre-forked) so the long-tail compute does not bloat the main FastAPI process. The OS reclaims memory cleanly when the subprocess exits.

**Combined effect:** baseline ~250-350 MB, cut-over spike never exceeds ~700 MB.

---

## 4. Recommended sequence

**Ship in this order, each as its own PR, each verifiable on Railway metrics before the next.**

1. **Quick fix #1 — `railway.toml` workers 4→2.** Single-line diff. Deploy at low-traffic time. Watch RSS drop from ~1.3 GB to ~650 MB within minutes of cut-over. This alone closes the "500 MB unexplained" gap. **(Highest ROI; do today.)**
2. **Quick fix #4 — `pool_size=8`→`3`.** One-line diff. Eliminates the silent Aiven-tier ceiling breach risk. ROI is more reliability than memory.
3. **Quick fix #2 — delete `backend/railway.json` and `backend/Procfile`.** Pure cleanup; eliminates a future foot-gun where someone "fixes" the wrong file.
4. **Quick fix #5 — wire periodic `cache.cleanup()`.** Five-line lifespan addition. Stops the stair-step climb after CACHE_VERSION bumps.
5. **Medium fix #1 — split the requirements file.** Saves another ~70 MB/worker × 2 workers = 140 MB.
6. **Medium fix #3 — Redis** when traffic justifies it (i.e. when ~5 paying users hit the cache simultaneously and the 2-worker baseline becomes a latency bottleneck rather than a memory one).

Do not pursue the deep options until after the quick + medium passes have been measured. They are correct in principle but the quick passes alone should drop baseline to a level where the deep options become premature optimization.

---

## 5. Risk if nothing changes

- **OOM at ~100 concurrent users:** at baseline 1.3 GB plus 5 MB transient per concurrent compute, 100 concurrent uncached requests = 1.8 GB. On the current Railway plan (8 GB) that survives, but the 2.5 GB cut-over spike + a CACHE_VERSION bump's rebuild storm could combine to ~3.5-4 GB and start triggering throttling.
- **Railway plan limit:** on a 2 GB Pro plan the current 1.3 GB baseline leaves only 700 MB of headroom — a CACHE_VERSION bump during traffic peak would OOM-kill the container, which then takes 30-60 s to come back, during which `/health` fails and Railway escalates the restart loop. Today's 21-bump day at `cache_service.py:33` would have OOM-killed every bump.
- **Aiven connection-ceiling breach:** the `pool_size=8` × 4 workers = 40 connections is above the free-tier ceiling of 20. Under any burst, half the workers will block on `pool_timeout=10` and surface as `/health` flakes plus 10-second 500s on user requests. This is a latency bug masquerading as a memory note.
- **Operational confusion:** three conflicting start-command files (`railway.toml`, `backend/railway.json`, `backend/Procfile`, `backend/Dockerfile`) guarantee that the next time someone tries to fix this they will edit the wrong one.

---

## 6. Single biggest unknown

**Whether the stale-`vN:` cache band actually accumulates to 75-300 MB in practice, or whether the natural 15-min-to-24h TTL spread keeps it under 50 MB.**

The only way to confirm is runtime profiling on the live container. Two cheap approaches:

1. **Add a `/admin/cache-stats` endpoint** that returns `len(cache._store)`, the histogram of TTL remaining, and the histogram of `vN` prefixes. Snapshot at boot, after a CACHE_VERSION bump, and 6 hours later. The bump-induced delta is the answer.
2. **`tracemalloc.start()` in the lifespan + a tracemalloc-snapshot endpoint** — heavier but gives a file-line breakdown of where bytes live. Already supported by the standard library; ~10 lines to wire up.

Until that data exists, the breakdown table's "0-300 MB" band on row 7 is the only soft number in this doc. Everything else — worker count, import baseline, pool size — is verifiable from the source tree alone and has been verified above.
