# YieldIQ Scoring Ground Truth — 30 Indian Stocks

> **Disclaimer:** This document is for internal scoring-engine calibration. Targets are approximate, reflect analyst consensus as of ~2026-04 and the author's judgment, and should not be interpreted as investment advice. Numbers are "reasonable ranges a thoughtful equity analyst would land on," not precise fair-value estimates.

---

## Purpose

YieldIQ's HEX scoring engine is currently producing catastrophic scores for several blue-chip Indian stocks (HDFCBANK=17, RELIANCE=25, ICICIBANK=27, ASIANPAINT=20, BAJFINANCE=22, TITAN=25). Before we can fix the engine, we need a **ground-truth baseline**: for each stock, what *should* the composite score be, roughly, under conventional equity analysis?

This document supplies that baseline for 30 hand-picked Indian tickers spanning the Nifty top-30 plus a few archetypes. It is the benchmark against which Phase 2 of the scoring audit will measure gaps.

The deliverable is **not** a stock recommendation. It is a calibration set.

---

## Rubric

| Score | Grade | Profile |
|------:|:-----:|---------|
| 85-100 | A+ | Best-in-class franchise, dominant moat, strong growth, reasonable valuation. Rare. |
| 75-84  | A  | Dominant / near-dominant franchise, strong fundamentals, reasonable valuation. |
| 65-74  | B+ | Strong franchise, solid fundamentals, some valuation concern OR moderate growth. |
| 55-64  | B  | Decent franchise, reasonable fundamentals, maybe sector headwinds. |
| 45-54  | C+ | Average. Cyclicals in a neutral part of the cycle. Mixed signals. |
| 35-44  | C  | Below-average. Weak moat OR high valuation OR deteriorating fundamentals. |
| 25-34  | D  | Problematic. Clear quality/moat concerns OR very expensive OR shrinking. |
| 0-24   | F  | Broken business, governance issues, deep value trap. |

### Calibration anchors

- **HDFCBANK: 78-85 (A/A+)** — India's premier private bank. High ROA, sticky low-cost deposit franchise, consistent growth. If the model gives this <70, the model is broken.
- **TCS: 75-82 (A)** — India's IT services gold standard. Expensive, yes, but earnings power is undeniable.
- **MARUTI: 68-75 (B+)** — Dominant Indian auto OEM. Cyclical but franchise is durable.
- **BPCL: 45-55 (C+)** — PSU oil marketing. Commodity cycle, high capex, moderate moat. Deep-value but trap risk.
- **ADANIENT: 35-50 (C)** — Diversified conglomerate, complex debt, governance questions priced in. Volatile.
- **RELIANCE: 65-75 (B+)** — Size + diversification + Jio moat. Arguably expensive given capex cycle.
- **ASIANPAINT: 58-68 (B/B+)** — Dominant decorative paints franchise. Expensive after rerating. Growth slowing post Birla paints entry.
- **NESTLEIND: 65-75 (B+)** — FMCG moat, Jan-Dec FY, premium valuation but defensible.

Targets below were calibrated against these anchors plus public analyst consensus and basic 5y ROE/ROCE, growth, and moat-durability reads.

---

## Per-stock targets

### BANKS (4 stocks)

#### HDFCBANK.NS — Target 78-85 (A)
- **Company:** HDFC Bank Limited
- **Sector:** bank
- **Moat:** wide — largest private-sector deposit franchise, best-in-class liability side, deep branch network, strong underwriting track record.
- **Business quality (1-5):** 5 — category-defining Indian private bank.
- **Growth profile:** growing — post-HDFC Ltd merger integration largely absorbed; loan book CAGR 15%+ over medium term likely.
- **Current valuation:** fair — ~2.5-2.8x P/B, cheaper than historical average after merger-drag derating.
- **Target score range:** 78-85
- **Target midpoint:** 82
- **Rationale (1 line):** Dominant private-bank franchise, high ROA, sticky CASA, valuation no longer expensive — should be firmly A tier.
- **Red flag:** if NIMs compress further post-merger or asset quality deteriorates in unsecured retail.
- **Canary flag:** **TRUE** — current YieldIQ score of 17 is catastrophically wrong.

