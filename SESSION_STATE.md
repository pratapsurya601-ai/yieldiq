# YieldIQ Session State — Live Working Memory

**Last updated:** 2026-05-19 15:35 IST · auto-maintained by Claude

> Paste this file's contents at the start of any new chat to skip context-rebuilding.

---

## 🔴 START HERE — Day 1 + Day 2 EXTENDED sprint (2026-05-19) — DEPLOYED & VALIDATED

### 11 PRs merged today

| PR | Theme | Impact (post-deploy) |
|---|---|---|
| #373 | reconciliation JOIN ticker normalization | enables `/admin/outliers` |
| #374 | `/admin/outliers` page | operator-visible outlier list |
| #375 | outlier sector audit doc | Day-1 baseline 312 |
| #376 | extreme-FV verdict-gate override | bad FVs no longer flip to "Notably Undervalued" |
| #377 | DCF-collapse safety net → Tier 2 fallback | wired but bottlenecked by peer lookup |
| #378 | verdict-gate wiring | suppresses bad verdicts at presentation time |
| #380 | Tier 2 v2 bucketing (NULL-ROCE carve-out) | 24 clean premium peers (was 0 then 30 with junk) |
| #381 | regulated NBFC recalibration | RECLTD ₹435 (was ₹1001), PFC ₹485 (was ₹1289) |
| #382 | HFC peer split (traditional vs premium) | LICHSGFIN ₹923 (was ₹1636) |
| #383 | **8-commit squash**: CANFINHOME reclassify, GI peer split (psu/private/health), LICHOUSFIN cleanup, stressed_private_banks, adaptive reconciliation threshold, asymmetric ROE clamp, direct peer lookup, sector map expansion, MIN_BUCKET_SIZE 5→3 | YESBANK ₹20 (was ₹40), NIACL ₹170 (was broken), STARHEALTH ₹576, ICICIGI ₹2388 |
| #384 | classify GICRE/GODIGIT/NIVABUPA/LICI as bank-like | GICRE ₹504 (was ₹964), NIVABUPA ₹84 (was ₹11 DCF collapse), GODIGIT ₹285 |

### Final post-deploy validation (live Neon DB, 2026-05-19 16:45 IST)

| Ticker | Old | New | Consensus | Drift |
|---|---:|---:|---:|---:|
| RECLTD | 1001 | **435** | 440 | -1.1% ✓ |
| PFC | 1289 | **485** | 515 | -5.9% ✓ |
| NIACL | broken | **170** | 170 | 0.0% ✓ |
| YESBANK | 40 | **20** | 19 | +4.3% ✓ |
| GICRE | 964 | **504** | 475 | +6.1% ✓ |
| NIVABUPA | 11 | **84** | 91 | -7.0% ✓ (DCF-collapse rescue) |
| ICICIGI | broken | **2388** | 2125 | +12.4% ✓ |
| STARHEALTH | broken | **576** | 579 | -0.5% ✓ |
| GODIGIT | broken | **285** | 366 | -22.3% (within band) |
| LICHSGFIN | 1636 | 923 | 613 | +50.6% (Day-3: pb_residual_income deeper recalibration) |
| LICI | broken | 1852 | 1046 | +77.1% (Day-3: operator EV data via insurance_appraisal_inputs) |

**9 of 11 stocks within ±25% of consensus. 2 stocks have documented Day-3 follow-up.**

### CRITICAL INFRA GOTCHAS — read first

### TL;DR
Day-1 baseline at 06:40 UTC was **312 benchmark-reconciliation outliers**
(37 over, 275 under). Shipped 9 PRs across two days targeting the worst
offenders. Tomorrow's 10am IST reconciliation is the honest read.

### Sequence shipped today (chronological)

| PR | Description | Day |
|---|---|---|
| #373 | reconciliation JOIN ticker normalization | 1 |
| #374 | `/admin/outliers` page | 1 |
| #375 | outlier sector audit doc | 1 |
| #376 | extreme-FV verdict-gate override | 1 |
| #377 | DCF-collapse safety net → Tier 2 fallback | 1 |
| #378 | wire `_apply_confidence_verdict_gate` into analysis service | 1 |
| #380 | Tier 2 quality-bucket rules v2 (NULL-ROCE bank carve-out + single-axis reject) | 2 |
| #381 | Regulated NBFC fair_pb recalibration (RECLTD/PFC/IRFC/HUDCO) | 2 |
| #382 | HFC peer-group split — traditional vs premium | 2 |

