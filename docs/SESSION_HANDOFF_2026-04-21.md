# YieldIQ — Session Handoff (2026-04-21)

Handoff document for the next Claude session (or any engineer) continuing
YieldIQ work. Covers state, open loops, debugging playbooks, and pointers
to where secrets/config live.

**⚠️ This file contains NO secrets.** All tokens/keys/passwords live in
Railway / Vercel / Razorpay / Supabase / Neon dashboards — pointers below.

---

## 1. State of the app as of end-of-day 2026-04-21

### What's in production (deployed on Railway + Vercel, all merged to `main`)

| Shipped today | What it does |
|---|---|
| Razorpay subscription stack | `/create-subscription`, `/verify-subscription`, `/webhook` — ₹799 Analyst + ₹1,499 Pro, monthly + annual |
| Razorpay PAYG stack | `/create-order?plan_id=single_analysis&ticker=X` + `/verify` + `/payg-unlocks` — ₹99 per-analysis unlock, 24h TTL |
| Razorpay webhook signature verification | Handles subscription.activated / charged / halted / cancelled / completed |
| users_meta tier enforcement | 60s in-process cache + `invalidate_tier_cache(user_id)` on payment success — paid users unlock instantly without re-login |
| PAYG frontend (CTA + badge) | `frontend/src/components/payg/` — UnlockCTA, UnlockBadge, PaygHydrator |
| Bank-native Prism metrics | 5 of 6 axes lit for banks (previously all "n/a") using ROA, ROE, Cost-to-Income, Advances/Deposits YoY |
| ROCE unit mismatch fix | Was null for all flagships; now TCS=54.9%, ITC=36.6%, etc. See `_fetch_roce_inputs` in `analysis_service.py` |
| Bare-ticker canonicalization (Bug A) | `/stock-summary/TCS` no longer misroutes to US pipeline; auto-appends `.NS` for known Indian tickers |
| current_ratio unit fix | New `_fetch_current_assets()` helper; matches Crore unit with EBIT |
| save_cached() TypeError fix | Public stock-summary cache-write no longer silently fails |
| Sentry integration | Backend project `python-fastapi` on `yieldiq.sentry.io`; frontend project TBD |
| 4 real-bug fixes from Sentry triage | TMPV DCF cap spam (606 events/day killed), NaN in risk_stats, JSONResponse.results, session rollback cascade |
| PAYG table + RLS | `payg_unlocks` with `razorpay_payment_id` unique idx, self-select RLS policy |

### Outstanding items (ordered by priority)

1. **Onboarding Prism hex shows 5 "n/a" circles** — pre-existing UX issue. Mobile screenshot at `/onboarding/...`. Fix: pre-populate demo ticker (TCS with real scores) instead of placeholder. Not a regression; see section 7.
2. **Migration 012 SQLAlchemy skip error** — `sqlalchemy.cyextension.immutabledict.immutabledict is not a sequence`. Every Railway boot logs this. Cosmetic but will bite when adding new migrations. Investigation deferred.
3. **revenue_cagr_3y null on TCS** — backend returns null. Logs show revenue CAGR clamping for several tickers due to >50% growth. TCS specifically is different (likely `enriched.income_df` empty/missing). Investigation deferred.
4. **PREMCO-X.NS / TATAGOLD-E.NS Sentry spam** — these tickers don't exist. Something in YOUR codebase is calling them (check TICKER_ALIASES, canary list, or batch scripts).
5. **LTIM.NS delisted warning** — LTIM merged into LTIMINDTREE.NS. Add alias: `TICKER_ALIASES["LTIM.NS"] = "LTIMINDTREE.NS"` in `backend/routers/analysis.py`.
6. **yfinance cookie UNIQUE constraint (HDFCBANK)** — 33 events. yfinance library internal race. Add Sentry filter rule: `logger:yfinance AND message:"cookieschema"`.
7. **Frontend UX grade C+ → A+ roadmap** — see section 8 below. 1-2 weeks of focused work.
8. **Sentry follow-up** — rotate the personal token that was used during triage (scope: `event:read`, `project:read`, `org:read`). Look for `claude-triage-apr21` in Settings → Account → API → revoke.

---

## 2. Where secrets / credentials live

**No secrets in this document.** The next session should ask the user for credentials only when needed, and only enough scope for the specific task.

