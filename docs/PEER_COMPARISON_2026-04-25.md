# Peer comparison audit — 2026-04-25

Competitive audit of YieldIQ vs the six peers it most directly overlaps
with in the Indian retail-investor stock-analysis market. Sources for
every peer claim are the URLs cited inline. Where a page could not be
fetched, the row is marked `verification pending` rather than guessed.

YieldIQ ground truth is taken from the live landing page
(`frontend/src/app/page.tsx`), the SEBI compliance layer
(`backend/services/analysis/sebi_filter.py`), and the merge-gate /
ticker-alias / sector-isolation docs in this repo.

---

## Executive summary

- **YieldIQ uniquely wins on transparent, editable DCF for Indian
  equities anchored to RBI 10-year G-Sec.** None of the six peers
  ship a per-stock DCF with editable WACC + 3-scenario output. The
  closest is Simply Wall St's analyst-consensus fair value, which is
  global, USD-priced, and not a true DCF the user can re-run.
- **YieldIQ uniquely loses on coverage breadth, brand trust, and
  data-product depth.** Tickertape and Trendlyne ship analyst
  consensus targets, broker recommendations, F&O/derivatives data,
  forward earnings forecasts and Excel/Google-Sheets connectors.
  YieldIQ has none of those today.
- **The one thing to copy in the next 30 days: a Tickertape-style
  scorecard strip.** Five labelled chips (Performance / Valuation /
  Growth / Profitability / Entry Point) above the analysis hero.
  YieldIQ already computes every input — the surface is missing.
- **The one thing to never copy: MoneyControl-style buy/sell calls
  with no published track record.** That path is both legally hostile
  in India (SEBI IA Regulations 2013) and brand-corrosive long-term.
  The SEBI filter (`backend/services/analysis/sebi_filter.py`) is a
  moat, not a tax.
- **Honest verdict: YieldIQ is launchable but narrow.** It is a credible
  DCF-and-quality second-screen for users who already know how to read
  Screener.in. It is not yet a one-stop dashboard. Position around the
  wedge ("editable DCF + scenario-weighted fair value, source-linked")
  rather than try to be Tickertape-but-better.

---

## Per-peer deep dive

### 1. Screener.in

The incumbent. Free hobby tier, pricing on a paid Premium tier at
₹4,999/year (per `strike.money/reviews/screener-in` and the public
`screener.in/premium/` page). Sample stock page
(`screener.in/company/RELIANCE/consolidated/`) shows tabs for Summary,
Chart, Analysis, Peers, Quarters, P&L, Balance Sheet, Cash Flow,
Ratios, Investors, Documents. **No DCF or fair value is displayed by
default.** Users can build a "DCF value" custom ratio in the screener
DSL, and there are community-maintained DCF screens
(`screener.in/screens/1476554/dcf-value-stocks/`), but per-stock
intrinsic value is not part of the page.

- **Best feature**: the screener DSL itself. 12-year historical
  fundamentals, custom ratios, peer tables — the canonical free
  fundamentals surface in India, used by everyone including YieldIQ
  users.
- **Worst flaw**: no opinionated valuation. The user is left to do the
  DCF math in their head or in Excel. The page is a data dump, not a
  model.

| Axis | Screener.in | YieldIQ |
| --- | --- | --- |
| Valuation methodology | Ratios only; DCF is user-DIY via DSL | 3-scenario DCF, editable WACC, sector-specific engines |
| Visual quality | Spartan, table-heavy, light only | Dark hero, animated demo card, scorecard ring, mobile-aware |
| Data freshness | Daily fundamentals, intraday quote | Daily prices, nightly recompute, quarterly fundamentals |
| Coverage | ~all listed NSE+BSE | ~2,900 stocks (landing claim) |
| SEBI compliance | Descriptive, no recs | Descriptive + post-filtered LLM (`sebi_filter.py`) |
| Onboarding friction | View free, login for alerts/watchlist | Login required for personal features; analysis free |
| Pricing | Free + ₹4,999/yr Premium | Free + ₹799/mo + ₹1,499/mo (per `page.tsx`) |
| Distinguishing feature | Custom screener DSL | Editable per-stock DCF with bear/base/bull |
| Weakness | No fair value, dated UI | Smaller coverage, no DSL, no Excel |