### Production-validated post-deploy (Day 2)

| Ticker | Old FV | New FV | Consensus | Drift |
|---|---:|---:|---:|---:|
| RECLTD | ₹1,001 | **₹435** | ₹440 | -1.1% ✓ |
| PFC | ₹1,289 | **₹485** | ₹515 | -5.9% ✓ |
| LICHSGFIN | ₹1,632 | **₹1,077** | ₹630 | still +71%, see carryover #1 |

### CRITICAL INFRA GOTCHAS — read first

1. **Prod DB is Neon, not Aiven.** The user-env DATABASE_URL persisted
   on this machine pointed at a dead Aiven cluster for most of the
   session. Verify with
   `[System.Environment]::GetEnvironmentVariable('DATABASE_URL', 'User')`
   — should contain `neon.tech`.
2. **Tool shells inherit env at parent startup.** `setx` doesn't reach
   already-running Claude Code. Workaround: read user-scope env at the
   top of each tool call via `[System.Environment]::GetEnvironmentVariable(...)`.
3. **Railway deploys from `main` only.** Branch pushes don't auto-deploy.
   Deploy takes 3-7 min after merge. **Do not validate before the deploy
   completes** — I burned cycles today recomputing LICHSGFIN 22 sec
   before the new container came up.
4. **Public stock-summary endpoint serves cache.** To force fresh
   compute: `DELETE FROM analysis_cache WHERE ticker IN (...)` then hit
   `/api/v1/public/stock-summary/<TICKER>.NS`.
5. **CI canary runs against live prod**, NOT PR code. 34 pre-existing
   prod violations exist; they show on every PR until prod heals. Use
   `gh pr merge --admin` when violations are demonstrably not caused
   by the PR. Verified via canary diff vs pre-fix snapshot — PRs
   #380/#381/#382 introduced zero new violations.

### Day-1 cache surgery
312 stale outlier `analysis_cache` rows were deleted at ~12:14 IST.
Most stocks have since rebuilt with the new code paths (safety net +
verdict gate). Tier 2 bucketing rebucketed all 160 peers (24 premium /
47 core / 89 tail) using v2 rules.

### Day 3 carryover (prioritised)

1. **`pb_residual_income` engine recalibration for HFCs** (1-2 hr).
   LICHSGFIN's actual primary FV path uses Gordon residual income with
   own ROE, not peer median. With LICHSGFIN ROE 15%, COE 9.8%, g 4%,
   produces residual P/B = 1.89× → FV ₹1,077. Same fix pattern as PR
   #381: drop ROE to through-cycle realized, bump COE for legacy-lender
   risk premium. Target post-fix LICHSGFIN FV ~₹700-800.

2. **Insurance EV data entry** (10 min operator task). File
   `docs/insurance-ev-day3-task.md` has exact URLs, SQL template, and
   verification queries. Need EV+VNB+growth from Q4FY26 investor decks
   for SBILIFE, ICICIPRULI, LICI. HDFCLIFE already done.

3. **General-insurance peer split** (~1 hr). Same problem PR #382 fixed
   for HFCs — ICICIGI (5.7× P/B premium) bundled with NIACL (0.94× PSU)
   and GICRE (1.11× PSU reinsurer). Split into `premium_gi` and `psu_gi`.

4. **Piotroski data gap for non-bank tickers** (1 hr diagnostic). INFY
   has NULL ROCE despite being IT services. Investigate missing
   `period_type='annual'` rows or NULL `current_liabilities`.

5. **HUDCO 1-analyst consensus audit**. Model FV ₹126 vs consensus
   ₹225 — but only 1 analyst. Cross-check via Damodaran/AceEquity.

### What did NOT happen today (and why fine)
- No CACHE_VERSION bump — none of today's PRs were cache-invalidating;
  cohort changes and constant tweaks affect future analyses only.
- No re-enrichment post-PR #380/382 — `tier2_peer_metrics` already
  carries v2 buckets; future runs auto-pick-up new rules.
