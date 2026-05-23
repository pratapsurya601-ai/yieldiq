# Runbook — `scripts/backfill_concall_summaries.py`

**Owner:** data-pipeline / cost-discipline.
**Last revised:** 2026-05-23 (Phase G-cost).

## What this script does

Walks `concall_transcripts`, finds rows that have a `pdf_url` and no
`ai_summary`, and calls Groq Llama 3.3 70B to generate a 5-bullet
SEBI-safe summary per row. Persists:

| Column | Source |
|---|---|
| `ai_summary` | Groq output (or sanitizer/unavailable sentinel) |
| `ai_summary_model` | `llama-3.3-70b-versatile` |
| `ai_summary_generated_at` | wall clock UTC |
| `transcript_text` | extracted PDF text (cached so retries skip the fetch) |
| **`ai_input_tokens`** | `usage.prompt_tokens` from Groq |
| **`ai_output_tokens`** | `usage.completion_tokens` from Groq |
| **`ai_cost_usd`** | computed via `compute_groq_cost_usd` |

Bold columns are added by **migration 058** (Phase G-cost). Apply that
migration before the first cost-tracked run, otherwise the script will
silently fail to persist costs.

## When to run

* After a fresh Phase G deploy (smoke run with `--dry-run` first).
* After the weekly `concall_transcripts_weekly.yml` cron has loaded a
  batch of new filings and you want their summaries populated eagerly
  (rather than waiting for end-user `/api/concalls` hits to lazy-load).
* **Never from cron.** Cost stacks. Always operator-triggered.

## Pre-flight

1. Confirm migration 058 is applied:
   ```sh
   psql "$DATABASE_URL" -c "\d concall_transcripts" | grep ai_cost_usd
   ```
   Expect: `ai_cost_usd | numeric(8,4)`.

2. Confirm `GROQ_API_KEY` is set in the runner env.

3. Confirm `pypdf` and `httpx` are installed (already in
   `requirements.txt`).

## Smoke test (3 rows, no DB writes)

```sh
python scripts/backfill_concall_summaries.py --dry-run --max-tickers 3
```

Expect: log lines per row, `processed=3`, no cost increase.

## Real run with cost cap

```sh
python scripts/backfill_concall_summaries.py \
    --rate-limit 0.5 \
    --cost-cap-usd 25
```

Expect: progress every 10 rows, hard-stop when cumulative spend hits
$25, exit code 0. The last log line will name the next `--resume-from-id`
to use.

## Resuming after a cost-cap stop

```sh
# Suppose previous run stopped at id=4823 with cap hit.
python scripts/backfill_concall_summaries.py \
    --cost-cap-usd 25 \
    --resume-from-id 4823
```

## Flag reference

| Flag | Default | Meaning |
|---|---|---|
| `--dry-run` | off | Walk queue, log, but do not call Groq or write. |
| `--max-tickers N` | unlimited | Cap distinct tickers in this batch. |
| `--rate-limit S` | 0.5 | Sleep S seconds between Groq calls. |
| `--cost-cap-usd N` | 100.0 | Hard-stop when cumulative spend (this run only) ≥ N. |
| `--resume-from-id N` | — | Skip rows with `id < N`. |

## Cost model

Pricing constants live in
`backend/services/concall_service.py::GROQ_PRICING_USD_PER_MTOKEN`.
Update the dict if Groq changes rates — the script picks the new
numbers up automatically.

Per-row estimate on a typical 20-page concall PDF (~12k input tokens,
~400 output tokens): **$0.007 - $0.010**. So `--cost-cap-usd 100`
permits ~10,000 - 15,000 rows.

## What the cost cap counts

Only spend from rows this invocation populated. Sunk spend from prior
runs (already in `ai_cost_usd` for older rows) is NOT included. The
running total resets at every invocation.

## Validation queries

```sql
-- Total spend across all populated rows (entire history)
SELECT
    COUNT(*)                       AS rows_with_cost,
    SUM(ai_cost_usd)::numeric(10,4) AS total_usd,
    AVG(ai_cost_usd)::numeric(10,6) AS avg_per_row,
    MAX(ai_cost_usd)::numeric(10,4) AS max_per_row
  FROM concall_transcripts
 WHERE ai_cost_usd IS NOT NULL;

-- How many rows are still waiting for a summary?
SELECT COUNT(*) FROM concall_transcripts
 WHERE pdf_url IS NOT NULL
   AND ai_summary IS NULL;
```

## Failure modes

| Symptom | Probable cause | Mitigation |
|---|---|---|
| Script exits with `no DB session available` | `DATABASE_URL` unset / unreachable | export env var, re-run |
| Cost increments by $0 each row | `_groq_client()` returned None (no API key) or Groq response lacked `usage` | check `GROQ_API_KEY`; check Groq client version |
| All rows persist `(summary unavailable)` | `pypdf` extraction failed for all PDFs | inspect PDF — may be image-based; OCR pipeline is a separate phase |
| Cost cap hit unexpectedly fast | Llama 3.3 70B pricing changed | update `GROQ_PRICING_USD_PER_MTOKEN` to new rates |

## Related

* Migration: `data_pipeline/migrations/058_concall_ai_cost_tracking.sql`
* Service: `backend/services/concall_service.py`
* Coverage audit: `docs/diagnostics/phase-g-concall-coverage-2026-05-23.md`
* GitHub Actions trigger (Phase G-operator-workflow):
  `.github/workflows/concall-backfill.yml` *(added in a later PR)*
