# YieldIQ — Pre-launch Health Audit (2026-04-25)

Snapshot taken ~05:30 UTC against `https://api.yieldiq.in` and `https://yieldiq.in`. All probes anonymous (free-tier paths only). Read-only audit — no code changes.

sector-scope: *

---

## 1. Critical (launch blockers — HIGH)

### C1. RELIANCE.NS preview returns `verdict: "data_limited"` with FV ₹762 vs price ₹1,328
- **Where:** `GET /api/v1/analysis/preview/RELIANCE.NS` (also rendered into the SSR `<title>` and `og:title` of `/analysis/RELIANCE.NS` as **"RELIANCE — Data Limited | YieldIQ"**).
- **What:** Confidence score 33, MoS −42.6%. The OG image and shared link a Reddit/Twitter user gets when they paste the URL says *"Data Limited"* on India's most-shared bellwether ticker. This is the single worst first impression possible.
- **Impact:** Launch-day virality killer. RELIANCE is the ticker every Indian retail investor types first.
- **Suggested fix:** Investigate why the local-DB+parquet fast path is returning low-confidence inputs for RELIANCE specifically (probably stale/missing FY ratios in parquet). Either (a) refresh the RELIANCE parquet partition, or (b) raise the data_limited gate so this verdict only applies when confidence < 25 and the missing fields are load-bearing. Until fixed, the page should fall back to "fairly_valued" wording with a soft "limited inputs" footnote rather than a Title-Case "Data Limited" headline.
- **ETA:** 30–60 min if it's parquet staleness; 2–3 h if it's the gate logic.
- **File pointers:** `backend/services/analysis/service.py` (verdict assignment), `backend/routers/analysis.py` (preview shaping), OG: `frontend/src/app/analysis/[ticker]/opengraph-image.tsx` (or wherever og:title is built).

### C2. `HUL.NS` returns `TickerNotFoundError` after 14 s wait
- **Where:** `GET /api/v1/analysis/preview/HUL.NS` → 200 body `{"error":"TickerNotFoundError (details suppressed)","ticker":"HUL.NS"}`, response time **13.99 s**.
- **What:** The canonical NSE symbol is `HINDUNILVR.NS` (which works fine — verdict overvalued, FV 1804, 0.7 s). But "HUL" is the universally-used colloquial name; every retail user will type it.
- **Impact:** (1) 14-second hang before the error renders kills perceived perf. (2) No alias mapping → user thinks the app is broken. (3) `docs/TICKER_ALIASES.md` does not contain a HUL entry.
- **Suggested fix:** Add an alias row `HUL → HINDUNILVR` in the alias table (and any other obvious ones — INFOSYS→INFY, MARUTI→MARUTISUZUKI, BAJAJFIN→BAJFINANCE, etc.). Also: short-circuit the 3-attempt × (3 s + 6 s) sleep loop the moment yfinance reports "no such symbol" (see C3).
- **ETA:** 30 min for HUL alias; 1 h for short-circuit.

### C3. Sync `time.sleep(3..9)` inside hot async path — `service.py:267`
- **Where:** `backend/services/analysis/service.py:267` — `_time.sleep(3 + _attempt * 3)` inside the yfinance fallback retry loop.
- **What:** `time.sleep` (not `asyncio.sleep`) blocks the event-loop thread on FastAPI/uvicorn. With concurrent requests this serializes the worker. For unknown tickers like `HUL.NS` it costs 9 s per request and during that window other requests stall.
- **Impact:** Under launch-day concurrency this will visibly degrade p95 across all routes, not just the offending request. Exactly the kind of hang screenshotted in C2.
- **Suggested fix:** Replace with `await asyncio.sleep(...)` (function and call chain must be async-aware), or move the StockDataCollector call onto a thread executor (`run_in_threadpool`). Better: cap at 1 retry with 1 s sleep when the prior attempt's exception is "ticker not found" vs a transient network error.
- **ETA:** 1–2 h with a careful test pass.

### C4. `DCF Regression Tests` red on `main` and on every open PR (22/50 regressions)
- **Where:** workflow runs 24922740945, 24922598549, 24922592447, 24922411333 (all on `main` push, today).
- **What:** Latest log: `Summary: 28/50 clean - 22 regressions - 0 missing — [FAIL] BLOCKING: 22 regressions exceeds threshold 3`. Examples: SHREECEM FV 11993 → 3439 (-71 %), AMBUJACEM 495 → 320 (-35 %), JSWSTEEL FV 154 → 0 (now `data_limited`), CIPLA verdict flipped data_limited → undervalued, DALBHARAT overvalued → fairly_valued.
- **Impact:** Per CLAUDE.md "Data-fix discipline" rule #1, no PR touching `backend/services/`, `backend/routers/`, `backend/validators/` should merge while canary/regression is failing on `main`. This means the merge gate is currently letting things through (or being bypassed). Regressions of this magnitude on cement and steel names suggest a recent change to the WACC/terminal-growth or sector-defaults table is silently re-pricing 30 % of coverage.
- **Suggested fix:** Bisect today's main commits between the last green DCF run and now. Triage: is the new behavior correct (rebaseline expectations) or wrong (revert)? Until decided, freeze backend merges.
- **ETA:** 2–4 h for triage; rebaseline or revert depending on root cause.

