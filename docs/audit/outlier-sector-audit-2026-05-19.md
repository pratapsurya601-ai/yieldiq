# Reconciliation Outlier Sector Audit — 2026-05-19

**Scope**: Day-1 baseline pass over the first Layer A reconciliation run
on `hotfix/reconciliation-ticker-form` (canonicalised JOIN landed at
`83b2e2f`). 338 outliers surfaced (37 over-valued by us, 301 under).
Investigation only — **no code changes**.

**Files inspected (read-only)**
- `backend/services/analysis/constants.py` — every classifier set
  (`FINANCIAL_COMPANIES`, `_NBFC_INSURANCE_BANKLIKE`, `REIT_TICKERS`,
  `ETF_TICKERS`, `DEFENSE_PSU_TICKERS`, `REALTY_TICKERS`,
  `CAPITAL_GOODS_TICKERS`, `CYCLICAL_TICKERS`, `HOLDING_COMPANIES`,
  `BRAND_MOAT_PREMIUM_TICKERS`).
- `backend/services/analysis/service.py` — routing dispatch
  (L739, L1098, L1178-1232, L3265-3340, L3537-3660).
- `models/industry_wacc.py` — `REGULATED_UTILITY_TICKERS` (L941-949).
- `backend/services/regulated_utility_valuation_service.py` — rate-base
  engine, `_SUB_TYPE_PARAMS` (L100-104), `_REGULATED_NBFC_TICKERS`
  (L93-95).
- `backend/services/corporate_actions_service.py` — STRUCTURAL action
  truncation (L44-50).
- `backend/services/analysis/ipo_framework.py` — 36-month / 60-month
  (pharma) IPO window (L36-49).

---

## 1. Baseline numbers

| metric                              | value |
|-------------------------------------|------:|
| reconciliation outliers (total)     |   338 |
| over (our FV > consensus median)    |    37 |
| under (our FV < consensus median)   |   301 |
| outlier threshold                   | 30 %  |
| minimum analyst coverage required   |    3  |

The 9:1 under:over split tells us this is overwhelmingly a *missing-engine*
or *wrong-engine* problem — generic FCF-DCF collapsing to ~0 on
businesses whose value is in the balance sheet (financials, regulated
utilities), the future order book (defence / capital goods) or land/
brand IP (realty / FMCG / pharma). Over-valuation is the long tail
(typically a sector-engine over-tuning, e.g. the rate-base Gordon math
on RECLTD).

---

## 2. Operator query — sector × valuation_model rollup

Run locally against Neon (sandbox has no DB access).

```sql
WITH outliers AS (
  SELECT
    ac.ticker,
    ac.payload->>'sector'                                    AS sector,
    ac.payload->>'industry'                                  AS industry,
    ac.payload->>'valuation_model'                           AS valuation_model,
    (ac.payload->'valuation'->>'fair_value')::float          AS our_fv,
    lc.target_median                                          AS consensus_fv,
    lc.analyst_count,
    ABS((ac.payload->'valuation'->>'fair_value')::float - lc.target_median)
      / NULLIF(lc.target_median, 0)                           AS abs_delta
  FROM analysis_cache ac
  JOIN (
    SELECT DISTINCT ON (ticker) ticker, target_median, analyst_count
    FROM consensus_estimates
    WHERE target_median > 0
    ORDER BY ticker, fetched_at DESC
  ) lc
    ON UPPER(REPLACE(REPLACE(ac.ticker,'.NS',''),'.BO',''))
     = UPPER(REPLACE(REPLACE(lc.ticker,'.NS',''),'.BO',''))
  WHERE (ac.payload->'valuation'->>'fair_value')::float > 0
    AND lc.analyst_count >= 3
    AND ABS((ac.payload->'valuation'->>'fair_value')::float - lc.target_median)
        / NULLIF(lc.target_median, 0) > 0.30
)
SELECT
  COALESCE(sector, 'NULL')           AS sector,
  COALESCE(valuation_model, 'NULL')  AS valuation_model,
  COUNT(*)                            AS outlier_count,
  SUM(CASE WHEN abs_delta > 0 AND analyst_count >= 3 THEN 1 ELSE 0 END)
                                      AS confirmed_count,
  ROUND(AVG(abs_delta)::numeric * 100, 1) AS avg_delta_pct,
  ROUND(MIN(abs_delta)::numeric * 100, 1) AS min_delta_pct,
  ROUND(MAX(abs_delta)::numeric * 100, 1) AS max_delta_pct
FROM outliers
GROUP BY sector, valuation_model
ORDER BY outlier_count DESC;
```

