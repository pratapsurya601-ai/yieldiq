# Reddit launch draft v2 — r/IndianStockMarket (2026-05-26)

Phase J-reddit. Refresh of the earlier
`docs/marketing/reddit-post-draft-2026-05-22.md` (v1, the NTPC
bear-floor bug post-mortem). v1 targeted r/IndiaInvestments and was
a technical bug post-mortem. v2 targets r/IndianStockMarket — broader
audience, higher volume — and frames the tool around the depth that
shipped in Block II Phases F/G/H/I (10-year historical data, concall
AI summarization, AR structured extraction, transparent score
breakdown).

Both posts are kept. v1 can still be cross-posted to
r/IndiaInvestments where the technical-audit tone fits better; v2 is
the broader launch post.

---

## Post

**Subreddit:** r/IndianStockMarket
**Account requirement:** at least 50 comment karma, account age
≥ 60 days (sub rule, verify before posting).
**Suggested post time:** weekday 09:30–10:30 IST (market open, sub
activity peaks).
**Title (under 300 chars):**

> I built a free DCF tool for Indian stocks that shows every number's source — 10y financials, concall AI summaries, and the actual score breakdown. Looking for hard cases that break it.

**Body (target ~900 words, under 40k chars):**

---

Hi r/IndianStockMarket. I run a free valuation tool for Indian stocks
at yieldiq.in and we've reached the point where the model is dense
enough that I want to put it in front of people who'll genuinely try
to break it. Not asking anyone to use it, asking technically-minded
investors to throw their hardest case at it.

Quick context on what it actually does, then what's behind it, then
what I want from you.

**What it shows**

For any of ~2,300 NSE/BSE-listed stocks you get:

- A 3-scenario DCF (bear / base / bull) with the explicit fair-value
  rupee numbers, not a single point estimate that hides the
  uncertainty.
- Margin of safety vs. today's price.
- A YieldIQ score (0–100) and letter grade, blended from valuation,
  quality, moat, and safety.
- The 9-point Piotroski F-score on every stock, plus a moat
  classification (Wide / Narrow / None) based on a sector-aware
  rubric.
- A 2-sentence AI summary of what actually matters about the
  business, generated from the latest filings (not a press release
  rewrite).

The free tier is 5 deep analyses per day. No card required to sign
up. Browsing and the prism view are free without an account at all.

**What's behind it (the parts I'm proud of)**

This is the part that took the most work, and it's the part I'd most
like the sub to poke at.

- **10-year financials, source-linked.** Every revenue, EBITDA, debt
  number on the analysis page clicks through to the filing it came
  from. AR, quarterly results, RBI data for banks. If a number on
  the screen disagrees with the filing, that's a bug and I want to
  know.
- **Concall AI summarization.** We pull conference-call transcripts
  for ~1,200 companies and run an extractive + abstractive summary
  pipeline that pulls out what management actually said about
  capex, demand, margins, and forward commentary. Not action
  calls — what the CEO actually said, in 6 bullet points, with
  attribution.
- **Annual report structured extraction.** ARs are PDFs that change
  layout every year per company. We run a structured-extraction
  pipeline that pulls capex breakdown, segment revenue, related-party
  transactions, and contingent liabilities into a table you can
  read in 15 seconds instead of 90 minutes.
- **Score breakdown transparency panel.** Every component of the
  0–100 score is itemized. You can see exactly how much DCF
  contributed, how much Piotroski contributed, how much moat
  contributed. If you disagree with the weighting, you can re-run
  with your own weights.
- **Per-sector models.** Banks and NBFCs use P/B with residual-income
  logic. FMCG uses stable-growth DCF. Utilities have rate-base
  flooring on the bear case (we shipped this after a bug made
  NTPC's bear case read as ₹0 — write-up on r/IndiaInvestments if
  you want the gory details).
- **Indian risk-free rate.** WACC anchored to the 10y G-Sec from RBI
  data, not the US Treasury. ERP and terminal growth calibrated to
  Indian markets, not ported from a Damodaran US template. This
  changes fair value materially for capex-heavy names.

**What I want from you**

Two specific asks.

1. **Find a case where the fair value is wrong.** Pick the stock you
   know best — your largest holding, the one you've modelled
   yourself, a sector you've worked in. Run it. If the bear / base /
   bull numbers diverge meaningfully from what you'd compute by
   hand, tell me in the comments or via the in-app feedback. I read
   every report and we ship fixes within 24 hours when they're
   correct.

2. **Find a number that doesn't match the source.** Click any number
   on the analysis page. It opens the filing. If the number on
   the screen doesn't match what's in the filing, that's a bug I
   want to know about before more users see it.

**What I'm not going to do**

- I'm not going to tell you what action to take. The tool is
  descriptive. It says "this DCF model produces this fair value
  under these assumptions" — what you do with that is your own
  call.
- I'm not registered with SEBI as an investment adviser, and the
  tool isn't going to pretend otherwise. Every page carries the
  disclaimer.
- I'm not going to add a Telegram channel, an alerts system that
  pings you when a stock crosses some threshold framed as a call
  to action, or any other feature that lives in the "tipster"
  category. That's not the product.

**Pricing**

Free tier is 5 analyses/day, all features included. Paid is ₹799/mo
(unlimited + portfolio + saved scenarios) or ₹1,499/mo (CSV/PDF
export + API + priority compute). Browsing and the prism view are
free without an account.

**Where to start**

yieldiq.in — search any ticker. Try your largest holding first;
you'll see what we mean by source-linked. Or pick a name where the
analyst consensus diverges (mid-cap pharma, capex infra, anything
REIT-adjacent) and see whether the model lands in a sensible place.

