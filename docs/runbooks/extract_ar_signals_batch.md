# Runbook -- `scripts/extract_ar_signals_batch.py`

**Owner:** data-pipeline / LLM-cost discipline.
**Last revised:** 2026-05-26 (Phase H-extract, Block II).

## What this script does

Walks `company_annual_reports` (migration 027), picks rows that:

1. Have a non-empty `ar_url`, AND
2. Do NOT yet have an `ar_signals` row at the running service's
   `(model_version, prompt_version)`.

For each candidate it calls
`ar_intel_service.extract_ar_signals_from_url` which:

1. Downloads the AR PDF (`httpx`, 8 MB cap, 60 s timeout).
2. Extracts text via `pypdf`.
3. Splits the text into deterministic chunks
   (`chunk_ar_text`, ~60k chars / chunk).
4. Calls Anthropic Sonnet 4.5 per chunk with the prompt-cached
   system prompt.
5. Merges the per-chunk JSON, validates the schema, runs the
   JSON-walking SEBI sanitizer over every free-text leaf.
6. UPSERTs into `ar_signals` (migration 060) keyed by
   `(annual_report_id, model_version, prompt_version)`.

## When to run

* After `data_pipeline/sources/nse_annual_reports.py` has populated
  `company_annual_reports.ar_url` for the target universe.
* Operator-triggered only -- the
  `.github/workflows/ar-backfill.yml` button is the canonical entry
  point. **Never** run this from cron.

## Pre-flight

1. Confirm migration 060 is applied:
   ```sh
   psql "$DATABASE_URL" -c "\d ar_signals" | grep quality_flag
   ```
   Expect: `quality_flag | text | not null default 'ok'::text`.

2. Confirm Anthropic key is set:
   ```sh
   test -n "$ANTHROPIC_API_KEY" && echo OK
   ```

3. Smoke-test on 3 ARs:
   ```sh
   python scripts/extract_ar_signals_batch.py --dry-run --max-rows 3
   ```
   Expect: 3 candidate rows logged, no writes.

4. Real 3-AR run (cheap, < $1):
   ```sh
   python scripts/extract_ar_signals_batch.py \
       --max-rows 3 --cost-cap-usd 5
   ```
   Expect: 3 rows persisted, `processed=3 failed=0` in the
   summary line. If `failed >= 2`, the pre-flight gate aborts
   with exit code 2 -- DO NOT proceed; investigate the URLs.

## Real backfill

Default operator command (top-200 x 10y, ~2000 rows):

```sh
python scripts/extract_ar_signals_batch.py \
    --max-rows 2000 --cost-cap-usd 500
```

Budget guidance:
* Mean cost per AR ~ $0.20-$0.30 (per Phase H-audit probe).
* 2000-AR projection ~ $400-$600.
* Set `--cost-cap-usd` 10-20% above the projection so the cap
  fires on a runaway rather than on the planned spend.

## Resume after a cost-cap stop

The script logs the last `id` on cost-cap:

```
COST CAP HIT — cumulative $99.8721 >= $100.00. Last id=15234.
Re-run with --resume-from-id=15234 to continue.
```

```sh
python scripts/extract_ar_signals_batch.py \
    --resume-from-id 15234 --cost-cap-usd 200
```

## Versioning + re-extraction

* `ar_intel_service.EXTRACTOR_VERSION` is the `model_version`
  string. Change it (e.g. when switching to Sonnet 4.7) to make
  the LEFT-JOIN-NOT-EXISTS candidate query re-process every row.
* `PROMPT_VERSION` (int) does the same when the system prompt
  changes. The UNIQUE constraint on
  `(annual_report_id, model_version, prompt_version)` keeps the
  previous row around for diffing.

## Failure-mode reference

| Result | quality_flag | What happened |
|---|---|---|
| Clean extraction | `ok` | All chunks parsed, sanitizer clean |
| Banned vocab caught | `sebi_withheld` | A free-text field had a SEBI banned word -- public reader returns `{signals: null, withheld: true}` |
| All chunks failed | `extraction_failed` | LLM call / JSON parse failed every chunk; cost row still written so we don't re-spend |
| pypdf text < 2000 chars | `extraction_failed` | Image-only AR; no LLM call made, $0 spent |

## SEBI discipline

The JSON-walking sanitizer fires on these JSON paths
(`_SEBI_CHECK_FIELD_BASES` in `ar_intel_service.py`):

* `quote`, `drivers`, `purpose`, `description`, `nature`,
  `qualification`, `outlook`, `management_outlook`,
  `commentary`, `notes`.

Structural enum fields (`type`, `direction`, `relationship`,
`fy`, `as_of`, ...) are exempt because their controlled
vocabulary legitimately overlaps with the ban list
(e.g. `type='rating_action'`).

## Cost meter cross-check

After the batch run:

```sql
SELECT model_version,
       COUNT(*)                              AS n_rows,
       SUM(cost_usd)                         AS total_usd,
       AVG(cost_usd)                         AS avg_usd,
       SUM(input_tokens)                     AS sum_in_tok,
       SUM(output_tokens)                    AS sum_out_tok,
       COUNT(*) FILTER (WHERE quality_flag = 'sebi_withheld') AS withheld,
       COUNT(*) FILTER (WHERE quality_flag = 'extraction_failed') AS failed
  FROM ar_signals
 WHERE extracted_at >= now() - interval '1 day'
 GROUP BY model_version;
```

Compare `SUM(cost_usd)` against the Anthropic console for the
same window. They should match within ~1% (the SDK reports
`cache_read_input_tokens` separately; our cost math sums them
with regular input).