| Secret | Lives in | Used by |
|---|---|---|
| `RAZORPAY_KEY_ID` (live) | Railway env (yieldiq-backend), Razorpay dashboard → Settings → API Keys | Backend payment endpoints |
| `RAZORPAY_KEY_SECRET` | Railway env only | Backend signature verification |
| `RAZORPAY_WEBHOOK_SECRET` | Railway env + Razorpay dashboard → Settings → Webhooks | Webhook signature verification |
| `RAZORPAY_PLAN_ANALYST_MONTHLY` | Railway env | Value: `plan_SeLyaLj2qXVspj` (₹799 Analyst Monthly, live mode) |
| `RAZORPAY_PLAN_ANALYST_ANNUAL` | Railway env | Value: `plan_Sg41RoFQUiIPmL` (₹6,999 — user's note) |
| `RAZORPAY_PLAN_PRO_MONTHLY` | Railway env | Value: `plan_Sg42T5NlnA9sxi` (₹1,499) |
| `RAZORPAY_PLAN_PRO_ANNUAL` | Railway env | Value: `plan_Sg43CwzVRWevvH` (₹13,999) |
| `SUPABASE_URL` | Railway env + Vercel env | Auth backend |
| `SUPABASE_ANON_KEY` | Railway env + Vercel env (public) | Client-side Supabase |
| `SUPABASE_SERVICE_KEY` | Railway env only | Admin operations (signup w/ email_confirm, RLS-bypass writes) |
| `DATABASE_URL` | Railway env | Neon Postgres pooler endpoint `ep-silent-thunder-*` on project `rapid-cherry-02607615` |
| `JWT_SECRET` or `YIELDIQ_JWT_SECRET` | Railway env | FastAPI JWT signing |
| `GROQ_API_KEY` | Railway env | AI summary generation (Gemini was removed, Groq-only) |
| `FMP_API_KEY` | Railway env | Financial Modeling Prep |
| `FINNHUB_API_KEY` | Railway env | Finnhub market data |
| `SENTRY_DSN` | Railway env + Vercel env | Error reporting |

**Neon project:** `rapid-cherry-02607615` (AWS Asia Pacific 1 / Singapore, 465 MB, actively used). There's an older `yieldiq-data` project (290 MB, stale since Apr 14) that can be deleted after a 7-day safety window.

**Razorpay mode:** LIVE. All plan IDs above are live-mode. The dashboard's "Test Mode" toggle must be OFF when viewing these plans.

---

## 3. Debugging playbooks I built + used

### 3a. ROCE / ratio unit-mismatch probe

URL: `https://api.yieldiq.in/api/v1/public/roce-probe/{ticker}`
Source: `backend/routers/public.py:roce_probe`

Returns DB values (Crores) + enriched values (raw INR) + the simulated main-flow compute. Any new ratio suspected of unit-mismatch: add it to this probe. Delete the endpoint once you're confident (it's a dev tool, not a product feature).

### 3b. Sentry triage via personal token

Don't share the token. Have the user create a token with scopes `event:read`, `project:read`, `org:read`, then run:

```powershell
$env:SENTRY_TOKEN = "<paste>"
$headers = @{ Authorization = "Bearer $env:SENTRY_TOKEN" }
Invoke-RestMethod -Uri "https://sentry.io/api/0/projects/yieldiq/python-fastapi/issues/?query=is:unresolved&sort=freq&limit=30" -Headers $headers | ConvertTo-Json -Depth 10
```

Paste the JSON back into Claude. Classify each as 🔴 real bug / 🟡 worth fixing / ⚪ noise / 🔵 duplicate. Token should be revoked after each session.

**Sentry org slug:** `yieldiq` | **Backend project slug:** `python-fastapi`

### 3c. Neon SQL queries (when you need DB ground truth)

Connect via Neon dashboard → project `rapid-cherry-02607615` → SQL Editor. Branch: `production`, database: `neondb`.

Patterns I used:

```sql
-- Check latest ROCE inputs in company_financials
WITH tickers AS (SELECT unnest(ARRAY['TCS','INFY',...]) AS t)
SELECT t.t AS ticker,
       (SELECT ebit FROM company_financials
          WHERE ticker_nse=t.t AND statement_type='income' AND period_type='annual'
          ORDER BY period_end_date DESC LIMIT 1) AS ebit,
       ...
FROM tickers t;

-- Flush cache for specific tickers
DELETE FROM analysis_cache
WHERE ticker = ANY(ARRAY['TCS.NS','INFY.NS',...]);

-- Inspect cached field
SELECT ticker, payload->'quality'->>'roce' AS cached_roce, computed_at, cache_version
FROM analysis_cache WHERE ticker = 'TCS.NS';
```

### 3d. Canary-diff discipline (CLAUDE.md rule 1)

