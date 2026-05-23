# Phase I-audit -- Bank operational-KPI coverage (2026-05-26)

**Status:** read-only diagnostic. No code or data changes.
**Author:** Phase I dispatch (Block II).
**Purpose:** evidence base to gate Phase I-schema / I-ingest /
I-frontend / I-operator-workflow.

This document is the static snapshot committed alongside
`scripts/audit_bank_kpi_coverage.py`. The script regenerates a fresh
copy (date-stamped) on every run against the live DB; this checked-in
copy is the version the Phase I plan is anchored to.

---

## 1. Why this audit exists

Competitor surfaces (screener.in, banknote.in, tijori) show per-bank
operational metrics that YieldIQ currently does not: branches
(total + tier split), ATMs, customer base, GNPA, NNPA, provision
coverage ratio, CASA, cost-to-income, credit-deposit ratio.

The generic `company_financials` and `ratio_history` tables do not
carry bank-specific operational fields. Phase I adds them as a
schema + ingest path + frontend panel. The Phase B.0 / B.1 work
established that the banking cohort scoring is highly sensitive to
NPA cycles -- per-bank GNPA / PCR are first-class inputs to the
ROE-quality boost and stress flag in `sector_overrides.py`
(`banking_roe_quality_boost`, `banking_stress_flag`).

Today those helpers receive `None` for the asset-quality inputs in
production because no upstream column populates them. This audit
quantifies the gap before committing schema + ingest work.

---

## 2. Universe (38 tickers)

Source: `_PURE_BANK_TICKERS_FOR_DE` in
`backend/services/analysis/sector_overrides.py`. This is the broader
commercial-bank predicate used by the Day-111b D/E numerator fix,
and is the right universe for Phase I -- it includes Tier-1 private
banks, Tier-2 private banks, the top PSU set, and the small-finance
banks.

Tier-1 private (5): HDFCBANK, ICICIBANK, KOTAKBANK, AXISBANK, INDUSINDBK.
Tier-2 / regional / mid-cap private (5): FEDERALBNK, IDFCFIRSTB,
AUBANK, BANDHANBNK, RBLBANK.
PSU (12): SBIN, PNB, BANKBARODA, CANBK, BANKINDIA, IOB, UCOBANK,
CENTRALBK, INDIANB, MAHABANK, IDBI, UNIONBANK.
Older private + small-finance (16): YESBANK, KARURVYSYA, CUB,
DCBBANK, SOUTHBANK, TMB, CAPITALSFB, ESAFSFB, EQUITASBNK, UJJIVANSFB,
SURYODAY, FINOPB, JANASURF, UTKARSHBNK, FINCABK, SFBAJM.

Total: 5 + 5 + 12 + 16 = 38 distinct tickers (full set: AUBANK,
AXISBANK, BANDHANBNK, BANKBARODA, BANKINDIA, CANBK, CAPITALSFB,
CENTRALBK, CUB, DCBBANK, EQUITASBNK, ESAFSFB, FEDERALBNK, FINCABK,
FINOPB, HDFCBANK, ICICIBANK, IDBI, IDFCFIRSTB, INDIANB, INDUSINDBK,
IOB, JANASURF, KARURVYSYA, KOTAKBANK, MAHABANK, PNB, RBLBANK, SBIN,
SFBAJM, SOUTHBANK, SURYODAY, TMB, UCOBANK, UJJIVANSFB, UNIONBANK,
UTKARSHBNK, YESBANK).

---

## 3. KPI coverage today (expected starting state)

