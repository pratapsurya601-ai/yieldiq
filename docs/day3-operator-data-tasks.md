# Day 3 morning operator-data tasks (2026-05-19)

Two engines exist but are gated on operator-curated data. Without
this data they fall through to generic DCF, which produces broken
under-outliers for the affected tickers.

**Total operator time: ~20 minutes** if investor relations pages are
open in tabs.

**Outliers each task resolves:**
- Insurance EV: SBILIFE, ICICIPRULI, LICI (currently +77% over-shoot)
- Realty land-bank: OBEROIRLTY, GODREJPROP, PHOENIXLTD, PRESTIGE,
  SOBHA, BRIGADE, LODHA (currently 80-90% under-shoot, all 7 are
  in the under-outlier set)

---

## Task 1: Life-insurance Embedded Value (10 min)

**Already done** (earlier this week):
| Ticker | EV (Cr) | VNB (Cr) | Margin | Growth |
|---|---|---|---|---|
| HDFCLIFE | 50,000 | 3,900 | 26.5% | 16.98% |

**Still needed:**
| Ticker | EV (Cr) | VNB (Cr) | Margin | Growth |
|---|---|---|---|---|
| SBILIFE | ? | ? | ? | ? |
| ICICIPRULI | ? | ? | ? | ? |
| LICI | ? | ? | ? | ? |

**Where to find:**
- SBILIFE: https://www.sbilife.co.in/en/about-us/investor-relations/financial-reports
- ICICIPRULI: https://www.iciciprulife.com/about-us/investor-relations.html
- LICI: https://licindia.in/investor-relations

Open the Q4 FY26 investor presentation (April–May 2026), find the
"Embedded Value" slide. Look for:
- "Indian Embedded Value (IEV)" — current year, in Cr
- "Value of New Business (VNB)" — FY26 annual, in Cr
- "VNB Margin %"
- "Embedded Value Operating Profit Growth" or "EV growth YoY"

**Entry path:** `/admin/insurance-ev` (operator UI) — recommended.

Or via SQL:
```sql
INSERT INTO insurance_appraisal_inputs (
  ticker, period_end, embedded_value_cr, value_new_business_cr,
  vnb_margin_pct, ev_growth_yoy_pct, source_url, entered_by, notes
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

---

## Task 2: Realty land-bank inputs (10 min)

The realty developers DCF-fix engine is wired but routes only when
`realty_land_bank_inputs` has a row for the target ticker. Currently
only DLF has data (entered manually).

**Already done:**
| Ticker | Land Acres | Mkt Value (Cr) | Book (Cr) | Unsold (Cr) | Pre-sales (Cr) |
|---|---|---|---|---|---|
| DLF | 10,500 | 81,000 | 6,000 | 16,996 | 21,000 |

**Still needed** (in priority order — all are current under-outliers):
| Ticker | Why high priority | Where |
|---|---|---|
| OBEROIRLTY | -88.7% drift (₹210 vs ₹1850) | https://www.oberoirealty.com/investor-relations |
| GODREJPROP | -86.3% drift (₹300 vs ₹2187) | https://www.godrejproperties.com/investors |
| PHOENIXLTD | -80.6% drift (₹388 vs ₹2000) | https://www.thephoenixmills.com/investors |
| PRESTIGE | recent under-outlier | https://www.prestigeconstructions.com/investors |
| SOBHA | recent under-outlier | https://www.sobha.com/investor-relations/ |
| BRIGADE | recent under-outlier | https://www.brigadegroup.com/investors |
| LODHA | recent under-outlier | https://www.lodhagroup.com/investor-relations |

Open Q4 FY26 / FY25 investor presentation (or annual report), find:
- **Land bank** — typically expressed in **acres** or **msf** (million sq ft)
  - Note: 1 acre ≈ 0.05 msf; if presented in msf, multiply by 20 to get acres
- **Land bank market value** — most developers disclose either market value
  (in Cr) or "GDV potential" (gross development value)
- **Unsold inventory** — in Cr (₹ of unsold built-up units)
- **Pre-sales pipeline** — bookings already done but not yet recognised

**Entry path:** `/admin/realty` (operator UI) or:

```sql
INSERT INTO realty_land_bank_inputs (
  ticker, reporting_fy, land_bank_acres, land_bank_market_value_cr,
  land_bank_book_value_cr, unsold_inventory_cr, pre_sales_pipeline_cr,
  uplift_per_share, source_url, entered_by
) VALUES
  ('OBEROIRLTY', 'FY25', /*acres*/, /*mv*/, /*bv*/, /*unsold*/, /*presales*/, 0.0,
   '<presentation URL>', 'pratapsurya601@gmail.com'),
  -- ... repeat for the other 6
;
```

`uplift_per_share` may stay at 0.0 — the engine computes it.

---

## Verification after entry

Both engines hit cache on first invocation. After entry, force a
recompute by purging cache + curl:

```powershell
$env:DATABASE_URL = [System.Environment]::GetEnvironmentVariable('DATABASE_URL', 'User')
psql $env:DATABASE_URL -c "DELETE FROM analysis_cache WHERE ticker IN ('SBILIFE.NS','ICICIPRULI.NS','LICI.NS','OBEROIRLTY.NS','GODREJPROP.NS','PHOENIXLTD.NS','PRESTIGE.NS','SOBHA.NS','BRIGADE.NS','LODHA.NS');"
foreach ($t in @('SBILIFE.NS','ICICIPRULI.NS','LICI.NS','OBEROIRLTY.NS','GODREJPROP.NS','PHOENIXLTD.NS','PRESTIGE.NS','SOBHA.NS','BRIGADE.NS','LODHA.NS')) {
  curl.exe -s -o /dev/null -w "$t HTTP %{http_code}`n" --max-time 60 "https://api.yieldiq.in/api/v1/public/stock-summary/$t"
}
```

Then check the cache:

```sql
SELECT
  REPLACE(ticker, '.NS', '') AS t,
  (payload->'valuation'->>'fair_value')::numeric AS fv,
  payload->'valuation'->>'valuation_method' AS method
FROM analysis_cache
WHERE ticker IN ('SBILIFE.NS','ICICIPRULI.NS','LICI.NS','OBEROIRLTY.NS','GODREJPROP.NS','PHOENIXLTD.NS','PRESTIGE.NS','SOBHA.NS','BRIGADE.NS','LODHA.NS')
ORDER BY ticker;
```

`valuation_method` should now show:
- `appraisal_value` for the 3 life insurers
- `pb_plus_land_bank` for the 7 realty developers

Outlier reduction expected: 10 stocks total drop out of the outlier
list.