Before merging anything that touches `backend/services/`, `backend/routers/`, `backend/validators/`, `backend/models/`, or `scripts/canary_stocks_50.json`:

```bash
python scripts/canary_diff.py
# must exit 0
```

The GH Actions workflow runs this on every PR. Direct pushes to main skip this gate — use only for hotfixes, and run canary locally after.

**SHARED_FIELDS canary guards:** `fair_value`, `margin_of_safety`, `bear_case`, `base_case`, `bull_case`, `roe`, `roce`, `wacc`, `ev_ebitda`, `revenue_cagr_3y`. Any change to these values on any of the 50 stocks must be explained in the PR description.

### 3e. Razorpay debugging

- Error `BadRequestError: The ID provided is invalid` → plan_id + mode mismatch between Railway env and Razorpay account/mode
- Character traps: `1` vs `l`, `0` vs `O` in plan IDs — always use Razorpay's copy icon, never retype
- Verify Razorpay keys + dashboard are the SAME account. See session transcript for the IncredibleItinerary mistake that cost ~2 hours
- Subscription signature is **NOT** Order signature. Use `hmac.sha256(secret, f"{payment_id}|{subscription_id}")`. Razorpay Python SDK's `verify_payment_signature` is Order-only

### 3f. Supabase schema gotchas

- `users_meta` PK is `id` (UUID referencing `auth.users`), NOT `user_id`
- `users_meta` does NOT have `razorpay_subscription_id` column — subscription metadata lives in the `subscriptions` table
- `subscriptions.razorpay_sub_id` is the FK to link a Razorpay subscription back to a user
- Trigger `handle_new_user()` auto-creates users_meta row on signup — do UPDATE not UPSERT

### 3g. JWT tier is stale snapshot

User's JWT carries tier from login time. Post-payment upgrades need `invalidate_tier_cache(user_id)` in `backend/middleware/auth.py` OR the user waits up to 60s for the cache to expire. Already wired in verify-subscription.

---

## 4. Agent workflow patterns that worked

When shipping multiple independent pieces, spawn parallel agents with worktree isolation:

```
Agent tool call with:
  isolation: "worktree"
  run_in_background: true
  prompt: <self-contained, like briefing a colleague who walked in cold>
```

**Prompt must include:**
- Full context (what the product is, what the bug is, how reproduced)
- Exact files / line numbers to edit
- Constraints (CLAUDE.md rules, canary-diff, naming conventions)
- Deliverable (branch name, NOT to merge, report format)
- Frontend agents: "read `node_modules/next/dist/docs/` before writing React/Next" (per `frontend/AGENTS.md` — Next.js 15 has breaking changes)

**Sessions where this worked:**
- 2026-04-21 afternoon: 2 parallel agents for Bank Prism + PAYG Frontend (each ~1h, no conflicts)
- 2026-04-21 evening: 4 parallel agents for Sentry top-4 bugs (all landed in ~10 min)

**Merge strategy for parallel branches:**
1. Verify each branch is based off latest main or a known-good ancestor
2. `git merge origin/branch-name --no-edit` one at a time from main
3. Expected: "Merge made by the 'ort' strategy" with small diff — no conflicts if scoped correctly
4. If ANY merge conflicts: stop, revert, investigate

**Sub-agent file paths:** agents return their own worktree path (e.g. `E:\Projects\yieldiq_v7\.claude\worktrees\agent-XXXXXX`). Don't edit those directly — read from them only if verifying what the agent did. The committed branch on `origin/<branch-name>` is the source of truth.

---

## 5. Recent commits timeline (reverse chron)

Today's `main` history (partial, latest first):

```
87e5b1c Merge remote-tracking branch 'origin/fix/tmpv-dcf-cap-sentry-noise'
7caa758 Merge remote-tracking branch 'origin/fix/risk-stats-nan-sanitize'
a58dd87 Merge remote-tracking branch 'origin/fix/yfinance-supplement-session-rollback'
193aebe Merge remote-tracking branch 'origin/fix/top-pick-jsonresponse-bug'
cc4b3bd Merge pull request #23 from pratapsurya601-ai/feat/payg-frontend-wiring
18d3f5b Merge pull request #24 from pratapsurya601-ai/feat/bank-prism-metrics
5f95863 fix(ratios): current_ratio uses DB values — same unit fix as ROCE
365cdad fix(analysis): canonicalize bare Indian tickers at service entry (Bug A)
c0cb91e fix(roce): use DB values in Crores — not enriched's raw-INR — for ROCE compute
51e81e5 diag(roce): add /api/v1/public/roce-probe/{ticker} probe endpoint  -- KEEP this endpoint for a week, then remove
1006516 feat(payments): PAYG single-analysis unlock persistence
6e51ca1 chore(db): enable RLS + self-select policy on payg_unlocks
fe86459 fix(auth+cache): tier enforcement + save_cached compute_ms bug
c18aa16 fix(payments): subscription signature verification + correct Supabase schema
0f24027 feat(payments): add Razorpay subscription webhook handler
```

