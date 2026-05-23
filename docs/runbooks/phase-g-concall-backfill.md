# Phase G — Concall Backfill (operator runbook)

**Status:** active.
**Owner:** operator on call.
**Workflow:** `.github/workflows/concall-backfill.yml`
**Related:**
- `docs/runbooks/concall-summary-backfill.md` — manual steps for the Groq summary path only.
- `docs/runbooks/concall-signals-extraction.md` — manual steps for the Anthropic signal-extraction path only.
- `docs/diagnostics/phase-g-concall-coverage-2026-05-23.md` — coverage audit baseline.

---

## 1. What this runbook covers

A single GitHub Actions button that runs any phase of the concall backfill chain end-to-end:

1. **transcripts** — fetch fresh PDFs from NSE for the top-N tickers over the last `days_back` days.
2. **summaries** — generate Groq free-text TL;DR summaries for transcripts that don't already have one.
3. **signals** — generate Anthropic structured-signal extractions (guidance / capex / margin / tone / quotes).
4. **all** — runs 1 → 2 → 3 in sequence.

The same workflow always runs in dry-run mode by default. Flip `dry_run` to `false` to actually write to the DB and spend LLM credit.

---

## 2. Trigger from the GitHub UI

1. Open `Actions` → `Concall Backfill (operator)` in the GitHub UI.
2. Click `Run workflow`.
3. Fill the inputs:

| Input | Default | Notes |
|---|---|---|
| `phase` | `all` | One of `transcripts | summaries | signals | all`. |
| `top_n` | `200` | Universe size. Reused as `--top` (transcripts), `--max-tickers` (summaries), `--max-rows` (signals). |
| `days_back` | `1825` (5y) | Only used by the transcripts phase. |
| `cost_cap_usd` | `100` | Hard-stop USD spend per LLM phase. Counted from rows populated by this run. |
| `dry_run` | `true` | `true` -> no DB writes, no LLM calls. Always run dry first. |

4. Click `Run workflow` again to confirm.

---

## 3. Expected runtimes

Sourced from the Phase G-audit (2026-05-23) coverage data: 4,495 transcripts across a 10-month window for the union universe (342 tickers).

| Phase | top_n | dry_run | Real runtime estimate |
|---|---|---|---|
| transcripts | 200, days_back=1825 | true | ~5 min (NSE crawl, no LLM) |
| transcripts | 200, days_back=1825 | false | ~30-60 min (NSE rate-limit + downloads) |
| summaries | 200 | true | ~2 min |
| summaries | 200 | false | ~15-30 min (Groq is fast; mostly DB I/O) |
| signals | 200 | true | ~2 min |
| signals | 200 | false | ~45-90 min (Anthropic is slower, rate-limited to 1 req/s by default) |
| **all** | 200 | true | ~10 min |
| **all** | 200 | false | ~2-3 hr |

Budget cap math (defaults):
- summaries: Groq pricing ~$0.05 / 1M output tokens. 200 transcripts × ~1.5k output tokens = ~$0.015 total — `cost_cap_usd=100` is wildly above the natural cap.
- signals: Anthropic Sonnet 4.5 = $3/$15 per Mtoken (input/output). 200 transcripts × ~12k input + ~3k output = ~200 × ($0.036 + $0.045) ≈ $16. Default `cost_cap_usd=100` gives ~6x headroom.

---

## 4. Validation queries

After a real (non-dry) run, against Neon PG:

```sql
-- 4a. Were new transcripts ingested in the last 24h?
SELECT COUNT(*) AS new_transcripts,
       MIN(filing_date) AS oldest,
       MAX(filing_date) AS newest
FROM concall_transcripts
WHERE inserted_at >= now() - interval '24 hours';

-- 4b. How many got a Groq summary in this run?
SELECT COUNT(*) AS summarised_recent
FROM concall_transcripts
WHERE ai_summary IS NOT NULL
  AND ai_summary_at >= now() - interval '24 hours';

-- 4c. Anthropic signal rows from this run + spend.
SELECT COUNT(*) AS signal_rows,
       SUM(ai_cost_usd)::numeric(10, 4) AS total_usd,
       SUM(CASE WHEN quality_flag = 'sebi_withheld' THEN 1 ELSE 0 END)
         AS withheld_rows
FROM concall_signals
WHERE extracted_at >= now() - interval '24 hours';

-- 4d. Distribution of management_tone (sanity: any one bucket >90% is suspect).
SELECT management_tone, COUNT(*)
FROM concall_signals
WHERE extracted_at >= now() - interval '24 hours'
GROUP BY 1
ORDER BY 2 DESC;
```

If `withheld_rows / signal_rows > 0.20` (more than 20% withheld), open a follow-up to tighten the extractor prompt — high false-positive on SEBI vocab.

---

## 5. Rollback

The workflow is additive — re-running with the same inputs is idempotent (UPSERT on the natural keys). True rollback (drop data inserted by this run) is rarely needed; when it is:

```sql
-- 5a. Drop the most recent extraction batch (signals only — keeps
-- transcripts + summaries, which are cheap to regenerate).
BEGIN;
DELETE FROM concall_signals
WHERE extracted_at >= now() - interval '24 hours';
COMMIT;

-- 5b. Nuclear option — drop ALL derived data and re-run from scratch.
-- Only do this if the data is provably corrupt, not for cost reasons.
BEGIN;
TRUNCATE concall_signals;
UPDATE concall_transcripts
   SET ai_summary = NULL,
       ai_summary_at = NULL;
COMMIT;
```

After 5b, re-run the workflow with `phase=all dry_run=false`.

---

## 6. Common failure modes

| Symptom | Likely cause | Action |
|---|---|---|
| Workflow exits 0 but `signal_rows` query shows zero | `dry_run=true` was left on | Re-run with `dry_run=false`. |
| Anthropic 401 in logs | `ANTHROPIC_API_KEY` secret rotated | Update repo secret, re-run. |
| Cost-cap hit mid-batch | Run was larger than expected | Bump `cost_cap_usd`, re-run with `--resume-from-id` (manual CLI only — workflow does not expose this yet). |
| `concall_transcripts.transcript_text IS NULL` for many rows | NSE PDF downloader failed silently | Inspect the transcripts step logs; the script logs per-ticker failures. |

---

## 7. Manifest entry

Real-data runs are covered by the manifest entry `v_phase_g_intel_signals_2026_05_26` (added in PR #569) — public cache reads on the analysis page will recompute against the freshest signals after that timestamp.