The audit script probes each KPI against every plausible source column
in `bank_operational_kpis` (target table -- doesn't exist yet),
`ratio_history`, `financials`, and `company_financials`. The expected
result on a clean main today, mirrored against the per-bank probe in
`docs/bank_data_availability.md` (2026-04-21, 7 flagship banks):

| KPI | Expected coverage | Expected source | Resolved today |
|---|---|---|---|
| branches_total | 0 / 38 (0%) | AR / investor presentation | none |
| branches_tier_split | 0 / 38 (0%) | AR / investor presentation | none |
| atms_total | 0 / 38 (0%) | AR / investor presentation | none |
| customers_millions | 0 / 38 (0%) | AR / investor presentation | none |
| gnpa_pct | 0 / 38 (0%) | NSE/BSE XBRL Sch XVIII | none |
| nnpa_pct | 0 / 38 (0%) | NSE/BSE XBRL Sch XVIII | none |
| pcr_pct | 0 / 38 (0%) | NSE/BSE XBRL Sch XVIII | none |
| casa_pct | 0 / 38 (0%) | NSE/BSE XBRL Sch V | none |
| cost_to_income_pct | ~5 / 38 (13%) derivable | operating_expense / revenue (derived) | `company_financials.operating_expense` populated for SBIN, BANKBARODA, KOTAKBANK, AXISBANK, INDUSINDBK per 2026-04-21 audit |
| credit_deposit_pct | 0 / 38 (0%) | NSE/BSE XBRL Sch V + VII | none -- advances/deposits not broken out |

**Missing entirely:** 9 / 10 KPIs (90%) -- above the 70% RESCOPE
threshold. **Partially derivable:** 1 / 10 (cost-to-income via
`operating_expense / revenue` on five tickers).

---

## 4. Source recommendations per KPI

| KPI | Recommended source | Notes |
|---|---|---|
| gnpa_pct | NSE / BSE quarterly XBRL Schedule XVIII (Asset Classification) | Reuse `data_pipeline/sources/bse_xbrl.py` + `bse_quarterly_xbrl.py` patterns. Direct numeric tags. |
| nnpa_pct | NSE / BSE quarterly XBRL Schedule XVIII | Same fetcher as GNPA. |
| pcr_pct  | NSE / BSE quarterly XBRL Schedule XVIII | Same fetcher. Often disclosed as a separate ratio tag. |
| casa_pct | NSE / BSE quarterly XBRL Schedule V (Deposits) | Compute from `current + savings` over `total_deposits` if the ratio tag is absent. |
| credit_deposit_pct | NSE / BSE quarterly XBRL Schedule V + VII | `advances_total / deposits_total`. |
| cost_to_income_pct | XBRL Schedule A/B + Form A; fallback derived `operating_expense / (interest_earned + non_interest_income)` | `operating_expense` is already populated for 5/38 banks per the 2026-04-21 audit. |
| branches_total / tier split | Bank annual report (`company_annual_reports.ar_url`) -- "performance highlights" section, typically pages 1-15 | Use the Phase H Anthropic extractor with a new bank-ops prompt template. |
| atms_total | Same AR section | Same extractor. |
| customers_millions | Same AR section | Same extractor. RBI DBIE has aggregate figures but not per-bank consistently. |

For the AR path, the existing Phase H pipeline
(`scripts/extract_ar_signals_batch.py`, `ar_signals` migration 060)
gives us prompt caching, cost tracking, and the SEBI-vocab JSON
sanitiser for free. The new `I-ingest-b` script reuses that scaffolding
with a different output schema targeting `bank_operational_kpis`.

---

## 5. Verdict

**RESCOPE** (proceed with narrowed initial scope).

90% of the Phase I KPIs have no source today. This is the EXPECTED
starting state -- the `bank_operational_kpis` table does not exist
yet and the NSE/BSE XBRL Schedule extractors (V / VII / XI / XVIII)
have not been written. The previously-existing per-bank audit
(`bank_data_availability.md`, 2026-04-21) already documented the same
gap and explicitly TODO'd these as separate extractors.

Ship I-schema + I-ingest narrowed to the highest-confidence subset
(GNPA / NNPA / PCR / CASA from BSE quarterly XBRL); defer
branches / ATMs / customer base to the AR-PDF extraction path;
cost-to-income and credit-deposit are derivable once the underlying
deposits/advances columns are broken out.

### Scope for the four follow-on PRs

- **I-schema** -- ship `061_bank_operational_kpis.sql` exactly as
  specified in the Phase I plan (10 metric columns + source + URL +
  ticker / period_end / period_type UNIQUE). Migration 060 is taken
  (`ar_signals`), so this Phase uses **061**.
- **I-ingest-a** -- BSE XBRL Schedules V / XVIII fetcher for the four
  financial KPIs (GNPA / NNPA / PCR / CASA) on the 3-bank pre-flight
  sample (HDFCBANK, SBIN, AXISBANK). `--dry-run`, `--resume-from`.
- **I-ingest-b** -- AR-PDF Anthropic extractor for the operational
  KPIs (branches / ATMs / customers). `--cost-cap-usd 50` per the
  Phase H precedent. **Conditional** -- proceed only after I-ingest-a
  ships and is operating cleanly; otherwise defer with the AR path
  documented as "manual entry for now".
- **I-frontend** -- `BankKpiPanel.tsx` rendering only when the ticker
  is in `is_pure_bank_for_de()`; gracefully degrades when columns are
  null (the expected state on day one). Manifest entry scoped to
  `["bank_operational_kpis", "bank_kpis"]`. No CACHE_VERSION bump.
- **I-operator-workflow** -- `bank-kpi-backfill.yml` mirroring
  `concall-backfill.yml` and `ar-backfill.yml`, with phase choice
  `xbrl` / `ar` / `all`, `top_n_banks`, `cost_cap_usd`, `dry_run`.

### Why not HARD STOP

The gap is real but every one of the missing KPIs has a documented,
reachable source (XBRL Schedules V / XVIII for the financial KPIs;
the same AR-PDF channel Phase H already uses for the operational
KPIs). The cost / engineering profile is well understood. RESCOPE
(not HARD STOP) reflects shipping the foundation now and filling
data via the operator workflow over time, rather than blocking
schema + frontend on full data availability.

---

## 6. Reproducibility

```
python scripts/audit_bank_kpi_coverage.py \
    --env-file .env.local --env-line 2
```

Output paths embed the run date; reruns against a different DB
snapshot write new files without overwriting today's. The probe is
defensive against missing tables / columns -- once `I-schema` lands
the same script will start picking up `bank_operational_kpis` rows
without any code change.