#### ICICIBANK.NS — Target 75-83 (A)
- **Company:** ICICI Bank Limited
- **Sector:** bank
- **Moat:** wide — #2 private bank, strong digital stack, well-diversified loan book, consistent ROA >2%.
- **Business quality (1-5):** 5 — arguably executed better than HDFCB over FY20-FY25.
- **Growth profile:** growing — steady loan book CAGR ~15%, fee income expanding.
- **Current valuation:** fair — ~3x P/B, but earns it via ROA/ROE.
- **Target score range:** 75-83
- **Target midpoint:** 79
- **Rationale:** Premier private bank compounder with best-in-industry execution over last 5 years — clear A tier.
- **Red flag:** corporate-cycle credit costs if capex slows; unsecured retail stress.
- **Canary flag:** **TRUE** — current 27 is catastrophically wrong.

#### KOTAKBANK.NS — Target 65-73 (B+)
- **Company:** Kotak Mahindra Bank Limited
- **Sector:** bank
- **Moat:** narrow-to-wide — strong brand, conservative underwriting, but smaller deposit franchise than HDFC/ICICI.
- **Business quality (1-5):** 4 — high-quality but has lost relative momentum post RBI embargoes and founder-succession friction.
- **Growth profile:** steady — loan growth slower than peers recently.
- **Current valuation:** fair-to-expensive — ~2.5x P/B, rich vs. growth rate.
- **Target score range:** 65-73
- **Target midpoint:** 69
- **Rationale:** Good franchise but relative underperformer vs. HDFCB/ICICI; B+ fits, not A.
- **Red flag:** growth gap to peers persists; succession transitions.
- **Canary flag:** **TRUE** — current 34 is too low for this quality of franchise.

#### SBIN.NS — Target 60-68 (B / B+)
- **Company:** State Bank of India
- **Sector:** bank
- **Moat:** narrow-to-wide — scale moat (largest Indian bank), but PSU governance drag.
- **Business quality (1-5):** 4 — much improved vs. a decade ago; ROA ~1%, clean asset quality for a PSU.
- **Growth profile:** steady — 12-14% loan CAGR, diversified book.
- **Current valuation:** cheap — ~1.3-1.5x P/B, lowest among top-tier banks.
- **Target score range:** 60-68
- **Target midpoint:** 64
- **Rationale:** Dominant PSU bank at cheap valuation with improved fundamentals — solid B / B+ tier; does not deserve A because ROA structurally below privates.
- **Red flag:** government-driven lending, cyclical credit costs, dilution risk.
- **Canary flag:** **TRUE** — current 38 is too low given cheap valuation + improved metrics.

---

### IT SERVICES (6 stocks)

#### TCS.NS — Target 75-82 (A)
- **Company:** Tata Consultancy Services
- **Sector:** it_services
- **Moat:** wide — scale, client stickiness, ~50%+ ROE, #1 Indian IT franchise.
- **Business quality (1-5):** 5
- **Growth profile:** steady — 6-9% USD revenue growth guidance, GenAI uncertainty.
- **Current valuation:** expensive — ~28-30x forward P/E.
- **Target score range:** 75-82
- **Target midpoint:** 78
- **Rationale:** Gold-standard Indian IT services franchise; A tier, kept below A+ by near-term growth moderation and rich multiple.
- **Red flag:** GenAI disruption of traditional services revenue; BFSI discretionary cuts.
- **Canary flag:** **TRUE** — current 44 is sharply wrong.

#### INFY.NS — Target 68-76 (B+ / A)
- **Company:** Infosys Limited
- **Sector:** it_services
- **Moat:** wide — #2 Indian IT with strong digital capabilities and client list.
- **Business quality (1-5):** 5
- **Growth profile:** steady — similar to TCS, slight growth edge in digital.
- **Current valuation:** fair-to-expensive — ~24-27x forward.
- **Target score range:** 68-76
- **Target midpoint:** 72
- **Rationale:** Premier IT franchise, marginally cheaper and slightly higher growth than TCS — B+ to A.
- **Red flag:** margin pressure, deal ramp delays, leadership churn.
- **Canary flag:** FALSE — current 73 is inside the target range. Calibration win.