If you find a bug, my DMs are open or the in-app feedback button
goes to me directly. Thanks for reading.

---

*Edit: to be clear — all numbers on the tool are model outputs from
publicly available data. They are not investment advice or
recommendations. Do your own work.*

---

## SEBI-safe vocabulary check

The post body, FAQ replies, and checklist were scrubbed against the
discipline-rules banned-vocab list (action verbs, conviction
adjectives, prescriptive modal verbs, and the comparative-rating
lexicon). A regex grep over this file returns no matches in any
prose section.

Words used instead: fair value, scenario, bear / base / bull, model
output, classification, margin of safety, descriptive.

---

## 5 anticipated FAQ replies (pre-drafted)

These are the questions I expect to be asked in the thread within
the first 2 hours. Pre-drafted so I'm not typing under pressure.

### FAQ-1: "Isn't this just Screener.in with extra steps?"

> Screener.in is a brilliant data layer — I use it daily. The
> difference is that Screener gives you the numbers; we give you
> the valuation model on top of those numbers. You can see "ROCE
> 18% / debt-to-equity 0.4" on Screener, but Screener doesn't tell
> you what the stock is worth under a 12% WACC and 6% terminal
> growth. We do, scenario by scenario, with every input editable.
> The two tools are complementary, not competitive.

### FAQ-2: "How is your data better than yfinance / TickerTape?"

> Honest answer — for the basic price + ratio fields, it isn't. We
> use NSE / BSE / RBI as primary sources and have a yfinance
> fallback for fields where the primary feed is patchy. The
> differentiation is in the derived stuff: 10y reconstructed
> financials with source links, concall summarization, structured
> AR extraction. None of those exist in TickerTape today.

### FAQ-3: "Why trust a DCF? Garbage in, garbage out."

> Right — which is why every assumption is editable. Don't trust
> our WACC of 11%? Change it. Don't trust the 5% terminal growth?
> Change it. The point of the DCF is not to give you a "true"
> fair value (there isn't one); it's to make the assumptions
> visible so you can challenge them. A DCF you can't change is a
> black box. A DCF you can change is a thinking tool.

### FAQ-4: "What about banks / NBFCs / insurance? DCF doesn't work for them."

> Correct. We don't use DCF for them. Banks and NBFCs use a P/B
> model with residual income logic and a CET1 floor. Insurance
> uses an embedded-value approach. The engine picks the right
> model for the sector. You'll see this in the methodology page
> and in the score-breakdown panel for the specific stock.

### FAQ-5: "Is this SEBI registered? Why trust an unregistered tool?"

> No, not SEBI-registered, and the disclaimer says so on every
> page. We don't give action-oriented calls, we don't run a
> Telegram channel, we don't take payment for tips. We're a
> descriptive model — closer to a calculator than an advisory
> service. SEBI registration is required for advisers; we're
> explicitly not one. If you want an adviser, hire an RIA.

---

## Pre-launch checklist

Run through this BEFORE the post goes live. All boxes must be
ticked.

### Account / sub rules

- [ ] Posting account has ≥ 50 comment karma (sub rule).
- [ ] Posting account is ≥ 60 days old (sub rule).
- [ ] Sub rules re-read within last 24h — no rule changes since
  draft. (Self-promo allowed iff substantive content + flair
  appropriately as "Discussion" not "Promotion".)
- [ ] Post flair set to "Discussion" not "Promotion" not
  "Educational".

### Product readiness

- [ ] yieldiq.in homepage loads in < 2s on mobile 4G (run real
  Lighthouse).
- [ ] /search returns results for "reliance" / "tcs" / "hdfc"
  within 300ms.
- [ ] Anon /analysis/RELIANCE.NS renders without auth wall.
- [ ] Every "data source" link on the analysis page actually
  opens a filing — spot check 3 random tickers.
- [ ] Phase J-copy-1 changes deployed (no stale FALLBACK_CARDS
  prices, "Refreshed each evening" copy live).
- [ ] /legal/disclaimer matches landing footer exactly.
- [ ] Status page (yieldiq.in/status) shows all-green.
- [ ] Sentry alert for /analysis/* P95 > 3s is armed.
- [ ] Session-observation harness (Phase J-obs) deployed — we
  can replay first-100-user sessions for debugging.

### Comment-seeding plan

3 honest, non-shilly comments to drop in the first hour, from the
posting account (no sockpuppets):

1. Direct reply to first commenter who asks "what's different"
   — link the methodology page.
2. Top-level comment with a concrete example: "Try TATAMOTORS — the
   bear/base/bull spread is genuinely wide because of the JLR
   cyclicality, and the model shows you why."
3. Top-level comment with the bug bounty: "If anyone finds a fair
   value that's off by > 25% from what you'd compute by hand, I
   ship a fix within 24h or we don't deserve your trust. DM me."

### Post-launch monitoring (first 4 hours)

- [ ] Refresh thread every 15 min, reply to every comment within
  30 min.
- [ ] Monitor admin /session-traces endpoint for spike traffic +
  any errors first-time users hit.
- [ ] Monitor Sentry for any new error class triggered by the
  traffic.
- [ ] Monitor Railway worker queue depth — if it backs up, scale
  before users see degraded analysis times.
- [ ] If post gets removed by mods, DO NOT re-post. DM mods,
  ask why, fix, try again next week.

### Kill criteria

If any of these happen in the first 30 min, **delete the post and
return tomorrow**:

- Backend P95 latency > 5s on /analysis/*
- Any 500 rate > 1% on any public endpoint
- Sentry firing on a new error class triggered by the traffic
- DB connection pool saturation
