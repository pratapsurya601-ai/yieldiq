# Data quality known gaps — 2026-04-29

This document captures tickers for which no public annual financials exist
in the `financials` table despite material listed market cap (> Rs. 1000 Cr).
These are NOT data-pipeline bugs — they are mostly recent IPOs / spinoffs
where audited annual filings have not yet been published or ingested.

The frontend should treat these tickers with a **`data_limited`** badge
(do not show DCF, do not show full hex, suppress fair-value text). The
canary regression suite should also exclude them.

## Untouchable tickers (mcap > Rs. 1000 Cr, COUNT(annual financials)=0)

| ticker | mcap (Cr) | company | sector | likely reason |
|---|---:|---|---|---|
| LGEINDIA | 107,103 | LG Electronics India Limited | Technology | recent IPO (post Oct 2025) |
| LENSKART | 92,310 | Lenskart Solutions Limited | Healthcare | recent IPO |
| RUBICON | 15,465 | Rubicon Research Limited | Healthcare | recent IPO |
| CANHLIFE | 13,324 | Canara HSBC Life Insurance | Financial Services | recent IPO |
| ABLBL | 12,773 | Aditya Birla Lifestyle Brands | Consumer Cyclical | demerger spinoff |
| SKFINDUS | 11,189 | SKF India (Industrial) Limited | Industrials | demerger spinoff |
| ORKLAINDIA | 8,873 | Orkla India Limited | Consumer Defensive | recent IPO |
| WEWORK | 7,243 | WeWork India Management | Real Estate | recent IPO |
| KWIL | 6,389 | Kwality Wall's (India) Limited | Consumer Defensive | demerger / new listing |
| CRAMC | 5,451 | Canara Robeco AMC | Financial Services | recent IPO |
| MIDWESTLTD | 4,618 | Midwest Limited | Basic Materials | recent IPO |
| ELLEN | 3,770 | Ellenbarrie Industrial Gases | Basic Materials | recent IPO |
| RAYMONDREL | 2,926 | Raymond Realty Limited | Real Estate | demerger spinoff |
| BUILDPRO | 2,666 | Shankara Buildpro Limited | Consumer Cyclical | demerger spinoff |
| STUDDS | 1,914 | Studds Accessories Limited | Consumer Cyclical | recent IPO |
| STLNETWORK | 1,432 | STL Networks Limited | Communication Services | demerger spinoff |
| DIGITIDE | 1,384 | Digitide Solutions Limited | Industrials | demerger spinoff |

Total: **17 tickers**.

## Recommended frontend treatment

For any ticker in the table above:

1. **Stock detail page**: Render with `data_limited=true` -- show only price,
   market cap, and a one-liner explaining "Annual financial filings not yet
   available; full analysis returns once filings publish (typically 6-12
   months post listing/spinoff)."
2. **Screener / hex grid**: Either hide or render greyed-out with a tooltip.
   Do NOT include them in screener percentile rankings -- they will pollute
   the distribution.
3. **DCF / fair value endpoints**: Return HTTP 422 with
   `{"error": "data_limited", "reason": "no_annual_filings"}`.

## Maintenance

Re-run the discovery query monthly:

```sql
WITH mc AS (
  SELECT DISTINCT ON (ticker) ticker, market_cap_cr
  FROM market_metrics WHERE market_cap_cr IS NOT NULL
  ORDER BY ticker, trade_date DESC
)
SELECT mc.ticker, mc.market_cap_cr, s.company_name, s.sector
FROM mc
JOIN stocks s ON s.ticker = mc.ticker
LEFT JOIN financials f ON f.ticker = mc.ticker AND f.period_type='annual'
WHERE mc.market_cap_cr > 1000
GROUP BY mc.ticker, mc.market_cap_cr, s.company_name, s.sector
HAVING COUNT(f.*) = 0
ORDER BY mc.market_cap_cr DESC LIMIT 50;
```

When a ticker drops off this list (because its first annual filing has
been ingested), remove it from the frontend's `data_limited` allowlist.
