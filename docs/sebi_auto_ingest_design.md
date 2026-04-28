# SEBI quarterly-results auto-ingest — design

Status: SCAFFOLDING merged. Real crawler is a 1–2 week follow-up.

## Goal

A new BSE/NSE corporate filing should land in YieldIQ within 24h:

1. Detected on BSE or NSE corporate-filings feed.
2. Downloaded (XBRL preferred, PDF fallback).
3. Parsed into `company_financials` via the existing
   `data_pipeline/sources/nse_xbrl_fundamentals.py` pipeline.
4. Analysis cache invalidated for that ticker so the next page view
   recomputes FV.
5. Eligible users (watchlist + holdings, tier-gated) notified.

Today (pre-task) only step 3 exists, behind a manual GH Actions
workflow run. Steps 1, 2, 4, 5 are gaps — this task lays the
foundation for closing them.

## Data sources

### BSE
- Announcements API (JSON):
  `https://api.bseindia.com/BseIndiaAPI/api/AnnGetData/w?strCat=Result&strPrevDate=YYYYMMDD&strToDate=YYYYMMDD&strScrip=&strSearch=P`
- Attachment URL pattern:
  `https://www.bseindia.com/xml-data/corpfiling/AttachLive/<UUID>.{pdf,xml}`
- Rate-limit: tolerant. Akamai sometimes wall-gardens but rotating
  User-Agent + cookie prime works.

### NSE
- Corporate financial results API:
  `https://www.nseindia.com/api/corporates-financial-results?index=equities&from_date=DD-MM-YYYY&to_date=DD-MM-YYYY&period=Quarterly`
- Each row exposes a direct `xbrl` URL on `nsearchives.nseindia.com`.
- Rate-limit: aggressive. Cloudflare interactive challenge fires
  after ~60 req/min from a non-residential IP. Production crawler
  needs residential proxies or an API partnership.
- Cookie-prime pattern: see `backend/services/sebi_sast_service.py`.

## State machine

```
            +---------+
            | pending |  <-- enqueue_filing on detection
            +----+----+
                 |
                 | download xbrl/pdf
                 v
            +-----------+
            | downloaded|
            +-----+-----+
                 |
                 | parse (XBRL: existing pipeline | PDF: LLM TBD)
                 v
            +--------+
            | parsed |
            +---+----+
                 |
                 | upsert company_financials, bump cache
                 v
            +----------+        notify_users_of_new_quarterly
            | ingested | -----> + analysis_cache invalidation
            +----------+
                 |
                 | (terminal)
                 v
            (no further transitions)

  Any state -> failed   (retry_count++, error_message set, retry by cron up to 3x)
  Any state -> skipped  (e.g. PDF-only filing for very small co, or unsupported filing_type)
```

## Cron schedule

Asia/Kolkata, market days only (Mon–Sat):

```
*/30 9-18 * * 1-6   python scripts/run_sebi_crawler.py --mode discover --lookback-hours 2
*/10 9-19 * * 1-6   python scripts/run_sebi_crawler.py --mode process --limit 50
0     23 * * 1-6   python scripts/run_sebi_crawler.py --mode discover --lookback-hours 6
```

The 23:00 sweep catches post-market filings that come in after the
last `*/30` slot of the day.

First-deploy backfill: run once with `--lookback-hours 8760` (one
year) on a single host with rate-limiting tuned conservatively.

## Open implementation questions

1. **NSE anti-bot.** Cloudflare interactive challenge fires from
   datacentre IPs. Options: (a) residential proxy pool (Bright Data
   ~$5/GB), (b) request data-feed partnership with NSE, (c) lean on
   BSE for NSE-only-listed tickers (rare). Pick (a) for short-term;
   target (b) by Q3FY26.
2. **XBRL parser extension.** The IGAAP / Ind-AS / Ind-AS-2020 mapping
   in `data_pipeline/sources/nse_xbrl_fundamentals.py` covers the
   canonical line items used by the FV model. New filings sometimes
   expose segment data we don't yet capture — extend tag list as the
   cron uncovers gaps; do NOT block ingest on a missing optional tag.
3. **PDF-only filings.** Smaller microcaps file PDFs (no XBRL). Two
   options: (a) LLM extractor (OCR for image PDFs, text-extract for
   modern PDFs, then prompt structured-output to JSON), (b) skip and
   accept gap. Recommendation: skip in Phase 1, LLM in Phase 3.
4. **Cache invalidation strategy.** Two choices:
   - Bump global `CACHE_VERSION` — heavy, retriggers FV for every
     ticker. Forbidden by the v3 discipline rules without a canary
     diff.
   - Invalidate just the affected ticker's `analysis_cache` row —
     surgical and correct. **Use this.** Add an
     `analysis_cache_service.invalidate_ticker(symbol)` helper as part
     of the Phase 1 follow-up.
5. **Alert noise.** A filing detected at midnight should not page
   anyone. Default policy: queue notifications but defer dispatch to
   the 07:30 IST mail run. Exception: filing implies a > X% earnings
   surprise vs prior consensus → real-time push (X TBD by product).
6. **Backfill on first deploy.** Run discover with
   `--lookback-hours 8760` once, accepting ~30 min of NSE pressure
   and the certainty of partial data. Alternative: accept the gap
   (only forward filings get tracked). Recommendation: backfill, but
   gate behind `--dry-run` first to estimate volume.

## Frontend integration sketch

Per-stock page header:

> Last filing: 2026-04-22 — Q4FY25 results [View filing]

Backed by a new endpoint
`/api/v1/stocks/<ticker>/last_filing` that selects from
`sebi_filings_queue` where status='ingested' order by filing_date
desc limit 1.

A small toast on first page-view after a watchlisted ticker files:
"INFY filed Q4FY25 results 3h ago — FV updated."

## Follow-up phases

| Phase | Scope                                                      | Est  |
|------:|------------------------------------------------------------|------|
| 1     | Real BSE crawler — full discover + download + parse        | 3 d  |
| 2     | NSE crawler with residential-proxy + cookie rotation       | 4 d  |
| 3     | PDF→LLM extraction for non-XBRL filers                     | 5 d  |
| 4     | Wire `filing_alert_service.notify_users_of_new_quarterly`  | 2 d  |
|       | into the live notifications pipeline (off `dry_run`).      |      |
| 5     | Frontend last-filing badge + toast                         | 2 d  |

Total: ~16 dev-days. Phase 1 + 2 are the bulk of the value; Phase 3
is a long tail; Phases 4 & 5 are wiring once the data is reliable.

## Discipline notes

* The crawler must NOT bump `CACHE_VERSION`. See the v3 discipline
  rules in `memory/feedback_yieldiq_discipline.md`.
* Long ingest jobs run on the GH Actions matrix, not the Railway
  worker. The Railway cron only kicks discover/process; the heavy
  parse loop sits in `scripts/`.
* `process_pending` must remain idempotent — a re-run on the same
  row should be a no-op (status already advanced).
