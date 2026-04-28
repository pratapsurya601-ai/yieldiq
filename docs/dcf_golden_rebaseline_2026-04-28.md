# DCF Golden Rebaseline — 2026-04-28

## Why

The `dcf-regression` gate was failing on every PR opened today against
the same ~15 tickers (AXISBANK, ICICIBANK, KOTAKBANK, COALINDIA, BPCL,
IOC, …). The drifts were not regressions — they were the **intentional
output** of four scoring PRs merged the day prior:

| PR | Title | Effect on FV/MoS/score |
|---|---|---|
| #126 | `_normalize_pct` consolidation | Cleans up MoS/yield % handling; small upward FV nudges across many tickers |
| #134 | DCF mid-cap calibration | Compresses FV for high-multiple mid-caps (cement, paints) so they no longer pin to `under_review` zero |
| #136 | Peer-cap | Caps DCF output at peer-median × N for banks/PSUs; pulls down AXISBANK / ICICIBANK / EICHERMOT etc. that ran above peer band |
| #137 | `CACHE_VERSION` 65→66 | Invalidates cached pre-#126/#134/#136 outputs in prod; new values now flow through |

Per `scripts/test_dcf.py` doc-string ("WHEN TO REBASELINE"), every
`CACHE_VERSION` bump should be followed by a golden rebaseline.

## How

1. Local boot of FastAPI on `127.0.0.1:8765` with
   `YIELDIQ_DEV_MODE=true` + `AUTO_REFRESH_PARQUETS=0` (avoids the
   Railway prod rate-limit and the parquet-refresh phantom).
2. `python scripts/test_dcf.py --update --api-base http://127.0.0.1:8765 --rate 4.0`
3. Validation re-run (`test_dcf.py` without `--update`) → **51/51 clean,
   0 regressions** against the new golden.

No backend code changed; no `CACHE_VERSION` bump; this is a pure test
fixture update.

## Rebaselined tickers (>5% FV drift OR verdict change)

27 of 51 tickers shifted enough to be flagged. The four PRs land their
biggest effect on banks (peer-cap), heavy-multiple mid-caps (calibration),
and previously `data_limited` / zeroed names (`_normalize_pct`).

