# Day 3 morning task: Insurance EV data entry

**Goal**: populate `insurance_appraisal_inputs` for the 3 remaining life
insurers so the Appraisal Value engine fires on them (currently they
fall through to the generic P/BV path and mis-value).

**Time**: ~10 minutes if investor presentations are open in tabs.

**Already done** (PR earlier this week):
| Ticker | EV (Cr) | VNB (Cr) | Margin | Growth |
|---|---|---|---|---|
| HDFCLIFE | 50,000 | 3,900 | 26.5% | 16.98% |

**Still needed**:
| Ticker | EV (Cr) | VNB (Cr) | Margin | Growth |
|---|---|---|---|---|
| SBILIFE | ? | ? | ? | ? |
| ICICIPRULI | ? | ? | ? | ? |
| LICI | ? | ? | ? | ? |

## Where to find each number

For each ticker, open the Q4 FY26 investor presentation (April–May 2026)
and look for the "Embedded Value" slide (usually slide 8–12):

### SBILIFE
- URL: https://www.sbilife.co.in/en/about-us/investor-relations/financial-reports
- Look for: "Indian Embedded Value (IEV)" — current year value in Cr
- Look for: "Value of New Business (VNB)" — FY26 annual value in Cr
- Look for: "VNB Margin %" — usually right below VNB
- Look for: "Embedded Value Operating Profit Growth" or "EV growth YoY"

### ICICIPRULI
- URL: https://www.iciciprulife.com/about-us/investor-relations.html
- Same fields as above; check "Annual Embedded Value Report" PDF

### LICI
- URL: https://licindia.in/investor-relations
- LICI is bigger and slower-growing — EV around ₹7–8 lakh Cr typical
- VNB margin lower (~16–18%) due to product mix

## Entering the data

**Option A — Admin UI** (recommended, validates everything):
1. Open `https://www.yieldiq.in/admin/insurance-ev`
2. Click "Add Row" for each ticker
3. Paste values from the presentation
4. Save

**Option B — SQL directly** (if UI isn't deployed for this ticker yet):

```sql
INSERT INTO insurance_appraisal_inputs (
  ticker, period_end,
  embedded_value_cr, value_new_business_cr,
  vnb_margin_pct, ev_growth_yoy_pct,
  source_url, entered_by, notes
) VALUES
  ('SBILIFE',    '2026-03-31', /*EV*/, /*VNB*/, /*margin*/, /*growth*/,
   'https://www.sbilife.co.in/.../q4fy26-presentation.pdf',
   'pratapsurya601@gmail.com', 'Q4FY26 IEV disclosure'),
  ('ICICIPRULI', '2026-03-31', /*EV*/, /*VNB*/, /*margin*/, /*growth*/,
   'https://www.iciciprulife.com/.../q4fy26-presentation.pdf',
   'pratapsurya601@gmail.com', 'Q4FY26 IEV disclosure'),
  ('LICI',       '2026-03-31', /*EV*/, /*VNB*/, /*margin*/, /*growth*/,
   'https://licindia.in/.../q4fy26-presentation.pdf',
   'pratapsurya601@gmail.com', 'Q4FY26 IEV disclosure');
```

## Verification after entry

After inserting, purge the analysis_cache for these 3 tickers so they
rebuild with the appraisal engine:

```sql
DELETE FROM analysis_cache
  WHERE ticker IN ('SBILIFE.NS','ICICIPRULI.NS','LICI.NS','SBILIFE','ICICIPRULI','LICI');
```

Then trigger a fresh compute on each by hitting:
```
curl https://api.yieldiq.in/api/v1/public/stock-summary/SBILIFE.NS
curl https://api.yieldiq.in/api/v1/public/stock-summary/ICICIPRULI.NS
curl https://api.yieldiq.in/api/v1/public/stock-summary/LICI.NS
```

Expected fair-value ranges (sanity check; ±20% drift from consensus
is OK; > 30% drift means the EV/VNB inputs are wrong):

| Ticker | Consensus | Expected FV range | Why |
|---|---|---|---|
| SBILIFE | ₹2,346 | ₹2,000–2,800 | Premium private life insurer, P/EV ~2.0× |
| ICICIPRULI | ₹690 | ₹580–800 | Mid-tier private, P/EV ~1.7× |
| LICI | ₹1,045 | ₹900–1,200 | Public sovereign-backed, P/EV ~1.0× (size discount) |

If any drifts more than 30% from consensus, the EV input is likely
wrong — re-check the investor presentation slide.

## What this does NOT cover (separate task)

- **General insurance** (ICICIGI, NIACL, GICRE) — uses P/BV cohort, not
  appraisal engine. The `general_insurance` peer-group fallback is
  (3.0, 0.15) which is too high for NIACL (trades at 0.94× P/BV) and
  GICRE (trades at 1.11× P/BV). These need a `general_insurance` peer
  taxonomy fix similar to PR #382 — possibly split into "premium GI"
  (ICICIGI, STARHEALTH) and "PSU GI" (NIACL, GICRE).
- **Health insurance** (NIVABUPA, GODIGIT) — currently bundled with
  general_insurance. May warrant its own bucket given high P/B (3-6×)
  and growth profile. Future PR.
