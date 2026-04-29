# YieldIQ Methodology White Paper

**Version 1.0 — published 2026-04-28**
**Authors:** YieldIQ Research
**Status:** Open methodology. Suggest edits via GitHub.

---

## 1. Executive Summary

YieldIQ is a descriptive equity-analysis platform for the Indian listed market. It computes a fair-value estimate, a six-axis quality "Prism", and a composite letter grade for every stock it covers, and it shows the reader the inputs and intermediate steps behind each number.

YieldIQ is **not** investment advice. We are not a SEBI-registered Research Analyst, we make no buy/sell calls, and we do not manage money. Every output on the platform is a model artefact, presented descriptively, with the caveats and confidence flags that produced it.

We believe three things, and the rest of this paper is a record of the work we have done to live by them:

1. **Data correctness is upstream of everything.** A model that is fed half-corrupt inputs is worse than no model: it manufactures false confidence. Roughly half of our engineering effort is spent on the boring, unglamorous work of making sure ROE means ROE, that revenue is in crores when we say it is, and that a percentage is never accidentally multiplied by 100.

2. **Methodology depth is non-negotiable.** A discounted cash flow that uses one number for the discount rate of every business in India is not a DCF — it is a slogan. We carry a sector-aware WACC table, a sector-aware terminal-growth schedule, a peer-multiple ceiling, and explicit overrides for cyclical sectors (oil & gas, metals, airlines) where one peak year of FCF would otherwise dominate a 10-year forecast.

3. **Transparency is the deliverable.** Every number on the platform should click through to its source — a filing, a formula, a configuration value, a line of code. This white paper is the most concentrated form of that promise: the formulas, the cutoffs, the failure modes, and the file paths where they live.

This paper is roughly 12,500 words. It is written for the curious reader: a sceptical retail investor, an analyst evaluating us against a Bloomberg/Morningstar/Trendlyne baseline, a future engineer joining the team, or a future critic who wants to argue with us in good faith.

---

## 2. The Valuation Model

### 2.1 Why DCF for Indian equities

Indian markets present a peculiar valuation problem. The benchmark P/E for the Nifty 50 has hovered around 22–24 for most of the last decade, even as constituent businesses have spanned a 5x range of underlying quality, growth, and capital intensity. A relative-multiples-only model collapses that range into a single comparable, and it leaks every time inflation, interest rates, or risk appetite move.

A discounted-cash-flow model is the only valuation approach that:

- Forces the analyst to commit to an explicit forecast (revenue, margin, capex, working capital).
- Anchors the answer to an absolute risk-adjusted opportunity cost (the WACC), not to whatever cohort happens to be cheap or expensive.
- Decomposes cleanly when the answer is wrong: a missed FV is always traceable to a specific assumption that broke.

DCF has well-known failure modes — terminal-value sensitivity, garbage-in / garbage-out on growth assumptions, weak applicability to financials. We address each of these explicitly, in this section and the next.

A practical note on what the model does *not* attempt:

- We do not produce probability-weighted scenarios with explicit subjective probabilities. The bull / base / bear are mechanical perturbations (§2.6), not analyst forecasts. A model that asks the analyst to assign a 30% probability to the bear case is asking for a number that nobody can produce honestly.
- We do not produce sum-of-the-parts (SOTP) valuations as the primary FV for conglomerates. SOTP requires a segment-by-segment financial statement, which the public XBRL filings provide for only a minority of Indian conglomerates. We compute consolidated DCF and, where the structure demands it (Reliance, Mahindra, Bajaj group), surface a "segment dispersion" caveat on the analysis.
- We do not handle deeply distressed equity. A stock with persistent negative FCF, persistent negative net income, and negative book equity is outside the regime where DCF is even definable; we mark such tickers `dcf_reliable=False` and surface only the multiples-relative path.

### 2.2 Sector-aware WACC

The single largest analyst-facing concession in a typical retail DCF tool is the discount rate. Many tools use one number — a "12%" or a "10%" — across every business they cover. YieldIQ uses a sector-aware WACC table whose defaults reflect the structural differences between businesses, with a CAPM override when the company's own beta and capital structure are clean.

The table lives at `models/industry_wacc.py`. Below is an excerpt of the Indian sector defaults; the file carries 25+ India sectors and a parallel set of 15+ US sectors:

| Sector              | WACC (default) | Terminal g | Beta (typ.) | Notes                                                         |
|---------------------|---------------:|-----------:|------------:|---------------------------------------------------------------|
| FMCG                | 10.0%          | 4.0%       | 0.75        | Defensive demand; pricing power; low capex                    |
| IT services         | 11.0%          | 3.5%       | 1.05        | Asset-light; USD revenue; stable margins                      |
| Pharma              | 11.5%          | 3.5%       | 0.85        | R&D-heavy; FDA risk; high working capital                     |
| Hospitals           | 11.0%          | 4.0%       | 0.90        | Asset-heavy but stable demand                                 |
| Auto OEM            | 12.0%          | 3.0%       | 1.10        | Cyclical demand; capex-heavy                                  |
| Capital goods       | 12.0%          | 3.5%       | 1.10        | Order-book dependence; project execution risk                 |
| Regulated utility   | 9.0%           | 4.0%       | 0.65        | CERC / PNGRB tariff; ~15.5% regulated ROE; bond-like cash flow |
| Power               | 10.5%          | 3.0%       | 0.85        | Mix of merchant + regulated; capital-heavy                    |
| Oil & gas           | 11.0%          | 2.5%       | 0.95        | Commodity price risk; government influence                    |
| Metals & mining     | 13.0%          | 2.5%       | 1.30        | Highly cyclical; commodity-price sensitive                    |
| Cement              | 11.0%          | 3.5%       | 1.05        | Capex-heavy; regional pricing power                           |
| Real estate         | 13.0%          | 3.0%       | 1.30        | High leverage; project risk; illiquidity                      |
| Telecom             | 12.0%          | 3.0%       | 1.05        | Capital-intensive; spectrum costs                             |
| Airlines            | 11.5%          | 2.5%       | 1.35        | High capex; lease liabilities; fuel risk                      |
| Banking / NBFC      | (DCF disabled — see §2.5) |  |              | Use P/B-driven path                                           |

A few choices in this table deserve their own paragraph:

**Regulated utility at 9.0%.** The Central Electricity Regulatory Commission (CERC) sets a 15.5% return on equity for regulated transmission and distribution assets. The Petroleum and Natural Gas Regulatory Board (PNGRB) follows a similar regime for gas networks. The cash flows of NTPC, POWERGRID and GAIL are therefore more bond-like than equity-like over a 5–10 year window. Anchoring their WACC at the bond-cost end of the range (8.5–10.0%) is a deliberate choice: using a generic 12% for a regulated utility systematically under-values it.

**Metals at 13.0%.** Indian metal cycles run on global commodity prices, which the firm does not control. Even Tata Steel and JSW have observed FCF coefficients of variation north of 0.5 over the last decade. The higher discount rate is the price of admission for that cyclicality, and the lower terminal growth (2.5%) is the second seatbelt — see §2.3.

**Airlines at 11.5% with 2.5% terminal.** The terminal growth is anchored deliberately below India nominal GDP. Airlines are perpetually capacity-constrained by route rights, slots, and fuel; they grow with consumption but not with the economy as a whole.

**Banks and NBFCs are excluded from DCF.** A bank's "free cash flow" is structurally meaningless — its assets are loans and its liabilities are deposits, and the regulatory-capital constraint dominates the firm's reinvestment math. We use a P/B-driven path for banks and NBFCs (see §2.5).

**SaaS / software at 9.0%.** A small but distinct sector — Intellect Design, Newgen, Tally — characterised by recurring revenue, negative working capital (subscriptions are paid up-front), and high R&D intensity. The lower WACC reflects the higher predictability of subscription revenue; the higher terminal growth (4.0%) is the same recognition that asset-light recurring-revenue businesses face a longer compounding runway than capital-cycle businesses do.