- No fix for 34 pre-existing canary violations — will heal organically
  as cache rebuilds through traffic.

### When you resume
1. **First**: check `/admin/outliers` count. Target < 100 (from 312).
   Anything < 50 is a strong Day-2 win.
2. **Second**: skim Day-3 carryover list; pick by energy.
3. **Don't restart Claude Code** unless DATABASE_URL is stale — use
   the user-scope env trick.

---

---

## What this project is
Indian stock DCF valuation platform. Free tier 5 analyses/day, paid ₹799/₹1,499. NOT SEBI-registered as investment adviser — output framed as "model estimate, not investment advice".

## Stack
- Backend: FastAPI on Railway (`api.yieldiq.in`)
- Frontend: Next.js on Vercel (`yieldiq.in`)
- DB: Neon Postgres
- Auth: Supabase Google OAuth + custom backend JWT
- Data: NSE XBRL (integrated-filing endpoint), yfinance, RBI rates

## Key environments
- `DATABASE_URL` in `.env.local` (Neon)
- `unset GH_TOKEN && gh ...` for any gh CLI (keyring auth)
- Railway redeploys are MANUAL (auto-deploy unreliable)
- Vercel auto-deploys on push to main

---

## Session arc (2026-05-17 / 18 marathon)

**44 PRs merged in 24hr** including NSE XBRL pipeline migration (Mar 2026 data live, 97.8% universe coverage), Buffett MoS, SEBI-compliant labels, Google OAuth end-to-end fix, Banks/NBFCs P/B routing, holding-co auto-detect, recent-IPO sector-relative, TTM scale guard, USD reporter detection, Insurance XBRL, editable assumptions, Home dashboard v2, soft email-verify, reverse-DCF normalization, scheduler→GH Actions, plus 2 latent Python-scope bug fixes.

**Railway bill cut:** $35/mo → projected ~$5-7/mo.

---

## Today's session (2026-05-18 marathon continued)

### Landed (merged today)
- **PR #316** shares_outstanding reconciliation + CACHE_VERSION 101→102 — MERGED 07:26 UTC
- **PR #317** price-staleness hard-reject gate (live_quotes >2 days during market hours) — MERGED 07:26 UTC
- **PR #319** coverage_tier column rename (as_of_date → trade_date) — MERGED 08:26 UTC, stops log spam
- Background agent `a5c4` crashed at 12.7 min with API stream idle timeout; partial diff preserved + completed by hand

### Open for review (NOT MERGED)
- **PR #318** Regulated-Utility DCF engine (CACHE_VERSION 102→103). POWERGRID local FV ₹59→₹257 (verdict: overvalued → fairly_valued). 23 new tests pass. Files: new `regulated_utility_valuation_service.py` (290 LOC), service.py routing branch, industry_wacc.py companion tickers (IRFC/IEX/SJVN/HUDCO). Fixes NTPC/PFC/IRFC simultaneously.
- **PR #320** Pharma DCF (CACHE_VERSION 102→104, ahead of 103 to avoid #318 collision). MANKIND local FV ₹1244→₹1782 ✅. DRREDDY intentionally NOT included in USD_REPORTER_TICKERS — yfinance now returns INR (cohort flipped); design doc premise stale. 11 new tests pass. Files: forecaster.py FCF candidate wiring, ipo_framework.py sector-aware window (pharma=60 months), ticker_overrides.py MANKIND entry.

### Parallel agents in flight (5 spawned 2026-05-18 14:30 IST)
- TCS ADR price routing fix (highest priority from audit) — agent ae45
- Dividend payout 0% across all stocks — agent a91e
- HDFC merger phantom growth (design doc only, no code) — agent a46e
- DRREDDY XBRL re-ingest operator script — agent aefe
- Expand `cron-market-live-quotes` top-200 → top-1500 — agent a095