Expected output shape (column names):

```
 sector                    | valuation_model | outlier_count | avg_delta_pct
---------------------------+-----------------+---------------+---------------
 NULL                      | dcf             |   ~80         |  ~85
 Financial Services        | dcf             |   ~40         |  ~75
 Pharma                    | dcf             |   ~25         |  ~55
 Industrials               | dcf             |   ~20         |  ~70
 Real Estate               | dcf             |   ~15         |  ~60
 Insurance                 | dcf             |   ~10         |  ~80
 Cement                    | dcf             |   ~8          |  ~60
 Power & Utilities         | rate_base       |   ~5          |  ~50  (over)
 ...                                                          ...
```

Numbers above are a *hypothesis* anchored to the 9 known top-outlier
tickers — please replace this block with the actual roll-up after the
operator runs the query.

---

## 3. Pattern hypotheses (anchored on known top outliers)

| # | hypothesised group           | example tickers                            | symptom                          | est. outliers | root cause                                                                                                  |
|---|------------------------------|--------------------------------------------|----------------------------------|--------------:|-------------------------------------------------------------------------------------------------------------|
| A | Housing-finance NBFCs        | LICHSGFIN                                  | DCF FV ~₹0.77, consensus ~₹600   |    20-30      | `LICHSGFIN` is **NOT** in `_NBFC_INSURANCE_BANKLIKE` (constants.py L100-103 has `LICHOUSFIN` — the legacy ticker rename). `is_bank_like()` returns False → routed to DCF (negative FCF by design). |
| B | General + reinsurance        | GICRE, NIACL                               | DCF FV ~₹15, consensus ~₹350     |    10-15      | Insurance appraisal engine ships for **life only** (HDFCLIFE/SBILIFE/ICICIPRULI/LICI). General insurers in `_INSURANCE_TICKERS` but the appraisal engine refuses them (see `insurance_appraisal_service.py` L… caller branch). GICRE / reinsurance not in any classifier set. |
| C | Bank classifier miss         | YESBANK                                    | DCF FV ~₹19, consensus ~₹22-26   |     1-3       | YESBANK *is* in `FINANCIAL_COMPANIES` (constants.py L39) and `_NBFC_INSURANCE_BANKLIKE` (L91) → P/B path should fire. Hypothesis: pb_ratio path producing low FV due to negative trailing-equity TTM (post-AT1 write-down book is still depressed); not a routing miss, an engine miss. |
| D | Recent-IPO / no-history      | PINELABS, SAILIFE, WESTLIFE, PAYTM, AEGISVOPAK | DCF FV <<₹50, consensus ₹300-1,400 |    25-40   | `is_recent_ipo()` requires a `listing_date` argument (ipo_framework.py L100). Routing in service.py only fires when yfinance returns `firstTradeDateEpochUtc`. For these 2024/2025 listings the field is sparse → falls through to generic DCF on <3 years of audited financials. |
| E | Cement M&A — broken TTM      | INDIACEM                                   | DCF FV ~₹15, consensus ~₹300     |     2-5       | UltraTech absorbed India Cements 2025; TTM CFO/FCF straddles the deal close. `corporate_actions_service.STRUCTURAL_ACTION_TYPES` has `MERGER` but the seed migration (`042_seed_structural_mergers.sql`) does NOT include INDIACEM. Without a seed row, `has_structural_break` returns False → plain CAGR on a broken series. |
| F | Demerged stubs               | TMPV                                       | DCF FV ~₹0.5, "company" ~₹350    |     3-5       | Tata Motors PV ltd (`TMPV`) is the post-demerger PV stub. yfinance has minimal financials. Should be flagged as corp-actioned and short-circuited. Not in `HOLDING_COMPANIES`, no demerger seed row for the *child* ticker. |
| G | Mid-cap pharma → Tier 2      | NATCOPHARM                                 | DCF FV ~₹350, consensus ~₹900    |    10-15      | Pharma window already extended to 60 months (ipo_framework.py L47) but the Tier 2 Premium peer-cohort fallback is not the engine that fires by default — generic DCF still wins for tickers that aren't in any premium-cohort allowlist. Need explicit Tier 2 routing for mid-cap pharma. |
| H | Small/mid-cap IT → Tier 2    | ZENSARTECH                                 | DCF FV ~₹450, consensus ~₹800    |    10-15      | Same shape as G — generic DCF under-prices project-revenue IT services on a single-year FCF read. |
| I | Water / EPC / infrastructure | WABAG, ASHOKA                              | DCF FV ~₹500, consensus ~₹1,400  |    10-15      | WABAG → capital-goods engine was DISABLED 2026-05-18. ASHOKA → not in `CAPITAL_GOODS_TICKERS` (L1140) or in any infra cohort. Need sector-relative routing for road/infra/water EPC. |
| J | Regulated-utility OVERSHOOT  | RECLTD                                     | rate_base FV ~₹1,001 vs cons ₹440 |     3-5      | **NOT a routing miss** — see §4. Engine is firing; the (ROE=0.18, COE=0.105, g=0.05) tuple for `regulated_nbfc` produces fair_pb ≈ 2.36 (regulated_utility_valuation_service.py L100-104) which overshoots consensus by ~2×. |
| K | Generic-DCF / NULL-sector    | (residue)                                  | DCF FV near zero                 |   100-150     | yfinance returns NULL sector → no override fires → generic DCF path → trailing FCF crushes FV. Long-tail catch-all; needs the sector-resolution backfill (separate workstream). |