**The capex_intensity column.** Each row of the WACC table also carries `capex_intensity`, `wc_pct_revenue`, `rd_pct_revenue`, `depreciation_pct`, and a `fcf_conv_factor`. These are not used to discount cash flow — the WACC handles that — but they parametrise the FCF-base computation in `_compute_fcf_base`. The conversion factor (`fcf_conv_factor`) is the most material: 0.88 for IT services, 0.85 for SaaS, 0.72 for pharma, 0.65 for hospitals, 0.45 for airlines. A high conversion factor says NOPAT translates almost directly into FCF (asset-light); a low conversion factor says NOPAT is half-eaten by capex (asset-heavy).

When live data is reliable, the system overrides the sector default with a CAPM build-up:

```
Re   = Rf + β × MRP
WACC = (E/V) × Re + (D/V) × Rd × (1 − tax)
```

with India-specific anchors:
- `Rf` = live India 10-year government bond yield (^INBMK), refreshed every 6 hours
- `MRP` = 6.0% (Damodaran 2025 India equity-risk premium)
- Re floor = 9.0% (country risk + inflation), Re cap = 25.0%
- WACC floor = 9.0%, WACC cap = 20.0%
- Beta clipped to [0.5, 3.0]; falls back to a sector default when missing

Code: `models/forecaster.py::compute_wacc` (lines 499–645).

### 2.3 FCF projection: 10-year fade with terminal growth

We project free cash flow ten years out using a single-stage exponential fade. The formula:

```
g(t) = g_T + (g_0 − g_T) × exp(−k · t)
```

where:
- `g_0` = base growth derived from the company's history (revenue growth, FCF growth, sector blend)
- `g_T` = sector terminal growth (typically 3–4% for India, 2–2.5% for US)
- `k` = 0.25 (the fade constant)

The fade constant `k = 0.25` was deliberately reduced from 0.35 in v3 of the forecaster after we observed that high-growth pharma and IT companies were being faded to mediocrity by year 5 — punishing a real 18% compounder more than the data warranted. Code: `models/forecaster.py:36`.

Growth itself is constrained:
- `MAX_FCF_GROWTH = 35%` (`forecaster.py:33`)
- `MIN_FCF_GROWTH = −15%` (`forecaster.py:34`)

These bounds matter. Without them, a company with one weird historical year (e.g., a 70% revenue jump from a demerger or a one-off divestment gain) gets a terminal projection that is purely fictional.

The base growth is itself a blend of three signals (`forecaster.py:37`):

```
base_growth = 0.30 × ridge_regression_growth
            + 0.30 × random_forest_growth
            + 0.40 × rule_based_growth
```

The rule-based component is sector-aware: pharma and IT lean 80% on revenue growth (FCF is lumpy due to R&D and M&A), while balanced sectors like FMCG use a 65/35 revenue/FCF split. The full table is at `forecaster.py:347–377`.

The base FCF is selected from a candidate set:
1. **Latest reported FCF** — the strongest signal if positive.
2. **Maximum of the last three positive FCF years** — corrects for one-off bad capex years.
3. **NOPAT proxy** — `EBIT × (1 − tax) × FCF_conv_factor`, where the conversion factor is sector-specific (0.88 for IT, 0.45 for airlines, 0.65 for hospitals — see `industry_wacc.py`). This is the most reliable base for asset-light businesses where D&A ≈ maintenance capex.
4. **75th-percentile historical FCF margin** — a fallback for companies with volatile FCF history.

The selection takes the median of (latest, NOPAT, max-3yr) and applies a NOPAT floor at 60% — preventing one bad capex year from collapsing the valuation.

**Cyclical override.** For oil & gas, metals, chemicals, autos, sugar, and airlines, we replace the "max" candidate with the 5-year median of positive FCFs. This is a direct response to the BPCL incident of April 2026, where a one-off FY24 FCF of ₹26,390 Cr (driven by inventory gains on a falling crude price) propagated into the terminal and produced a DCF FV of ₹716 against analyst consensus of ₹400–500. Code: `forecaster.py:222–260`. Cement was originally in the cyclical set but was removed (`forecaster.py:214`) because the current Indian infrastructure cycle has structurally higher base FCF than the 5-year lookback — applying the cyclical median was crushing legitimate compounders like SHREECEM and ULTRACEMCO.

**Margin-fade scaffold.** When the trailing-twelve-month operating margin exceeds 130% of the trailing-3-year average, we taper the projected FCF over years 1–3 to migrate from the (peak) TTM margin back to the (normalised) 3-year average. This is a one-sided guard: when TTM ≤ 130% × 3-year avg, the multiplier is 1.0 throughout. Code: `forecaster.py:836–867`.

The terminal value is computed as:

```
TV = terminal_FCF × (1 + g_T) / (WACC − g_T)
```

where `terminal_FCF` is the average of years 8, 9, 10 of the projection (smoothing out the last-year stochastic component). The terminal value is discounted back to year 0 at the WACC.

Equity value:

```
Equity = sum(PV(FCF_t) for t in 1..10) + PV(TV) − total_debt + total_cash
FV / share = Equity / shares_outstanding
```

### 2.4 Worked example — TCS

Inputs (as of late April 2026, illustrative):
- Sector: `it_services` → WACC default 11.0%, terminal g 3.5%, NOPAT→FCF conv 0.88
- Latest revenue: ₹2,52,000 Cr
- Operating margin (TTM): 24.0%
- Trailing-3-year average op margin: 24.5% (no peak fade triggered)
- Latest reported FCF: ₹46,500 Cr
- Total debt: ~₹9,000 Cr
- Total cash: ~₹52,000 Cr
- Shares outstanding: 362 Cr

CAPM build-up for WACC: with β = 0.95 (yfinance), Rf = 6.95% (live G-Sec), MRP = 6.0%:
```
Re   = 0.0695 + 0.95 × 0.06 = 12.65%
Rd   = 4.5% (interest expense / total_debt, clipped)
E/V ≈ 0.96 (very low debt), D/V ≈ 0.04
WACC = 0.96 × 12.65% + 0.04 × 4.5% × 0.75 ≈ 12.27%
```

Base growth: rule-based at 11.5% (sector-blended, 75% revenue, 25% FCF growth, mean-reverted toward the long-run target of ~6% for >₹50,000 Cr market cap), blended with ML signals → ~10.5%.

NOPAT proxy: `2,52,000 × 0.245 × 0.75 × 0.88 ≈ 40,750` Cr. Selected base FCF: median of (46,500, 40,750, 50,300) = ₹46,500 Cr.

Year-by-year projection (g fades from 10.5% to 3.5% with k = 0.25):

| Year | Growth | FCF (₹ Cr) | DF (12.27%) | PV (₹ Cr) |
|-----:|-------:|-----------:|------------:|----------:|
| 1    | 10.5%  | 51,380     | 0.891       | 45,780    |
| 2    | 9.0%   | 56,000     | 0.794       | 44,460    |
| 3    | 7.7%   | 60,310     | 0.707       | 42,650    |
| 4    | 6.7%   | 64,350     | 0.630       | 40,540    |
| 5    | 5.9%   | 68,150     | 0.561       | 38,230    |
| 6    | 5.4%   | 71,830     | 0.500       | 35,920    |
| 7    | 4.9%   | 75,350     | 0.445       | 33,540    |
| 8    | 4.6%   | 78,820     | 0.397       | 31,290    |
| 9    | 4.4%   | 82,290     | 0.353       | 29,050    |
| 10   | 4.2%   | 85,750     | 0.315       | 27,010    |

Terminal FCF (avg of years 8–10) ≈ ₹82,287 Cr. Terminal value:
```
TV = 82,287 × 1.035 / (0.1227 − 0.035) = 9,71,200 Cr
PV(TV) = 9,71,200 × 0.315 ≈ 3,06,100 Cr
```

Equity value:
```
sum PV(FCF) = 3,68,470 Cr
PV(TV)      = 3,06,100 Cr
Net cash    =   43,000 Cr
Equity      = 7,17,570 Cr

FV / share  = 7,17,570 × 1e7 / 362e7 ≈ ₹1,982
```

This is illustrative. The real number on the platform will differ by ±5–8% depending on intra-day price drift, the exact live G-Sec yield, and the latest quarterly FCF.