### C5. Daily blog post workflow failing — Groq token-per-day limit hit
- **Where:** `.github/workflows/daily_blog_post.yml`, run 24923554464.
- **What:** `Rate limit reached for model llama-3.3-70b-versatile … TPD: Limit 100000, Used 99785, Requested 4733`.
- **Impact:** No blog post on launch day → no SEO surface, no fresh content, no daily indexing signal to Google. Also, this workflow has been failing for at least a day on schedule.
- **Suggested fix:** (a) Move to a smaller Groq model for the daily job (llama-3.1-8b is plenty for a 5-stock summary), or (b) upgrade to Dev Tier ($), or (c) cache yesterday's post and only regenerate when the top-5 list actually changes.
- **ETA:** 15 min to swap model; 30 min for the cache-check approach.

---

## 2. Should-fix (degraded UX — MEDIUM)

### M1. `/discover` hero says **"YieldIQ 50 is warming up"** instead of showing names
- **Where:** rendered SSR HTML at `https://yieldiq.in/discover`. Snippet: `YieldIQ 50 is warming up — The daily ranking rebuilds as stocks are analys…`
- **What:** Anonymous user lands on Discover and sees an empty state instead of the hero card with stock names. Combined with C1 (RELIANCE data_limited) this is two-for-two on first impressions.
- **Impact:** The Discover page is the user's second click after the homepage. Empty hero = "this app has no data."
- **Suggested fix:** Either backfill the daily ranking ahead of launch, or replace the empty state with a server-rendered top-5 fallback computed from the screener (sort=mos desc, score>50, limit 5). Never show "warming up" to anon users on the most-trafficked page.
- **ETA:** 1 h for the fallback; depends on cron for the rebuild.

### M2. `Canary Diff` failing on `main` (last manual run 2026-04-24 19:35) — 6 violations
- **Where:** run 24908249465. `single_source_of_truth: 1`, `mos_math_consistency: 1`, `scenario_dispersion: 2`, `canary_bounds: 1`, `forbidden_values: 1`.
- **Impact:** Per CLAUDE.md rule #1, these must be zero before any backend merge. Currently main is dirty.
- **Suggested fix:** Pull `canary_report.md` from that run, fix the 6 specific stocks, re-run.
- **ETA:** 2–3 h.

### M3. `Sector Isolation` merge gate flagged on PRs missing `sector-scope:` declaration
- **Where:** runs 24922835967, 24922650137, 24922591250 — all PR-body parser failures, not real isolation breaks.
- **What:** Working as designed. Multiple recent PRs forgot the `sector-scope:` line in the body.
- **Suggested fix:** Add a PR template with the `sector-scope: *` line pre-filled. Not blocking launch but causes friction now.
- **ETA:** 10 min (PR template).

### M4. Public screener query rejects shorthand `filters=pe_ratio<20,roce>15`
- **Where:** `GET /api/v1/public/screener/query?filters=pe_ratio<20,roce>15` → **HTTP 400** (unencoded). URL-encoded version (`%3C`/`%3E`) works fine and returns 50 results in ~1 s.
- **Impact:** Documentation/copy-paste hazard. Anyone sharing a screener URL on Twitter/Reddit will hit 400 if they paste raw `<` and `>`.
- **Suggested fix:** Either accept raw `<`/`>` server-side (FastAPI dependency that decodes once before parsing), or always emit URL-encoded share-links from the frontend.
- **ETA:** 30 min.

### M5. `POST /api/v1/public/screener/query` returns 405 (only GET supported)
- **Where:** Same endpoint, POST. Many JS clients reflexively POST when sending a JSON filter body.
- **Suggested fix:** Either accept POST with a JSON body (cleaner for complex filters) or document GET-only clearly.
- **ETA:** 30–60 min.

### M6. `/compare` SSR shipped only `Loading comparison…` — no SSR data
- **Where:** `https://yieldiq.in/compare` and `…?tickers=TCS.NS,INFY.NS` both serve `Loading comparison…` in the HTML.
- **Impact:** Bad TTFB-perceived; bad for crawlers; bad for shared compare URLs which won't unfurl with anything useful.
- **Suggested fix:** SSR at least the ticker chips and a skeleton with company names; hydrate scenarios client-side. Add OG image with the comparison summary.
- **ETA:** 2–3 h.

---

## 3. Nice-to-have (LOW)