| Ticker | Old FV | New FV | Drift | Old Verdict | New Verdict | Attribution |
|---|---:|---:|---:|---|---|---|
| SHREECEM.NS    |  3439.11 | 12490.59 | +263.2% | under_review  | overvalued    | #134 mid-cap calibration unblocks zeroed FV |
| TATASTEEL.NS   |     0.00 |    24.15 | +100.0% | data_limited  | under_review  | #126 normalize_pct gives non-zero FV |
| JSWSTEEL.NS    |     0.00 |   204.46 | +100.0% | data_limited  | under_review  | #126 normalize_pct gives non-zero FV |
| POWERGRID.NS   |   135.94 |   232.00 |  +70.7% | avoid         | avoid         | #134 calibration |
| AMBUJACEM.NS   |   319.71 |   485.63 |  +51.9% | overvalued    | fairly_valued | #134 cement-sector calibration |
| ICICIBANK.NS   |  1132.94 |   770.51 |  -32.0% | fairly_valued | overvalued    | #136 peer-cap firing on bank |
| RELIANCE.NS    |   762.21 |   973.08 |  +27.7% | data_limited  | overvalued    | #126 normalize_pct |
| AXISBANK.NS    |  1604.42 |  1240.36 |  -22.7% | undervalued   | fairly_valued | #136 peer-cap firing on bank |
| MARUTI.NS      | 10973.51 | 13083.00 |  +19.2% | overvalued    | fairly_valued | #134 calibration |
| COFORGE.NS     |   590.39 |   701.88 |  +18.9% | data_limited  | data_limited  | #126 normalize_pct |
| CIPLA.NS       |  1471.67 |  1747.50 |  +18.7% | undervalued   | data_limited  | #126 + verdict gate |
| BPCL.NS        |   473.52 |   558.12 |  +17.9% | undervalued   | undervalued   | #126 normalize_pct |
| TECHM.NS       |  1028.38 |  1176.34 |  +14.4% | overvalued    | overvalued    | #134 calibration |
| KOTAKBANK.NS   |   373.13 |   422.07 |  +13.1% | fairly_valued | fairly_valued | #136 peer-cap (uplift — bank below peer band) |
| KPITTECH.NS    |   507.99 |   445.35 |  -12.3% | overvalued    | overvalued    | #134 mid-cap calibration |
| EICHERMOT.NS   |  5397.18 |  4786.50 |  -11.3% | overvalued    | overvalued    | #136 peer-cap |
| TCS.NS         |  3495.56 |  3792.40 |   +8.5% | undervalued   | undervalued   | #126 normalize_pct |
| ITC.NS         |   309.75 |   335.45 |   +8.3% | fairly_valued | fairly_valued | #126 normalize_pct |
| NESTLEIND.NS   |   611.96 |   651.78 |   +6.5% | overvalued    | overvalued    | #126 normalize_pct |
| IOC.NS         |   245.44 |   261.09 |   +6.4% | data_limited  | data_limited  | #126 normalize_pct |
| COALINDIA.NS   |   373.04 |   395.13 |   +5.9% | fairly_valued | fairly_valued | #126 normalize_pct |
| BERGEPAINT.NS  |   188.36 |   196.77 |   +4.5% | overvalued    | data_limited  | verdict gate via #126 |
| ASIANPAINT.NS  |  1243.77 |  1287.77 |   +3.5% | overvalued    | data_limited  | verdict gate via #126 |
| DALBHARAT.NS   |  1704.87 |  1662.63 |   -2.5% | fairly_valued | overvalued    | verdict gate |
| MPHASIS.NS     |  2097.18 |  2047.75 |   -2.4% | fairly_valued | overvalued    | verdict gate |
| HCLTECH.NS     |  1553.98 |  1518.96 |   -2.3% | undervalued   | fairly_valued | verdict gate |
| ONGC.NS        |   511.93 |   514.37 |   +0.5% | undervalued   | data_limited  | verdict gate |

## Top 5 absolute drifts

1. **SHREECEM.NS**: 3439.11 → 12490.59 (+263.2%) — escapes `under_review` zero-FV bucket
2. **TATASTEEL.NS**: 0.00 → 24.15 (+100.0%) — escapes `data_limited`
3. **JSWSTEEL.NS**: 0.00 → 204.46 (+100.0%) — escapes `data_limited`
4. **POWERGRID.NS**: 135.94 → 232.00 (+70.7%)
5. **AMBUJACEM.NS**: 319.71 → 485.63 (+51.9%)

## What this means for future PRs

- Subsequent drifts on these 27 tickers will be measured against the
  **new** values, not the v32-v35-era values.
- PRs #126, #134, #136, #137 are now **absorbed** by the golden — they
  will not surface again as `dcf-regression` flags.
- The next calibration PR (whenever it lands) will surface its OWN
  drift on top of this baseline and require its OWN rebaseline,
  following the same playbook.
- `CACHE_VERSION` was **not** bumped; this is purely a test fixture.

## Reproducing

```powershell
# Worktree: E:\Projects\yq-rebaseline-golden, branch wkt/rebaseline-dcf-golden
$env:AUTO_REFRESH_PARQUETS="0"
$env:YIELDIQ_DEV_MODE="true"
Start-Process -FilePath "C:\ProgramData\miniconda3\python.exe" `
  -ArgumentList "-m","uvicorn","backend.main:app","--host","127.0.0.1","--port","8765","--log-level","warning" `
  -WindowStyle Hidden -PassThru
# wait ~8 sec for /health
python scripts/test_dcf.py --update --api-base http://127.0.0.1:8765 --rate 4.0
python scripts/test_dcf.py --api-base http://127.0.0.1:8765 --rate 4.0  # validates: 51/51 clean
```