**Hysteresis on FCF base selection.** A subtle but important detail: the FCF base candidates (latest_fcf, NOPAT proxy, max_recent_fcf) often sit within 10% of each other. Small upstream revisions to yfinance financials cause the candidate ranking to flip day-over-day, producing FV oscillation with no economic content. We added a hysteresis layer (`forecaster.py:269–296`): if yesterday's run used a particular candidate slot and today's top candidate is within 10% of the incumbent, we hold yesterday's choice. This eliminated the 26% same-day FV swing observed for RELIANCE on April 15–17, 2026, traced to a yfinance revision that flipped the median from `latest_fcf` to `nopat_proxy`. The hysteresis is recorded in the DCF trace as `fcf_base_source = "hysteresis(<prev_source>)"` so a reviewer can audit it.

**Pharma R&D adjustment.** R&D is investment, not recurring opex. We treat 60% of pharma R&D as growth capex (pipeline build) and 40% as maintenance. The economic-NOPAT computation adds back 60% of R&D (after tax) before applying the 0.80 conservative conversion factor. This follows standard sell-side practice — EV/EBITDA multiples on pharma routinely ignore R&D for the same reason — and it materially raises the DCF FV for high-R&D pharma names like Sun Pharma and Dr. Reddy's. Code: `forecaster.py:160–170`.

### 2.5 Worked example — KOTAKBANK (P/B path)

Banks and NBFCs are routed away from DCF. Their fair value comes from a P/B-relative model anchored on regulated capital efficiency.

The mechanics: we compute a sector P/B median from `market_metrics.pb_ratio` over a peer cohort (filtered to liquid names: market cap > ₹500 Cr, sector = "Financial Services"). For each target bank, we solve:

```
implied_FV = current_price × (peer_median_PB / target_PB) × ROE_adjustment
```

where the ROE adjustment is `(target_ROE / peer_median_ROE) ^ 0.5` — a square-root weighting that gives credit for higher ROE without letting it dominate the answer.

KOTAKBANK example (illustrative):
- Peer P/B median (HDFCBANK, ICICIBANK, AXISBANK, SBIN, INDUSINDBK): 2.4
- KOTAKBANK current P/B: 3.6
- KOTAKBANK ROE: 14.0%; peer median ROE: 13.5%
- Current price: ₹1,800
- ROE adjustment: `sqrt(14.0 / 13.5) = 1.018`
- Naive P/B-relative FV: `1,800 × (2.4 / 3.6) = 1,200`
- ROE-adjusted FV: `1,200 × 1.018 ≈ 1,222`

This is mechanically conservative for premium banks — KOTAKBANK has historically traded at a structural P/B premium, so a peer-median model will frequently flag it as overvalued. We surface this as the model's view; we do not editorialise it as a buy/sell.

The peer median is sanity-bounded: P/B is filtered to `[0.2, 50]` to suppress garbage rows in `ratio_history`. See `backend/services/peer_cap_service.py:245`.

### 2.6 Bull / base / bear scenarios

Every DCF run produces three scenarios. The dispersion is generated by perturbing the two highest-leverage assumptions:

| Scenario | Growth perturbation | WACC perturbation |
|----------|---------------------|-------------------|
| Base     | Model output        | Model output      |
| Bull     | +200 bps to g_0     | −50 bps to WACC   |
| Bear     | −200 bps to g_0     | +50 bps to WACC   |

The fade constant and terminal growth are held fixed across scenarios — they are sector parameters, not company-specific tuning knobs.

The canary harness enforces `bull > base > bear` with at least 5% spread on each side (gate 3 — see §6.2). A scenario set that violates this is symptomatic of a numerically unstable input — typically a near-zero NOPAT proxy or a base growth that hits the +35% / −15% clamp.

### 2.7 Peer-multiple cap

A DCF can blow past plausible valuations on small- and mid-cap names with thin coverage data. JUSTDIAL once showed an 91% margin-of-safety reading; EMAMILTD showed 82%. The DCF was internally consistent — the inputs were just wrong, and no internal model check could see that.

A one-line sanity check against sector peers tells you the displayed FV would price the stock at 5–10× the median P/E of comparable businesses. That is almost never a mispricing — it is a model miscalibration.

The peer-cap rule:

```
peer_implied_FV = current_price × (peer_median_PE / target_PE)
                  (or EV/EBITDA-implied, take the lower of the two)

if 1.5 × peer_implied_FV < dcf_FV:
    displayed_FV = 1.5 × peer_implied_FV
    fair_value_source = "peer_capped"
```

Code: `backend/services/peer_cap_service.py::compute_peer_cap`. Implementation details:

- Minimum 3 liquid peers (`_MIN_PEERS = 3`) to compute a median; below that, no cap is applied.
- Liquidity floor: market cap > ₹500 Cr (`_MIN_PEER_MCAP_CR`).
- Match priority: industry first (tighter), sector if industry yields fewer than 3 peers.
- For non-banks, take the lower of P/E-implied and EV/EBITDA-implied. For banks, P/B-only.
- Sanity bounds: P/E ∈ [3, 250]; EV/EBITDA ∈ [1, 100]; P/B ∈ [0.2, 50] — these clip out the upstream pipeline noise (a known issue: ~30% of IT-services tickers in `ratio_history.pe_ratio` carry a normalised score < 1 instead of a true ratio; see `peer_cap_service.py:225–245`).

The 1.5× headroom is deliberate. It preserves legitimate undervaluation calls — a stock that DCF says is 50% undervalued AND that trades at a 1.4× peer-multiple premium will still display its full DCF FV. The cap only fires in the implausible tail.

When the peer cap fires, model confidence is automatically deducted (see §3.5).

**Why 1.5×, not 1.0× or 2.0×?** The factor was chosen empirically. We ran the cap at 1.0× (no headroom) on the canary 50 and observed that 8 stocks with legitimate undervaluation calls (TVS Motor in late 2025, Tata Motors during the JLR turnaround, Federal Bank during the credit-cycle inflection) were being clipped. We ran the cap at 2.0× and observed that JUSTDIAL and EMAMILTD continued to display 60–70% MoS readings that were artefacts. 1.5× preserved every legitimate call we could identify and clipped every artefact we could identify. We will revisit when the universe is large enough to drive this from data rather than from inspection.

**Bank P/B-only path.** For banks (sector = "Financial Services"), the cap is computed against peer P/B, not P/E. Earnings volatility from provisioning cycles makes bank P/E an unstable comparable; book value is not. The `_BANK_LIKE_SECTORS` set is at `peer_cap_service.py:70`.

**What the cap does NOT do.** It does not adjust the underlying DCF. The DCF inputs and outputs are preserved in the trace; only the *displayed* fair value is modified. This is deliberate: the cap is a sanity filter on what we present to the user, not a tuning of the underlying model. A future engineer auditing the cap's effect can read `fair_value_source` in any cached `analysis_payload` to see whether DCF or peer-cap drove the displayed number.

---

## 3. Quality Scoring

### 3.1 The composite

The YieldIQ Composite Score (0–100) is a quality-tilted blend of four factors. The split is deliberately quality-heavy; a margin-of-safety reading is a *price* signal, not a *business* signal, and over-weighting it penalises premium-priced compounders (Nestle, Asian Paints, Titan) whose fundamentals are excellent.

| Factor             | Weight | Source                                                         |
|--------------------|-------:|----------------------------------------------------------------|
| Business Quality   | 50 pts | Piotroski F-score (25) + Economic moat (25)                    |
| Growth             | 20 pts | Revenue growth trajectory, percent-form input                  |
| Valuation          | 20 pts | Margin of safety from DCF (or P/B path)                        |
| Sentiment          | 10 pts | Analyst consensus upside (where available)                     |
|                    | 100    |                                                                |

Code: `dashboard/utils/scoring.py::compute_yieldiq_score`.

The valuation cutoffs:
- MoS ≥ 40% → 20 pts; ≥ 25% → 16; ≥ 10% → 12; ≥ 0% → 8; ≥ −15% → 5; ≥ −30% → 3; else 0.

The growth cutoffs (after auto-converting decimal inputs to percent — see the bug history at `scoring.py:69–82`, where every decimal-form `enriched["revenue_growth"]` of 0.15 was being scored against a percent-form scale and slotted into the "≥ 0" bucket):
- Rev growth ≥ 20% → 20; ≥ 10% → 15; ≥ 5% → 10; ≥ 0% → 5; else 0.