#### HCLTECH.NS — Target 65-73 (B+)
- **Company:** HCL Technologies
- **Sector:** it_services
- **Moat:** narrow-to-wide — strong in infrastructure services and engineering R&D; dividend yield higher than peers.
- **Business quality (1-5):** 4
- **Growth profile:** steady
- **Current valuation:** fair — ~22-25x forward.
- **Target score range:** 65-73
- **Target midpoint:** 69
- **Rationale:** Solid tier-1 IT franchise with differentiated infra/ER&D mix — B+ tier.
- **Red flag:** products & platforms segment volatility.
- **Canary flag:** **TRUE** — current 37 is too low.

#### WIPRO.NS — Target 50-60 (C+ / B)
- **Company:** Wipro Limited
- **Sector:** it_services
- **Moat:** narrow — has lost relative ground to peers; inconsistent execution, leadership churn.
- **Business quality (1-5):** 3
- **Growth profile:** flat-to-steady — lagging tier-1 peers.
- **Current valuation:** fair — ~20x forward, discount to peers.
- **Target score range:** 50-60
- **Target midpoint:** 55
- **Rationale:** Tier-1 IT but structural laggard; C+/B seems right.
- **Red flag:** continued market-share loss to TCS/INFY.
- **Canary flag:** FALSE — current 66 is actually *high* vs. target (YieldIQ too generous here).

#### TECHM.NS — Target 48-58 (C+ / B)
- **Company:** Tech Mahindra Limited
- **Sector:** it_services
- **Moat:** narrow — telecom-vertical concentration, margin volatility.
- **Business quality (1-5):** 3
- **Growth profile:** flat — telecom capex cycle drag, margins recovering off lows.
- **Current valuation:** fair — ~25x forward, optically high on depressed earnings.
- **Target score range:** 48-58
- **Target midpoint:** 53
- **Rationale:** Below tier-1 peers in margin structure and consistency; recovery story but unproven.
- **Red flag:** telecom capex delay; margin recovery slower than guided.
- **Canary flag:** FALSE — current 51 is within target. Calibration win.

#### MPHASIS.NS — Target 55-65 (B)
- **Company:** Mphasis Limited
- **Sector:** it_services
- **Moat:** narrow — BFSI-heavy mid-cap IT, solid client relationships.
- **Business quality (1-5):** 4
- **Growth profile:** steady — BFSI spending recovery key.
- **Current valuation:** fair — ~22-24x forward.
- **Target score range:** 55-65
- **Target midpoint:** 60
- **Rationale:** Quality mid-cap IT; B tier.
- **Red flag:** BFSI client concentration.
- **Canary flag:** FALSE — current 48 is slightly low but within tolerance.

---

### FMCG (3 stocks)

#### HINDUNILVR.NS — Target 65-73 (B+)
- **Company:** Hindustan Unilever Limited
- **Sector:** fmcg
- **Moat:** wide — unmatched FMCG distribution and brand portfolio in India.
- **Business quality (1-5):** 5
- **Growth profile:** flat-to-steady — rural slowdown, volume growth lackluster last 2-3 years.
- **Current valuation:** expensive — ~50x P/E despite weak growth.
- **Target score range:** 65-73
- **Target midpoint:** 69
- **Rationale:** Dominant franchise but valuation / growth mismatch keeps it B+, not A.
- **Red flag:** sustained rural weakness, premiumisation not offsetting mass-segment pressure.
- **Canary flag:** **TRUE** — current 34 is far too low for this franchise quality.

#### ITC.NS — Target 62-70 (B / B+)
- **Company:** ITC Limited
- **Sector:** fmcg
- **Moat:** wide (cigarettes) + narrow (other FMCG/hotels/paper).
- **Business quality (1-5):** 4
- **Growth profile:** steady — cigarettes stable, non-cig FMCG growing, hotels demerger executed.
- **Current valuation:** fair — ~25x, cheapest among large FMCG.
- **Target score range:** 62-70
- **Target midpoint:** 66
- **Rationale:** Diversified cash machine with cheap valuation and improving mix — B+ tier.
- **Red flag:** cigarette tax shock; non-cig FMCG margin path.
- **Canary flag:** FALSE — current 61 is inside range. Calibration win.