Sum (mid-points): ≈ 194-292 outliers explained by groups A-J; balance
(≈ 50-140) attributed to group K and below-the-line tickers we don't
have a hypothesis for yet.

---

## 4. RECLTD deep-dive (claimed routing bug)

**Claim**: RECLTD outlier (FV ₹1,001 vs consensus ₹440) is a routing
miss — should be rate_base, might be running generic DCF.

**Finding**: **Not a routing miss.** Three independent confirmations:

1. **Membership** — `REGULATED_UTILITY_TICKERS` at
   `models/industry_wacc.py:941-949` contains `"RECLTD"` explicitly.
   `_REGULATED_NBFC_TICKERS` at
   `backend/services/regulated_utility_valuation_service.py:93-95`
   contains `"RECLTD"`.

2. **Dispatch order** — `backend/services/analysis/service.py:808`
   computes `is_regulated_utility_ticker`. The branch at L1178 routes
   to `compute_regulated_utility_fair_value()`. ETF / REIT short-
   circuits (L777-798) do not match RECLTD.

3. **Arithmetic check** — for `regulated_nbfc` sub-type
   (`_SUB_TYPE_PARAMS` at L100-104): `(ROE − g)/(COE − g) = (0.18 −
   0.05)/(0.105 − 0.05) = 0.13 / 0.055 ≈ 2.364`. RECLTD FY25 BVPS
   ≈ ₹425 → FV ≈ ₹1,004. That matches the observed ₹1,001 to within
   rounding. The engine **is** firing; it's just over-tuned for the
   PSU lender-NBFC cohort given current consensus.

**Operator verification SQL**:

```sql
SELECT
  ticker,
  payload->>'valuation_model'                           AS valuation_model,
  payload->'valuation'->>'fair_value'                   AS fv,
  payload->'valuation'->>'method'                       AS method,
  payload->'computation_inputs'->>'valuation_model'     AS ci_valuation_model,
  payload->'computation_inputs'->>'is_regulated_utility' AS is_regulated_utility
FROM analysis_cache
WHERE UPPER(REPLACE(REPLACE(ticker,'.NS',''),'.BO','')) = 'RECLTD';
```

Expected: `valuation_model = "rate_base"`, `is_regulated_utility =
"True"`, `method` contains "rate_base" or "gordon". If `valuation_model
= "dcf"` then it *is* a routing miss and §4 is wrong — escalate.

**Recommended fix (DESIGN ONLY — not for this PR)**: re-calibrate
`_SUB_TYPE_PARAMS["regulated_nbfc"]` so the FV band centres on
consensus. Options:
- Raise COE to 0.115-0.12 (PSU lender-NBFC risk premium has widened
  post-RBI tightening). At COE = 0.115 / g = 0.05: fair_pb ≈ 2.0 →
  FV ≈ ₹850.
- Pull `allowed_ROE` down to realised 5y average (~0.165 for RECLTD)
  rather than the headline 0.18. At ROE = 0.165 / COE = 0.105 / g =
  0.05: fair_pb ≈ 2.09 → FV ≈ ₹890.
- Either gets RECLTD inside the ±30% band without breaking PFC/IRFC.
  Re-calibration PR should run canary-diff on all four regulated-NBFC
  tickers (PFC, RECLTD, IRFC, HUDCO) before merge.

---

## 5. Per-suspect verification queries

For each known top-outlier ticker, the query the operator can run to
confirm the hypothesised routing path.

```sql
-- Generic shape — substitute :ticker
SELECT
  ticker,
  payload->>'sector'                              AS sector,
  payload->>'industry'                            AS industry,
  payload->>'valuation_model'                     AS valuation_model,
  payload->'valuation'->>'fair_value'             AS fv,
  payload->'valuation'->>'method'                 AS method,
  payload->'valuation'->>'verdict'                AS verdict,
  payload->'computation_inputs'->>'fcf_ttm'       AS fcf_ttm,
  payload->'computation_inputs'->>'wacc'          AS wacc,
  payload->'computation_inputs'->>'terminal_growth' AS g,
  payload->>'data_issues'                         AS data_issues
FROM analysis_cache
WHERE UPPER(REPLACE(REPLACE(ticker,'.NS',''),'.BO','')) = :ticker;
```

| ticker      | hypothesis                                     | expected `valuation_model` if hypothesis is right |
|-------------|------------------------------------------------|---------------------------------------------------|
| TMPV        | demerged stub, no corp-action skip             | `dcf` (i.e. wrong — should be data_limited)       |
| LICHSGFIN   | not in NBFC banklike set                       | `dcf` (wrong — should be `pb_ratio`)              |
| YESBANK     | engine miss not routing miss                   | `pb_ratio` (right routing, wrong number)          |
| RECLTD      | engine overshoot                               | `rate_base` (right routing, over-tuned)           |
| GICRE       | general insurer / reinsurer not routed         | `dcf` (wrong — should be cohort-relative)         |
| NIACL       | general insurer not routed                     | `dcf` (wrong)                                     |
| NATCOPHARM  | mid-cap pharma not in Tier 2 cohort            | `dcf` (wrong — should be sector-relative)         |
| ZENSARTECH  | small-cap IT not in Tier 2 cohort              | `dcf` (wrong)                                     |
| WABAG       | capital-goods engine disabled                  | `dcf` (wrong — needs sector engine)               |
| ASHOKA      | infra/road EPC not in any cohort               | `dcf` (wrong)                                     |
| INDIACEM    | post-M&A TTM not truncated                     | `dcf` (right model, broken inputs)                |
| AEGISVOPAK  | 2024 IPO, no listing_date                      | `dcf` (wrong — should be ipo-routed)              |
| PINELABS    | 2024 IPO                                       | `dcf` (wrong)                                     |
| SAILIFE     | 2024 IPO                                       | `dcf` (wrong)                                     |
| PAYTM       | 2021 IPO + ongoing regulatory disruption       | `dcf` (right routing if outside 36m window; engine miss inside) |
| WESTLIFE    | restaurant — broken TTM via COVID overhang     | `dcf` (right model, normalisation miss)           |

