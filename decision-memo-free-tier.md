# Decision memo — Free tier v2

**Branch:** `policy/free-tier-v2`
**Author:** agent (free-tier redesign)
**Date:** 2026-04-22
**Status:** proposal for user review — NOT merged to main

---

## 1. Current state (evidence, with cites)

### 1a. Enforcement — it's 5/**day**, not 5/month

The peer audit flagged "5 analyses / month" as the cap. That is **what the
pricing page advertises** but it is **not** what the backend enforces.

- `backend/middleware/rate_limit.py:12-17` — `TIER_LIMITS = {"free": 5, ...}`
- `backend/middleware/rate_limit.py:28` — key is `f"{user_id}:{date.today().isoformat()}"` — **per-day, resets at UTC midnight**.
- `backend/middleware/rate_limit.py:10` — docstring: "Daily rate limiter per user. Resets at midnight UTC."
- `backend/middleware/auth.py:53` — duplicate constant: `TIER_LIMITS = {"free": 5, ...}`.
- `backend/middleware/auth.py:231-259` — `check_analysis_limit` raises 429 "Daily analysis limit reached".

So the real quota today is:

> **Free users get 5 full deep analyses per UTC day, on `/api/v1/analysis/{ticker}` only.**

Everything else is already effectively unlimited for free users:

- `/api/v1/prism/{ticker}` — public, no auth gate, no rate limit
  (`backend/routers/prism.py:35`, dependencies list is empty).
- `/api/v1/public/stock-summary/{ticker}` — public
  (`backend/routers/public.py:22`).
- `/api/v1/public/demo-cards`, search, screener — public.
- Other `/analysis/*` sub-routes (`/analysis/{ticker}/scenarios`,
  `/similar-stocks`, `/historical-fv`, etc.) use
  `get_current_user_optional`, i.e. **no rate-limit enforcement** —
  only the main `/analysis/{ticker}` entry point is throttled
  (`backend/routers/analysis.py:930, 1085, 1191, 1257, 1305, 1402`).

### 1b. Frontend promises (mismatch)

- `frontend/src/app/page.tsx:198` — pricing teaser card:
  `tagline: "5 analyses a month. All core features."`  ← **wrong word**
- `frontend/src/app/(marketing)/pricing/page.tsx:76` — feature matrix:
  `"5 full analyses per month"`  ← **wrong word**
- `frontend/src/app/(app)/home/page.tsx:53` — in-app empty state:
  `"You've used all 5 analyses today"` ← correct day-scoped wording
- `frontend/src/components/layout/AnalysisCounter.tsx:26` — "X/5 analyses today"
- `frontend/src/components/layout/DesktopNav.tsx:76` — "X/5"
- `frontend/src/app/(app)/account/page.tsx:254` — "X/5 analyses today"
- `frontend/src/lib/constants.ts:12` — `TIER_LIMITS = { free: 5, ... }`
- `frontend/src/store/authStore.ts:21` — default `analysisLimit: 5`
- `frontend/src/store/paygStore.ts:4` (comment) — "Free tier gets 5 analyses / day."

Hero-section copy that IS currently accurate:

- `frontend/src/app/page.tsx:246-248` — "2,900 stocks · Free DCF · 30s per analysis"
- `frontend/src/app/page.tsx:267` — "No sign-up needed"
- `frontend/src/app/page.tsx:234` — CTA "Analyse any stock free"
- `frontend/src/app/page.tsx:396` — CTA "Analyse your first stock free"

The hero doesn't promise "month" vs "day" — the problem sits inside the
pricing teaser and the full pricing page.

---

## 2. Problem (the funnel leak)

Peer audit reading: **"5 analyses / month is a top-of-funnel killer."**
Against the Indian peer set:

| Peer           | Free snapshot                                               | Free deep        |
|----------------|-------------------------------------------------------------|------------------|
| Screener.in    | Unlimited peer/snapshot views (all 5000+ Indian tickers)    | Unlimited basic  |
| Tickertape     | Unlimited Scorecard + snapshot views                        | ~Unlimited       |
| Moneycontrol Pro | Fully paywalled beyond headline                          | 0                |
| **YieldIQ today** | **Unlimited Prism/snapshot (good!)** | **5 / day, AND messaged as 5/MONTH** |

The backend is already generous (5/day is materially better than
5/month), but the **messaging** tells new visitors it is 5/month — which
is stingier than Screener/Tickertape and closer to Moneycontrol's paid
wall. We get the funnel damage of stinginess without having actually
been stingy in code.

Two separate problems, one fix:

1. **Copy lies to the user.** "5/month" signals this is not a tool
   they can actually use; they bounce before realising it's 5/day.