### L1. Some preview times are >1 s (ICICIBANK 1.16 s, SBIN 1.02 s)
Most bellwethers serve in 0.3–0.7 s. ICICIBANK and SBIN are noticeably slower. Likely cache miss on this probe; not blocking. Worth a follow-up cache-warming script for the top 50.

### L2. `og:image:alt` is generic ("RELIANCE stock analysis on YieldIQ")
Could include verdict + score for richer alt text. Cosmetic.

### L3. Discover-50 empty state styling
The "warming up" empty state itself is well-designed (see M1) but could include 3–5 example tickers users can browse manually instead of a dead end.

---

## 4. All clear (working well)

- **Frontend SSR is fast.** All four pages 0.16–0.82 s TTFB on a cold anonymous hit. Home `/` in 0.16 s. Excellent.
- **Public screener fields endpoint** clean, well-shaped, fast (`fields`, `ops`, `sort_keys` all returned).
- **Public screener query (encoded)** returns 50 results in ~1 s with full ratios + verdict + FV per row. Ready for SEO indexing.
- **All-tickers index** populated with `last_updated` per row — recent (today/yesterday).
- **Auth gating works** — `/api/v1/debug/parquet-status` returns 401 to anon, not 200. No accidental DEBUG leak.
- **SEBI vocabulary lint** passes locally (`scripts/check_sebi_words.py` → "no banned vocabulary in user-facing frontend strings").
- **9 of 10 bellwether previews** return well-formed JSON with FV, verdict, MoS, score, grade, Piotroski, moat — the data model is solid.
- **OG metadata** is fully wired (`og:title`, `og:description` with FV/price, `og:image` URL, dimensions, alt). The infrastructure is right; it's the *content* (C1) that needs fixing.
- **Most-recent merge-gate workflow runs are green** (`Frontend SEBI Vocabulary Lint`, `OG Image Health`, `Retention Emails`, `Canary Diff` on most PRs). Pipeline hygiene is mostly working.

---

## Probe data appendix

### Bellwether preview probes (10)

| Ticker | HTTP | Time (s) | FV | Verdict | Notes |
|---|---|---|---|---|---|
| RELIANCE.NS | 200 | 0.54 | 762.21 | **data_limited** | conf=33, MoS −42.6 % — see C1 |
| TCS.NS | 200 | 0.75 | 3495.56 | undervalued | clean |
| INFY.NS | 200 | 0.30 | 1822.77 | undervalued | clean |
| HDFCBANK.NS | 200 | 0.30 | 726.16 | fairly_valued | clean |
| ICICIBANK.NS | 200 | 1.16 | 1132.94 | fairly_valued | slow — see L1 |
| ITC.NS | 200 | 0.31 | 309.75 | fairly_valued | clean |
| BHARTIARTL.NS | 200 | 0.31 | 1853.81 | fairly_valued | clean |
| SBIN.NS | 200 | 1.02 | 783.09 | overvalued | slow — see L1 |
| LT.NS | 200 | 0.71 | 3471.88 | overvalued | clean |
| HUL.NS | 200 | **13.99** | — | TickerNotFoundError | see C2, C3 |

(MoS/score fields live nested under `valuation`/`quality` rather than top-level; populated for all rows except HUL.)

### Frontend page probes

| URL | HTTP | TTFB / total (s) | Bytes |
|---|---|---|---|
| `https://yieldiq.in/` | 200 | 0.16 | 38166 |
| `https://yieldiq.in/discover` | 200 | 0.82 | 34060 |
| `https://yieldiq.in/discover/screener` | 200 | 0.74 | 31057 |
| `https://yieldiq.in/analysis/RELIANCE.NS` | 200 | 0.70 (cold) / 0.39 (warm) | 34371 |
| `https://yieldiq.in/compare` | 200 | 0.72 | 29953 |

### CI snapshot (last 50 runs, 2026-04-24 → 2026-04-25)

- 16 / 50 failed
- Recurring failures: `DCF Regression Tests` (≥6 hits, real — C4), `Sector Isolation` (3 hits, all PR-body parse failures — M3), `Daily blog post` (Groq TPD — C5), `Canary Diff` on main (real — M2)
- Green: `Frontend SEBI Vocabulary Lint`, `OG Image Health`, `Retention Emails`, most PR Canary Diffs

---

## Launch readiness verdict

**Not ready as-is.** C1 alone (RELIANCE shows "Data Limited") will sink launch-day word of mouth. C4 (DCF regressions on main) means there's no safety net for further fixes. Recommended sequence before going public:

1. Fix C1 (RELIANCE verdict + OG title) — single highest ROI.
2. Triage C4 — figure out which recent change broke 22/50 stocks; revert or rebaseline.
3. Fix C5 (swap Groq model) so daily blog runs on launch day.
4. Address M1 (Discover hero) so the second click isn't an empty state.
5. Add HUL alias (C2 partial) and async-sleep fix (C3) for hardening.

Estimated total: 1 focused day.