#### NESTLEIND.NS — Target 65-75 (B+)
- **Company:** Nestle India Limited
- **Sector:** fmcg
- **Moat:** wide — iconic brands (Maggi, Nescafe, KitKat), pricing power.
- **Business quality (1-5):** 5
- **Growth profile:** steady — volume growth decelerating; price-led growth dominant.
- **Current valuation:** expensive — ~65x P/E.
- **Target score range:** 65-75
- **Target midpoint:** 70
- **Rationale:** Dominant FMCG franchise; rich valuation prevents A tier.
- **Red flag:** volume-growth stall; royalty rate hikes.
- **Canary flag:** **TRUE** — current 47 is too low.

---

### CONSUMER DISCRETIONARY (3 stocks)

#### MARUTI.NS — Target 68-75 (B+)
- **Company:** Maruti Suzuki India Limited
- **Sector:** auto
- **Moat:** wide — ~40% Indian passenger-vehicle market share, unmatched dealer/service network.
- **Business quality (1-5):** 5
- **Growth profile:** steady-to-growing — SUV portfolio rebuilt, EV rollout starting.
- **Current valuation:** fair — ~25x forward.
- **Target score range:** 68-75
- **Target midpoint:** 72
- **Rationale:** Dominant PV franchise with cyclical tailwinds — B+.
- **Red flag:** EV transition execution; hybrid/EV tax regime.
- **Canary flag:** **TRUE** — current 33 is catastrophically wrong.

#### TITAN.NS — Target 65-73 (B+)
- **Company:** Titan Company Limited
- **Sector:** retail
- **Moat:** wide — Tanishq jewellery brand dominance; disciplined capital allocation.
- **Business quality (1-5):** 5
- **Growth profile:** growing — 15%+ jewellery CAGR, market-share gains from unorganised.
- **Current valuation:** expensive — ~70x P/E.
- **Target score range:** 65-73
- **Target midpoint:** 69
- **Rationale:** Best-in-class retail compounder; expensive but quality justifies B+.
- **Red flag:** gold price shock, competitive intensity from Kalyan / Senco.
- **Canary flag:** **TRUE** — current 25 is catastrophically wrong.

#### ASIANPAINT.NS — Target 58-68 (B / B+)
- **Company:** Asian Paints Limited
- **Sector:** fmcg (paints treated as FMCG-adjacent)
- **Moat:** wide — dominant decorative paints franchise, dealer network, supply chain.
- **Business quality (1-5):** 4 (down from 5 pre-Birla entry)
- **Growth profile:** flat — volume growth weak, Birla Opus disrupting pricing.
- **Current valuation:** fair — ~45x P/E, down from ~70x peak.
- **Target score range:** 58-68
- **Target midpoint:** 63
- **Rationale:** Dominant franchise facing real competitive disruption; B/B+ with derating already underway.
- **Red flag:** Birla Opus market-share erosion accelerates.
- **Canary flag:** **TRUE** — current 20 is far too low.

---

### COMMODITIES / ENERGY (4 stocks)

#### RELIANCE.NS — Target 65-75 (B+)
- **Company:** Reliance Industries Limited
- **Sector:** diversified (energy + telecom + retail)
- **Moat:** wide — Jio telecom moat, retail scale, O2C scale.
- **Business quality (1-5):** 4
- **Growth profile:** growing — retail + Jio tariff hikes + new energy optionality.
- **Current valuation:** fair-to-expensive — ~25x P/E, SOTP-dependent.
- **Target score range:** 65-75
- **Target midpoint:** 70
- **Rationale:** Size, diversification, Jio-pricing power — solidly B+.
- **Red flag:** capex cycle on new energy / AI gigafactories; O2C cycle downturn.
- **Canary flag:** **TRUE** — current 25 is catastrophically wrong.

#### ONGC.NS — Target 48-58 (C+ / B)
- **Company:** Oil and Natural Gas Corporation
- **Sector:** commodity
- **Moat:** narrow — upstream scale, regulated pricing drag.
- **Business quality (1-5):** 3
- **Growth profile:** flat — production stagnant, windfall tax regime.
- **Current valuation:** cheap — ~7-9x P/E, high dividend yield.
- **Target score range:** 48-58
- **Target midpoint:** 53
- **Rationale:** Cheap PSU commodity play; cyclical; moderate moat — C+.
- **Red flag:** crude collapse, windfall tax hike.
- **Canary flag:** FALSE — current 60 slightly above target but defensible.