### 2. Tickertape

The polished consumer face of the Smallcase group. Sample page
(`tickertape.in/stocks/reliance-industries-RELI`) ships a five-chip
**Stock Scorecard** — Performance / Valuation / Growth / Profitability
/ Entry Point — each rendered with a verbal label ("Low / High / Good")
plus a one-line interpretation ("Seems to be overvalued vs market
average", "Stock is underpriced and not overbought"). Pricing
(per `tickertape.in/pricing`): ₹299/mo, ₹699/3mo, ₹2,399/yr.

- **Best feature**: the scorecard grammar. Five categorical chips that
  translate raw ratios into a verdict the user can scan in one second.
  This is the visual UX YieldIQ should learn from.
- **Worst flaw**: no DCF, no editable assumptions. The "Valuation"
  chip is a comparative ratio call ("vs market average"), not an
  intrinsic-value model. And the "Entry Point" / "Profitability"
  language sits at the edge of SEBI IA scope — Tickertape gets away
  with it because it's part of the Smallcase regulated entity.

| Axis | Tickertape | YieldIQ |
| --- | --- | --- |
| Valuation methodology | Comparative ratio chip | True 3-scenario DCF |
| Visual quality | Best-in-class polish, mobile-first | Strong but narrower surface |
| Data freshness | Live quotes, intra-day | Daily quotes, nightly recompute |
| Coverage | All NSE+BSE listed | ~2,900 stocks |
| SEBI compliance | Verbal labels lean advisory; covered by Smallcase IA registration | Filtered, no advisory verbs (`BANNED_WORDS` in `sebi_filter.py`) |
| Onboarding friction | View partial free, account for full | Account for personal features |
| Pricing | ₹2,399/yr Pro | ₹799/mo Analyst, ₹1,499/mo Pro |
| Distinguishing feature | Scorecard chips + Smallcase integration | Editable DCF + source-linked filings |
| Weakness | No DCF, no editable assumptions | No baskets, no broker integration |

### 3. Trendlyne

Institutional-tilt analytics product. Public stock URLs returned 404 in
this audit (`verification pending` on the per-stock page screenshot),
but the product is well-documented: **DVM scores** (Durability /
Valuation / Momentum) are the headline framework, free at the score
level, with screeners, alerts, broker target-price aggregation, Excel
and Google-Sheets connectors gated behind paid tiers. Pricing:
GuruQ ₹2,390/yr, StratQ+ ₹7,425/yr (per `strike.money/reviews/trendlyne`
and `trendlyne.com/subscription`).

- **Best feature**: broker consensus aggregation + Excel/Sheets live
  connectors. That is a serious analyst-grade workflow integration
  YieldIQ does not touch.
- **Worst flaw**: dense, jargon-heavy UI. DVM is not self-explanatory
  to a first-time user, and the per-stock pages bury the headline
  number under a wall of tables.

| Axis | Trendlyne | YieldIQ |
| --- | --- | --- |
| Valuation methodology | DVM "Valuation" ordinal score; broker target consensus | 3-scenario DCF + sector engines |
| Visual quality | Dense, table-heavy | Cleaner, opinionated hero |
| Data freshness | Live + EOD | Daily + nightly recompute |
| Coverage | All NSE+BSE | ~2,900 stocks |
| SEBI compliance | Broker recs aggregated, not authored | Filtered, no advisory verbs |
| Onboarding friction | Free score view, login for alerts | Account for personal features |
| Pricing | ₹2,390/yr GuruQ, ₹7,425/yr StratQ+ | ₹799/mo, ₹1,499/mo |
| Distinguishing feature | DVM + broker consensus + Excel connect | Editable DCF + scenario weighting |
| Weakness | Steep learning curve | No broker consensus, no Excel |

### 4. StockEdge

Research-and-scans heavy. Primary sample stock URL was unreachable
(404 on both `stockedge.com/share/...` and `web.stockedge.com/share/...`)
so per-page features are `verification pending`. From the pricing page
and reviews: 500+ predefined scans across Price/Volume/Technical/
Fundamental/Candlestick/F&O, Mutual Fund analytics, and a "Club" tier
with community access. Pricing: Premium quarterly ₹999, Club monthly
₹2,499, Club annual at ~₹39/day (per
`strike.money/reviews/stockedge` and `stockedge.com/pricing`).

- **Best feature**: the scan library. Hundreds of opinionated,
  ready-to-run technical and fundamental filters. Closest direct
  competitor to Screener's DSL but pre-baked rather than DSL-driven.
- **Worst flaw**: no per-stock fair value or DCF visible in the public
  marketing surface. Heavy on technical scans, light on intrinsic-value
  thinking.

| Axis | StockEdge | YieldIQ |
| --- | --- | --- |
| Valuation methodology | Scan-based, no DCF | True DCF |
| Visual quality | Mobile-first app, dense desktop | Dark hero + ring + chips |
| Data freshness | EOD + intra-day | Daily + nightly |
| Coverage | NSE+BSE + Mutual Funds | NSE+BSE equities |
| SEBI compliance | Club has community/expert calls — closer to advisory edge | Hard filter |
| Onboarding friction | App install + login | Web, account for personal |
| Pricing | ₹999/qtr, ₹2,499/mo Club | ₹799/mo, ₹1,499/mo |
| Distinguishing feature | 500+ pre-baked scans | Editable DCF |
| Weakness | No intrinsic-value layer | No scan library |

### 5. Simply Wall St

Global product, **the only peer in this set that ships per-stock
intrinsic value as a first-class output.** Sample page
(`simplywall.st/stocks/in/energy/nse-reliance/...`) headlines an
"analyst consensus target fair value of ₹1.73k" with a verdict
("23.3% undervalued"), plus the signature Snowflake hex chart across
six axes (Valuation, Future Growth, Past Performance, Financial
Health, Dividends, Management). Pricing: from $7.50/mo (annual) up
to $20/mo Unlimited (per `simplywall.st/plans` and
`stockunlock.com/simply-wall-st-review.html`); USD only, no INR
localised pricing surfaced.

- **Best feature**: the Snowflake. One image, six axes, instantly
  legible. The closest visual analogue to YieldIQ's score ring +
  chips, and arguably better at communicating multi-dimensional
  quality at a glance.
- **Worst flaw**: the "fair value" is **analyst consensus**, not a
  rebuilt DCF. And USD-only pricing is a real friction for Indian
  retail users who think in ₹299–₹2,400/yr SaaS bands.

| Axis | Simply Wall St | YieldIQ |
| --- | --- | --- |
| Valuation methodology | Analyst-consensus fair value (not a true rebuilt DCF on the headline) | True 3-scenario DCF, editable assumptions |
| Visual quality | Snowflake hex is best-in-class | Strong, but no equivalent multi-axis viz |
| Data freshness | Daily refresh | Daily + nightly |
| Coverage | Global incl India | India only, ~2,900 |
| SEBI compliance | Global product, descriptive | India-tuned hard filter |
| Onboarding friction | Some pages public, paywall for portfolios | Account for personal features |
| Pricing | $7.50–$20/mo USD | ₹799–₹1,499/mo INR |
| Distinguishing feature | Snowflake + global breadth | India-tuned DCF + RBI G-Sec WACC |
| Weakness | Not a true editable DCF; USD pricing | No global coverage; no Snowflake-equivalent viz |

### 6. MoneyControl Pro

The incumbent news+research portal. Per-stock URL was blocked from
fetch (`verification pending` on the page screenshot), but pricing and
feature claims are well-documented: ₹699/yr Pro, ₹2,499 Super Pro
launch tier (per `traderhq.com/moneycontrol-pro-review-...` and
`storyboard18.com/.../moneycontrol-launches-super-pro/`). Includes
MC Insights (fundamental analysis), MC Forecasts, SWOT, ~40 weekly
investment ideas, daily technical calls, and Super Pro adds
SEBI-registered "Alpha Generators" with live trading strategies plus
WhatsApp AI alerts.

- **Best feature**: distribution. MoneyControl is a verb in Indian
  retail. Anyone learning markets stumbles into it within a week.
  Pro at ₹699/yr is a near-trivial AOV to capture.
- **Worst flaw**: no published track record on its picks. The
  recommendation engine is opinion-as-content with no audit trail —
  exactly the model YieldIQ was built to refuse.

| Axis | MoneyControl Pro | YieldIQ |
| --- | --- | --- |
| Valuation methodology | SWOT + analyst calls, no transparent DCF | Transparent DCF |
| Visual quality | Ad-heavy free, cleaner Pro | No-ad, modern dark hero |
| Data freshness | Live news, live quotes | Daily + nightly |
| Coverage | All NSE+BSE | ~2,900 |
| SEBI compliance | Super Pro routes calls through SEBI-registered analysts | Hard filter, no calls authored |
| Onboarding friction | Free read, account for Pro | Account for personal |
| Pricing | ₹699/yr Pro, ₹2,499 Super Pro | ₹799/mo, ₹1,499/mo |
| Distinguishing feature | Brand reach + news firehose | Methodology transparency |
| Weakness | No published pick performance | No news, no community |

---

## YieldIQ's competitive positioning

### The wedge (one sentence)

**The only Indian-equity tool that shows you a 3-scenario DCF with
editable WACC anchored to the RBI 10-year G-Sec, and links every
input back to the filing it came from.**

That sentence is true of zero of the six peers. Screener has no DCF.
Tickertape has no DCF. Trendlyne has DVM scores but not a DCF. StockEdge
has scans, not valuation. Simply Wall St has a fair-value number but
it's analyst consensus, not a model the user can rebuild. MoneyControl
has SWOT and tips, not a methodology.

### Three features worth doubling down on (next 60 days)

1. **The "every assumption is editable" promise.** Today the landing
   page claims it; the user-facing edit affordance needs to be
   one-click obvious on every analysis page, with a "reset to model
   defaults" button. This is the wedge — operationalize it visually.
2. **Source-link integrity.** "Every number clicks through to the
   filing" is the second pillar of the wedge. Every cell in the
   analysis page should have a hover/source link to the annual report
   page or RBI release it came from. Audit and harden this until it's
   100%.
3. **Sector-specific engines.** Banks/NBFCs P/B + residual income,
   FMCG stable-growth DCF — call this out explicitly per stock
   ("Valued as: Wide-moat FMCG, stable-growth DCF"). Peers all use
   one engine for everything; this is a real and verifiable
   differentiator (`docs/SECTOR_ISOLATION.md`).

### Three features worth dropping or de-prioritising

1. **Trying to match Tickertape on F&O / derivatives / live
   intraday.** Different product, different infra cost, different user.
2. **Building a community / forum tier.** StockEdge Club already owns
   that mode and it pulls the brand toward tipster territory, which
   the SEBI filter exists to prevent.
3. **Broker integration / portfolio sync.** Trendlyne and Tickertape
   both have it; it is expensive, low-margin, and brings KYC and
   compliance load that is orthogonal to the wedge. Per the project
   roadmap memo, this is already on the cut list — keep it cut.

### Pricing positioning

YieldIQ's stated tiers (₹0 / ₹799/mo / ₹1,499/mo) sit **above** every
direct peer on a monthly-equivalent basis:

| Product | ₹/yr equivalent (paid entry) |
| --- | --- |
| MoneyControl Pro | 699 |
| Trendlyne GuruQ | 2,390 |
| Tickertape Pro (annual) | 2,399 |
| StockEdge Premium (annual ~) | ~3,996 |
| Screener Premium | 4,999 |
| Trendlyne StratQ+ | 7,425 |
| **YieldIQ Analyst** | **9,588** |
| **YieldIQ Pro** | **17,988** |
| Simply Wall St (Unlimited, USD→INR @ ₹84) | ~20,160 |

This is defensible only if the wedge is narrated explicitly. The
target user is not the ₹699/yr MoneyControl reader — it's the user
already paying for Screener Premium AND building DCFs in Excel,
who would happily pay ₹799/mo to skip the spreadsheet. Speak to that
buyer or compress the Analyst tier toward ₹399/mo.

---

## Quick wins to ship in week 1 post-launch

Each is small enough to land in a single PR, scoped to close an
obvious gap a peer-comparing user would notice in the first 30
seconds on the analysis page.

1. **Scorecard strip above the hero (4–6 hours).**
   What: a Tickertape-style row of 5 chips — Valuation / Quality /
   Growth / Safety / Momentum — derived from existing scores.
   Why: every peer (Tickertape, Trendlyne, Simply Wall St) leads with
   a one-glance verdict strip. YieldIQ has the inputs, not the chip.
2. **"Valued as" engine tag on the hero (1–2 hours).**
   What: a small label like `Engine: Wide-moat FMCG · Stable-growth
   DCF · WACC 11.4%` next to the fair value number.
   Why: makes the sector-specific engine visible — a wedge feature
   currently invisible to first-time visitors.
3. **Inline source-link icons on every key cell (1 day).**
   What: small filing-link icons on Revenue, EBITDA, Net Profit,
   D/E rows that click through to the source.
   Why: the landing page promises this; the analysis page should
   actually deliver it on every cell, not just some.
4. **"Edit assumptions" CTA pinned to the DCF block (2–4 hours).**
   What: a sticky "Edit WACC / growth / margin" button visible
   without scrolling, opening an inline drawer.
   Why: the wedge is editability. Today it requires hunting.
5. **Plan-ladder context strip on /pricing (2 hours).**
   What: a small comparison row showing where competitor pricing
   sits and what YieldIQ adds.
   Why: ₹799/mo looks expensive in isolation; in context next to
   "Screener has no DCF, Tickertape has no DCF, Simply Wall St is
   $9/mo", it reads as honest.
6. **Demo-card autoplay seeded from canary-50 (2 hours).**
   What: the homepage `DemoCard` already cycles four hardcoded
   tickers — promote the live `/api/v1/public/demo-cards` payload
   to draw from the canary-50 instead of `FALLBACK_CARDS`.
   Why: more visible diversity → less "this is just a 4-stock toy"
   read on first impression.
7. **Snowflake-style mini hex on the analysis hero (1 day).**
   What: a small 5-axis radial chart (Valuation / Quality / Growth /
   Health / Moat) — the same idea Simply Wall St uses, scaled down.
   Why: Simply Wall St's Snowflake is the most-copied viz in equity
   research for a reason — it makes "good in some ways, weak in
   others" legible in one image.
8. **"Why it's different" strip on every analysis page footer
   (2 hours).**
   What: a 3-line strip — "DCF anchored to 10-yr G-Sec · Editable
   assumptions · Source-linked filings" — on every analysis result.
   Why: carries the wedge from marketing into the product surface,
   where most peer-curious users actually are.
9. **Public peer-comparison page on the marketing site (4 hours).**
   What: a `/vs` page or `/compare` table showing this audit's
   findings publicly (minus internal numbers).
   Why: searchable inbound. Users who Google "YieldIQ vs
   Screener" should land on a page YieldIQ owns.
10. **Bear/base/bull share-card image (1 day, reuses Satori
    pipeline).**
    What: a Twitter/WhatsApp-shareable PNG with the ticker, ring
    score, and the bear/base/bull triplet.
    Why: organic distribution; the demo card already has the design.

---

## Sources

- Screener.in: <https://www.screener.in/company/RELIANCE/consolidated/>,
  <https://www.screener.in/premium/>,
  <https://www.strike.money/reviews/screener-in>
- Tickertape: <https://www.tickertape.in/stocks/reliance-industries-RELI>,
  <https://www.tickertape.in/pricing>
- Trendlyne: <https://www.strike.money/reviews/trendlyne>,
  <https://trendlyne.com/subscribe/>,
  <https://trendlyne.com/product-details/>
- StockEdge: <https://stockedge.com/pricing>,
  <https://www.strike.money/reviews/stockedge>,
  <https://blog.stockedge.com/stockedge-club-features/>
- Simply Wall St: <https://simplywall.st/stocks/in/energy/nse-reliance/reliance-industries-shares>,
  <https://simplywall.st/plans>,
  <https://stockunlock.com/simply-wall-st-review.html>
- MoneyControl Pro: <https://traderhq.com/moneycontrol-pro-review-expert-insights-smart-investors/>,
  <https://www.storyboard18.com/brand-marketing/moneycontrol-launches-super-pro-an-ultra-premium-intelligence-led-markets-product-72881.htm>