The sentiment cutoffs:
- Analyst upside ≥ 20% → 10; ≥ 10% → 7; ≥ 0% → 4; else 1.

**Why quality-heavy?** A 50/20/20/10 split — half the points to capital efficiency and durability — is unusual for a public scoring product. Most retail screeners weight valuation at 30–40% because cheap-and-cheerful is easier to market. Our experience running the scoring engine across the Nifty 100 over the last year is that the modal failure of a value-heavy composite is to flag structurally broken businesses (declining-revenue PSUs, capital-destroying retail names) as A-grade simply because they are cheap. The quality-heavy weighting tolerates an A-grade Nestle with a single-digit MoS — which is what serious long-horizon investors actually want — at the cost of producing fewer "A-grade dirt-cheap PSU" signals. We are explicit about that trade-off, and we believe it is the right one for the audience we serve.

**Why is sentiment in the composite at all?** Analyst-consensus-upside is a weak signal in India — coverage is thin outside the Nifty 200, and the analysts who cover most Indian small-caps have material conflicts. We carry it at 10% because the directional information is real (a tracked stock with 25%+ analyst upside has empirically outperformed one with 0% upside, controlling for quality) but we cap its weight to keep it from dominating. For sentiment-light tickers (no analyst coverage), the 10 sentiment points default to 4 (the "≥ 0%" bucket) and the score's effective range becomes 0–94 rather than 0–100.

### 3.2 Piotroski F-score, Indian-bank adapted

The standard Piotroski F-score (Piotroski, 2000) is a 9-point binary checklist on Profitability, Leverage/Liquidity, and Operating Efficiency. We use the orthodox version for non-financial companies and a domain-adapted variant for banks and NBFCs.

**Standard (non-financial):**

Profitability (4 pts):
1. Net income > 0
2. Operating cash flow > 0
3. ROA improving year-over-year
4. Operating cash flow > Net income (quality of earnings)

Leverage / Liquidity (3 pts):
5. Long-term debt / Total assets falling
6. Current ratio improving
7. No share dilution (shares outstanding flat or falling)

Operating efficiency (2 pts):
8. Gross margin improving
9. Asset turnover improving

**Bank/NBFC adaptation.** The orthodox formula penalises banks for "high leverage" — but a bank IS a leveraged business by design; the fact that HDFCBANK has D/E of 8 is not a quality signal, it is the structure of the industry. For banks and NBFCs we substitute:

- (5) replaced with **CAR improvement** (Capital Adequacy Ratio year-over-year)
- (6) replaced with **GNPA improvement** (lower is better)
- (9) replaced with **Cost-to-income improvement** (lower is better)

The score is then transformed to the Quality component:

```
piotroski_pts = min(piotroski / 9 × 25, 25)
```

A 9/9 Piotroski earns the full 25 quality points; a 5/9 earns 13.9.

### 3.3 Moat classification

Moat grades drive the second 25 points of the Quality factor. The classification engine (`screener/moat_engine.py`) emits one of four labels:

| Label    | Score | Threshold criteria                                                         |
|----------|------:|---------------------------------------------------------------------------|
| Wide     | 25    | ROE > 18%, ROCE > 18%, gross margin > 35%, all sustained 5+ years         |
| Moderate | 15    | At least 3 of 4: ROE > 15%, ROCE > 15%, GM > 25%, market-share leadership |
| Narrow   | 18    | Some moat signal — pricing power, scale, IP, distribution                 |
| None     | 0     | Commodity-economics business; ROE / margins track sector mean             |

(The Moderate row scores between Narrow and Wide because the engine treats a "well-distributed-but-not-spectacular" business as quality but not as a defensible compounder. Mapping table: `dashboard/utils/scoring.py:57–64`.)

A historical bug worth narrating: between 2026-02 and 2026-04-24, the "Moderate" label was missing from the moat-points map, so every Moderate-moat ticker (HDFCBANK, ICICIBANK, TCS, HCLTECH, MARUTI, HUL, NESTLE, ASIANPAINT) was being scored as no-moat (0 pts instead of 15). This single bug was depressing composite scores by 15–20 points across most of the Nifty 30. The fix is a one-line addition to `_moat_map`; the canary harness now catches an equivalent regression at the median-score gate.

### 3.4 Worked example — composite for INFY

A worked composite, illustrating the four factors composing into a letter grade. INFY (Infosys), late April 2026:

- **Piotroski:** 7/9 — meets profitability, OCF positivity, OCF > NI, no dilution, GM improving, asset turnover improving; misses the LTD-falling and current-ratio-improving rows in a year of buybacks.
  → `pio_score = 7/9 × 25 = 19.4`.
- **Moat grade:** Wide. INFY meets all four sustained-criteria thresholds (ROE > 18%, ROCE > 18%, GM > 35%, multi-decade duration). → `moat_pts = 25`.
- **Quality factor:** `19.4 + 25 = 44.4` → rounded to 44/50.
- **Revenue growth:** TTM ~9.2% (decimal-form 0.092 in `enriched`, auto-converted to percent 9.2 by the input guard). 9.2 falls in the [5, 10) bucket. → `grw_score = 10/20`.
- **MoS (illustrative):** DCF FV ≈ ₹1,720 vs CMP ₹1,610 → MoS = 6.8%. 6.8 falls in the [0, 10) bucket. → `val_score = 8/20`.
- **Analyst upside:** consensus target ~₹1,790 → 11% upside. → `sent_score = 7/10`.
- **Composite:** 44 + 10 + 8 + 7 = **69 → B+**.

This is a textbook B+ — high quality, growing in the high single digits, fairly priced, modest analyst upside. A reader expecting a "buy signal" from INFY would be disappointed; a reader looking for a quality-tilted hold-grade compounder would not.

### 3.5 Grade boundaries

The composite letter grade:

| Composite | Grade |
|-----------|-------|
| ≥ 85      | A+    |
| 75–84     | A     |
| 65–74     | B+    |
| 55–64     | B     |
| 45–54     | C+    |
| 35–44     | C     |
| < 35      | D     |

(`scoring.py:97–104`.) These boundaries are calibrated against the Nifty 100 distribution: roughly 5% of large-caps are A+, 20% are A, 30% are B-grade, and the long tail is C/D — typically PSU-heavy or low-quality cyclicals.

### 3.6 Model-confidence deduction

Two events trigger an automatic confidence deduction on the displayed grade:

1. **Peer-cap fired.** When DCF FV was capped at 1.5× peer-implied, we display the capped FV but flag the analysis as "model-capped" and reduce composite confidence by one band (e.g., A → A-confidence-low). The grade letter is unchanged; the descriptive caveat is.

2. **Data-limited inputs.** If any of the underlying axes (Pulse, Quality, Moat, Safety, Growth, Value — see §4) returns a "data_limited=True" flag because its required inputs are missing, the composite carries a "data limited" badge. This typically affects mid-caps where `ratio_history` coverage is thinner.

Both flags are surfaced in the API response and on the UI; neither hides the underlying number.

---

## 4. The Hex / Prism Visualisation

The Prism is a six-axis radar chart that decomposes a stock's quality across orthogonal dimensions. Each axis scores 0–10 (centred at 5.0 = neutral).

### 4.1 The axes

| Axis    | What it measures                                     | Primary inputs                                                |
|---------|------------------------------------------------------|---------------------------------------------------------------|
| **Value**   | Cheapness vs DCF and peer multiples              | Margin of safety, P/E, P/B (banks), revenue multiple (IT)     |
| **Quality** | Capital efficiency and earnings quality          | Piotroski F-score, ROCE / ROE, op-margin stability            |
| **Growth**  | Revenue + EPS trajectory                          | 3y revenue CAGR, EPS CAGR, advances/deposits YoY (banks)      |
| **Safety**  | Solvency and downside protection                  | D/E, interest coverage, Altman Z (or GNPA / Tier-1 for banks) |
| **Moat**    | Durable competitive advantage                     | Moat grade, market cap (banks), op-margin stability           |
| **Pulse**   | Near-term momentum and insider/analyst flow       | Estimate revisions, insider activity, promoter pledge changes |