#### BPCL.NS — Target 45-55 (C+)
- **Company:** Bharat Petroleum Corporation Limited
- **Sector:** commodity
- **Moat:** narrow — OMC scale, regulated retail pricing.
- **Business quality (1-5):** 3
- **Growth profile:** flat — refining + marketing, high capex ahead.
- **Current valuation:** cheap — ~7-10x P/E.
- **Target score range:** 45-55
- **Target midpoint:** 50
- **Rationale:** PSU OMC, cyclical, deep value but trap risk — C+ anchor.
- **Red flag:** marketing-margin shocks when crude spikes; privatisation stalled.
- **Canary flag:** FALSE — current 45 is within range. Calibration win.

#### TATASTEEL.NS — Target 40-52 (C / C+)
- **Company:** Tata Steel Limited
- **Sector:** commodity
- **Moat:** narrow — Indian ops integrated and low-cost; Europe a drag.
- **Business quality (1-5):** 3
- **Growth profile:** flat — cyclical; Europe restructuring underway.
- **Current valuation:** fair — cyclical P/E misleading.
- **Target score range:** 40-52
- **Target midpoint:** 46
- **Rationale:** Cyclical commodity with European drag; C / C+.
- **Red flag:** China steel dumping, Europe losses widen.
- **Canary flag:** N/A — not in today's observations.

---

### ENGINEERING / CAPEX / UTILITIES (4 stocks)

#### LT.NS — Target 68-76 (B+ / A)
- **Company:** Larsen & Toubro Limited
- **Sector:** engineering
- **Moat:** wide — dominant Indian EPC player, strong order book, diversified.
- **Business quality (1-5):** 5
- **Growth profile:** growing — India capex supercycle, Middle East orders strong.
- **Current valuation:** fair-to-expensive — ~30x P/E.
- **Target score range:** 68-76
- **Target midpoint:** 72
- **Rationale:** Dominant EPC franchise riding capex cycle — B+ to A.
- **Red flag:** execution delays, working-capital blowout.
- **Canary flag:** **TRUE** — current 46 is too low.

#### ULTRACEMCO.NS — Target 62-70 (B / B+)
- **Company:** UltraTech Cement Limited
- **Sector:** cement
- **Moat:** wide — #1 Indian cement franchise, scale + distribution.
- **Business quality (1-5):** 4
- **Growth profile:** growing — capacity additions post Kesoram / India Cements acquisitions.
- **Current valuation:** fair-to-expensive — ~35x P/E.
- **Target score range:** 62-70
- **Target midpoint:** 66
- **Rationale:** Dominant cement franchise consolidating sector — B+.
- **Red flag:** price wars post Adani entry; demand softness.
- **Canary flag:** **TRUE** — current 38 is too low.

#### POWERGRID.NS — Target 58-68 (B / B+)
- **Company:** Power Grid Corporation of India
- **Sector:** utility
- **Moat:** wide — regulated monopoly in interstate transmission.
- **Business quality (1-5):** 4
- **Growth profile:** steady — RE transmission capex visible.
- **Current valuation:** fair — ~15-18x P/E, high dividend yield.
- **Target score range:** 58-68
- **Target midpoint:** 63
- **Rationale:** Regulated utility monopoly with visible growth and dividends — solid B/B+.
- **Red flag:** regulatory-return cut.
- **Canary flag:** **TRUE** — current 28 is far too low.

#### NTPC.NS — Target 55-65 (B)
- **Company:** NTPC Limited
- **Sector:** utility
- **Moat:** wide — dominant power generation, thermal + growing renewables.
- **Business quality (1-5):** 4
- **Growth profile:** steady-to-growing — renewables IPO of subsidiary, thermal capacity additions.
- **Current valuation:** fair — ~15-17x P/E.
- **Target score range:** 55-65
- **Target midpoint:** 60
- **Rationale:** PSU power utility with RE optionality — B.
- **Red flag:** coal availability, regulatory return cuts.
- **Canary flag:** FALSE — current 50 is within range / slightly low.

---

### PHARMA (2 stocks)

