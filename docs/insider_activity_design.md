# Insider Activity + Bulk/Block Deals — Design Notes

Status: **scaffolding only** (Task 8, branch `wkt/task8-insider`). No
production wiring. No analysis-page integration. No live scraping yet.

This doc records what was built, what is stubbed, the upstream sources,
and the open questions that block the next phase.

## What ships in this PR

| Artifact | Path |
| --- | --- |
| Schema migration | `backend/migrations/016_create_insider_activity.sql` |
| Read service | `backend/services/insider_activity_service.py` |
| Bulk/block ingest stub | `scripts/ingest_bulk_block_deals.py` |
| SEBI insider ingest stub | `scripts/ingest_insider_txns.py` |
| Sample fixture (5 tickers, 17 rows) | `tests/fixtures/insider_activity_sample.json` |
| Tests | `tests/test_insider_activity_service.py` |

The two new tables — `bulk_block_deals` and `insider_transactions` — are
created idempotently via `CREATE TABLE IF NOT EXISTS`. The migration
also adds a natural-key `UNIQUE INDEX` on insider filings so the ingest
script can `ON CONFLICT DO UPDATE` cleanly.

## Why a new table when `bulk_deals` already exists

`data_pipeline/models.py::BulkDeal` (table `bulk_deals`) is already
populated daily by `data_pipeline/sources/nse_bulk_deals.py` and is the
live source of truth today. Its schema diverges from the canonical one
in the v3 governance roadmap:

| Column | Legacy `bulk_deals` | New `bulk_block_deals` |
| --- | --- | --- |
| date | `trade_date` | `deal_date` |
| bulk vs block | `deal_category` | `deal_type` |
| BUY/SELL | `deal_type` ('BUY'/'SELL') | `buy_sell` ('B'/'S') |
| exchange | _missing_ | `exchange` ('NSE'/'BSE') |

Open question #1 (below) tracks the migration plan.

## Sources

### Bulk + block deals

| Source | URL | Format | Auth | Refresh |
| --- | --- | --- | --- | --- |
| NSE bulk (historical) | `https://www.nseindia.com/api/historical/bulk-deals` | JSON | NSE cookies (`curl_cffi` impersonation) | daily, post-18:30 IST |
| NSE bulk (current day) | `https://www.nseindia.com/api/bulk-deals?type=bulk` | JSON | same | live |
| NSE block | `https://www.nseindia.com/api/historical/block-deals` | JSON | same | daily |
| BSE bulk | `https://www.bseindia.com/markets/equity/EQReports/bulk_deals.aspx` | HTML | UA only | daily, post-18:00 IST |
| BSE block | `https://www.bseindia.com/markets/equity/EQReports/block_deals.aspx` | HTML | UA only | daily |

NSE anti-bot: rate-limits IPs and rejects unprimed sessions. The
working pattern in `data_pipeline/sources/nse_bulk_deals.py` uses
`curl_cffi` with `impersonate="chrome"` and warms cookies via a homepage
GET. **Do not** call NSE from Railway worker dynos — see the discipline
note in `memory/feedback_yieldiq_discipline.md`.

### Insider filings (SEBI Reg 7 / PIT)

| Source | URL | Format | Refresh |
| --- | --- | --- | --- |
| **NSE PIT (preferred)** | `https://www.nseindia.com/api/corporates-pit?index=equities&from_date=DD-MM-YYYY&to_date=DD-MM-YYYY` | JSON | T+2 |
| SEBI portal (fallback) | `https://www.sebi.gov.in/sebiweb/other/OtherAction.do?doInsiderTrading=yes` | HTML | T+2 |
| BSE insider trading | `https://www.bseindia.com/corporates/Insider_Trading_new.aspx` | HTML | T+2 |

The T+2 cadence is mandated by SEBI PIT Regulation 7(2): the company
must publish the disclosure within two trading days of receiving
notice from the insider.

The NSE PIT feed is the same one already polled live by
`backend/services/sebi_sast_service.py` for the Pulse axis. Once
`insider_transactions` is populated daily by
`scripts/ingest_insider_txns.py`, the pulse pipeline should switch from
"fetch + aggregate every run" to "read from table" — saving an external
call per pulse refresh.

## What is stubbed

Everything that touches the network or DB. Each fetch function in the
ingest scripts logs `STUB ... → returning []` and returns an empty
list. Each `upsert_rows()` warns when called without `--dry-run` and
discards the rows because the SQLAlchemy session helper isn't wired in
yet (open question #2).

## Refresh frequency targets

- `bulk_block_deals` — once per trading day, after 18:30 IST. Cron in
  GitHub Actions, NOT in the Railway worker (NSE is slow + anti-bot).
- `insider_transactions` — once per trading day, with a 30-day lookback
  window so we catch corrections / late filings.

## Open questions

1. **Migration of legacy `bulk_deals` rows.** Do we (a) backfill
   `bulk_block_deals` from the existing `bulk_deals` table, mapping
   columns and defaulting `exchange='NSE'`, then drop `bulk_deals`; or
   (b) keep both and dual-write until a clean cutover?
   Recommendation: (a), in a follow-up PR after this scaffolding lands.
2. **DB session helper.** `backend/services/local_data_service.py`
   already has a Postgres connection pool for read paths but no helper
   for batched UPSERTs. Either expose a small `execute_many()` wrapper
   on it, or add a thin `backend/services/_pg_writer.py`. Pick one
   before wiring `upsert_rows()`.
3. **BSE-only insider filings.** Some BSE-only listings file insider
   disclosures with BSE only, not NSE. The MVP uses the NSE PIT feed
   alone. Follow-up: add `Insider_Trading_new.aspx` parsing for the
   ~200 BSE-only tickers we track (post Phase A of the BSE-only
   universe ingest).
4. **Frontend integration.** Out of scope here. The "Insider Activity:
   None" placeholder in `frontend/src/components/analysis/InsightCards.tsx`
   should be wired to `summarize_insider_activity()` in a separate PR
   once the tables are populated for at least 30 days.
