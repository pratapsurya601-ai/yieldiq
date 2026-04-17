// frontend/src/lib/blog.ts
// ═══════════════════════════════════════════════════════════════
// Blog post data — markdown content + metadata.
// SEBI-safe: educational content only, no buy/sell recommendations.
// ═══════════════════════════════════════════════════════════════

export interface BlogPost {
  slug: string
  title: string
  description: string
  date: string  // ISO YYYY-MM-DD
  author: string
  category: "valuation" | "fundamentals" | "tax" | "framework" | "guide"
  readTime: number  // minutes
  content: string  // markdown
}

export const BLOG_POSTS: BlogPost[] = [
  {
    slug: "what-is-dcf-valuation",
    title: "What is DCF Valuation? A Plain English Guide for Indian Investors",
    description: "Understand Discounted Cash Flow (DCF) valuation — the technique used by Warren Buffett, hedge funds, and YieldIQ. Learn how to estimate what a stock is really worth.",
    date: "2026-04-10",
    author: "YieldIQ Team",
    category: "valuation",
    readTime: 7,
    content: `## The 30-second answer

DCF (Discounted Cash Flow) is a way to figure out what a business is **really worth today** based on the cash it will produce in the future.

Imagine your friend asks you to lend ₹100 today and promises to pay you ₹110 next year. Would you do it? It depends on:

1. How confident are you that he'll pay back? (**risk**)
2. What else could you do with that ₹100? (**opportunity cost**)
3. Will inflation eat into the ₹110? (**time value of money**)

DCF does the same thing for stocks. We estimate the future cash flows of a business, then discount them back to today's value.

---

## The formula (don't panic)

$$\\text{Fair Value} = \\sum_{t=1}^{n} \\frac{\\text{FCF}_t}{(1 + r)^t} + \\frac{\\text{Terminal Value}}{(1 + r)^n}$$

In plain English:
- **FCF** = Free Cash Flow (cash left after the business pays for everything)
- **r** = Discount rate (your required return — typically 10-13% for Indian stocks)
- **n** = Number of years we forecast (usually 10)
- **Terminal Value** = What the business is worth at the end of year 10 if it lives forever

---

## Why DCF matters more in India

Indian stocks have wider valuation ranges than US stocks. The same FMCG company can trade at 30× P/E in 2021 and 50× P/E in 2024 with no fundamental change. Multiples lie. Cash flows don't.

DCF forces you to ask: **"Does the future cash this business generates actually justify the current price?"**

Often the answer is no. Sometimes it's yes. That's what makes DCF useful.

---

## What DCF gets RIGHT

✅ **Forces honest assumptions.** You have to write down what growth you expect, what margins, what discount rate. No hand-waving.

✅ **Anchored to reality.** Cash flows are real. Earnings can be manipulated. EBITDA can be massaged. FCF is what's left after capex and working capital.

✅ **Works across industries.** Same framework for HUL (FMCG), TCS (IT), and Reliance (oil + retail + telecom).

---

## What DCF gets WRONG

❌ **Garbage in, garbage out.** If you assume 25% growth forever, the model says fair value is ₹10,000. That doesn't mean buying at ₹500 is a steal — it means your assumptions are unrealistic.

❌ **Sensitive to discount rate.** Move WACC from 11% to 13% and fair value can drop 30%. Small inputs, big outputs.

❌ **Useless for early-stage companies.** A 2-year-old startup with negative cash flow can't be DCF'd meaningfully.

❌ **Banks and insurance are different.** They have leverage built into the business. Use Dividend Discount Model or P/B for these instead.

---

## How YieldIQ does DCF

We make it easy:

1. **Pull historical FCF** from the last 5 years of audited financials
2. **Forecast 10 years forward** using historical growth, sector benchmarks, and analyst consensus
3. **Add terminal value** assuming 3-4% perpetual growth (slightly above India's long-run inflation)
4. **Discount at WACC** — calculated from your stock's beta, India's risk-free rate, and a 6% equity risk premium
5. **Subtract net debt** to get equity value, divide by shares outstanding

Then we compare it to current market price → that's your **Margin of Safety**.

---

## Try it yourself

Pick any Indian stock you own. Open its [analysis page on YieldIQ](/search) and see:
- The DCF fair value
- Bear / Base / Bull scenarios
- The exact assumptions (WACC, growth rate, terminal growth)
- Reverse DCF — what growth is the market pricing in?

If the implied growth is wildly higher than the company's history, the stock is priced for perfection. If it's lower, you might have margin of safety.

---

## Disclaimer

DCF is a model, not a crystal ball. The output is only as good as the assumptions. Always combine valuation with quality (does the business have a moat?), risk (how leveraged is it?), and your own judgment.

YieldIQ is not registered with SEBI as an investment adviser. This article is educational, not investment advice.
`,
  },
  {
    slug: "piotroski-f-score-explained",
    title: "Piotroski F-Score: The 9-Point Quality Test for Indian Stocks",
    description: "Learn how Joseph Piotroski's F-Score helps separate quality value stocks from value traps. The 9 questions every investor should ask.",
    date: "2026-04-08",
    author: "YieldIQ Team",
    category: "fundamentals",
    readTime: 6,
    content: `## What is the Piotroski F-Score?

In 2000, accounting professor Joseph Piotroski published a paper showing that **a simple 9-point financial test** could separate winning value stocks from losing ones. His backtest beat the market by 7.5% per year.

23 years later, his test still works — and it's especially useful in India where many stocks look cheap on P/B but are actually deteriorating businesses.

---

## The 9 Questions

For each, the company gets **1 point if YES**, 0 if NO. Total: 0 to 9.

### Profitability (4 points)

1. **Is Net Income positive this year?**
   The company is making money.

2. **Is Operating Cash Flow positive?**
   Profits are real, not accounting fiction.

3. **Is ROA improving vs last year?**
   The business is becoming more efficient with assets.

4. **Is Operating Cash Flow > Net Income?**
   No earnings manipulation. Real cash backs up reported profits.

### Leverage / Liquidity (3 points)

5. **Is long-term debt lower than last year?**
   Balance sheet is getting safer, not riskier.

6. **Is Current Ratio improving?**
   Short-term liquidity is healthier.

7. **Is Share Count NOT increasing?**
   No dilution from new equity issues.

### Operating Efficiency (2 points)

8. **Is Gross Margin improving?**
   Pricing power or cost discipline is improving.

9. **Is Asset Turnover improving?**
   Sales per ₹ of assets is going up.

---

## Score Interpretation

| F-Score | What it means |
|---|---|
| **8-9** | **Top quality.** Improving across the board. |
| **6-7** | **Good.** Solid fundamentals, mostly improving. |
| **4-5** | **Average.** Mixed signals. |
| **2-3** | **Weak.** Multiple deteriorating metrics. |
| **0-1** | **Avoid (data shows distress).** Most metrics getting worse. |

---

## Why F-Score is Especially Powerful in India

Indian small and mid caps often look cheap on traditional metrics:
- Low P/E
- Low P/B
- "Asset-rich" balance sheet

But many are **value traps** — businesses in structural decline, with hidden liabilities, or with promoters extracting value through related-party transactions.

F-Score catches these because it focuses on **trends** (is the business getting better or worse?) not levels.

A small-cap textile mill at P/B 0.5 sounds cheap. But if its F-Score is 2 — gross margins falling, debt rising, ROA declining — it's cheap for a reason.

---

## How to use F-Score with YieldIQ

Every stock analysis page on YieldIQ shows the Piotroski F-Score prominently:
- **8-9 points**: Look for these in our [High Piotroski filter](/screens/high-piotroski)
- **Combine with Margin of Safety**: A high F-Score AND undervalued = classic Buffett setup
- **Watch the trend**: A stock that went from F-Score 7 → 4 over 3 years is sending warning signals

---

## A real Indian example

In 2020, **Adani Enterprises** had:
- ROA negative
- Long-term debt rising
- Operating cash flow negative

F-Score: 2.

In 2024 (after the Hindenburg saga and recovery):
- ROA positive and improving
- Some deleveraging
- OCF turned positive

F-Score: 6.

The F-Score captured both phases factually — without taking a view on the business. Investors who used it had a quantitative way to see the change.

---

## What F-Score MISSES

❌ **Doesn't measure valuation.** A high-quality company at 80× P/E is still expensive.

❌ **Doesn't measure moat.** A commodity producer with great year-over-year improvements still has no pricing power.

❌ **Lagging by 6 months.** It's based on annual financials, so by the time you see the score change, the market often has too.

❌ **Hard for financials.** Banks and NBFCs have totally different metrics. Piotroski intended this for non-financial companies.

---

## Action items

1. Open any stock you own on [YieldIQ](/search)
2. Note its current Piotroski F-Score
3. Look at the trend (is it 7 → 8 or 7 → 5?)
4. Use [the High Piotroski filter](/screens/high-piotroski) to find stocks scoring 8 or 9
5. Combine with valuation — never buy a high-Piotroski stock just because the score is high

---

YieldIQ is not registered with SEBI as an investment adviser. This article is educational, not investment advice.
`,
  },
  {
    slug: "margin-of-safety-explained",
    title: "Margin of Safety: Buffett's Most Important Concept",
    description: "What is Margin of Safety, why Warren Buffett calls it 'the three most important words in investing,' and how to apply it to Indian stocks.",
    date: "2026-04-05",
    author: "YieldIQ Team",
    category: "framework",
    readTime: 5,
    content: `## The 3 most important words in investing

Warren Buffett, when asked to summarize sound investing in three words, said:

> **"Margin of Safety."**

This concept, taught to him by his mentor Benjamin Graham, is the foundation of value investing.

---

## What it means

If a business is worth ₹500 per share and you can buy it for ₹350, you have a **30% margin of safety**.

That cushion exists for one reason: **you might be wrong**.

Maybe the company won't grow as fast as you projected. Maybe a competitor disrupts them. Maybe the discount rate should have been higher. Maybe interest rates spike.

When you buy at a 30% discount to your estimate of fair value, you can be **wrong by 30% and still not lose money**.

---

## The math

$$\\text{Margin of Safety \\%} = \\frac{\\text{Fair Value} - \\text{Current Price}}{\\text{Current Price}} \\times 100$$

For ITC at ₹303 with our DCF fair value at ₹527:

$$\\text{MoS} = \\frac{527 - 303}{303} \\times 100 = +73.9\\%$$

A +73.9% MoS means: even if the fair value estimate is 40% too optimistic, you still have 30%+ upside.

A **-30% MoS** means: even if your estimate is 30% too low, you'd still be losing money buying today.

---

## Why MoS Matters More in India

Three reasons:

### 1. Higher uncertainty
Indian companies face:
- More volatile macro (rates, currency, oil)
- Less analyst coverage outside Nifty 100
- Promoter risk (pledging, related-party transactions)
- Regulatory shifts (GST, telecom, banking, mining)

When uncertainty is high, you need a bigger cushion.

### 2. Wider valuation swings
The same Indian stock can swing 50-100% in a year on no fundamental change. Buying with margin of safety means you're less affected by sentiment.

### 3. No safety net
US investors have decades of bull markets, deep liquidity, and hedging tools. Indian retail investors mostly buy and hold. Your only protection is the price you paid.

---

## How much MoS is enough?

Rough guide based on quality:

| Company Type | Minimum MoS |
|---|---|
| Wide moat, predictable (HUL, Asian Paints) | **15-20%** |
| Narrow moat, decent quality (HDFC Bank, Maruti) | **25-30%** |
| Cyclical (Tata Steel, JSW) | **40-50%** |
| Distressed turnaround | **60%+** |

Higher uncertainty → bigger margin needed.

---

## Common mistakes

### ❌ Buying with negative MoS hoping for momentum
"Stock is going up, who cares about valuation."
Famous last words. When sentiment turns, no MoS = no floor.

### ❌ Anchoring to a number
If fair value is ₹500, you don't HAVE to buy at ₹350. You can wait for ₹300 and get more MoS. Patience is part of the discipline.

### ❌ Using a single fair value estimate
Better: build bear / base / bull cases. Make sure even bear case price gives you some MoS.

### ❌ Ignoring quality
A 50% MoS on a deteriorating business isn't a deal — it's a value trap. Always check quality (Piotroski, moat, ROCE) alongside MoS.

---

## How YieldIQ shows MoS

On every stock analysis page, you'll see:

- **Fair Value** (our DCF estimate)
- **Current Price** (live market price)
- **MoS%** (the difference, color-coded green/red)
- **Bear / Base / Bull** scenarios so you see the range

You can also use the [Reverse DCF](/stocks/ITC/reverse-dcf) page to see what growth the market is implying — another lens on margin of safety.

---

## A real example

In March 2020 (COVID crash):
- ITC traded at ~₹150
- Our DCF fair value at the time: ~₹260
- MoS: +73%

By Sept 2024:
- ITC: ~₹500+
- That MoS played out as +233% returns

Was ITC "guaranteed" to work? No. But the high MoS gave investors a cushion against being wrong about COVID, demand recovery, and policy.

---

## Bottom line

Margin of Safety is **not** about being clever or having an edge. It's about acknowledging your fallibility and pricing it in.

Pay 70 cents for ₹1 of value. If you're wrong, you might break even. If you're right, you make 40%+. That asymmetry — over many decisions, over many years — is how wealth gets built.

---

YieldIQ is not registered with SEBI as an investment adviser. This article is educational, not investment advice.
`,
  },
  {
    slug: "reverse-dcf-explained",
    title: "Reverse DCF: How to Tell What Growth the Market is Pricing In",
    description: "The most under-used valuation tool. Reverse DCF tells you what FCF growth rate the current price is implying — so you can judge whether it's realistic.",
    date: "2026-04-02",
    author: "YieldIQ Team",
    category: "valuation",
    readTime: 5,
    content: `## The problem with normal DCF

When you do a normal DCF, you have to assume:
- Growth rate (5%? 10%? 15%?)
- Terminal growth (3%? 4%?)
- WACC (10%? 12%?)
- Margins, capex, working capital...

Change any input by 1-2%, and fair value moves 20-30%. Result: people just pick assumptions that give them the answer they want.

---

## Reverse DCF flips it

Instead of guessing growth and computing fair value, reverse DCF does the opposite:

> **"Given the current market price, what growth rate is the market implying?"**

This is much harder to bias. The market price is a fact. The implied growth rate is just math.

Then you can ask: **"Is that growth rate achievable?"**

---

## How it works

YieldIQ's reverse DCF binary-searches over FCF growth rates from -30% to +60% until it finds the rate where DCF intrinsic value = current market price.

Example for **TCS** at ₹3,650:

We solve: at what growth rate does DCF give ₹3,650?

Answer: **~12% FCF growth for 10 years**.

Then we compare:
- **Historical FCF growth** for TCS: ~9%
- **Indian IT sector long-term growth**: 8-10%
- **Implied growth**: 12%

Conclusion: TCS at ₹3,650 is pricing in growth that's higher than its history and the sector average. Not impossible — TCS is a quality company. But the market has zero margin for disappointment.

---

## The verdict bands

YieldIQ classifies implied growth into bands:

| Implied Growth | Verdict | What it means |
|---|---|---|
| **< 5%** | Conservative | Market expects no growth. Easy to beat. |
| **5-10%** | Reasonable | Achievable for most quality companies. |
| **10-15%** | Aggressive | Possible for above-average businesses. |
| **15-25%** | Very Aggressive | Only top-decile companies sustain this. |
| **> 25%** | Unrealistic | Almost no large-cap delivers this for a decade. |

---

## Real examples

### **HDFC Bank in 2019**
- Price: ₹1,200
- Implied growth: 18%
- Historical: 20%

Reasonable. The market wasn't even pricing in HDFC's actual track record. Stock returned ~50% over 3 years.

### **DMart in 2021**
- Price: ₹4,800
- Implied growth: 30%
- Historical: 25%

Aggressive. The market was extrapolating peak performance. Stock has underperformed since — implied growth was just too steep.

### **Adani Enterprises in 2022**
- Price: ₹3,500
- Implied growth: 45%+

Unrealistic. Almost no large-cap sustains 45% FCF growth for a decade. The market was pricing in pure narrative. Hindenburg's report (Jan 2023) crushed this assumption.

---

## When implied growth is LOW

This is the contrarian's playground. Examples:

- **Coal India** in 2020: Implied growth was -2% (the market expected DECLINE).
- **PSU banks** in 2017-2020: Implied growth was 0-3%.
- **Pharma** in 2018: Implied growth was 4-5% after the FDA crackdown.

When implied growth is below 5%, the market is essentially saying "this business is dead." If the business **isn't actually dead**, that's where multi-baggers live.

---

## How to use Reverse DCF on YieldIQ

Visit any stock's [Reverse DCF page](/stocks/ITC/reverse-dcf):

1. See the **implied growth rate**
2. Compare with the **historical growth**
3. Read the **plain English verdict**
4. Adjust the **WACC and terminal growth sliders** for sensitivity
5. Look at **years to justify price** at historical growth

If the model needs 20 years of historical-rate growth to justify today's price, the stock is priced for perfection.

---

## Why this is so under-used

Reverse DCF is RARE because:
- Tijori charges ₹330/month for it
- Screener.in doesn't have it
- Tickertape doesn't have it

Most retail investors have never seen it. We give it free as a lead-gen.

---

## A practical workflow

1. **Find a stock you like** (good business, you understand it)
2. **Run reverse DCF** to see implied growth
3. **Ask honestly: can this business deliver that growth?**
4. **If yes** → consider it a candidate (combine with quality + valuation)
5. **If no** → either wait for a lower price or pass

That's it. No emotion. No hot tips. Just math + judgment.

---

## Bottom line

Normal DCF is "what is this stock worth?"
Reverse DCF is "what does the price assume?"

The second question is more honest. It exposes the assumptions baked into market prices and lets you decide whether you agree.

---

YieldIQ is not registered with SEBI as an investment adviser. This article is educational, not investment advice.
`,
  },
  {
    slug: "economic-moat-explained",
    title: "What is an Economic Moat? The Business Quality Test that Buffett Uses",
    description: "Wide moat, narrow moat, no moat — what these mean, why they matter, and how to spot durable competitive advantages in Indian companies.",
    date: "2026-03-30",
    author: "YieldIQ Team",
    category: "framework",
    readTime: 6,
    content: `## What is a moat?

In medieval times, a moat was the water-filled trench around a castle that kept invaders out.

Warren Buffett borrowed the word for business: **a moat is anything that prevents competitors from eating your profits.**

A great business has a wide moat. A good business has a narrow moat. A commodity business has no moat at all.

---

## Why moats matter

Two businesses can have identical financials today. The one with a moat will compound its earnings for 20 years. The one without will see margins collapse the moment competition shows up.

Moats determine:
- **How long abnormal profits last**
- **How much pricing power you have**
- **How much you have to reinvest just to stay in place**
- **How much of value goes to shareholders vs employees vs customers**

---

## The 5 types of moats

### 1. Brand power
Customers pay more for the same product because of the brand.

**Indian examples:**
- **HUL** — pays for the Surf brand even when Wheel is 30% cheaper
- **Asian Paints** — homeowners trust the brand for emotional reasons
- **Titan** — same gold + jewellery, but Tanishq commands a premium

### 2. Switching costs
Once a customer is locked in, leaving is painful or expensive.

**Indian examples:**
- **TCS, Infosys** — clients deeply integrated, switching IT vendor takes years
- **HDFC Bank** — moving primary bank account is a hassle
- **Polycab** — once distributors stock your brand, switching disrupts their business

### 3. Network effects
The product gets better as more people use it.

**Indian examples:**
- **Bharti Airtel** — more subscribers = better network = more subscribers
- **Eternal (Zomato)** — more restaurants attract more diners attract more restaurants
- **NSE** — more buyers attract more sellers attract more liquidity

### 4. Cost advantage
You can produce the same product cheaper than anyone else.

**Indian examples:**
- **Reliance Jio** — built fiber + 4G at scale, marginal cost near zero
- **DMart** — cluster store model, lower costs than competitors per sq ft
- **Hindustan Zinc** — owns one of the world's largest zinc mines

### 5. Regulatory / Licensing
Government licenses or regulations create artificial scarcity.

**Indian examples:**
- **HAL, BEL** — defense PSU monopolies
- **Coal India** — owns 80% of Indian coal reserves
- **Power Grid** — monopoly on inter-state transmission

---

## How to spot a moat (4 questions)

### 1. Has ROCE been > 15% for 5+ years?
ROCE measures how efficiently a business generates returns on the money invested in it. Sustained high ROCE = pricing power = moat.

### 2. Are gross margins stable or expanding?
Commodity businesses have margins that move with input costs. Moat businesses can pass costs through or absorb them without margin damage.

### 3. Does revenue grow without proportional asset growth?
HUL grows revenue 10% without spending 10% more on plants. That's because the brand does the work. Steel companies need more blast furnaces to grow — no moat.

### 4. Does the company need pricing actions to drive growth?
HUL raises prices every year and demand barely flinches. Asian Paints raised prices 8 times in 2022 and won market share. That's pricing power = moat.

---

## What "Wide Moat" looks like in YieldIQ

We classify every stock as:
- **Wide Moat** — durable advantage, likely to persist 10+ years
- **Narrow Moat** — has an edge but not bulletproof
- **None** — commodity-like, no defensible advantage

Examples from our cache:
- **Wide:** ITC, HUL, TCS, Asian Paints, HDFC Bank, Nestle
- **Narrow:** Maruti, ICICI Bank, Wipro, Bharti Airtel
- **None:** Most steel, most cement, most realty, most discretionary

---

## Why moat matters for valuation

DCF is highly sensitive to terminal growth. A wide-moat company can grow at 4% terminal forever — because its competitive position is durable.

A no-moat company should be valued with **0% terminal growth or even decay** — because competition will eat into margins eventually.

This is why HUL trades at 60× P/E and Tata Steel at 8× P/E. Both companies are profitable, but HUL's profits are durable. Tata Steel's profits depend on the steel cycle.

---

## How to use moat in YieldIQ

Every stock page shows the moat grade:

1. **Filter for Wide Moat stocks** in our [Wide Moat screener](/screens/wide-moat)
2. **Combine with valuation** — wide moat + undervalued = compounder you can hold for 10 years
3. **Avoid No Moat at high multiples** — paying 30× P/E for a commodity producer rarely ends well
4. **Watch for moat erosion** — once-dominant businesses (Nokia, Yahoo, Kodak) lost moats over decades

---

## Common moat mistakes

### ❌ Confusing market share with moat
Maruti has 40% car market share but its moat is narrowing every year as Hyundai, Tata, and Mahindra catch up. Market share is a result, not a moat.

### ❌ Confusing brand with moat
A brand is only a moat if customers pay more BECAUSE of it. Many "branded" Indian companies don't actually have pricing power — they're just well-known.

### ❌ Assuming moats last forever
30 years ago, Hindustan Motors (Ambassador) had a moat. Today, the brand is dead. Moats can erode. Watch ROCE trends.

### ❌ Ignoring valuation because of moat
A wide-moat business at 80× P/E can still lose you money for years. Moat protects the business. Margin of safety protects YOU.

---

## Bottom line

A great business with a wide moat, bought at a fair price, held for 10 years — that's how Buffett built his empire.

YieldIQ's DCF, quality scoring, and moat classification are designed to help you find these. But the work is yours: read annual reports, listen to concalls, understand the business.

---

YieldIQ is not registered with SEBI as an investment adviser. This article is educational, not investment advice.
`,
  },
  {
    slug: "how-to-analyze-indian-stock-5-minutes",
    title: "How to Analyze an Indian Stock in 5 Minutes (The YieldIQ Method)",
    description: "A repeatable 5-minute checklist using YieldIQ tools. Quality, valuation, growth, risk — answered for any Indian stock.",
    date: "2026-03-26",
    author: "YieldIQ Team",
    category: "guide",
    readTime: 5,
    content: `## The 5-minute framework

Most retail investors spend either 30 seconds (look at price chart) or 30 days (read 10 years of annual reports) on a stock. Both are bad.

Here's a **5-minute framework** that catches 80% of the value of a deep dive.

---

## Step 1: Open the stock page (30 sec)

Search the ticker on YieldIQ. You'll see:
- Current price
- DCF fair value
- Margin of safety %
- YieldIQ Score (0-100)
- Verdict (Undervalued / Fairly Valued / Overvalued / High Risk)

If MoS is +20% or better AND score is 60+, this is a candidate. Continue.
If MoS is heavily negative OR score is below 40, skip. Move on.

---

## Step 2: Check the moat (1 min)

Scroll to the Quality section. Look for:
- **Moat: Wide / Narrow / None**
- **Piotroski F-Score: 0-9**
- **Sector**

A Wide Moat stock with F-Score 7+ is a quality compounder candidate. A No Moat stock is a trade, not an investment.

---

## Step 3: Run the Reverse DCF (1 min)

Click the "Reverse DCF" link. You'll see:
- **Implied growth rate** the market is pricing in
- **Historical growth** the company has actually delivered
- **Verdict band** (Conservative / Reasonable / Aggressive / Very Aggressive / Unrealistic)

Quick test:
- If Implied Growth ≤ Historical Growth → Reasonable, MoS is real
- If Implied Growth >> Historical → Aggressive, MoS may be illusory
- If Implied Growth > 25% → Unrealistic, walk away regardless of other metrics

---

## Step 4: Check Risk (1 min)

Click Risk Analysis. Look at:
- **Max Drawdown** (the worst peak-to-trough fall)
- **Beta vs Nifty**
- **Volatility %**

Rules of thumb:
- Beta < 0.8 = defensive (FMCG, Pharma, Utilities)
- Beta 0.8-1.2 = market-like (Banks, IT, Auto)
- Beta > 1.2 = aggressive (small caps, cyclicals)

If a stock has dropped 60%+ in the last 3 years, you need a strong reason for what's changed.

---

## Step 5: Check Recent News (1 min)

Click News & Filings. Look for:
- 🔴 **Critical filings** (results, auditor change, qualified opinion)
- 🟡 **High importance** (board meeting, dividend, M&A)
- The AI Summary at the top

Scan headlines for the last 2 weeks. Anything that contradicts your thesis = red flag.

---

## Step 6: The Final Question (30 sec)

Ask yourself: **"Would I be comfortable owning this for 5 years if the market closed tomorrow?"**

If yes — and the price gives you margin of safety — it's a candidate.
If no — even at a 50% discount — pass.

---

## A concrete example: ITC

**Step 1 (Open page):** Score 80, MoS +51%, Verdict: Undervalued. ✅ Continue.

**Step 2 (Moat):** Wide Moat (cigarette pricing power, FMCG brands, hotels), F-Score 7. ✅ Quality.

**Step 3 (Reverse DCF):** Market implies 6% growth. ITC has historically delivered 8-9%. ✅ Reasonable, real margin of safety.

**Step 4 (Risk):** Beta 0.6 (defensive), max drawdown -30% (post-COVID), volatility 18%. ✅ Low risk.

**Step 5 (News):** Quarterly results showed FMCG growth +12%, hotel demand strong. No red flags. ✅

**Step 6:** Would I own ITC for 5 years if markets closed? Yes — durable business, dividend yield 3%+, regulatory risk has been priced in for years.

**Conclusion:** Candidate for further research (annual report, concall, peer comparison). Not a "buy" — that's your decision.

---

## What this 5-minute method DOESN'T do

❌ Replace deep due diligence for large allocations
❌ Catch promoter fraud or accounting manipulation
❌ Predict short-term price movements
❌ Tell you when to sell

For a 1% portfolio position, 5 minutes is enough.
For a 10% position, do the deep dive.

---

## When to dig deeper

If the 5-minute analysis is positive AND you're considering a meaningful position:

1. Read the **last 2 annual reports** (Director's Report + MD&A — skip the boilerplate)
2. Listen to the **last 4 concalls** (or use [YieldIQ's Concall AI](/concall) to summarize them)
3. Check the **shareholding pattern** — promoter pledging > 5% is a flag
4. Run **scenarios** in our DCF — what does bear case look like?

---

## Bottom line

You don't need a CFA to analyze stocks. You need:
1. A repeatable framework
2. Tools that surface the right data
3. Discipline to walk away from 90% of stocks

YieldIQ gives you the tools. The discipline is yours.

---

YieldIQ is not registered with SEBI as an investment adviser. This article is educational, not investment advice.
`,
  },
  {
    slug: "stcg-ltcg-tax-fy-2025-26",
    title: "STCG vs LTCG: Indian Capital Gains Tax Explained (FY 2025-26)",
    description: "Post-Budget 2024 tax rates, holding period rules, exemptions, set-offs, and ITR filing tips for Indian equity investors.",
    date: "2026-03-22",
    author: "YieldIQ Team",
    category: "tax",
    readTime: 7,
    content: `## The 30-second summary

For listed Indian equity (with STT paid):

| Holding Period | Tax | Rate | Exemption |
|---|---|---|---|
| **< 12 months** | STCG | **20%** | None |
| **≥ 12 months** | LTCG | **12.5%** | First ₹1.25L exempt per year |

These rates apply to transactions **on or after 23 July 2024** (Union Budget 2024 changes).

---

## What changed in Budget 2024?

Before 23 July 2024:
- STCG: 15%
- LTCG: 10% above ₹1L

After 23 July 2024:
- STCG: **20%** (up 5pp)
- LTCG: **12.5%** above ₹1.25L (rate up, exemption up)

This is a meaningful increase. A ₹10L STCG that cost ₹1.5L in tax now costs ₹2L.

---

## STCG (Short-Term Capital Gains)

### Definition
Profit on equity shares held for **less than 12 months** before sale.

### Rate
**20% flat** (Section 111A of Income Tax Act).

### Example
You bought 100 shares of TCS at ₹3,200 in March 2025.
You sold them at ₹3,800 in October 2025 (7 months held).
Profit = (3,800 - 3,200) × 100 = ₹60,000.
Tax = 20% × ₹60,000 = **₹12,000**.

---

## LTCG (Long-Term Capital Gains)

### Definition
Profit on equity shares held for **12 months or more** before sale.

### Rate
**12.5%** above the ₹1.25L exemption (Section 112A).

### Example
You bought 50 shares of HDFC Bank at ₹1,400 in 2022.
You sold them at ₹1,800 in 2025 (3+ years held).
Profit = (1,800 - 1,400) × 50 = ₹20,000.

This is well below ₹1.25L exemption → **₹0 tax**.

But if you had ₹1,80,000 in LTCG that year:
- First ₹1,25,000: exempt
- Remaining ₹55,000: taxed at 12.5% = **₹6,875**

---

## The exemption is per FY, not per stock

The ₹1.25L LTCG exemption is **combined across all your equity sales in a financial year**.

If you sold 5 stocks with these LTCG amounts:
- Stock A: ₹40,000
- Stock B: ₹30,000
- Stock C: ₹20,000
- Stock D: ₹50,000
- Stock E: ₹35,000
- **Total: ₹1,75,000**

You don't get ₹1.25L exemption per stock. You get ONE ₹1.25L exemption for the whole year.

Taxable LTCG: ₹1,75,000 - ₹1,25,000 = ₹50,000.
Tax: 12.5% × ₹50,000 = **₹6,250**.

---

## Loss set-offs (Important!)

### STCL (Short-Term Capital Loss)
- Can offset against STCG (same year)
- Can offset against LTCG (same year)
- Carry forward 8 years if unused

### LTCL (Long-Term Capital Loss)
- Can ONLY offset against LTCG (cannot offset STCG)
- Carry forward 8 years

### Tax loss harvesting
If you have a stock down 20%+ that you'd hold anyway, you can sell + immediately rebuy. The realized loss reduces your taxable gains.

**Rules:**
- The 30-day "wash sale" rule from US tax law **does NOT apply in India** (yet)
- You can sell on Tuesday and buy back on Wednesday — perfectly legal
- The new holding period resets, so plan around 12-month threshold

---

## Common scenarios

### "I sold within 12 months for a small loss"
That's a Short-Term Capital Loss (STCL). Set off against any other STCG or LTCG you have this year, OR carry forward 8 years.

### "I made ₹80,000 LTCG"
₹0 tax. Below the ₹1.25L exemption.

### "I made ₹3L LTCG and ₹50K STCL"
- STCL of ₹50K offsets LTCG of ₹50K
- Net LTCG: ₹2.5L
- Less exemption: ₹2.5L - ₹1.25L = ₹1.25L taxable
- Tax: 12.5% × ₹1.25L = **₹15,625**

### "I bought IPO shares and sold on listing day"
That's STCG (held < 12 months). 20% flat rate. No exemption.

### "I got bonus shares and sold within 12 months"
Bonus shares have **₹0 cost basis**. Selling at any price = full STCG.
But your original shares' cost basis stays the same — quirk of accounting.

---

## What about pre-23 July 2024 transactions?

Sales **before 23 July 2024** are taxed at the OLD rates (10% LTCG, 15% STCG).

In your ITR for FY 2024-25 (filed in 2025), you'll have BOTH old and new rates depending on transaction date. Most brokers' Tax P&L reports split these correctly.

---

## Grandfathering (pre-Feb 2018 holdings)

If you bought equity **before 1 Feb 2018**, you get a special benefit:
- Cost basis = **higher of (actual cost, FMV on 31 Jan 2018)**
- This is to avoid taxing gains that accrued before LTCG was reintroduced

Example: You bought Infosys at ₹50 in 1999. FMV on 31 Jan 2018 was ₹1,180. You sold at ₹1,500 in 2025.

LTCG = (1,500 - 1,180) × shares = use ₹1,180 as cost, not ₹50.

This benefit only matters for very long-term holders.

---

## How to file (the ITR section)

Capital gains go in:
- **ITR-2** for individuals (no business income)
- **ITR-3** if you also have business income

Schedule **CG → Items A1 to B6** for shares.

Required:
- Total sale consideration
- Cost of acquisition
- Date of purchase, date of sale
- ISIN code (your broker provides this)

**Most brokers (Zerodha, Groww) provide pre-formatted Tax P&L Excel files** that you can directly attach or use as a worksheet.

---

## How YieldIQ helps

Our [Tax Report tool](/portfolio/tax-report) does all of this automatically:

1. Paste your Zerodha Tax P&L CSV (or any broker)
2. We classify each trade as STCG or LTCG
3. We aggregate per FY
4. We apply the ₹1.25L LTCG exemption
5. We auto-set off STCL against LTCG
6. We compute total tax owed
7. **Pro tier**: ITR-ready CSV export for your CA

Saves hours of Excel work every March.

---

## Disclaimer

This is general information based on Income Tax Act 1961 (as amended). Your actual tax depends on your income slab, deductions, and specific circumstances. Always consult a qualified Chartered Accountant before filing.

YieldIQ is not registered with SEBI as an investment adviser, and is not a tax advisor. This article is educational, not tax advice.
`,
  },
]

// Helper to look up a post by slug
export function getBlogPost(slug: string): BlogPost | undefined {
  return BLOG_POSTS.find(p => p.slug === slug)
}

// Helper to get sorted posts (newest first)
export function getAllBlogPosts(): BlogPost[] {
  return [...BLOG_POSTS].sort((a, b) => b.date.localeCompare(a.date))
}

// Helper to get related posts (same category, exclude current)
export function getRelatedPosts(slug: string, limit: number = 3): BlogPost[] {
  const current = getBlogPost(slug)
  if (!current) return []
  return BLOG_POSTS
    .filter(p => p.slug !== slug && p.category === current.category)
    .slice(0, limit)
}