#### SUNPHARMA.NS — Target 65-73 (B+)
- **Company:** Sun Pharmaceutical Industries Limited
- **Sector:** pharma
- **Moat:** wide — largest Indian pharma, strong specialty (Ilumya, Cequa) franchise.
- **Business quality (1-5):** 4
- **Growth profile:** growing — specialty-led growth, India formulations steady.
- **Current valuation:** fair-to-expensive — ~30x P/E.
- **Target score range:** 65-73
- **Target midpoint:** 69
- **Rationale:** Top Indian pharma with specialty optionality — B+.
- **Red flag:** US generics price pressure, Ilumya competition.
- **Canary flag:** **TRUE** — current 28 is catastrophically wrong.

#### DIVISLAB.NS — Target 60-70 (B / B+)
- **Company:** Divi's Laboratories Limited
- **Sector:** pharma
- **Moat:** wide — scale API/CSM player, high-quality manufacturing, strong client moat.
- **Business quality (1-5):** 4
- **Growth profile:** steady-to-growing — custom synthesis revival, GLP-1 optionality.
- **Current valuation:** expensive — ~55-60x P/E.
- **Target score range:** 60-70
- **Target midpoint:** 65
- **Rationale:** High-quality API / CSM franchise; rich valuation trims score — B/B+.
- **Red flag:** custom-synthesis order lumpiness.
- **Canary flag:** **TRUE** — current 28 is too low.

---

### NBFC / FINANCIALS (2 stocks)

#### BAJFINANCE.NS — Target 68-76 (B+)
- **Company:** Bajaj Finance Limited
- **Sector:** nbfc
- **Moat:** wide — best-in-class retail-lending franchise, cross-sell flywheel, 4%+ ROA.
- **Business quality (1-5):** 5
- **Growth profile:** growing — AUM CAGR 25%+; tech-led moat compounding.
- **Current valuation:** fair-to-expensive — ~5-6x P/B, derated from peak.
- **Target score range:** 68-76
- **Target midpoint:** 72
- **Rationale:** Premier Indian NBFC; even post-derate it is B+/A.
- **Red flag:** unsecured-retail asset-quality cycle; regulatory tightening.
- **Canary flag:** **TRUE** — current 22 is catastrophically wrong.

#### BAJAJFINSV.NS — Target 62-72 (B / B+)
- **Company:** Bajaj Finserv Limited
- **Sector:** nbfc (holdco: BAJFIN + insurance + broking)
- **Moat:** wide — holdco over BAJFIN + Bajaj Allianz + Bajaj Broking + AMC.
- **Business quality (1-5):** 4
- **Growth profile:** growing
- **Current valuation:** fair — holdco discount.
- **Target score range:** 62-72
- **Target midpoint:** 67
- **Rationale:** Holdco of high-quality financial-services stack — B+.
- **Red flag:** insurance regulatory changes; holdco discount widens.
- **Canary flag:** **TRUE** — current 25 is catastrophically wrong.

---

### TELECOM (1 stock)

#### BHARTIARTL.NS — Target 70-78 (A)
- **Company:** Bharti Airtel Limited
- **Sector:** telecom
- **Moat:** wide — duopoly-plus-Jio market structure, premium ARPU mix, Africa subsidiary tailwind.
- **Business quality (1-5):** 5
- **Growth profile:** growing — ARPU hikes ahead; Africa contributes.
- **Current valuation:** expensive — ~40x P/E, but FCF ramp visible.
- **Target score range:** 70-78
- **Target midpoint:** 74
- **Rationale:** Premier Indian telecom in consolidated market — A.
- **Red flag:** Jio 5G pricing war; spectrum payouts.
- **Canary flag:** **TRUE** — current 48 is too low.

---

### DIVERSIFIED (1 stock)

#### ADANIENT.NS — Target 35-50 (C)
- **Company:** Adani Enterprises Limited
- **Sector:** diversified
- **Moat:** moderate — incubator for Adani group infra businesses; execution strong but governance discount real.
- **Business quality (1-5):** 2
- **Growth profile:** growing (nominal) but capital-intensive
- **Current valuation:** expensive — SOTP-dependent; Hindenburg-related discount partially unwound.
- **Target score range:** 35-50
- **Target midpoint:** 43
- **Rationale:** Growth is real, governance discount is real — C is fair.
- **Red flag:** any fresh short-seller / regulatory action; debt roll-over stress.
- **Canary flag:** FALSE — current 43 is exactly on target midpoint. Calibration win.

---

## Summary table — 30 stocks at a glance

