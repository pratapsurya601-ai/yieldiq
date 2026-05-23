# Runbook — `scripts/extract_concall_signals_batch.py`

**Owner:** data-pipeline / LLM-cost discipline.
**Last revised:** 2026-05-23 (Phase G-intel-phase1 b).

## What this script does

Walks `concall_transcripts`, finds rows where:
1. `transcript_text` is populated (Day-104b's PDF extraction already
   ran via the summary backfill), AND
2. No `concall_signals` row exists yet with this `transcript_id`.

For each candidate it calls Anthropic Sonnet 4.5 via
`concall_intel_service.extract_concall_signals_full`, JSON-schema-
validates the response, runs the SEBI string-leaf sanitizer, and
UPSERTs into `concall_signals` with all of:

| Column | Source |
|---|---|
| `ticker`, `fiscal_period`, `concall_date`, `transcript_source` | from row + LLM |
| `guidance_changes`, `capex_commitments`, `margin_commentary`, `key_quotes` | JSON-validated LLM output |
| `management_tone` | LLM enum (`bullish` \| `neutral` \| `cautious` \| `defensive`) |
| `extractor_version` | `concall-intel-v1-anthropic-2026-05-23` |
| `quality_flag` | `'ok'` or `'sebi_withheld'` (from JSON-walker) |
| `transcript_id` | source row's `concall_transcripts.id` |
| `ai_input_tokens`, `ai_output_tokens`, `ai_cost_usd` | from Anthropic `usage` |

Migration 059 must be applied before the first run (already done in
phase-g-intel-phase1-a PR).

## When to run

* After `backfill_concall_summaries.py` has populated `transcript_text`
  on a meaningful slice of rows. Without that, this script finds 0
  candidates (the smoke test on an empty inventory confirms this).
* Operator-triggered only. Anthropic Sonnet costs ~10x Groq —
  cost discipline matters more here.
* Easiest entry point: the GitHub Actions workflow shipped in
  Phase G-operator-workflow.

## Pre-flight

1. Confirm migration 059 is applied:
   ```sh
   psql "$DATABASE_URL" -c "\d concall_signals" | grep quality_flag
   ```
   Expect: `quality_flag | text`.

2. Confirm both API keys are set:
   ```sh
   echo "${GROQ_API_KEY:?missing}" "${ANTHROPIC_API_KEY:?missing}"
   ```
   (Sonnet runs via ANTHROPIC_API_KEY; the row's `transcript_text`
   was originally created with GROQ_API_KEY by the summary backfill,
   so both should already be set in the runner env.)

3. Confirm there are candidate rows:
   ```sh
   psql "$DATABASE_URL" -c "
     SELECT COUNT(*)
       FROM concall_transcripts ct
       LEFT JOIN concall_signals cs ON cs.transcript_id = ct.id
      WHERE ct.transcript_text IS NOT NULL
        AND cs.id IS NULL
   "
   ```
   If 0 — run the summary backfill first.

## Smoke test (no LLM calls)

```sh
python scripts/extract_concall_signals_batch.py --dry-run --max-rows 3
```

Expect: log lines per row, `processed=3` (or fewer if the queue is
small), spend stays at $0.0000.

## Real run with cost cap

```sh
python scripts/extract_concall_signals_batch.py \
    --rate-limit 1.0 \
    --cost-cap-usd 25
```

Expect: progress every 10 rows, cumulative cost climbs by ~$0.03-$0.05
per row, hard-stop when ~500-800 rows have processed. The script logs
the next `--resume-from-id` to use.

## Resuming after a cost-cap stop

```sh
python scripts/extract_concall_signals_batch.py \
    --cost-cap-usd 25 \
    --resume-from-id 4823
```

## Flag reference

| Flag | Default | Meaning |
|---|---|---|
| `--dry-run` | off | Walk + log, no Anthropic calls, no writes. |
| `--max-rows N` | unlimited | Stop after N rows. |
| `--rate-limit S` | 1.0 | Sleep S seconds between Anthropic calls. |
| `--cost-cap-usd N` | 50.0 | Hard-stop when cumulative spend ≥ N. |
| `--resume-from-id N` | — | Skip `concall_transcripts.id < N`. |