Code: `backend/services/hex_service.py`. Each axis function defines a `_neutral_axis(why)` fallback (score = 5.0, `data_limited=True`) when its required inputs are missing — never a silent zero, always a labelled neutral.

Each axis has sector branches. Banks route Quality and Growth through bank-specific formulas (ROA / ROE / cost-to-income; advances / deposits / PAT YoY). IT routes Safety through a D/E + op-margin-stability formula because Altman Z is meaningless for asset-light businesses.

### 4.2 Sector-aware axis formulas

The Quality axis (`_axis_quality`, `hex_service.py:537–651`):

**General branch:**
```
score = 5.0
score += (Piotroski − 4.5) × 0.6              # 9/9 → +2.7
score += (ROCE_or_ROE − 15.0) × 0.12          # 15% = neutral
if op_margin_stdev over 3+ years:
    score += clip((5.0 − stdev) × 0.1, −1.0, 1.0)
```

**Bank branch:**
```
score = 5.0
score += clip((ROA  − 1.0) × 2.5,  −2.0, 3.0)   # 1.0% ROA = neutral
score += clip((ROE − 12.0) × 0.25, −2.0, 2.5)   # 12% ROE = neutral
score += clip((55.0 − C2I) × 0.05, −1.2, 0.8)   # 55% cost-to-income = neutral
```

The Value axis sigmoid (general, `hex_service.py:409`):
```
signal = mos_pct + clip((22 − PE) × 3.3, −13, 13)
score  = 10 / (1 + exp(−0.08 × signal))
```

Calibration points: MoS −50% → 0.18; MoS −33% → 0.67; MoS 0% → 5.00; MoS +33% → 9.34.

**Sector-relative Value band (Stage 2).** Alongside the 0–10 sigmoid we now publish a sector-percentile band for the Value axis. Each stock's Value position is calculated relative to its sector peers, not an absolute scale. We rank by Margin of Safety for general stocks, by P/Book Value for banks, and by Revenue Multiple for IT services. A stock in the top 10% of MoS for its sector shows "Deep discount"; the bottom 10% shows "Notable premium to peers". Mid-range positions surface as "Below peers", "In range", or "Above peers". When fewer than 10 sector peers have valid data we mark the stock as "Insufficient peer data" rather than show a misleading score. The numeric sigmoid score continues to drive the central composite; the band is a peer-context overlay rendered by the `ValueBandChip` component on the analysis page.

The full formula reference, with line numbers, is in `docs/audit/HEX_AXIS_SOURCE_MAP.md`.

### 4.3 Per-axis failure modes (and what we do about them)

Every axis has at least one silent-neutral path. The complete failure-mode catalogue lives in `docs/audit/HEX_AXIS_SOURCE_MAP.md`; the highlights:

- **Pulse** falls back to a yfinance `recommendations_summary` lookup when the upstream `hex_pulse_inputs` row is absent. For Indian tickers, yfinance's recommendations feed is sparse — the fallback is dead for the majority of names, so Pulse defaults to 5.0 with `data_limited=True`. The Q3 2026 SEBI auto-ingest project (§8) is the source for `hex_pulse_inputs.estimate_revision_30d` going forward.

- **Quality** is sensitive to ROE unit mismatches. yfinance returns ROE as a decimal (0.245 for 24.5%); the `_normalize_pct` canonicaliser handles it, but a code path that bypasses the helper would feed 0.245 into `(0.245 − 15) × 0.12 = −1.77` and collapse the axis. The April 2026 Nifty-collapse incident — HDFCBANK at 17/100, BAJFINANCE at 22, RELIANCE at 25 — was traced partly to this bug (and partly to the missing Moderate moat-grade row in §3.3, and partly to a D/E percent-vs-ratio bug in the Safety axis).

- **Moat** depends on `analysis_cache.payload.quality.moat` being a recognisable label. The string match catches "wide", "moderate", "narrow", "none", "no moat"; "n/a" falls through. For non-bank tickers where the moat engine returns "N/A (Financial)" by mistake, the axis falls back to a numeric `moat_score` proxy, then to op-margin stability, and ultimately to neutral 5.0 if all three signals are missing.

- **Safety** for banks is a documented blind spot. The orthodox formula uses GNPA / NNPA / Tier-1, but those fields are not currently populated in the production schema (planned source: BSE XBRL filings / RBI Form A). Until the bank-quality ingest lands, banks fall back to a P/BV proxy that *inverts* credit risk — richer banks score safer. We disclose this on the analysis page as a caveat; the fix is on the Q4 2026 roadmap.

- **Growth** for banks uses a `total_assets` YoY proxy in lieu of `advances` YoY (advances is a sub-item of total assets that requires the bank-specific schedule of the financial statement to extract cleanly). The proxy is reasonable when investment-portfolio shifts are quiet but overstates growth in quarters with heavy book reshuffling.

- **Value** for IT carries a unit-mismatch footgun: the formula divides revenue by 1e7 to convert raw INR to crores, but `financials.revenue` is already stored in crores in some upstream paths. When the unit is already in crores, the second division produces a near-zero rev_multiple and saturates the axis to ~10. The audit has flagged this; the fix is canary-tested.

The principle to take away: when an axis returns 5.0, *something* failed silently. The axis carries a `data_limited` flag and a `why` string; the UI surfaces both. A consumer who reads only the headline composite and ignores the per-axis detail is using the product incorrectly.

### 4.4 Refraction (axis disagreement)

A stock with all six axes near 7.0 is a textbook "high quality" — confirmed across every dimension. A stock with Value at 9.0 and Quality at 2.0 is something quite different: a structurally-broken business whose price has finally fallen far enough to be cheap. Refraction is the visual signal for this disagreement.

The refraction metric:
```
refraction = stdev(axes) / mean(axes)
```

A refraction below 0.15 indicates a "coherent" reading (most axes pointing the same way). Above 0.30 indicates an axis-disagreement Prism — one or two axes are dragging or dragging up the composite, and the reader should look at the detail before trusting the headline grade.

The Prism UI renders refraction as a translucent halo around the radar — coherent stocks have a tight halo, disagreement stocks have a ragged one.

---

## 5. Data Pipeline & Quality

### 5.1 Sources

YieldIQ ingests from three primary sources, in priority order:

1. **NSE / BSE XBRL filings.** The legally authoritative source for income statements, balance sheets, cash flow, and shareholding patterns. We pull the quarterly and annual XBRL packs and parse them into our canonical `financials` and `shareholding_pattern` tables. An automated ingester runs on the SEBI quarterly filing window (Q3 FY26 design lives in `docs/sebi_auto_ingest_design.md`).

2. **yfinance (Yahoo Finance).** The fallback source for fields not yet harvested from XBRL (analyst ratings, beta, shares outstanding, dividend history). Used as a fast-path during initial coverage; replaced by XBRL once a ticker passes the ingestion threshold.

3. **Daily prices.** End-of-day close from NSE for the live `daily_prices` table; intraday delayed quotes for the live UI ticker. We do not run a sub-second feed; we are not a trading platform.

A complete sources matrix lives at `docs/DATA_STRATEGY.md`. The standing quarterly maintenance runbook is `docs/DATA_COVERAGE_RUNBOOK.md`.

### 5.2 Unit conventions — the central canonicaliser

Every public market data feed in India presents quantities in one of three units (raw INR, lakhs, crores), in one of two percent conventions (decimal 0.235 or percent 23.5), and with periodic upstream changes that nobody sends a memo about. The single most expensive bug class in YieldIQ's first year was a unit mismatch: a number that meant ROE 23.5% being interpreted as 2,350%, or revenue in lakhs being used as if it were crores.

The canonical conversion lives at `backend/services/analysis/utils.py::_normalize_pct`. The current implementation:

```python
def _normalize_pct(val) -> float | None:
    """Normalize to PERCENT form (23.5 for 23.5%)."""
    if val is None:
        return None
    v = float(val)
    if v == 0:
        return 0.0
    if -1.0 < v < 1.0:               # decimal form (yfinance)
        return round(v * 100, 2)
    return round(v, 2)                # already percent
```

The `[-1, 1]` window is principled: yfinance bounds its decimal-form percentages to that range. Any value with `|v| ≥ 1` is therefore already in percent form and must NOT be re-multiplied.