2. **5/day is still tighter than Screener/Tickertape** for a deep-DCF
   tool. A retail investor evaluating 3 stocks across a weekend runs
   out on Sunday morning.

---

## 3. Proposed policy — Free tier v2

Target: **match Screener/Tickertape on "looking around is free"; gate
only the things competitors actually charge for.**

### 3a. Anonymous (no login)

Unlimited, no auth:

- `GET /api/v1/prism/{ticker}` — already public, keep public
- `GET /api/v1/prism/compare` — already public, keep public
- `GET /api/v1/public/stock-summary/{ticker}` — already public
- `GET /api/v1/public/demo-cards` — already public
- Search + screener query — already public

**Change:** none. The anon surface is already correct.

### 3b. Authed free (existing `tier: "free"`)

| Quota                                      | Today       | Proposed    |
|--------------------------------------------|-------------|-------------|
| Full deep analyses (`/analysis/{ticker}`)  | 5 / day     | **3 / day** |
| Prism views                                | unlimited   | unlimited   |
| Watchlist size                             | 10 stocks   | 10 stocks   |
| Portfolio / broker imports                 | 1 / 1       | 1 / 1       |
| Alerts                                     | none        | none        |
| AI narrative (Groq long-form)              | included    | **gated**   |
| Reverse DCF                                | included    | **gated**   |
| Scenario tweaks (custom WACC/growth)       | included    | **gated**   |
| Historical fair-value chart (12m)          | 30d snippet | **30d only** |
| 10-yr financials                           | 3-yr        | **3-yr only**|
| Concall AI summaries                       | locked      | locked      |
| Tax report, CSV/PDF export                 | locked      | locked      |

Why **3 / day** and not "unlimited deep":

- Deep analysis triggers a full DCF compute + Groq/Gemini call (cold
  ~30s, warm via cache). It's genuinely our most expensive path.
- 3/day × 30 days = 90/month, vs Moneycontrol Pro's 0/month and vs
  our current effective 150/month — still materially more generous
  than the audit-flagged "5/month" perception.
- The **narrative+reverse-DCF+scenarios** paywall (not the count)
  becomes the real upgrade trigger. Count is just a soft nudge.
- This matches the peer audit's recommendation verbatim:
  **"unlimited views of current snapshot + fair value band, gate
  historical FV, AI narrative, reverse DCF, and scenario tweaks
  behind paywall."**

### 3c. Analyst (₹799/mo) — unchanged pricing

- Unlimited deep analysis
- AI narrative (Groq long-form) — **now a paid trigger**
- Reverse DCF — **now a paid trigger**
- Custom scenario tweaks — **now a paid trigger**
- Full 12-month Time Machine (historical FV)
- 10-yr financials
- Peers / compare (3 side-by-side)
- Portfolio Prism + Portfolio Health
- Concall AI summaries
- Tax Report
- Unlimited watchlist + alerts
- 5 broker accounts

### 3d. Pro (₹1,499/mo) — unchanged pricing

Everything in Analyst, plus:

- Alerts (price, valuation, earnings)
- Excel/CSV/PDF export of any analysis
- API access (100 req/day)
- Priority concall processing
- Save + share custom screens
- 10 broker accounts
- Earnings-day morning digest
- Compare up to 5 stocks
- Beta ring (early features)

---

## 4. Rationale — peer-by-peer

**Screener.in.** Gives unlimited snapshot + ratios + peers for free.
Our Prism matches on volume (unlimited anon) but adds live DCF they
don't have. Our moat vs Screener is valuation, not gating.

**Tickertape.** Scorecard free, Basket/Pro locked. Same pattern.

**Moneycontrol Pro.** Hard paywall. Bad model for us — we aren't
a brand retail already trusts, so a Moneycontrol-style wall keeps
discovery at zero.

**Our differentiator.** Fair value with scenario ranges, AI narrative,
reverse DCF. Nobody else gives these on Indian stocks. Paywalling
**these** (and not the snapshot) is how competitors like Seeking Alpha
structure Pro vs free — discovery is open, *interpretation* is paid.

---

## 5. Rollback plan

### Trigger

Revert if any of the following within 7 days of deploy:

- Signup rate drops >15% vs the 7-day baseline BEFORE this change
- `/api/v1/analysis/{ticker}` 429 rate doubles (the tighter daily
  cap hits users worse than expected — they churn rather than upgrade)
- Support tickets mentioning "I used to get 5, why only 3" exceed
  5 in a week

### Revert recipe

