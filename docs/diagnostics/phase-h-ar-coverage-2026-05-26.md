# Phase H-audit -- Annual Report Coverage Diagnostic (2026-05-26)

**Status:** placeholder pending first operator run against Neon.
**Script:** `scripts/audit_ar_coverage.py`
**Author:** Phase H dispatch (Block II)
**Purpose:** evidence base to gate Phase H-schema / H-extract /
H-frontend / H-operator-workflow.

> This file is the committed companion to the audit script. The
> script regenerates it (with the same path) when run against the
> live Neon snapshot, populating the empty numeric cells below.
> The values here are the structural template + thresholds so
> reviewers can see the gate logic ahead of the run.

---

## 1. Why this audit exists

Phase H mirrors the Phase G concall pattern but for ANNUAL REPORTS:
prompt-cached Anthropic extraction of structured signals (segment
revenue/EBIT, capex commitments, related-party transactions,
auditor flags, contingent liabilities, management outlook) from the
AR PDFs already indexed in `company_annual_reports` (migration 027)
via `data_pipeline/sources/nse_annual_reports.py`.

AR PDFs are 5-50x larger than concall PDFs (100-300 pages vs
15-30). Before committing budget to a top-200 x 10y (~2000 AR)
backfill, the audit answers three questions:

1. How many tickers in top-200 / canary-333 already have AR rows
   in `company_annual_reports`?
2. What's the source mix (BSE / NSE / manual seed)?
3. What does a typical AR PDF cost to extract end-to-end via
   Anthropic Sonnet 4.5 with prompt caching?

---

## 2. Universe (populated by the script)

| Bucket | Count |
|---|---|
| Canary v3 (333) | _filled by script_ |
| Top 200 by market cap | _filled by script_ |
| Union (deduped) | _filled by script_ |

---

## 3. Coverage headline (populated by the script)

| Group | Any row | Any in 1y | Any in 5y | Any in 10y | Meets 5y >= 5 | Meets 10y >= 10 |
|---|---|---|---|---|---|---|
| Canary v3 | -- | -- | -- | -- | -- | -- |
| Top-200 | -- | -- | -- | -- | -- | -- |
| Union | -- | -- | -- | -- | -- | -- |

---

## 4. Source breakdown (populated by the script)

| Source | Rows | Share |
|---|---|---|
| bse | -- | -- |
| nse | -- | -- |
| manual | -- | -- |
| company_website | -- | -- |

---

## 5. PDF probe -- end-to-end cost estimate

The script samples 10 random AR PDFs (deterministic seed
`20260526`), downloads them with `httpx` (8 MB cap, 60 s timeout),
extracts text via `pypdf`, and projects extraction cost assuming
Sonnet 4.5 ($3 / Mtoken input, $15 / Mtoken output, ~1500 output
tokens per AR after chunked merge).

| Metric | Value |
|---|---|
| Sample size | 10 |
| Successful end-to-end | _filled by script_ |
| Failed | _filled by script_ |
| Mean PDF size | _filled by script_ |
| Mean extracted chars | _filled by script_ |
| Mean estimated input tokens | _filled by script_ |
| Min / Mean / Max cost per AR (USD) | _filled by script_ |
| Projected 2000-AR cost (USD) | _filled by script_ |

Prompt caching is NOT modelled in this projection -- real spend
will be lower once the cache warms up.

---

## 6. Verdict gate

Filled in by `build_summary` -- one of:

| Verdict | Trigger | Action |
|---|---|---|
| PROCEED | top-200 coverage >= 50% AND mean cost/AR <= $0.30 | Ship H-schema, H-extract, H-frontend, H-operator-workflow. |
| PROCEED WITH CAUTION | top-200 coverage 30-50% OR mean cost/AR $0.30-$0.50 | Ship all four; narrow initial batch. |
| HARD STOP | top-200 coverage < 30% | Open a separate phase to backfill AR URLs. Pause H-schema. |
| HARD STOP | mean cost/AR > $0.50 | Open a separate phase to switch model / re-chunk. Pause H-schema. |

Thresholds match the spec:
- coverage hard-stop < 30%, warn < 50%
- cost/AR hard-stop > $0.50, warn > $0.30

---

## 7. Reproducibility

```
python scripts/audit_ar_coverage.py \
    --env-file .env.local --env-line 2
```

Outputs (paths embed the run date):

* `reports/ar_coverage_<YYYY-MM-DD>.csv` -- per-ticker counts.
* `reports/ar_coverage_summary_<YYYY-MM-DD>.json` -- machine summary.
* `reports/ar_sample_extraction_<YYYY-MM-DD>.json` -- 10-AR probe.
* `docs/diagnostics/phase-h-ar-coverage-<YYYY-MM-DD>.md` -- this file.

Run with `--skip-pdf-probe` for a fast coverage-only pass.

---

## 8. Wiring to Phase H follow-ups

* If verdict = PROCEED: H-schema PR adds migration `060_ar_signals.sql`,
  H-extract PR adds `backend/services/ar_intel_service.py` + batch
  script, H-frontend PR adds `ARSignalsPanel`, H-operator-workflow PR
  adds `ar-backfill.yml`.
* If verdict = PROCEED WITH CAUTION: same four PRs but the operator
  runbook recommends `--max-rows 200` for the first run and
  `--cost-cap-usd 50` to keep the meter honest.
* If verdict = HARD STOP: the dispatch agent stops and reports.