Full log: `cd E:/Projects/yieldiq_v7 && git log --oneline -50`

---

## 6. Key files + entry points to know

### Backend (FastAPI, Python 3.x)

| File | Role |
|---|---|
| `backend/main.py` | FastAPI app entry, Sentry init |
| `backend/middleware/auth.py` | JWT decode, tier refresh from users_meta, `invalidate_tier_cache()` |
| `backend/routers/payments.py` | All Razorpay: create-order, create-subscription, verify, verify-subscription, webhook, payg-unlocks |
| `backend/routers/analysis.py` | Authed analysis endpoints. `get_top_pick` at ~line 791 |
| `backend/routers/public.py` | Public (no-auth) endpoints: stock-summary, risk-stats, roce-probe (dev), payg-unlocks list |
| `backend/services/analysis_service.py` | **THE beast** — `get_full_analysis` at line ~1367. Contains `_fetch_roce_inputs`, `_fetch_current_assets`, `_canonicalize_ticker`. 2800+ lines. |
| `backend/services/ratios_service.py` | `compute_roce`, `compute_current_ratio`, `compute_revenue_cagr`, etc. Pure functions |
| `backend/services/validators.py` | `validate_analysis` + TMPV cap-aware suppression |
| `backend/services/hex_service.py` | Prism axis score computation (now bank-aware) |
| `backend/services/ticker_search.py` | `INDIAN_STOCKS` list (400+). Used by `_canonicalize_ticker` |
| `data_pipeline/db.py` | SQLAlchemy engine. Has `SET search_path TO public` event listener for Neon pooler |
| `data_pipeline/sources/yfinance_supplement.py` | yfinance batch fetch with per-ticker rollback discipline |
| `data_pipeline/sources/nse_xbrl_fundamentals.py` | NSE XBRL parser (extended with TA/CL/EBIT in FIX-XBRL-ROCE) |

### Frontend (Next.js 15)

| File | Role |
|---|---|
| `frontend/src/api/index.ts` | Axios client + auth interceptor |
| `frontend/src/store/authStore.ts` | Zustand auth state |
| `frontend/src/store/paygStore.ts` | Zustand PAYG unlocks state |
| `frontend/src/lib/payg.ts` | `startPaygCheckout()` orchestrator |
| `frontend/src/components/payg/` | UnlockCTA, UnlockBadge, PaygHydrator |
| `frontend/src/app/(app)/account/page.tsx` | Pricing + subscribe flow. Handler at line ~116 `handleUpgrade` |
| `frontend/src/app/(app)/analysis/[ticker]/AnalysisBody.tsx` | 429 tier-gate + PAYG CTA |
| `frontend/src/components/analysis/QualityRatios.tsx` | Bank-aware ratio cards |

### Database schema

| File | Content |
|---|---|
| `db/schema.sql` | Supabase full schema (users_meta, subscriptions, payg_unlocks, watchlist, etc.) |
| `db/migrations/001_payg_unlocks.sql` | Standalone migration (already run in Supabase) |
| `data_pipeline/migrations/` | Pipeline DB migrations (Neon). Migration 012 is the current_liabilities one |

---

## 7. Known UX issues to fix

From screenshots reviewed:

1. **Onboarding hex placeholder** — shows 5 "n/a" circles. Fix: pre-populate TCS with real scores as demo.
2. **Mobile Prism cramped** — 6 axes on narrow screens. Redesign options documented in the Oct roadmap section.
3. **Market cap formatting** — `₹1.44L Cr` ambiguous. Use `₹14,400 Cr` or `₹1.44 Lakh Cr`.
4. **"Insufficient data"** messages — replace with actionable explanations. Bank-Prism merge did this for 3 cards; audit other null-states for similar treatment.
5. **Loading states** — shimmer/skeleton matching final layout, not spinners.

---

## 8. Frontend UX A+ roadmap (from this session's analysis)

**Week 1:**
- Day 1-2: fix onboarding + mobile Prism + copy polish (B+ floor)
- Day 3: narrative summary at top of analysis pages (Groq-powered, cache)
- Day 4: share cards (`@vercel/og` or `satori`) — biggest growth loop
- Day 5: tooltips on every metric + peer comparison context

