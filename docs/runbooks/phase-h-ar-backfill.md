# Phase H — Annual Report Backfill (operator runbook)

**Status:** active.
**Owner:** operator on call.
**Workflow:** `.github/workflows/ar-backfill.yml`
**Related:**
- `docs/runbooks/extract_ar_signals_batch.md` — manual CLI steps for the Anthropic AR-signals extractor.
- `docs/diagnostics/phase-h-ar-coverage-2026-05-26.md` — coverage + per-AR cost-probe baseline.
- `docs/runbooks/phase-g-concall-backfill.md` — sibling concall runbook this one mirrors.

---

## 1. What this runbook covers

A single GitHub Actions button that runs any phase of the AR backfill chain end-to-end:

1. **transcripts** — ingest AR PDF URLs + metadata from NSE into `company_annual_reports`. No LLM spend.
2. **extract** — download each AR PDF, pypdf-extract + chunk the text, call Anthropic Sonnet 4.5, merge + validate + SEBI-sanitise, UPSERT into `ar_signals` (migration 060).
3. **all** — runs 1 → 2 in sequence.

There is **no** intermediate "summaries" phase here — unlike concalls (which use a cheap Groq TL;DR step before the structured Anthropic extraction), AR signals are pulled directly from the PDF.

The workflow always runs in dry-run mode by default. Flip `dry_run` to `false` to actually write to the DB and spend LLM credit.

---

## 2. Trigger from the GitHub UI

1. Open `Actions` → `AR Backfill (operator)` in the GitHub UI.
2. Click `Run workflow`.
3. Fill the inputs:

| Input | Default | Notes |
|---|---|---|
| `phase` | `all` | One of `transcripts | extract | all`. |
| `top_n` | `200` | Universe size. Reused as `--top` (transcripts) and `--max-rows` (extract). |
| `cost_cap_usd` | `100` | Hard-stop USD spend for the extract phase only. |
| `dry_run` | `true` | `true` -> no DB writes, no LLM calls. Always run dry first. |

4. Click `Run workflow` again to confirm.

> The transcripts phase uses the `ingest_annual_reports.py` script's default `--years-back 5`. If you need a longer history window (e.g. 10y for the full Block II target), run that script directly from a developer machine rather than extending this workflow — the operator surface is deliberately narrow.

---

## 3. Expected runtimes and spend

Sourced from the Phase H-audit (2026-05-26) PDF probe (`docs/diagnostics/phase-h-ar-coverage-2026-05-26.md`) and the extractor docstring: per-AR Sonnet 4.5 spend ~$0.20-$0.30 (100-page AR, ~22k input tokens chunked 2-3 ways, ~1500 output tokens, prompt caching not modelled).

| Phase | top_n | dry_run | Real runtime estimate |
|---|---|---|---|
| transcripts | 200 | true | ~2 min (no NSE writes) |
| transcripts | 200 | false | ~15-30 min (NSE JSON feed + URL ingest) |
| extract | 200 | true | ~3 min (walk + log, no LLM) |
| extract | 200 | false | ~2-4 hr (Anthropic, 1 req/s default rate-limit) |
| **all** | 200 | true | ~5 min |
| **all** | 200 | false | ~3-5 hr |

Budget cap math (defaults):

- `top_n=200`, mean cost $0.25/AR → ~$50 spend. Default `cost_cap_usd=100` gives 2x headroom.
- Full Block II target = top-200 × ~10 fiscal years ≈ **2000 ARs**. At mean $0.25/AR that's **~$500 all-in**. Either run 5 successive batches at the default cap, or raise `cost_cap_usd` to ~500 for a single shot — pick batches if you want the cost-cap as a real circuit breaker.

The extractor has its own pre-flight hard-stop: if >50% of the first 5 rows fail extraction, it exits 2 without burning the rest of the budget.

---

## 4. Validation queries

After a real (non-dry) run, against Neon PG:

```sql
-- 4a. Top-line: how many signal rows exist, broken down by quality.
SELECT COUNT(*), quality_flag
FROM ar_signals
GROUP BY quality_flag;

-- 4b. Were new signal rows written in the last 24h, and what did they cost?
SELECT COUNT(*) AS signal_rows,
       SUM(ai_cost_usd)::numeric(10, 4) AS total_usd,
       SUM(CASE WHEN quality_flag = 'sebi_withheld' THEN 1 ELSE 0 END)
         AS withheld_rows
FROM ar_signals
WHERE extracted_at >= now() - interval '24 hours';

-- 4c. Per-ticker coverage check: how many fiscal years extracted per ticker?
SELECT car.ticker, COUNT(DISTINCT car.fiscal_year) AS years_extracted
FROM ar_signals s
JOIN company_annual_reports car ON car.id = s.annual_report_id
GROUP BY car.ticker
ORDER BY years_extracted DESC
LIMIT 20;

-- 4d. Were new AR URLs ingested in the last 24h (transcripts phase)?
SELECT COUNT(*) AS new_ars,
       MIN(fiscal_year) AS oldest_fy,
       MAX(fiscal_year) AS newest_fy
FROM company_annual_reports
WHERE created_at >= now() - interval '24 hours';
```

If `withheld_rows / signal_rows > 0.20` (more than 20% withheld for SEBI vocab), open a follow-up to tighten the extractor prompt — high false-positive rate on the banned-vocabulary list.

---

## 5. Rollback

The workflow is additive — re-running with the same inputs is idempotent (UPSERT on `(annual_report_id, model_version, prompt_version)`). True rollback (drop data inserted by this run) is rarely needed; when it is:

```sql
-- 5a. Drop just the most recent extraction batch (keeps the AR URL
-- index in company_annual_reports, which is cheap to regenerate
-- but slower to re-crawl from NSE).
BEGIN;
DELETE FROM ar_signals
WHERE extracted_at >= now() - interval '24 hours';
COMMIT;

-- 5b. Nuclear option — drop ALL extracted signals and re-run from
-- scratch. Only do this if the data is provably corrupt, not for
-- cost reasons (each truncate-and-rerun is another ~$500 of spend).
BEGIN;
TRUNCATE ar_signals;
COMMIT;
```

After 5b, re-run the workflow with `phase=extract dry_run=false` — there's no need to re-ingest URLs unless the NSE feed changed.

---

## 6. Common failure modes

| Symptom | Likely cause | Action |
|---|---|---|
| Workflow exits 0 but `ar_signals` row count unchanged | `dry_run=true` was left on | Re-run with `dry_run=false`. |
| Extract phase exits 2 immediately | Pre-flight smoke test (>50% extraction failures in first 5 rows) — PDFs unreadable or Anthropic 4xx | Inspect logs; check Anthropic key + pypdf can open the sample URLs by hand. |
| Anthropic 401 in logs | `ANTHROPIC_API_KEY` secret rotated | Update repo secret, re-run. |
| Cost-cap hit mid-batch | Run was larger than expected, or cache cold | Bump `cost_cap_usd`, re-run. The script is resumable via `--resume-from-id` on a manual CLI run (not exposed by this workflow yet). |
| Transcripts phase logs many `NSE 403` or `cookie expired` | NSE rate-limited or cookie-jar stale | Re-run after 10-15 min; the script's per-ticker `--sleep` defaults to 1.5s. |
| `withheld_rows / signal_rows > 0.20` | Extractor prompt is over-eager on SEBI vocab | Open a prompt-tuning follow-up; do NOT relax the banned-vocabulary list. |
| `ar_signals` empty for a ticker but `company_annual_reports` has rows | AR PDF download / pypdf failure for that ticker | Check per-ticker logs in the extract phase; common cause is BSE-hosted PDFs > 8 MB cap. |

---

## 7. Manifest entry

H-operator-workflow is pure workflow wiring — no engine code paths, no schema changes, no cache surface changes. **No manifest bump and no `CACHE_VERSION` bump are required.** The relevant manifest entries were added by PR #576 (H-schema) and PR #580 (H-frontend).