### Verified in prod (post-deploy)
- ✅ **HINDPETRO**: price ₹3,870 → ₹387 (PR #317 working — staleness gate caught 9-day-old live_quotes row, fell through to daily_prices)
- ❌ **POWERGRID**: FV ₹59.66 vs CMP ₹291 — unchanged. Shares fix did NOT help. Real DCF issue (regulated-utility model mismatch — audit's Step 2)
- ❌ **MANKIND**: FV ₹1,244 vs CMP ₹2,494 — unchanged. Pharma DCF mis-tuned
- ❌ **DRREDDY**: FV ₹3,949 vs CMP ₹1,295 — unchanged (overflow gone, but +205% MoS is a different bug)
- ⚠️ **POLICYBZR**: quarantined by validator (validation_critical). NOT broken by PR #316. Live_quotes had stale ₹16,479 (real ~₹1,718); waiting on bulk_refresh to overwrite. yfinance returns correct ₹1,718 right now.

### Honest assessment of PR #316
The "78.8% of cached rows affected" number from audit a79a was DB-row count, NOT user-visible FV fixes. PR #316 helped 0 of the 4 broken tickers in the audit's critical list. The shares-reconciliation only fires when DB has a `shares_outstanding_raw` value that differs from legacy `shares`; for these 4 tickers either both columns matched or the raw column was NULL. **PR #316's actual surface impact is invisible — confirms shares are correct silently. PR #317 is the real prod win today.**

### Root-cause finding: top-200 coverage gap
The `cron-market-live-quotes` GH Actions workflow only refreshes top-200 tickers by FV + portfolio holdings. HINDPETRO/POLICYBZR/MANKIND/POWERGRID are NOT in that set → live_quotes goes stale until manual `bulk_refresh_live_quotes` is fired. GitHub Actions cron itself is also unreliable (1 of ~37 expected fires landed today).
- **Permanent fix needed (P1 next session):** expand cron-market-live-quotes from top-200 to top-1500, OR have `pulse_daily` also write live_quotes (Pulse already covers 1500 tickers)

### Audit reality check (competitive audit pasted earlier)
- "Most critical NOT-shipped: POWERGRID broken / MANKIND broken / TCS ADR price / Discover warming up / HDFC merger phantom growth / Dividend 0% on 5/5"
- POWERGRID + MANKIND confirmed today — these are **sector-engine** problems, not shares
- DRREDDY same story
- POLICYBZR same — live_quotes write-time bug
- **Implication: today's two PRs addressed price-staleness (real win for many tickers) and shares-reconciliation (silent correctness). The audit's listed critical bugs are still mostly open and need the Model Reliability Program's Phase 2 (sector engines).**

### Open since today
- 🔴 **POWERGRID DCF**: needs regulated-utility engine (audit Step 2)
- 🔴 **MANKIND / DRREDDY**: pharma DCF calibration — investigation needed
- 🔴 **POLICYBZR live_quotes write-time bug**: yfinance occasionally writes wrong price to live_quotes (POLICYBZR ₹16,479 was within last 2 days). Bulk refresh masks it but doesn't prevent recurrence. Need write-time sanity gate (reject yfinance value if delta from previous live_quotes > N%).
- 🟡 **cron-market-live-quotes top-200 → top-1500**: scope expansion needed
- 🟡 **Post-v102 discipline artifacts**: snapshot_50_stocks.py + canary_diff.py --diff-against latest + test_dcf.py --update — not yet run (waiting on bulk_refresh)

---

## 🔴 CRITICAL OPEN BUG — shares_outstanding mixed-units

### Scope (from audit a79a, 2026-05-18 06:15)
- **78.8% of cached rows affected (219/278)**
- 30 tickers need >50% FV correction
- `equity_value=0` currently for HDFCBANK/ICICIBANK/CHOLAFIN — fix RESTORES to ~₹800/₹1661/₹1775
- ARSHIYA goes ₹619→₹7 (90× drop, microcap — needs sanity check)
- SAMPANN: separate negative-equity bug, out of scope

### Root cause
- Legacy `financials.shares_outstanding` column DESIGNED as lakhs (per `data_pipeline/models.py:121`)
- Actual data: mixed lakh/crore/raw across ingest paths
- yfinance path: divides raw by 1e5 (→lakhs) at insert
- BSE/NSE XBRL paths: historically inconsistent
- `_lakhs_to_raw` (×1e5) only works if source actually was lakhs

### Fix shipped today
- **PR #316 MERGED 2026-05-18 07:26 UTC** — `enriched["shares"]` reconciled via `shares_or_warn` against post-normalization `shares_outstanding_raw`
- CACHE_VERSION 101→102 forced full cache rebuild
- **Real-world impact: silent correctness only.** None of the 4 audit-critical broken tickers (POWERGRID/MANKIND/DRREDDY/POLICYBZR) were fixed by this PR — their bugs are elsewhere. The 78.8% audit number was DB-row count, not user-visible FV fixes.

### Files for follow-up
- `data_pipeline/migrations/020_shares_outstanding_normalize.sql`
- `scripts/normalize_shares_outstanding.py`
- `backend/validators/shares_outstanding.py`
- `backend/services/analysis/service.py:957, 2390`
- `data_pipeline/sources/yfinance_supplement.py:203` (`_to_lakhs`)
- `data_pipeline/pipeline.py:273` (`_lakhs_to_raw`)

---

## Other open bugs

### 🟡 P1 — Bank ROE source (deferred to proper project)
yfinance `total_equity` includes AT1 perpetual bonds + minority interest. HDFCBANK shows ROE 8.8% vs real 17%. Affects ~30 lenders. KOTAKBANK on YieldIQ 50 leaderboard with wrong ROE.
- **Tracking:** `docs/design/bank-equity-source-fix.md`
- Fix: 1-2 weeks (clean equity source via NSE XBRL or compute TCE locally)

### 🟡 P2 — DRREDDY FV mis-direction (overflow fixed earlier)
- `equity_value = 2.96e17` overflow gone (fixed before today)
- Current state: FV ₹3,949 vs CMP ₹1,295 = +205% MoS undervalued. Probably wrong direction.
- Likely pharma DCF model issue (margin / growth normalization)
- Needs investigation in next session

### 🟡 P3 — Canary state (~5/50 violations remaining after fixes)
- 3 bank ROE bound violations (covered by P1)
- 1 GRASIM ROE (clears when cache invalidates post #313)
- 1 ADANIPORTS forbidden_values (was misdiagnosed — actually the shares bug per current P0)

---

## Operator actions still pending (you, not Claude)

1. ✅ Migration 011 applied
2. ✅ **Railway env vars confirmed** (`WEB_CONCURRENCY=1`, `AUTO_REFRESH_PARQUETS=0`, `MALLOC_ARENA_MAX=2`, `PYTHONMALLOC=malloc`) — but memory still 1.5GB post-deploy; may need ENABLE_INPROCESS_SCHEDULER=0 check
3. **GitHub repo secrets** for GH Actions cron (PR #309): `NEON_DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`
4. **Smoke-test 3 cron workflows**: `cron-market-live-quotes`, `cron-market-fx-rates`, `cron-market-index-snapshots`
5. **Delete test accounts:** `yieldiq.audit.test+nov2026@gmail.com`
6. **Add `NEXT_PUBLIC_SENTRY_DSN`** to Vercel
7. **Railway memory monitoring**: 1.5GB plateau observed 2026-05-18 12:08 IST — investigate if persists after v102 cache fully warm. Restart `focused-vibrancy` if it climbs past 1.8GB.

---

## Design docs ready / referenced

- `docs/design/confidence-metric-v2.md` (Phase-1 done per PR #303)
- `docs/design/reverse-dcf-normalization.md` (done per PR #310)
- `docs/design/corporate-actions-overlay.md` (Phase-A done per PR #302)
- `docs/design/bank-equity-source-fix.md` (tracked, deferred)

---

## Deferred / not started

- Source-link every number to NSE filing
- Pricing tier restructure (₹399/₹1,499/₹4,999)
- Damodaran reconciliation page
- Watchlist MoS-threshold alerts
- YouTube Hinglish content engine
- Mobile-native compressed view
- L3 Phase-B (verified corp-actions seed) + Phase-C (wire-in)
- L2 Phase-2/3 (cross-engine + structural-break)
- L5 follow-ups (reverse-DCF universe re-cache)

---

## Operating patterns established

- Multiple parallel agents → batch merges via gh CLI admin
- `unset GH_TOKEN` prefix every gh command (keyring auth)
- Pre-existing canary fails are OK to admin-override; new fails need investigation
- Agents bailing on speculative scope are CORRECT — don't override
- Design-first agent pattern for risky changes
- Cache evictions are safe (just slower next-load) but should target affected tickers not full table
- Railway redeploys are manual — `auto-deploy` is unreliable