**Week 2:**
- Day 1-3: mobile-first PWA polish (next-pwa, haptics, swipe, pull-refresh)
- Day 4: interactive onboarding carousel
- Day 5: content marketing launch (first newsletter)

**Bottleneck will be copy + design, not code.**

---

## 9. Key architectural decisions / gotchas

- **Unit contract:** XBRL pipeline stores monetary values in INR Crores. yfinance returns raw INR (×10⁷). When mixing values from both sources in a single ratio, ALWAYS use the DB value when available. The pattern is documented in `_fetch_roce_inputs` + `_fetch_current_assets`.
- **Ticker format:** Canonical form is `.NS` suffix for NSE Indian stocks. `.BO` for BSE. Bare ticker (e.g. `TCS`) is ambiguous — always canonicalize at service entry.
- **Tier gating:** JWT contains stale tier snapshot. Always refresh from `users_meta` on authed requests via `_get_fresh_tier()`. Invalidate cache on payment success.
- **Cache invalidation:** `analysis_cache.cache_version` is the safety net. Bumping `CACHE_VERSION` in backend makes every existing row a miss. Use only when changing SHARED_FIELDS values (i.e. a real data-fix shipment).
- **Razorpay subscription signatures:** NOT the Order signature scheme. Manual HMAC: `hmac.sha256(secret, f"{payment_id}|{subscription_id}")`.
- **Supabase RLS:** Backend uses service role (bypasses RLS). Client-side (Zustand-via-REST) is anon key — RLS matters there. `payg_unlocks` has a self-select policy.
- **yfinance fragility:** cookieschema UNIQUE races, delisted-ticker warnings, stale post-demerger fundamentals (TMPV.NS). Plan to replace with an official NSE/BSE feed for flagships eventually.
- **Neon cold start:** Free tier compute suspends after idle. First query wakes it up (~3-5s). Search_path event listener in `data_pipeline/db.py` ensures unqualified queries resolve on Neon.

---

## 10. Next-session suggested openers

Depending on priority:

- **"Continue Sentry triage — show me the next 30 issues after today's fixes land"** — in 24h the top-30 will look completely different. Another triage session will catch the next tier.
- **"Ship the onboarding fix + mobile Prism responsive redesign"** — biggest visible UX win
- **"Wire up the first newsletter send from the app"** — growth engine
- **"Run canary-diff locally and show me the report"** — safety check on today's merges
- **"Extend XBRL parser for NIM, CAR, NNPA, CASA"** — completes bank Prism (see `docs/bank_data_availability.md` for what data's missing and which schedules have it)
- **"Clean up the dev-only /roce-probe endpoint now that the fix is verified"**
- **"Investigate why PREMCO-X.NS and TATAGOLD-E.NS are being called — something internal is hitting them"**

---

## 11. Lessons / landmines from today

- **Always verify the Razorpay DASHBOARD ACCOUNT matches the keys on Railway.** I lost 2 hours because the user's Razorpay account was for a different business entirely ("IncredibleItinerary" instead of YieldIQ). Never assume; have the user compare Key IDs char-by-char.
- **1 vs l, 0 vs O in plan IDs — use the copy button, never retype.** Sentry even spared one event showing a typo'd plan_id.
- **Don't deploy a backend "fix" and assume it worked.** Flush cache, hit the endpoint, inspect the actual response. Multiple "fixed" claims in this session turned out to still be broken because caches were serving old data.
- **"Invalidated 0 cache rows" means the cache key doesn't exist in that form** — usually a ticker normalization mismatch.
- **Unit-mismatch bugs are invisible in code review.** The only way to catch them is end-to-end probing with real data. Build dev-only probes like `/roce-probe` early.
- **Sentry's `LoggingIntegration(event_level=ERROR)`** fires on any `logger.error()`. Downgrading legitimate-but-expected warnings (like "DCF cap applied") from ERROR to WARNING or INFO stops Sentry spam without losing observability.
- **Silent `except Exception: pass`** is the enemy. Every `pass`-ed exception today was either actively hiding a real bug or one cascade away from being hidden.
- **Don't trust a user's claim that they fixed something without verification.** "I redeployed" / "I swapped the env var" — ask for evidence (logs, dashboard screenshot, a curl response).

---

*Handoff author: Claude (2026-04-21 session, ~20 hours of continuous work)
Repo root: `E:\Projects\yieldiq_v7\`
Primary worktree used: `E:\Projects\yieldiq_v7\.claude\worktrees\gallant-cannon-645889\`
Main branch tip at handoff: `87e5b1c`*