**Bug history that this guard prevents.** The previous version of this function used a `(−5, 5)` window. That window double-multiplied legitimate small percent values — corrupting ROE / ROCE / ROA for low-margin stocks (e.g., GRASIM ROE 2.35% → 235%, ROCE 3.5% → 350%). The fix shipped 2026-04-28; the test that prevents its return is `tests/regression/test_normalize_pct_double_multiplication.py`. That test slices the function source from `utils.py` at runtime so any future edit is automatically re-verified — the test cannot get out of sync with the implementation.

We also emit a `_PCT_BOUNDARY_BAND = 0.05` warning at runtime: if a value lands within ±0.05 of the threshold, we log a warning so a future upstream-feed unit-flip is observable before it corrupts a million reads.

The same convention is duplicated in two places by design:
- `backend/services/analysis/utils.py::_normalize_pct` (the production hot path)
- `backend/services/analytical_notes._normalize_pct` (the rule-engine local helper, slightly different threshold for narrative generation)
- `data/collector._normalize_pct_to_decimal` (the collector path, which goes the *other* direction — percent-or-decimal in, decimal out)

The duplication is deliberate. A single canonical helper would force every caller to depend on the analysis module, which would create circular imports. The three implementations are tested against the same 100-row table at `tests/test_unit_normalization_comprehensive.py` to keep them synchronised in behaviour.

### 5.3 Active data-quality mitigations

Beyond the unit canonicaliser, the platform carries several explicit data-quality guards:

- **Negative-equity ROE refusal.** A profitable company with negative book equity (PAYTM-style accumulated losses) would produce a spurious −439% ROE chip. The fallback ROE computer (`backend/services/analysis/utils.py::_compute_roe_fallback`) refuses to return a value when equity ≤ 0 and stashes the reason into `enriched["input_quality_flags"]`.

- **CAGR sanity clamp.** `_sanitize_cagr` strips any |CAGR| > 50% to None — a 80% three-year CAGR on revenue is almost always a demerger, divestment, or unit-change artefact. The downside is real (a genuine fast-grower goes to None); the audit document `HEX_AXIS_SOURCE_MAP.md` Bug #5 traces this and the financials-table fallback path.

- **Peer-median sanity bounds.** P/E values from `ratio_history` are clipped to [3, 250] before taking the median. Without this, a misparsed pe_ratio of 0.45 (a normalised score, not a real P/E) drags the median into bizarro territory.

- **Cyclical FCF override.** Already discussed in §2.3 — replaces `max_recent_fcf` with the 5-year median for known cyclical sectors.

### 5.4 The MGT-9 / cement-cycle case study

A short case study to illustrate the unit-mismatch hazard end-to-end.

In February 2026 we observed that SHREECEM's composite score had collapsed from 78 to 41 over two weeks, with no corresponding price move and no fundamental news. The investigation took five days and surfaced a chain of three independent issues:

1. **The trigger.** A new ingest path for the MGT-9 (the annual return form filed under Section 92 of the Companies Act, 2013) had been added to extract shareholder-pattern data. The MGT-9 lists shares in *number*, not in lakhs or crores. Our parser inherited a "lakhs assumed" default from the shareholding-pattern ingest. Result: SHREECEM's reported shares-outstanding doubled overnight, halving every per-share metric.

2. **The amplifier.** The `_normalize_pct` regression (the (−5, 5) double-multiplication bug, since fixed) was active in production. When the per-share ROE recomputed against the corrupted shares count, the ratio fell into the (−5, 5) window and was multiplied by 100, producing a 350% ROCE display. The display caught analyst attention before the price-collapse did.

3. **The propagator.** The peer-cap engine looked up SHREECEM's peer cohort (cement). The cyclical-FCF override was active on cement — meaning every cement stock was being clipped to its 5-year median FCF base, but India's current infrastructure cycle has structurally higher cement FCF than the 5-year lookback. Three cement stocks (SHREECEM, ULTRACEMCO, AMBUJACEM) were simultaneously showing FV / CMP ratios below 0.35.

The remediation took three patches:
- Patch 1: MGT-9 parser unit-tag fix (commit log 2026-02-18).
- Patch 2: `_normalize_pct` window correction (commit log 2026-04-28; documented at length in §5.2).
- Patch 3: Cement removed from the cyclical-FCF override set (`forecaster.py:214`).

The case study is the canonical reason for the discipline rules in §6.1 and the sector-isolation gate in §6.4. Each patch alone was a "fix"; deployed in isolation against a per-ticker canary, each one would have been declared green. The discipline that catches multi-step interactions is the sector-aggregated gate that asked "are *all* cement stocks moving the same way?".

### 5.5 ratio_history weekly maintenance

`ratio_history` is the table behind every multiples-based feature on the platform: peer-cap, the Value axis sector branches, the screener, and the public stock-summary endpoint. It is populated by a weekly maintenance job (`scripts/refresh_ratio_history.py`) that:

1. Pulls the latest annual financial statements from `financials`.
2. Pulls the latest market cap from `market_metrics`.
3. Computes `pe_ratio = market_cap / pat`, `pb_ratio = market_cap / total_equity`, `ev_ebitda = enterprise_value / ebitda` — in the same unit (₹ Cr) on both sides.
4. Sanity-bounds each ratio against historical distributions; flags rows that fall outside.
5. Upserts the result keyed by `(ticker, period_end, period_type)`.

Weekly cadence is deliberate: the ratios are slow-moving (their numerator changes daily, but the denominator only changes on each annual report), and a daily refresh would generate noise without signal.

The audit log of any ratio-history anomaly is at `docs/ratio_history_audit_design.md`. The known cohort of garbage rows (HCLTECH, TECHM, WIPRO showing pe_ratio < 1 because of an upstream pipeline normalisation issue) is documented and is the reason for the [3, 250] sanity bound in the peer-cap engine.

### 5.6 The source-linking promise

Every number that appears on a YieldIQ stock page should click through to its source. The implementation:

- Income-statement numbers (revenue, EBIT, net income) link to the underlying XBRL filing on the BSE portal.
- Cash-flow numbers (operating cash flow, FCF, capex) link the same way.
- Live price links to the NSE quote page.
- Computed numbers (margin of safety, fair value, composite score) expand into a "show the inputs" panel that lists the upstream values and the formula version.

When a number cannot be source-linked — typically because the underlying field comes from yfinance rather than from a filing — we display a "Yahoo Finance, last updated ..." annotation rather than pretending it has a primary source.

This promise is enforced structurally: every number on the analysis page reads from a single `analysis_payload` object that carries an explicit `source` and `as_of` field per metric. The serialiser refuses to render a number that lacks both fields. This was not free — it required a payload-schema migration in early 2026 — but it eliminated an entire class of "the number on the screen and the number in the cache disagree" support tickets.

### 5.7 The DCF trace ring buffer

Production DCF runs are observable. Every analysis run writes a structured trace into an in-memory ring buffer (`screener.dcf_engine.DCF_TRACES`) keyed by ticker; a 24-hour window is retained per ticker. The trace contains:

- The selected FCF base, the source slot (`latest_fcf` / `nopat_proxy` / `max_recent_fcf` / `hysteresis(...)` / etc.), and the full candidate dictionary.
- The base growth, the year-by-year fade schedule, and the year-by-year FCF projection.
- The WACC build-up: Rf source, beta, beta source, Re, Rd, E/V, D/V, tax rate.
- The terminal value, the equity bridge, and the per-share FV.
- Whether the peer cap fired, and if so the peer cohort, the implied FV, and the displayed FV.
- The CACHE_VERSION the trace was generated under.

When a stock's displayed FV moves unexpectedly, the trace is the first artefact a triage agent reads. It is also the source of the "show inputs" panel on the analysis UI — the user sees the same trace the engineer does.

---

## 6. Discipline & Validation

YieldIQ's data-quality philosophy is not an aspiration; it is enforced by automated gates that block any merge that would regress the production view. This section is the catalogue of those gates.

### 6.1 The three CLAUDE.md rules

The root `CLAUDE.md` carries three rules, with rationale:

1. **Never ship a data fix without running canary-diff first.** Any PR that touches `backend/services/`, `backend/routers/`, `backend/validators/`, `backend/models/`, or `scripts/canary_stocks_50.json` must show a clean canary-diff exit before merge. The GH Actions workflow (`canary_diff.yml`) enforces this at PR time.