| ticker | sector | moat | score_range | score_mid | current_actual | gap | flag |
|---|---|---|---|---:|---:|---:|---|
| HDFCBANK.NS | bank | wide | 78-85 | 82 | 17 | **+65** | **RED** |
| ICICIBANK.NS | bank | wide | 75-83 | 79 | 27 | **+52** | **RED** |
| KOTAKBANK.NS | bank | narrow-wide | 65-73 | 69 | 34 | +35 | **RED** |
| SBIN.NS | bank | narrow-wide | 60-68 | 64 | 38 | +26 | **RED** |
| TCS.NS | it_services | wide | 75-82 | 78 | 44 | +34 | **RED** |
| INFY.NS | it_services | wide | 68-76 | 72 | 73 | -1 | ok |
| HCLTECH.NS | it_services | narrow-wide | 65-73 | 69 | 37 | +32 | **RED** |
| WIPRO.NS | it_services | narrow | 50-60 | 55 | 66 | -11 | amber |
| TECHM.NS | it_services | narrow | 48-58 | 53 | 51 | +2 | ok |
| MPHASIS.NS | it_services | narrow | 55-65 | 60 | 48 | +12 | amber |
| HINDUNILVR.NS | fmcg | wide | 65-73 | 69 | 34 | +35 | **RED** |
| ITC.NS | fmcg | wide | 62-70 | 66 | 61 | +5 | ok |
| NESTLEIND.NS | fmcg | wide | 65-75 | 70 | 47 | +23 | **RED** |
| MARUTI.NS | auto | wide | 68-75 | 72 | 33 | +39 | **RED** |
| TITAN.NS | retail | wide | 65-73 | 69 | 25 | +44 | **RED** |
| ASIANPAINT.NS | fmcg | wide | 58-68 | 63 | 20 | +43 | **RED** |
| RELIANCE.NS | diversified | wide | 65-75 | 70 | 25 | +45 | **RED** |
| ONGC.NS | commodity | narrow | 48-58 | 53 | 60 | -7 | ok |
| BPCL.NS | commodity | narrow | 45-55 | 50 | 45 | +5 | ok |
| TATASTEEL.NS | commodity | narrow | 40-52 | 46 | N/A | N/A | N/A |
| LT.NS | engineering | wide | 68-76 | 72 | 46 | +26 | **RED** |
| ULTRACEMCO.NS | cement | wide | 62-70 | 66 | 38 | +28 | **RED** |
| POWERGRID.NS | utility | wide | 58-68 | 63 | 28 | +35 | **RED** |
| NTPC.NS | utility | wide | 55-65 | 60 | 50 | +10 | amber |
| SUNPHARMA.NS | pharma | wide | 65-73 | 69 | 28 | +41 | **RED** |
| DIVISLAB.NS | pharma | wide | 60-70 | 65 | 28 | +37 | **RED** |
| BAJFINANCE.NS | nbfc | wide | 68-76 | 72 | 22 | +50 | **RED** |
| BAJAJFINSV.NS | nbfc | wide | 62-72 | 67 | 25 | +42 | **RED** |
| BHARTIARTL.NS | telecom | wide | 70-78 | 74 | 48 | +26 | **RED** |
| ADANIENT.NS | diversified | moderate | 35-50 | 43 | 43 | 0 | ok |

**Red-flagged rows (|gap| > 20): 21 of 29** — the scoring engine is systematically under-scoring wide-moat Indian blue chips.

Calibration wins (|gap| <= 5): INFY, TECHM, ITC, BPCL, ADANIENT. Interestingly, these span IT, commodities, FMCG, and diversified — so the engine is not uniformly broken; it fails hardest on **banks, NBFCs, consumer franchises, and pharma**.

---

## Notes on confidence

- Target midpoints are judgment calls anchored to analyst consensus and basic fundamentals; individual midpoints can reasonably move +/- 5 points. The **ranges**, not the midpoints, are the real ground truth.
- Any gap > 20 points is almost certainly a real engine defect, not a calibration difference of opinion.
- Any gap in 10-20 range is ambiguous — could be legitimate analyst disagreement or engine bias. Treat as amber.
- Any gap <= 10 is fine.

This document is a **calibration reference**, not investment advice. Use it to measure the scoring engine, not to buy or sell stocks.
