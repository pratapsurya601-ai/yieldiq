# Day-103d: schema cleanup — retarget concall + AR panels at canonical tables

**Date:** 2026-05-22
**Branch:** `day103d-schema-cleanup`
**Predecessors:** PR #515 (Day-103b annual reports), PR #517 (Day-103a concalls)

## What happened

Two Day-103 agents working in parallel each shipped a brand-new table
for surfaces the codebase already covered:

| Day-103 created (DUPLICATE) | Already existed |
|---|---|
| `concalls` (migration 051) | `concall_transcripts` (migration 010) |
| `annual_reports` (migration 052) | `company_annual_reports` (migration 027) |

The duplicates worked in isolation against their own seed rows, but
they were disconnected from the rest of the data pipeline — the NSE
corporate-announcement crawler that populates `concall_transcripts`
on a weekly schedule, and the Phase-2 Claude AR extractor that
populates `company_annual_reports`, both wrote to tables the new
panel endpoints did not read. The agents did not grep for existing
schema before creating new tables, so the duplication was not caught
at review time.

## Why we chose refactor over dual-write

Three options were on the table:

1. **Keep the duplicates and dual-write from ingestion.** Rejected
   because it doubles the write path on every weekly NSE crawl for
   no incremental user-visible value, and creates two sources of
   truth that will inevitably drift.
2. **Migrate data between the tables.** Rejected because the
   duplicate tables only hold a handful of HDFCBANK.NS seed rows —
   there is no production data worth migrating.
3. **Refactor the service layer to read from the canonical tables.**
   Chosen. The response contract of both endpoints stays identical,
   so frontend panels keep working with zero change. The internal
   change is small (two service files, two test files), and the
   duplicates are dropped in a single migration.

The frontend response shape is unchanged — `period`, `date`,
`source_url`, `ai_summary`, `has_full_transcript` for concalls;
`fiscal_year`, `filed_date`, `source_url` for annual reports — so
no `CACHE_VERSION` bump and no manifest entry are required.

## Schema mapping decisions

**concalls → concall_transcripts.** The canonical table has no
`ai_summary` column. We chose not to add one in this narrow refactor;
instead `list_concalls` returns `ai_summary: null` for every row and
the frontend renders period + date + transcript link only. The
`summarise_concall` helper is left in place but unwired — a follow-up
PR will add either a dedicated `concall_transcript_summaries` cache
table or an `ai_summary` column with the matching
`ai_summary_model` / `_generated_at` fields, at which point the
helper gets wired back in.

The `period` field is parsed out of the canonical table's free-text
`subject` column (e.g. `"Q3 FY25 earnings call"` → `"Q3-FY25"`) via
a tolerant regex. When the regex doesn't match (analyst meets,
strategic updates), we fall back to the truncated raw subject so the
panel always renders something meaningful.

**annual_reports → company_annual_reports.** Column rename only:
`filed_date` → `published_at`, `source_url` → `ar_url`. The
canonical table also carries the Claude-extracted structured layer
(`segment_data`, `capex_commitments`, etc.) which is harmless to the
link-index read path and gives a future PR a free upgrade path to
surface AR-derived insights on the panel.

## Migration sequence for operators

The migrations are idempotent and ordered. On a fresh Neon instance:

1. **Skip** `051_concalls.sql`, `051a_concalls_seed.sql`,
   `052_annual_reports.sql`, `052a_annual_reports_seed.sql`. Each
   carries a `SUPERSEDED` banner at the top.
2. **Apply** `053_drop_day103_duplicates.sql` — idempotent
   `DROP TABLE IF EXISTS`. Safe to run even if 051/052 were never
   applied.
3. **Apply** `054_hdfcbank_demo_seed.sql` — inserts the HDFCBANK.NS
   demo rows into the canonical tables. `ON CONFLICT DO NOTHING` so
   re-runs are safe.

On an instance where 051/052 were already applied, step 2 will drop
the duplicate tables and step 3 will populate the canonical tables.
The panels keep responding 200 with non-empty payloads throughout.