2. **Never bump CACHE_VERSION without a before/after snapshot.** A `CACHE_VERSION` bump invalidates every cached `analysis_cache` row in production. Bumping it casually means a cold-restart for every Indian retail user. The discipline: snapshot 50 stocks before, run canary-diff against the snapshot after, explain any FV change > 15% in the PR body.

3. **Never declare a bug "fixed" based on a single Chrome MCP test.** The fix is fixed when canary-diff passes 5/5 gates on all 50 stocks AND seven consecutive nightly canary runs are clean AND the fix is reproducible from snapshotted inputs.

These rules exist because between v32 and v35 we shipped six "fixes" that left 4 of 5 stocks in a worse state. The rules are the institutional memory of those failures.

### 6.2 The canary harness — five gates

The canary harness (`scripts/canary_diff.py`) runs five gates against a curated 50-stock universe (sector-balanced, mix of large/mid/small cap, defined in `scripts/canary_stocks_50.json`). It exits 0 only if all five gates pass with zero violations.

| Gate                    | What it catches                                                                  | Threshold                      |
|-------------------------|----------------------------------------------------------------------------------|--------------------------------|
| 1. Single Source of Truth | Public stock-summary and authed analysis endpoints disagree on shared fields  | Any field mismatch             |
| 2. MoS Math Consistency | `mos != (fv − cmp) / cmp`                                                        | > 2 percentage points off      |
| 3. Scenario Dispersion  | `bull > base > bear` violated, or spread < 5% on either side                     | Strict ordering required       |
| 4. Canary Bounds        | Any ticker's FV / score / MoS falls outside the committed bounds                 | Any out-of-bounds value        |
| 5. Forbidden Values     | Sentinels (−999, NaN) or obvious unit-bug ranges (ROE > 200%, FV < 0)            | Any forbidden value detected   |

Gate 1 is the most powerful: it catches every drift between the public read path and the authed analysis path, which is the single most common breaking-change vector in the codebase. Gate 4 is the most boring: it catches everything else by simply asserting "this stock's FV must remain in [committed_low, committed_high]". Gate 5 is the cheapest: it catches the entire class of unit-flip bugs that have historically cost us most.

In addition to the five gates, the harness supports a `--diff-against` mode that compares current state to a committed snapshot and flags any FV drift > 15% or MoS drift > 10pp as `suspicious — investigate`. This is separate from the gate path: a flagged drift does not block a merge, but it appears prominently in the PR comment so reviewers see it.

### 6.3 CACHE_VERSION discipline

Every `CACHE_VERSION` bump is logged at `docs/cache_version_discipline.md` with the rationale and the canary-diff result. A representative entry:

> v65 = fix/normalize-pct-bound-correction (2026-04-28): `_normalize_pct` window narrowed from (−5, 5) to (−1, 1). Pre-bump snapshot: scripts/snapshots/snapshot_2026-04-28T08-12.json. Post-bump diff: 14 of 50 tickers shifted FV upward (median +3.1%, max +8.4%, all within bounds). No tickers regressed.

The discipline is institutional. A bump without an entry on this page fails review.

### 6.4 The sector-isolation gate

The canary harness operates at the per-ticker level. The sector-isolation gate operates one layer above it: it aggregates the canary 50 by sector, diffs each sector's median FV, median composite, and median MoS against a committed baseline (`scripts/sector_snapshot.json`), and requires PR authors to declare which sectors they meant to touch.

The format is a single line in the PR body:

```
sector-scope: Cement, Banks
```

(Or `sector-scope: *` for genuine cross-sector framework changes.)

The gate exists because of PR #69 — the modern re-enactment of the v32→v35 incident. PR #69 was a regulated-utility WACC tweak. The intended scope was "NTPC". The actual outcome:

| Stock      | Intended scope     | Actual shift                |
|------------|--------------------|-----------------------------|
| NTPC       | regulated utility  | FV +8% (intended)           |
| SHREECEM   | cement (not scoped)| FV −71% (regression)        |
| AMBUJACEM  | cement (not scoped)| FV −35% (regression)        |
| BHARTIARTL | telecom (not scoped)| score +16 (suspicious)     |

Per-ticker canary reported `investigate` on each, but had no way to frame the finding as "three out of three Cement stocks moved the same way — that is not drift, that is leakage." The sector-isolation gate is the framing.

Drift thresholds:
- Median FV drift > 5% in an undeclared sector → fail.
- Median composite drift > 3 points in an undeclared sector → fail.
- Median MoS drift → advisory only (informational).

A sector with fewer than 2 valid-data tickers is reported as `insufficient_data` and does not gate. The full runbook is `docs/SECTOR_ISOLATION.md`.

### 6.5 The discipline_rule_3 workflow — nightly verification

Discipline rule 3 in §6.1 — "the fix is fixed only after seven consecutive nightly canary runs are clean" — is not aspirational. It is a GitHub Actions workflow (`.github/workflows/discipline_rule_3.yml`) that runs nightly, exercises the canary harness against the production endpoints, and writes a daily verdict into a JSONL ledger (`docs/canary_history.jsonl`). The verdict format:

```json
{"date": "2026-04-27", "exit_code": 0, "gate_violations": 0,
 "fetch_failures": 0, "clean": true, "commit": "a1b2c3d4e5f6"}
```

A "clean" run is `exit_code == 0 AND gate_violations == 0 AND fetch_failures == 0`. The dashboard (`/admin/canary`) reads the ledger and shows a 30-day strip; engineers can see at a glance whether the platform has had its seven-day clean streak for any pending bug-fix verification.

The fetch-failures threshold is 2 — one stock can flake without blocking; three flakes mean the API is genuinely unhealthy and the run fails. The flake is then itself a maintenance event: the stock is investigated, and if its fetch keeps failing it is removed from the canary 50 with a documented reason.

### 6.6 Performance retrospective methodology

YieldIQ does not currently publish a quarterly performance retrospective. The design lives at `docs/performance_retrospective_design.md`; the implementation is on the Q4 2026 roadmap (§8).

The intended methodology:
- Take every public DCF FV and composite grade from a chosen quarter-end (e.g., 2026-Q1).
- Wait one year (the standard equity-research forecast horizon).
- Score each prediction against the realised one-year forward return.
- Publish a "calibration" plot (predicted MoS vs realised return) and a "grade hit rate" table (A+ / A / B / etc. vs forward return distribution).
- Publish the sample, the misses, and the misses we cannot explain.

We will publish the retrospective regardless of whether it is flattering. The discipline is to make the ledger public so that the platform's claims can be tested against its own history.

---

### 6.7 What review does not catch

For honesty's sake: the gate suite is not a full guarantor of correctness. There are failure modes that the canary does not catch by design.

- **Universe gaps.** The canary 50 is sector-balanced but does not cover every sector deeply. A regression that affects only paper, only sugar, or only specific PSU enterprises will not be caught at the gate; it will surface only at the per-ticker analysis level. The mitigation is the sector-isolation gate's `insufficient_data` reporting — when a sector slips below 2 valid tickers in the canary, the gate explicitly disclaims it.
- **Schema-level changes.** A change to the `analysis_payload` JSON schema that adds a new field is invisible to gate 1 (single source of truth — only checks shared fields) and gate 4 (canary bounds — does not test fields not yet bounded). Such changes are caught by the API-contract test (`tests/test_analysis_contract.py`) which type-checks the response against a Pydantic schema.
- **Slow drift.** A bug that drifts an FV by 0.5% per week is below the 5% sector-isolation threshold. After ten weeks, drift compounds to 5%, but no individual run flags it. The mitigation is the snapshot-vs-baseline trend report, which we run quarterly and publish internally.
- **External-dependency outages.** When yfinance returns a partial response or the live G-Sec feed staleness exceeds 6 hours, the model falls back gracefully but the gate does not currently distinguish "fallback was used" from "primary data was used". A 2026-Q3 enhancement adds a `data_source_telemetry` field to the analysis payload so the gate can fail when the canary 50 has more than 10% fallback usage — a signal that an upstream dependency is degraded.