## Cost model

Constants in
`backend/services/concall_intel_service.py::ANTHROPIC_PRICING_USD_PER_MTOKEN`.
Update them in one place; this script picks the new numbers up
automatically.

Per-row estimate (Sonnet 4.5, 20-page concall, ~12k input + ~600 output):
**$0.045 / row**. So `--cost-cap-usd 50` permits ~1,100 rows.

**Prompt caching is enabled** — the system prompt is identical across
calls, so `cache_read_input_tokens` quickly dominates the input side
after the first ~10 calls in a batch. Watch per-row cost in the log;
it should drop visibly once the cache warms.

Why is the default cap lower than `backfill_concall_summaries.py`'s
$100? Because per-row spend is ~10x. $50 here is the same order of
magnitude in operational risk as $100 on the summary backfill.

## What `quality_flag` means

| Value | Meaning |
|---|---|
| `ok` | LLM output passed schema validation AND the JSON-walking sanitizer found no banned vocabulary in free-text fields. |
| `sebi_withheld` | A banned word (`buy`, `sell`, `strong`, `recommend`, `target`, etc.) appeared in `key_quotes[].quote`, `margin_commentary[].drivers`, `margin_commentary[].purpose`, or `management_tone`. The row is still persisted with the structured signals; downstream code should NOT render rows with `sebi_withheld` until a human reviews them. |

The frontend filter that gates rendering lives in
`frontend/components/ConcallSignalsPanel.tsx` (shipped in PR (c)).

## Schema-fail circuit breaker

If >30% of rows in a batch fail schema validation, the script logs an
ERROR and recommends pausing. Most likely cause: Anthropic released a
model update that changed default output formatting. Iterate on
`_SYSTEM_PROMPT` in `concall_intel_service.py` (the constraints are
already strong, but a model update can still drift formatting).

## Validation queries

```sql
-- Per-quality_flag count + spend
SELECT quality_flag,
       COUNT(*)                       AS rows,
       SUM(ai_cost_usd)::numeric(10,4) AS total_usd,
       AVG(ai_cost_usd)::numeric(10,6) AS avg_per_row
  FROM concall_signals
 WHERE ai_cost_usd IS NOT NULL
 GROUP BY quality_flag
 ORDER BY rows DESC;

-- How many candidate rows remain?
SELECT COUNT(*)
  FROM concall_transcripts ct
  LEFT JOIN concall_signals cs ON cs.transcript_id = ct.id
 WHERE ct.transcript_text IS NOT NULL
   AND cs.id IS NULL;

-- Withheld-rate by ticker (find the worst offenders)
SELECT ticker, COUNT(*) FILTER (WHERE quality_flag='sebi_withheld') AS withheld,
       COUNT(*) AS total
  FROM concall_signals
 GROUP BY ticker
 HAVING COUNT(*) FILTER (WHERE quality_flag='sebi_withheld') > 0
 ORDER BY withheld DESC
 LIMIT 20;
```

## Failure modes

| Symptom | Probable cause | Mitigation |
|---|---|---|
| Exits with `ANTHROPIC_API_KEY not set` | env var missing | export it, re-run |
| 0 candidate rows on every run | `transcript_text` never populated | run `backfill_concall_summaries.py` first |
| Spend per row very high ($0.10+) | prompt caching disabled or SDK too old | confirm `anthropic>=0.40.0`; check that `system=[...]` block in service module has `cache_control` |
| Many rows withheld | Anthropic model regressed on SEBI-strictness | inspect the withheld rows; iterate on `_SYSTEM_PROMPT` |
| `>30% schema fail` ERROR | Anthropic model output drift | pause batch; update prompt; re-test on 5 rows |

## Related

* Service: `backend/services/concall_intel_service.py`
* Migration (cost columns): `data_pipeline/migrations/058_concall_ai_cost_tracking.sql`
* Migration (signals quality_flag): `data_pipeline/migrations/059_concall_signals_quality_flag.sql`
* Sibling backfill: `docs/runbooks/concall-summary-backfill.md`
* Operator workflow (UI trigger): `.github/workflows/concall-backfill.yml`
  *(added in G-operator-workflow PR)*