---

## 6. Recommended Day 2-7 fix sprint priority

Ordered by **outlier-resolution-per-LOC**. All entries are *design-only*
proposals to be scoped + planned; this audit doc does not authorise any
code change.

| rank | fix family                            | est. outliers cleared | scope (LOC) | risk        |
|------|---------------------------------------|----------------------:|-------------|-------------|
|  1   | Housing-finance classifier add        |              20-30    | 1 set entry | trivial — `_NBFC_INSURANCE_BANKLIKE` already has `LICHOUSFIN`; add `LICHSGFIN` and the 5 other housing-finance peers (CANFINHOME, AAVAS already present, AADHAARHFC, REPCOHOME, SUNDARMHLD, GICHSGFIN). |
|  2   | NULL-sector backfill (group K)        |             100-150   | data-side    | medium — touches the ingest pipeline, not a constants.py one-liner. Probably the single biggest dial. Separate workstream — flag here, don't try to land in the same sprint. |
|  3   | Recent-IPO routing via report-count   |              25-40    | small        | low — `MIN_ANNUAL_REPORTS_FOR_DCF=3` already defined (ipo_framework.py L64) but unwired. Adding the fallback `len(annual_financials) < 3 → ipo_path` in service.py closes the firstTradeDate gap. |
|  4   | General insurance Tier 2 fallback     |              10-15    | small        | low — interim, until the dedicated general-insurance engine ships (currently deferred). Route `_INSURANCE_TICKERS − {life set}` to the Tier 2 peer cohort. |
|  5   | Mid-cap pharma / small-cap IT cohorts |              20-30    | medium       | medium — needs curated Tier 2 ticker lists per sector and the cohort engine wired as a fallback before generic DCF for those sectors. |
|  6   | Cement / corp-action seed extension   |               2-5     | data-side    | trivial — add INDIACEM (and any other 2024-25 M&A close) to `042_seed_structural_mergers.sql`. |
|  7   | Demerger child-ticker skip            |               3-5     | small        | trivial — add TMPV (and the JIO Financial / ITC Hotels family) to a `DEMERGED_STUBS` set with hard short-circuit to `data_limited`. |
|  8   | Regulated-NBFC re-calibration         |               3-5     | tiny         | low — tune `_SUB_TYPE_PARAMS["regulated_nbfc"]`. Canary-diff PFC/RECLTD/IRFC/HUDCO before merge (rule #1). |
|  9   | Infra / road EPC cohort               |              10-15    | medium       | medium — needs a fresh cohort engine; defer until #1-#8 land and we re-measure. |

Total cleared by ranks 1, 3, 4, 6, 7, 8 (trivial+low risk, no new
engines): ≈ 63-100 outliers, on a baseline of 338. Day 7 target:
**outliers < 240** without writing any new sector engine.

Ranks 2, 5, 9 are the medium-risk swings that move the baseline below
150.

---

## 7. What this doc does NOT change

- No code edits.
- No CACHE_VERSION bump.
- No production rollout.
- No canary-diff run (none required — read-only investigation).
- No PR with code.

Companion PR is **documentation only** (this file).

---

## 8. Follow-ups for the operator

1. Run the §2 rollup query on Neon and paste the actual numbers back
   into the table in §2 — this doc commits the hypothesised shape, not
   the verified shape.
2. Run §4 RECLTD verification SQL and confirm `valuation_model =
   "rate_base"`. If `dcf`, re-open §4.
3. Run the §5 per-ticker checks and mark each row in the table either
   ✅ (hypothesis confirmed) or ❌ (escalate).
4. Once §2 numbers are filled in, draft the rank-1 housing-finance
   classifier PR. That fix is small enough to land in the same week as
   this audit and validates the audit framework end-to-end.