```bash
# On the production branch (main), after this lands there:
git revert <merge-sha>          # one atomic revert
# OR surgically, bump just the one constant back:
#   backend/middleware/rate_limit.py:13  "free": 3  →  "free": 5
#   backend/middleware/auth.py:53        "free": 3  →  "free": 5
#   frontend/src/lib/constants.ts:12      free: 3   →  free: 5
#   frontend/src/store/authStore.ts:21    analysisLimit: 3  →  5
#   plus the two copy lines below (hero, pricing page)
```

No DB migrations, no cache key rotation, no environment-variable
surgery. Rate limiter is in-memory per worker — the change takes effect
on the next Railway restart (automatic on merge).

---

## 6. Implementation touch points

**Backend (constant change, no logic refactor):**

- `backend/middleware/rate_limit.py:13` — `"free": 5` → `"free": 3`
- `backend/middleware/auth.py:53` — `"free": 5` → `"free": 3`
  (duplicate constant — both are read in different paths, both must
  match or `/auth/me` will report a different limit than the enforcer.)

**Frontend (constant + copy):**

- `frontend/src/lib/constants.ts:12` — `free: 5` → `free: 3`
- `frontend/src/store/authStore.ts:21` — `analysisLimit: 5` → `analysisLimit: 3`
- `frontend/src/app/page.tsx:198` — pricing teaser tagline:
  `"5 analyses a month. All core features."` →
  `"3 deep analyses per day. Unlimited Prism snapshots."`
- `frontend/src/app/page.tsx:246-249` — stats strip:
  `"Free DCF" · "30s per analysis"` →
  `"3 deep analyses/day free" · "Unlimited Prism"`  (optional polish)
- `frontend/src/app/(marketing)/pricing/page.tsx:76` — feature row:
  `"5 full analyses per month"` →
  `"3 full analyses per day (90+/month)"`
- `frontend/src/app/(app)/home/page.tsx:53` — empty state:
  `"You've used all 5 analyses today"` → `"You've used all 3 analyses today"`
  (actually: frontend reads `analysisLimit` from server so this is
  already dynamic — but the hard-coded "5" string here needs to go.)
- `frontend/src/components/layout/AnalysisCounter.tsx` — already uses
  `TIER_LIMITS[tier]`, no change needed; display flips automatically.
- `frontend/src/components/layout/DesktopNav.tsx` — same, no change.
- `frontend/src/store/paygStore.ts:4` — comment update `5 / day` → `3 / day`.

**NOT touched (deliberate out-of-scope):**

- Auth store + session logic (hard constraint)
- Tier rename (hard constraint — stays "free"/"analyst"/"pro")
- Razorpay / billing wiring (pricing unchanged)
- Prism router, public router (already correct — unlimited anon)
- AI narrative / reverse DCF / scenarios route wiring — **paywalling
  these is a separate PR.** This PR is the quota change and messaging.
  See §7.

**No backend services/ or backend/routers/ touched → canary-diff not
required under `CLAUDE.md` rule 1** (that rule scopes to
`backend/services/`, `backend/routers/`, `backend/validators/`,
`backend/models/`, `scripts/canary_stocks_50.json`). Middleware is
explicitly outside that list. Still safe to run canary before merge
as a sanity check.

---

## 7. What this PR does NOT do (deferred)

The audit asked for paywalls on AI narrative, reverse DCF, scenario
tweaks, and historical FV depth. Those require adding `Depends(require_tier("analyst"))`
to specific sub-routes:

- `POST /api/v1/analysis/{ticker}/rewrite` (AI narrative) — `backend/routers/analysis.py`
- Reverse DCF endpoint — needs identification
- Scenario tweak endpoint — needs identification
- Historical FV depth cutoff — needs service-level guard

These are **policy decisions, not just constant flips**. They need
a separate PR with:

- Explicit list of which sub-routes to gate
- Graceful 402-style "upgrade required" response shape
- Frontend upgrade nudge UI

**This PR intentionally stops at the quota + messaging change** so
the user can review the policy direction before we gate endpoints.

---

## 8. Open questions for user

1. **Is 3/day the right number** or does the user want 5/day (just
   drop the "month" lie) or 10/day (get generous)?
2. **Should we narrow the cap at all** or is the whole fix just
   "correct the pricing copy from month → day" and keep 5/day?
3. **Timing of the paywall PR** — land quota change first, then
   AI/reverse-DCF gates? Or all together?

I've implemented **3/day** per the task spec. If the user picks a
different number at review, it's two constants (`rate_limit.py:13`,
`auth.py:53`) plus the mirror in `frontend/src/lib/constants.ts:12`
and the one default in `frontend/src/store/authStore.ts:21`, plus the
three copy strings. ~10-minute change.
