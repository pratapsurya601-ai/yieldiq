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
  {
    slug: "dcf-valuation-indian-stocks-guide",
    title: "How DCF Valuation Works for Indian Stocks (Without the Jargon)",
    description: "A plain-English guide to Discounted Cash Flow for Indian investors. Learn FCF, WACC, terminal value and why the India risk-free rate changes everything — with a worked Reliance example.",
    date: "2026-04-20",
    author: "YieldIQ Team",
    category: "valuation",
    readTime: 10,
    content: `## Why this guide exists

Most explainers of DCF were written for US stocks. They assume a 4% risk-free rate, a stable currency, and a GDP that grows at 2%. None of those apply in India.

This guide walks through DCF the way it actually works when you're valuing a stock on the NSE. No finance degree needed. By the end, you will know what Free Cash Flow is, how to think about WACC without memorising a formula, why terminal value is usually 60-70% of your answer, and how all of this fits together.

We will use **Reliance** and **ITC** as recurring examples because most Indian investors already have a feel for these businesses.

---

## The one-sentence version

A company is worth all the cash it will produce in the future, discounted back to today.

That is it. Everything else is plumbing.

---

## Step 1: Understand Free Cash Flow (FCF)

A company's "profit" is not the same as its cash. Profit can include non-cash items (depreciation), it can be massaged through accounting choices, and it ignores the money the company spends to keep growing.

Free Cash Flow is what is left after the business has paid for everything it needs to pay for:

**FCF = Cash from Operations - Capital Expenditure**

Cash from Operations is cash the business actually collected from customers, minus cash actually paid to suppliers and employees. It sits at the bottom of the cash flow statement.

Capex is what the company spent on factories, machinery, software, stores — anything it had to buy to keep running.

Whatever is left is yours (in theory) as a shareholder. That is why FCF matters more than Net Profit.

### Quick ITC example

In a typical recent year, ITC reported roughly these orders of magnitude:

- Cash from operations: around fifteen to eighteen thousand crore
- Capex: around three to four thousand crore
- FCF: roughly twelve to fourteen thousand crore

That FCF — the cash left over — is what gets discounted in the DCF.

---

## Step 2: Why future cash matters more than past earnings

A retailer that earned two hundred crore last year but is shutting down is worth less than a retailer that earned one hundred crore last year but is doubling every two years.

Markets are forward-looking. So is DCF.

Past earnings tell you what the business has done. Future cash tells you what it will do. Stock prices follow the second, not the first. This is also why a stock can have a great earnings report and fall 5% — the market was already pricing in better.

---

## Step 3: WACC in three paragraphs

WACC stands for Weighted Average Cost of Capital. It is the return you expect from the investment. If you could earn 11% in a safer alternative, you should not discount this company's cash flows at less than 11%.

For a pure-equity company, WACC is basically Cost of Equity. Cost of Equity has three ingredients: the risk-free rate (what you could earn in Indian government bonds), the equity risk premium (the extra you demand for taking stock market risk), and beta (how volatile this stock is vs the market).

For Indian stocks today, Cost of Equity typically lands somewhere between 11% and 14%. Boring large caps (HUL, Nestle) sit near the bottom of that band. Cyclicals and small caps sit near the top. If a company has meaningful debt, WACC is slightly lower than Cost of Equity because debt is cheaper after tax — but do not over-engineer this.

Rule of thumb: if you cannot decide, start with 12%. Then stress-test by trying 11% and 13%. If the stock only looks cheap at 10%, it is not really cheap.

---

## Step 4: The India risk-free rate is higher — and it matters

In the US, the 10-year Treasury yield is the risk-free rate. It sits around 4% in most years.

In India, the equivalent is the 10-year G-Sec yield, which typically sits between 6.5% and 7.5%. That is roughly **three percentage points higher** than the US.

This matters because every component of WACC stacks on top of the risk-free rate. If American bloggers tell you 8% is a reasonable discount rate for a quality stock, they are wrong for India by about 300 basis points. Use 11-13%.

A second consequence: Indian terminal growth should be higher too. US analysts use 2-3% terminal growth. For India, 4-5% is defensible because long-run nominal GDP growth is higher.

---

## Step 5: Terminal value — the elephant in the room

When you forecast 10 years of cash flows, you hit a wall: what happens in year 11 onwards?

The standard answer is the Gordon Growth formula:

**Terminal Value = FCF(year 10) x (1 + g) / (r - g)**

Where g is terminal growth (industry convention: 4% for India) and r is the discount rate (industry convention: 11-13%).

Terminal value is usually 60-70% of total DCF value. That is a lot. Small changes here swing fair value a lot. This is why being honest about terminal growth matters more than being precise about year 7 forecasts.

Two sanity checks:
- Never let terminal growth exceed long-run GDP growth (for India, cap at 5%)
- Never let terminal growth equal or exceed the discount rate (the math breaks)

---

## Step 6: Put it together — a Reliance-style worked example

We are not going to claim a specific fair value for Reliance — that depends on assumptions that shift every quarter. But the mechanics look like this.

Start with last year's FCF, say somewhere around thirty to forty thousand crore for a Reliance-scale business. Grow it forward for 10 years. In early years you might assume 10-12% growth (retail + Jio + petrochem mix), tapering to 5-6% by year 10.

Each year's cash flow gets divided by (1 + WACC) raised to the year number. Year 1 cash is divided by 1.12. Year 5 cash is divided by 1.12 to the fifth. By year 10 you are dividing by roughly 3.1 — meaning a rupee of cash ten years from now is worth about 32 paise today.

Add up all ten discounted cash flows. Then add the discounted terminal value. That gives you Enterprise Value. Subtract net debt. Divide by shares outstanding. That is the fair value per share.

On YieldIQ, you can see exactly this computation for any stock. For Reliance, check [reliance fair value](/stocks/RELIANCE/fair-value). For a cleaner FMCG example, try [ITC fair value](/stocks/ITC/fair-value).

---

## Step 7: What DCF is bad at

DCF is not magic. It has real blind spots.

**Banks and NBFCs.** Their "cash flow" includes deposits and loans, which is not the same as FCF for a normal business. Use dividend discount models or P/B-ROE frameworks instead.

**Early-stage companies with negative FCF.** If there is nothing positive to discount, DCF gives nonsense. Wait until the business is profitable or use a multiple-based approach.

**Cyclicals at the top of the cycle.** Using peak-year FCF as the starting point bakes in rosy assumptions. For cyclicals like steel, cement, chemicals, use a mid-cycle or normalised FCF.

**Companies with opaque accounting.** Garbage in, garbage out. If you do not trust the financials, no valuation model saves you.

---

## Step 8: Common DCF mistakes Indian retail investors make

**Using US discount rates.** 8% WACC is too low for India. You will get fair values that are always 50% above market and you will be permanently "buying undervalued stocks" that go nowhere.

**Ignoring dilution.** A company that issues 5% more shares each year quietly eats into per-share value. Count diluted shares, not just current shares.

**Forgetting net debt.** A stock with thirty thousand crore of debt is not worth the same as an identical stock with zero debt. Subtract net debt from enterprise value before dividing by shares.

**Over-forecasting.** You cannot predict year 8 FCF with precision. You can only predict a range. Build bear, base, and bull scenarios instead of a single point estimate.

---

## Step 9: How to use DCF on YieldIQ

Every stock page on YieldIQ runs a DCF in the background. You see:

- The base-case fair value
- Bear and bull scenarios
- The underlying WACC and terminal growth assumptions
- [Reverse DCF](/stocks/RELIANCE/reverse-dcf) — what growth the market is pricing in

For comparison across peers, the [compare tool](/compare) lines up two stocks side by side — so you can see, for instance, whether HDFC Bank is priced richer than ICICI Bank on a DCF-adjusted basis. You can also filter the [discover page](/discover) for stocks trading below their DCF fair value.

---

## Bottom line

DCF is not a crystal ball. It is a disciplined way of writing down your assumptions and letting the math push back when those assumptions are unrealistic.

Use the Indian risk-free rate (6.5-7.5%). Use an Indian equity risk premium (5-6%). End up at a WACC of 11-13% for most stocks. Cap terminal growth at 4-5%. Forecast a decade, then add terminal value. Subtract net debt. Divide by shares.

That is DCF. The rest is practice.

---

*Disclaimer: YieldIQ is not a SEBI-registered investment adviser. This article is educational only and does not constitute investment advice. Consult a qualified advisor before investing.*
`,
  },
  {
    slug: "margin-of-safety-20-percent-not-enough",
    title: "What is Margin of Safety — and Why 20% Isn't Enough for Indian Stocks",
    description: "Buffett's concept adapted for the Indian market. Why NSE stocks demand more cushion than US equities, and how to size margin of safety by business quality.",
    date: "2026-04-21",
    author: "YieldIQ Team",
    category: "framework",
    readTime: 8,
    content: `## The idea, in one line

Margin of Safety is the gap between what a stock is worth and what you pay for it. The bigger the gap, the more room you have to be wrong.

Benjamin Graham introduced the concept in the 1930s. Warren Buffett calls it "the three most important words in investing." It is simple arithmetic. It is also the single most under-applied idea in Indian retail investing.

---

## A thirty-second refresher

If a stock's fair value is ₹500 and the market price is ₹400, your Margin of Safety (MoS) is 20%.

If the price drops to ₹350, your MoS expands to 30%.

If the price rises to ₹525, you have negative MoS of 5% — you are paying more than the stock is worth, assuming your estimate of fair value is correct.

That last phrase is doing a lot of work. It is the reason 20% MoS is often not enough.

---

## Why 20% sounds reasonable in US textbooks

American value investing textbooks usually recommend 20-30% MoS. That works in a market where:

- Earnings visibility is high (strong analyst coverage, mandatory quarterly guidance in practice)
- The dollar is the world's reserve currency
- Accounting standards are strict and SEC enforcement is real
- Interest rates do not swing 200 basis points in a year
- A large company rarely has promoter-pledge risk

Indian investors face a different world. The 20% number does not transfer cleanly.

---

## Reason 1: Earnings volatility is higher in India

Indian corporate earnings whip around more than their US counterparts. Reasons include:

- A larger share of commodity and cyclical businesses
- Monsoon-dependent rural consumption
- Currency pass-through from a volatile rupee
- Regulatory shifts (GST changes, telecom spectrum rules, PLI schemes)

A company that grew earnings 18% a year for a decade can post a flat year out of nowhere. Your DCF was probably based on stable growth. When that assumption breaks, MoS becomes your only cushion.

---

## Reason 2: The rupee depreciates

The rupee has depreciated against the dollar at roughly 3-4% per year over the long run. That creates two quiet problems for Indian equity valuations:

**Imported inflation.** Companies that import raw materials (chemicals, electronics, crude derivatives) see input costs rise every few years even when global prices are flat.

**FII flows.** When the rupee is weak, foreign investors sell first and ask questions later. Your stock can fall 15-20% in a quarter on no company-specific news.

Neither factor shows up in a "clean" DCF. A bigger margin of safety absorbs both.

---

## Reason 3: Promoter-related risk

In India, most listed companies have a dominant promoter family. That is usually fine — skin in the game is good. But it creates risks that barely exist in the US:

- **Promoter pledging**: shares pledged to raise loans. If the stock falls, lenders sell, which makes the stock fall more.
- **Related-party transactions**: the company pays above-market rates to suppliers owned by the promoter.
- **Governance mis-steps**: disclosed only when SEBI or auditors force the issue.

When one of these shows up, the stock often falls 30-50% in weeks. If you bought with 15% MoS, you are now sitting on a 25-35% loss.

---

## Reason 4: Analyst coverage is thin outside Nifty 100

For the top 100 Indian stocks, you can find 15-20 sell-side analyst models. Your DCF is one data point among many, and errors get corrected.

For smaller stocks, you might be the only person running a rigorous model. That is an opportunity. It is also a risk — you do not get the error correction from other analysts.

Thin coverage means a wider range of "correct" answers, which means a bigger margin of safety.

---

## Reason 5: Valuation bands swing more

The same Indian FMCG stock can trade at 40x earnings in one year and 70x in the next with barely any change in earnings. The Nifty's trailing PE has ranged from 15x to 28x in the last decade.

Multiple expansion and contraction in India is bigger than in the US. That is not a bug — it is a function of domestic liquidity, FII flows, and narrative cycles. But it means the gap between "fair value" and "market price" is inherently wider. You need more cushion to survive the down swings.

---

## Sizing MoS by business quality

Here is a defensible scaling based on quality and predictability. Use it as a starting point, adjust for your own conviction.

| Business Type | Examples | Minimum MoS |
|---|---|---|
| **Wide moat, defensive** | HUL, Nestle, Asian Paints, Pidilite | 20-25% |
| **Wide moat, cyclical exposure** | TCS, HDFC Bank, ITC | 25-30% |
| **Narrow moat, decent quality** | Maruti, ICICI Bank, Wipro | 30-35% |
| **Capital-intensive cyclical** | Tata Steel, UltraTech, Hindalco | 40-50% |
| **Turnarounds, small caps** | Anything below the top 200 | 50%+ |
| **Distressed / governance flags** | Promoter pledge >20%, qualified auditor | Pass |

Notice that even the best quality business deserves more than 20% MoS in India. "Best quality" does not mean zero risk.

---

## The hidden cost of too little MoS

Say you buy at a 10% MoS. You feel clever. Then the market drops 15% on rupee weakness. The company misses a quarter on input costs. An analyst downgrades. Before anything changes about the long-term thesis, you are down 25-30% on paper.

Retail investors rarely hold through that. They sell. They lock in the loss. They blame the market.

With a 35% MoS, the same sequence of events puts you at break-even or slight loss. You hold. You let the thesis play out.

Bigger MoS is not about buying at the exact bottom. It is about giving yourself room to not panic.

---

## Real patterns you can see on YieldIQ

Two patterns come up repeatedly on the platform:

**Pattern A: "Looked 10% undervalued, fell 40%."**
Stock X shows MoS of +10% based on the base case DCF. Over 18 months, the stock falls to -35% from entry. What happened: input costs rose, promoter pledged shares to fund an acquisition, and a competitor launched a cheaper product. Each event alone would have been survivable with a bigger cushion. Stacked, they were not.

**Pattern B: "Looked 40% undervalued, went nowhere."**
Stock Y shows MoS of +40% but trades sideways for three years before re-rating. That is the other side — a big MoS does not deliver returns quickly. It just limits downside.

You can find current MoS for any stock by going to its fair value page — for example, [ITC fair value](/stocks/ITC/fair-value) or [Reliance fair value](/stocks/RELIANCE/fair-value). To compare two stocks' MoS side by side, use [compare](/compare/ITC-vs-HINDUNILVR). To find stocks with the largest MoS across Nifty 50, start with the [discover page](/discover).

---

## How to actually use MoS

Three habits separate disciplined investors from the rest:

**Write it down.** Before buying, write: "I believe fair value is ₹X. Today's price is ₹Y. My MoS is Z%." If you cannot write it, you do not know it.

**Size position by MoS.** A stock with 40% MoS can get a 5% portfolio weight. A stock with 15% MoS deserves 1-2% at most. Let MoS scale your conviction.

**Re-check MoS quarterly.** Fair value moves with new earnings and new guidance. A stock that had 35% MoS at purchase can slip to 5% MoS after a strong rally — at which point you consider trimming.

---

## Common objections

*"But a great business deserves a premium."*
Yes. That is already in the fair value. MoS is on top of fair value, not a substitute for it.

*"I'm a long-term investor. MoS does not matter."*
Long-term returns depend on entry price. Buffett's compounding is only possible because he buys at big discounts. He does not pay fair value.

*"The market never lets me buy at 35% MoS on quality."*
Not true. COVID 2020, Sept 2018, demonetisation 2016, taper tantrum 2013 — each gave multi-week windows to buy wide-moat stocks at 40%+ MoS. Patience is the premium.

---

## Bottom line

Twenty percent margin of safety is a US textbook number. Indian markets — with their earnings volatility, rupee risk, promoter concentration, and wider multiple bands — demand more.

Use 25% as the floor for quality defensives. Use 35-40% for anything cyclical or mid-cap. Use 50%+ for anything small-cap or turnaround. And walk away when MoS is not there, even if the business is great.

The stocks you do not buy are as important as the ones you do.

---

*Disclaimer: YieldIQ is not a SEBI-registered investment adviser. This article is educational only and does not constitute investment advice. Consult a qualified advisor before investing.*
`,
  },
  {
    slug: "piotroski-f-score-nifty-50-examples",
    title: "Understanding the Piotroski F-Score (With Nifty 50 Examples)",
    description: "All 9 Piotroski criteria explained with Indian stock examples. How to use the F-Score to separate quality compounders from value traps on the NSE.",
    date: "2026-04-22",
    author: "YieldIQ Team",
    category: "fundamentals",
    readTime: 9,
    content: `## Why this score still works after 23 years

In 2000, accounting professor Joseph Piotroski asked a simple question: within the cheapest 20% of stocks (bottom quintile on book-to-market), could a mechanical 9-point test separate the winners from the losers?

The answer was yes. His 9-point system, now called the **Piotroski F-Score**, beat the market by about 7.5% a year over the 1976-1996 backtest.

What makes it still useful in India today is that it focuses on **trends**, not levels. A company with declining margins and rising debt is dangerous even at low P/B. A company with improving margins and falling debt is interesting even at higher P/B. The F-Score captures this without needing judgment calls.

---

## The 9 criteria (one point each)

For each test, the company gets 1 point if the answer is yes, 0 otherwise. Score range: 0 to 9. Higher is better.

### 1. Positive Net Income

Is the company profitable this year?

**What it catches.** Companies burning cash. In Indian small caps this alone filters out a lot of perpetually loss-making firms.

**Example pattern.** A Nifty 50 constituent like TCS scores easily here — consistently profitable for two decades. A turnaround story like a formerly distressed airline might fail this test until operations stabilise.

### 2. Positive Operating Cash Flow

Is the company generating cash from core operations (not just accounting profit)?

**What it catches.** Companies whose reported profit is not backed by real cash collection. A classic red flag is growing receivables faster than revenue — the "sales" are happening on paper but customers are not paying.

**Example pattern.** Asian Paints typically passes this test easily — FMCG and paints both have fast cash collection cycles. A capital goods company with long project cycles may fail this in a year when receivables balloon.

### 3. ROA improving year-over-year

Is Return on Assets this year higher than last year?

**What it catches.** Businesses that are becoming more efficient vs businesses that are flat or deteriorating.

**Example pattern.** HDFC Bank in its high-growth years routinely passed this test — ROA rose consistently. In a year where asset growth outpaces profit growth, even a quality bank can temporarily fail.

### 4. Operating Cash Flow greater than Net Income

Is the cash coming in bigger than the profit reported?

**What it catches.** Quality of earnings. When OCF > NI, the "profit" is backed by real cash. When NI > OCF, some of the profit is accounting — depreciation adjustments, working capital games, revenue recognition timing.

**Example pattern.** Nestle India and HUL typically pass this test every year — FMCG has depreciation higher than capex in cash terms. An IT services firm with rising unbilled revenue may fail this test one quarter.

### 5. Lower long-term debt vs last year

Did the company reduce long-term debt (or at least hold it flat on a proportional basis)?

**What it catches.** Balance sheet getting safer. Rising debt with flat profits is a classic deterioration signal.

**Example pattern.** A debt-free Nifty 50 name like TCS or Infosys passes trivially. A conglomerate that just did a large acquisition will likely fail this test the year of the deal.

### 6. Improving Current Ratio

Is short-term liquidity (current assets / current liabilities) stronger than last year?

**What it catches.** Working capital stress. A falling current ratio means bills are piling up faster than the money to pay them.

**Example pattern.** A well-run FMCG passes most years. A real estate firm with a launch-heavy year may fail as customer advances and supplier liabilities churn.

### 7. No new shares issued

Did the share count stay flat or decrease vs last year?

**What it catches.** Dilution. Every new share issued is a slice of your ownership given away.

**Example pattern.** Companies with active buybacks (select IT majors, a few FMCG names) do well here. Companies that issued fresh equity, or used ESOPs aggressively, fail this test.

### 8. Improving gross margin

Is gross margin (revenue minus cost of goods) higher this year vs last?

**What it catches.** Pricing power. A company that can raise prices, or cut input costs, sees gross margin expand. A company that cannot is squeezed.

**Example pattern.** Asian Paints and Pidilite have historically passed this test in most normal years — strong brands, ability to pass through input cost increases. A cement company in a year of rising coal costs is likely to fail.

### 9. Improving asset turnover

Is revenue per rupee of assets higher than last year?

**What it catches.** Productivity. A company growing revenue faster than assets is squeezing more out of each rupee of capex. A company growing assets faster than revenue is over-investing.

**Example pattern.** A mature FMCG or IT services firm usually does well here. A company in a heavy capex phase (setting up new plants, acquiring) may fail this test for 2-3 years even if the strategy is sound.

---

## Putting it together: how to read the score

| F-Score | Signal | What to do |
|---|---|---|
| **8-9** | Strong across the board, improving fundamentals | Candidate for deeper research |
| **6-7** | Healthy, mostly improving | Reasonable quality filter |
| **4-5** | Mixed signals, no clear direction | Usually skip |
| **2-3** | Multiple deteriorating metrics | Red flags, dig into why |
| **0-1** | Almost everything going wrong | Likely distress or in decline |

An F-Score in isolation is not a buy or sell signal. It is a quality filter. Combine it with valuation (is the stock trading at a sensible price?) and moat (is the advantage durable?).

---

## Illustrative Nifty 50 snapshot

Below is an illustrative table showing the kind of F-Score profile you might see across different Nifty 50 businesses. These are realistic ranges, not specific quoted data points — actual scores change year to year. Use YieldIQ's per-stock pages for live numbers.

| Company | Typical F-Score Range | Why |
|---|---|---|
| Asian Paints | 6-8 | Consistent profitability, strong cash flow, steady margin trend |
| TCS | 7-9 | Debt-free, strong FCF, buybacks help share count criterion |
| HDFC Bank | 6-8 | High ROA, improving operational metrics in most years |
| Tata Steel | 3-6 | Cyclical — score swings with the steel cycle |

The steel company example is telling: it is not a "bad" business, but the F-Score whips around because cyclicals deteriorate and improve on a 3-4 year rhythm. An F-Score of 4 for Tata Steel at the bottom of the cycle can precede a strong rally.

---

## Where the F-Score falls short

**Banks and NBFCs need a separate lens.** Piotroski designed this test for non-financial companies. For banks, metrics like asset turnover and gross margin do not map cleanly. Use NPL ratios, NIM trends, and credit cost trends instead.

**It is backward-looking.** The score is based on the last two years of annual filings. By the time a company's F-Score drops from 8 to 4, the market has often already re-rated the stock.

**No valuation input.** A company with F-Score 9 at a 60x PE is still risky. The score tells you about quality, not price.

**Cyclicals confuse it.** As above, commodity and capital-intensive cyclicals will fail multiple criteria at the bottom of their cycle — sometimes exactly when they are the most interesting.

---

## How to use the F-Score on YieldIQ

Every stock page on YieldIQ shows the current Piotroski F-Score along with the underlying components. For example, look up [HDFC Bank fair value](/stocks/HDFCBANK/fair-value) or [Asian Paints fair value](/stocks/ASIANPAINT/fair-value) and the F-Score is on the quality tab.

To filter for high-score stocks across the market, start with the [discover page](/discover) and sort by F-Score. Cross-reference with the [Nifty 50 page](/nifty50) to focus on large-cap quality.

A practical workflow:

1. Filter for F-Score 7 or higher
2. Within that set, filter for wide or narrow moat
3. Within that set, rank by margin of safety
4. Research the top 10 by hand

That funnel typically turns up a few genuine candidates per month.

---

## Common misuses

**Buying just because F-Score is 9.** Quality is one ingredient. Price matters too.

**Selling just because F-Score dropped from 8 to 6.** One criterion can flip temporarily — a capex-heavy year, for instance. Look at which specific criterion changed and why.

**Applying to banks without adjustment.** The framework needs modification for financials. Use sector-appropriate metrics.

**Treating it as predictive.** F-Score is a snapshot of recent quality trends. It is not a forecast of stock returns.

---

## Bottom line

The Piotroski F-Score is 23 years old and still one of the cleanest, most honest quality filters in fundamental investing. It works in India for the same reason it worked in 1990s US: most retail investors focus on price and ignore the quiet deterioration in the underlying business.

A high F-Score combined with reasonable valuation and a durable moat is as close to a textbook compounder setup as you will find. A low F-Score on a cheap stock is a value trap in the making.

Use it as a filter, not an oracle.

---

*Disclaimer: YieldIQ is not a SEBI-registered investment adviser. This article is educational only and does not constitute investment advice. Consult a qualified advisor before investing.*
`,
  },
  {
    slug: "moat-investing-india-competitive-advantage",
    title: "Moat Investing in India: How to Spot a Durable Competitive Advantage",
    description: "The 5 sources of economic moat adapted for Indian markets — brand, switching costs, network effects, cost advantage and efficient scale — with NSE examples.",
    date: "2026-04-23",
    author: "YieldIQ Team",
    category: "framework",
    readTime: 8,
    content: `## Why moats matter more than growth

Growth is everywhere. Every annual report claims a growth story. Most of them fade within three years because competition shows up, prices get undercut, and margins compress.

A moat is what prevents that. Morningstar's research team formalised the idea in the early 2000s into five moat sources. The framework was built on US data, but it adapts cleanly to the Indian market once you adjust for a few local factors.

This guide walks through all five, with recognisable NSE examples for each.

---

## Moat source 1: Intangible assets (brand)

A brand is a moat only if customers pay more **because of the brand** — not just because the brand is well known.

Test: if the company raised prices 5% tomorrow, would customers walk away?

### Indian examples

**Asian Paints.** A homeowner repainting a house every 7-10 years wants a brand they trust. The product is undifferentiated in chemistry. The trust is the moat. Asian Paints has held market leadership for decades, passed through input cost inflation, and earned ROCE consistently above 25%.

**HUL.** The Dove, Surf Excel, and Lux brands command a premium over nearly identical private-label products. HUL's distribution network (millions of kirana stores reached consistently) reinforces the brand moat — small retailers stock HUL because consumers demand it, and consumers demand it because it is everywhere.

**Titan (Tanishq).** In jewellery, trust is everything. Customers pay Tanishq a premium because they trust the purity certification and the after-sales service. A smaller jeweller selling identical gold at the same purity cannot match the price.

### When brand is not a moat

Many "branded" Indian companies do not actually have pricing power. Cars, two-wheelers, and appliances have strong brands but thin moats — customers switch on 5-10% price differences. Brand recognition is not the same as brand moat.

---

## Moat source 2: Switching costs

Once a customer commits, leaving is painful or expensive. The switching cost can be financial (contract terms), operational (training, integration), or psychological (sunk cost, familiarity).

### Indian examples

**TCS and Infosys.** Large enterprise IT contracts last years. Once a client's core systems are running on a specific vendor's platform, switching means re-training hundreds of staff, re-integrating dozens of systems, and accepting 12-24 months of productivity loss. That is why Indian IT majors have historically held 95%+ client retention rates even when competition undercuts them on price.

**HDFC Bank and Kotak Mahindra Bank.** Switching a primary bank account sounds easy. In practice, it means updating salary accounts, auto-debit mandates, EMIs, UPI handles, investment linkages. Most customers never do it. This inertia is why banks can earn high ROAs on checking balances they pay almost no interest on.

**Polycab.** In electrical cables, once a distributor network commits to a brand, switching creates chaos for electricians, builders, and end customers. Polycab has used this to build a 20%+ share in a highly fragmented market.

### How to spot switching cost moats

- High customer retention rates (>90% in B2B)
- Long average contract length
- Low churn despite competitor pricing pressure
- Customers admit in surveys that switching would be "a hassle"

---

## Moat source 3: Network effects

The product or service gets more valuable as more people use it. This is the moat that scales the fastest and is the hardest for competitors to replicate.

### Indian examples

**Zomato and Swiggy.** More restaurants on the platform attract more diners. More diners attract more restaurants. The dynamic compounds. A new entrant would need to solve both sides simultaneously — which is why Indian food delivery is now effectively a duopoly.

**Naukri (Info Edge).** More job seekers attract more employers. More employers attract more job seekers. Naukri.com has held leadership in Indian online recruitment for two decades against well-funded attempts by Monster, Times Jobs, LinkedIn, and others.

**NSE and BSE.** Stock exchanges are classic two-sided networks. Liquidity attracts buyers and sellers. Buyers and sellers create more liquidity. NSE took market share from BSE in the 1990s by being marginally faster and more electronic — once the network tipped, BSE never caught up in cash equities.

**UPI.** At the system level, UPI is a network effect. Every merchant that accepts UPI makes the system more useful. Every user that has UPI makes it more important for merchants to accept it.

### When network effects are weak

Local network effects often do not survive nationally. A city-level classified platform does not automatically win at the national level. A regional language social app does not translate across states. Always test whether the network effect is truly compounding or just reflects large incumbent size.

---

## Moat source 4: Cost advantage

The company can produce the same product cheaper than anyone else. This moat comes from scale, location, process excellence, or access to a cheap input.

### Indian examples

**UltraTech Cement.** Cement is heavy and expensive to transport (roughly 8-10% of cost is logistics). UltraTech has plants strategically located across India, which means for most customers it has the shortest haul. That translates into a structural cost advantage vs smaller regional players.

**JSW Steel.** Integrated operations, captive power, and captive iron ore via the parent group mean JSW's cost per tonne of steel is among the lowest in the industry. In commodity businesses, being the low-cost producer is often the only durable moat.

**DMart (Avenue Supermarts).** Cluster store strategy (many stores in each city) lowers logistics and marketing cost per store. Ownership of store real estate (vs renting) lowers long-term occupancy cost. These operational choices mean DMart can offer lower prices than organised competition and still earn respectable margins.

**Hindustan Zinc.** Owns one of the world's largest integrated zinc operations. Grade, scale, and integration mean cost per tonne is consistently among the global bottom quartile. In a commodity, that is everything.

### When cost advantage fades

Cost moats erode when the underlying advantage changes. A company that won on cheap power loses its edge when renewable costs fall. A company that won on cheap labour loses its edge when automation takes over. Cost moats need constant reinvestment.

---

## Moat source 5: Efficient scale

Some markets are only profitable for one or two operators. A third entrant cannot earn a reasonable return because the market is not big enough to support them. This is "efficient scale" — natural monopoly or duopoly.

### Indian examples

**GAIL.** Gas pipelines have huge upfront capex and a fixed route. Once GAIL has laid the main pipeline between two cities, nobody builds a parallel one — the economics do not support it. That gives GAIL a near-monopoly on gas transportation in its geographies.

**ONGC's pipeline infrastructure.** Similar logic for crude oil transportation. Once the grid is laid, duplication is uneconomic.

**Power Grid Corporation.** Inter-state electricity transmission in India is effectively a regulated monopoly. Nobody builds a parallel 765-kV line.

**Indian airports (GMR, Adani).** Metro airports are natural monopolies in their catchment. A second major airport in the same city is extremely rare and politically difficult.

### The trade-off

Efficient scale moats are almost always regulated, which caps the upside. Power Grid cannot charge whatever it wants — tariffs are set by the regulator. GAIL's transportation charges are likewise regulated. So efficient scale gives stability but not spectacular returns.

---

## How to actually test for a moat (5 questions)

For any company you are researching, ask:

1. **Has ROCE been above 15% for at least 5 years?** Sustained high ROCE is the single best moat indicator.
2. **Are gross margins stable or rising?** Commodity businesses see gross margins collapse when input prices spike. Moat businesses hold or expand margins.
3. **Is the company raising prices without losing volume?** Annual price hikes that do not dent demand are direct evidence of pricing power.
4. **Can a new competitor show up with ₹1000 crore of capital and compete?** If yes, no moat. If the answer is "even ₹10000 crore would not be enough," you have a wide moat.
5. **What would happen if the promoter retired?** A moat that depends on one person is a narrow moat. A moat embedded in the business is wide.

---

## Moat grading on YieldIQ

Every stock page on YieldIQ shows a moat grade: Wide, Narrow, or None. The classification is based on the criteria above plus sustained ROCE patterns.

To see the moat grade for specific names, check pages like [HUL fair value](/stocks/HINDUNILVR/fair-value) or [TCS fair value](/stocks/TCS/fair-value). To compare moat profiles across peers, use the [compare tool](/compare/ASIANPAINT-vs-BERGEPAINT). To filter for wide moat names across the market, the [discover page](/discover) has a moat filter.

---

## Common moat mistakes

**Confusing size with moat.** Maruti has 40% car market share — but its moat is narrowing as Hyundai, Tata, and Mahindra catch up. Size is a result of past moat, not current moat.

**Assuming moats last forever.** Nokia had a moat in mobile phones. Kodak had a moat in photo film. Hindustan Motors had a moat with the Ambassador. All are gone. Watch ROCE trends and competitive disruptions.

**Paying any price for a wide moat.** A wide moat at 80x earnings can still deliver flat returns for a decade. The moat protects the business. Margin of safety protects the investor.

**Mistaking brand recognition for brand moat.** Being well known is not the same as having pricing power. Test the moat with the "raise prices 5% tomorrow" question.

---

## Bottom line

Five moat sources: brand, switching costs, network effects, cost advantage, efficient scale.

In India, brand-based moats tend to be strongest in FMCG and retail. Switching cost moats dominate enterprise IT and banking. Network effects are the fastest-growing moat category, visible in platform businesses. Cost advantage matters most in commodities and manufacturing. Efficient scale applies mostly to regulated infrastructure.

A business without any of these five is not investable at a premium. A business with two or three of them, bought at a reasonable price, is a textbook compounder.

---

*Disclaimer: YieldIQ is not a SEBI-registered investment adviser. This article is educational only and does not constitute investment advice. Consult a qualified advisor before investing.*
`,
  },
  {
    slug: "reading-indian-financial-statements-guide",
    title: "Quick Guide: How to Read Indian Company Financial Statements",
    description: "Annual report, quarterly results, P&L, balance sheet, cash flow — what each section means for Indian retail investors, with 2-3 key line items per section.",
    date: "2026-04-24",
    author: "YieldIQ Team",
    category: "guide",
    readTime: 9,
    content: `## What you will learn

Indian companies publish a lot of financial information. The annual report can run 300 pages. Quarterly results add more. Most of it is boilerplate. A small fraction is where the real signal lives.

This guide walks you through the four key documents — annual report, quarterly results, balance sheet, and cash flow statement — and for each, highlights the 2-3 line items retail investors should actually look at first.

---

## Annual Report vs Quarterly Results

Indian listed companies publish:

**Annual Report.** Released once a year, roughly 3-4 months after the fiscal year ends (most Indian companies close on 31 March, so annual reports drop in July-August). Contains: audited financials, Director's Report, MD&A (Management Discussion & Analysis), corporate governance section, related-party transactions.

**Quarterly Results.** Released within 45 days of quarter-end. Contains: unaudited (or limited-review audited) financials, segment data, a press release with highlights. No full MD&A, no related-party detail.

### What to read when

If you are researching a stock for the first time, read the **last 2 annual reports**. The MD&A tells you how management thinks. The related-party section tells you what is going on behind the scenes. The segment data tells you where the money actually comes from.

Quarterly results are useful for tracking a thesis. If your view was "FMCG growth will accelerate in H2," the quarterly result is your scorecard.

---

## The P&L statement

Also called the Profit and Loss statement or Income Statement. Flow: Revenue → EBITDA → PAT.

### Structure (simplified)

\`\`\`
Revenue from Operations       (top line)
  Less: Cost of Goods Sold
  Less: Employee Costs
  Less: Other Operating Expenses
= EBITDA
  Less: Depreciation & Amortisation
= EBIT (Operating Profit)
  Less: Finance Costs (interest)
  Plus: Other Income
= Profit Before Tax (PBT)
  Less: Tax
= Profit After Tax (PAT)   (bottom line)
\`\`\`

### 3 key line items to check

**1. Revenue growth year-over-year.** Compare this year's revenue to last year's same period. Growth below inflation (5-6% in India) means the company is shrinking in real terms.

**2. EBITDA margin.** EBITDA / Revenue. Compare to last year. Expanding margin signals pricing power or cost discipline. Contracting margin is a red flag, especially in a growing-revenue environment — it means either competition is intensifying or costs are running away.

**3. Other Income as a percent of PBT.** "Other Income" is usually interest on cash balances, dividends, and one-off sales. If Other Income is 30%+ of PBT, the company's core operations are weaker than the headline profit suggests.

### What to ignore (on first read)

Exceptional items. These are one-offs that companies split out. Occasionally meaningful (large asset sale, litigation settlement) but usually noise. Look at the base earnings first, then add back exceptionals only if you understand them.

---

## The Balance Sheet

A snapshot at a specific date. Three sections: Assets, Liabilities, Equity.

### Structure (simplified)

\`\`\`
ASSETS
  Non-current Assets
    Fixed Assets (plant, property, equipment)
    Intangibles (goodwill, software)
    Investments
  Current Assets
    Inventory
    Trade Receivables
    Cash & Cash Equivalents

LIABILITIES
  Non-current Liabilities
    Long-term Borrowings
    Deferred Tax
  Current Liabilities
    Trade Payables
    Short-term Borrowings
    Other Current Liabilities

EQUITY
  Share Capital
  Reserves & Surplus
\`\`\`

The accounting identity: Assets = Liabilities + Equity.

### 3 key line items to check

**1. Net Debt.** Total Borrowings (short-term + long-term) minus Cash & Equivalents. A company with ₹5,000 crore of debt and ₹4,500 crore of cash is nearly debt-free. A company with ₹5,000 crore of debt and ₹200 crore of cash is leveraged. Headline debt numbers lie — always calculate net debt.

**2. Trade Receivables vs Revenue.** If receivables are growing faster than revenue, customers are paying slower. This is a classic early warning of stress — either the customer base is weakening or the company is stuffing the channel with inventory.

**3. Reserves & Surplus growth.** Reserves should grow by roughly (PAT - Dividends) each year. If reserves are flat or shrinking despite reported profits, something is being written off that deserves investigation.

### The share capital trap

Share capital ("equity" in the narrow sense) is the face value of shares issued. It does not tell you market cap. A company with ₹100 crore share capital at ₹10 face value has 10 crore shares outstanding — whose market value might be anywhere. Do not confuse share capital with market value or book value.

---

## The Cash Flow Statement

The most honest statement. Profit can be engineered. Cash cannot easily be. Three sections:

**Cash Flow from Operating Activities (CFO).** Cash generated by core business — customer collections minus supplier and employee payments.

**Cash Flow from Investing Activities (CFI).** Money spent on or received from long-term assets — buying plants, acquiring companies, selling investments.

**Cash Flow from Financing Activities (CFF).** Money from or to capital providers — new equity, new debt, debt repayment, dividends.

### 3 key line items to check

**1. CFO vs Net Income.** For a healthy, stable business, CFO should be at least as large as Net Income, usually bigger (because of depreciation add-back). If CFO is chronically smaller than Net Income, the earnings quality is suspect — profits are not converting to cash.

**2. Capex (inside CFI).** Called "Purchase of Property, Plant & Equipment" or similar. Compare capex to depreciation. If capex > depreciation consistently, the company is investing for growth. If capex < depreciation, the company is slowly shrinking its asset base.

**3. Free Cash Flow.** FCF = CFO - Capex. This is what is left for shareholders after the business pays for everything. A company with positive, growing FCF is creating value. A company with negative FCF for years is either a startup or in trouble.

### Where dividends and buybacks appear

Both show up in Cash Flow from Financing Activities as outflows. Consistent dividends or buybacks funded from CFO (rather than from new debt) are healthy. Dividends funded by fresh borrowings are a red flag.

---

## Segment reporting (the hidden gem)

Indian accounting standards require companies with diversified operations to disclose segment-wise revenue, EBIT, and assets. This information is usually buried in the notes to accounts.

For conglomerates like Reliance, ITC, or L&T, segment data is where the real analysis happens. You can see which business is actually driving the numbers.

Example: for a hypothetical diversified company, the headline might read "revenue up 12%." The segment breakdown might reveal that the legacy business shrunk 5% while a new business grew 80%. Same headline, completely different story.

---

## Related-party transactions

Every annual report has a section listing transactions with entities controlled by the promoter family. In India, this is arguably the single most important governance disclosure.

What to look for:

- **Loans given to related parties.** These are often never repaid. Investor money funding promoter ventures.
- **Purchases from promoter-owned suppliers.** If the company pays above market rates, value is being transferred out.
- **Rentals paid to promoter-owned property.** Again, a channel for value transfer.

Small related-party transactions (under 1% of revenue) are normal. Large ones (5%+ of revenue, or growing year over year) deserve scrutiny.

---

## A practical 15-minute first read

When you open a company's financial statements for the first time:

1. **Revenue growth** over the last 3 years (P&L, top line)
2. **EBITDA margin trend** over the last 3 years (is it expanding, flat, or contracting?)
3. **Net debt trajectory** over the last 3 years (rising, flat, falling?)
4. **CFO vs Net Income** over the last 3 years (is profit converting to cash?)
5. **Capex vs Depreciation** (growing, maintaining, or shrinking asset base?)
6. **Segment split** if diversified (which businesses are driving growth?)
7. **Related-party transactions** (anything large or unusual?)

That is typically 15-20 minutes of work. It is enough to decide whether the company is worth deeper research.

---

## How YieldIQ helps

YieldIQ computes all these ratios automatically for every Indian stock. On any stock page — for example [ITC fair value](/stocks/ITC/fair-value) or [HDFC Bank fair value](/stocks/HDFCBANK/fair-value) — you see:

- 5-year revenue and EBITDA margin trends
- Net debt trajectory
- CFO to Net Income ratio
- FCF history
- Auto-flagged anomalies (receivables growing faster than revenue, CFO lagging profit, etc.)

For comparing two companies side by side on these metrics, use the [compare tool](/compare/ITC-vs-HINDUNILVR). To screen across the market for financial quality, the [discover page](/discover) lets you filter on many of these ratios at once.

The auto-audit on each stock page highlights the specific line items that look unusual, so you can go straight to the right section of the annual report instead of reading all 300 pages.

---

## Common beginner mistakes

**Reading only the press release.** Management will always frame the quarter positively. The numbers in the filing are the truth.

**Ignoring the notes to accounts.** Contingent liabilities, related-party transactions, pledged shares — all in the notes. Skip these and you miss the most important information.

**Focusing on PAT and ignoring cash flow.** PAT can be manipulated. Cash flow is harder to fake. Always check that profits are backed by cash.

**Comparing Indian companies to US companies line by line.** Accounting conventions, tax structures, and disclosure norms differ. Stick to Indian peers for comparisons.

---

## Bottom line

You do not need to read 300 pages to understand an Indian company. You need to read the right 20 pages, and for each section, look at the handful of line items that matter.

Start with revenue growth and EBITDA margin. Check net debt. Look at CFO vs profit. Scan related-party transactions. That is 80% of the signal in 15 minutes.

YieldIQ computes all these ratios automatically — check any stock's page for the auto-audit.

---

*Disclaimer: YieldIQ is not a SEBI-registered investment adviser. This article is educational only and does not constitute investment advice. Consult a qualified advisor before investing.*
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