The discipline philosophy is: every gate above is a *necessary* condition for shipping, never a *sufficient* one. Engineers retain individual responsibility for thinking about the failure modes that the gate does not encode.

## 7. Known Limitations

YieldIQ does not pretend to be a complete answer to the equity-valuation problem. Below is the candid catalogue of what it does not do well, and what it does not do at all.

**Mid-cap data gaps.** The peer-cap engine requires at least 3 liquid peers (market cap > ₹500 Cr) in the same industry. For genuine niche companies — small specialty chemicals players, regional NBFCs, single-product pharma — fewer than 3 peers exist with clean ratio data, and the cap simply does not fire. The DCF runs without a sanity ceiling, and the displayed FV may be in the implausible tail. The UI flags these analyses as "model-uncapped"; the user should weight them accordingly.

**Real-time delay.** Live prices on the platform are 15-minute-delayed quotes from NSE. We do not run a sub-second feed, and we will not. YieldIQ is a research tool, not a trading platform.

**India-only universe.** The platform covers ~1,000 NSE-listed stocks. We have a US WACC table and limited coverage for ~50 US tickers, but we do not claim US-quality coverage there. We do not cover unlisted equity, debt, mutual funds, or derivatives.

**Counterfactual nature of historical predictions.** When we publish the performance retrospective (§6.5), it will be a measurement of out-of-sample forecast accuracy on stocks that were already in the universe. It will *not* be a measurement of "what if you had followed YieldIQ's grades as a portfolio strategy" — we publish grades, not portfolios, and we make no claim of portfolio outperformance.

**Forecast horizon.** Our DCF projects ten years out. Beyond ten years, every input — growth, margin, capex, even the regulatory regime — is so uncertain that adding more years adds noise rather than signal. The terminal value handles the (long, uncertain) tail with a single Gordon-growth term. A reader who wants a 30-year explicit forecast will not find it here, and we believe they should not find it anywhere — a 30-year explicit forecast is a fictional precision.

**Asymmetry of bull and bear.** The bull / bear scenarios perturb growth and WACC by symmetric amounts (±200 bps and ∓50 bps respectively). In reality, the distribution of outcomes is asymmetric: the upside on a high-quality compounder is fatter than the downside, because terminal-value compounding is convex. Our scenarios understate this asymmetry. We have considered Monte Carlo dispersion but rejected it for now — the additional simulation cost is substantial and the user-facing benefit (a richer histogram of outcomes) is hard to communicate without inviting false confidence.

**Sector classification reliance.** Several model branches (the WACC default, the FCF base method, the Prism axis branches) depend on a clean sector tag. When the tag is wrong, the wrong branch fires. Our sector classifier is a hand-maintained ticker set plus a substring fallback on the yfinance industry string — it is reliable on the Nifty 200 but degrades on small-caps with sparse industry tags. Mitigation: the per-axis `data_limited` flag appears whenever a branch returns its neutral fallback, alerting the reader that a classification miss may be in play.

**Things we explicitly do not do:**
- We do not issue buy / sell / hold ratings. Every output is descriptive.
- We are not registered with SEBI as a Research Analyst (RA). Our content is informational, framed as analysis-of-public-data rather than as investment recommendation. SEBI's RA framework (Reg 23, 2014) applies to entities that provide buy/sell calls; we explicitly do not.
- We do not sync brokerage accounts, do not custody assets, and do not place orders.
- We do not cover South-East Asia equities, despite occasional requests. The data infrastructure for SE Asia is materially different from India and we have no plans for that expansion.
- We do not frame the platform as a "Bloomberg Terminal for retail." Bloomberg is a trading workstation; we are a research surface. The analogy oversells what we deliver.

---

## 8. Roadmap

A short list of what is on the docket in the next four quarters. We commit to publishing dates only when work is in flight; the dates below are intentions, not promises.

**Q3 2026 (July–September).**
- SEBI quarterly auto-ingest. The quarterly filing window is the single largest information shock in the Indian equity-research calendar; today, we ingest via a manual run of the XBRL parser, which leaves a 2–4 day data lag for ~600 mid-caps. The auto-ingest design (`docs/sebi_auto_ingest_design.md`) is a watcher on the SEBI / BSE filing endpoints with a 4-hour SLO from filing to coverage.
- RPT (Related-Party Transaction) analyzer. SEBI Reg 23 disclosures are PDF-first and inconsistent across filers. The design (`docs/related_party_analyzer_design.md`) uses a constrained LLM extractor to canonicalise RPT tables into a queryable schema, with human-in-the-loop validation on disagreements.

**Q4 2026 (October–December).**
- Performance retrospective Q1 publication. The first public retrospective will measure 2026-Q1 grades against 2027-Q1 realised one-year forwards. See §6.5.
- Insider activity surface. Today we ingest insider trades into `hex_pulse_inputs.insider_net_30d`; the next iteration adds a directional-event feed and a per-stock chart of insider net flow over the trailing year. Design at `docs/insider_activity_design.md`.
- Promoter pledge tracking. Pledges are a leading indicator of promoter financial stress; the design at `docs/promoter_pledge_tracking_design.md` adds a quarterly delta and an alerting hook.

**2027.**
- Multilingual narrative summaries (Hindi, Tamil, Marathi at minimum). The model output today is in English; a sizeable share of the retail audience prefers vernacular analysis.
- Mobile app. Today the platform is a responsive web app; a native-shell mobile app is on the roadmap once the web feature surface stabilises.
- Options-flow integration. Equity options flow is a useful sentiment indicator for liquid Nifty / Bank-Nifty constituents; we plan a read-only integration with NSE option-chain data, surfaced as a Pulse-axis input.

---

## 9. References & Acknowledgments

### Academic and methodological

- Damodaran, A. *Investment Valuation*, 3rd ed., Wiley, 2012. The DCF chapters and the sector-by-sector cost-of-capital tables on his NYU page are the source of our base WACC defaults; the 2025 update fixes our India MRP at 6.0%.
- Piotroski, J. D. (2000). "Value Investing: The Use of Historical Financial Statement Information to Separate Winners from Losers from Losers." *Journal of Accounting Research* 38: 1–41. The 9-point F-score is reproduced in §3.2.
- Greenwald, B., Kahn, J., Sonkin, P., van Biema, M. *Value Investing: From Graham to Buffett and Beyond*, Wiley, 2001 — and Greenwald, B. *Competition Demystified*, Portfolio, 2005. The Wide / Narrow / None moat taxonomy follows Greenwald's framework.
- Altman, E. I. (1968). "Financial Ratios, Discriminant Analysis and the Prediction of Corporate Bankruptcy." *Journal of Finance* 23: 589–609. The Z-score in the Safety axis is the original 1968 formulation.

### India-specific regulatory

- SEBI (Listing Obligations and Disclosure Requirements) Regulations, 2015 — the source of our quarterly-filing schema.
- SEBI (Research Analysts) Regulations, 2014, Reg 23 — the regulatory boundary we explicitly stay outside of.
- Companies Act, 2013, Section 188 — the related-party transaction definition that the RPT analyzer canonicalises against.
- CERC Tariff Regulations, 2024 — the source of the 15.5% regulated-utility ROE and the regulated-utility WACC anchor.
- RBI Master Direction — Capital Adequacy of Banks (consolidated, 2024) — the source of the bank-Piotroski adaptation in §3.2.

### Open-source acknowledgments

The platform stands on a great deal of free software. With particular gratitude:
- **yfinance** (Ran Aroussi and contributors) — our fallback feed for fields not yet harvested from XBRL.
- **pandas** and **numpy** — the analytical core of every model in this paper.
- **scikit-learn** — the Ridge and RandomForest blending for the FCF growth forecaster.
- **FastAPI** (Sebastián Ramírez) — the API layer for the analysis service.
- **Next.js** (Vercel) — the frontend.
- **PostgreSQL** and **DuckDB** — the operational and analytical data stores respectively.
- **SQLAlchemy** — the ORM behind every database-touching service.

### Suggesting edits

This paper is open methodology. Errata, clarifications, and rebuttals are welcome. Each section has a "Suggest edit" link in the footer of the published page; the link targets the section in this markdown source on GitHub.

---

*Last updated: 2026-04-28. This paper is descriptive, not advisory. Nothing here is investment advice.*
