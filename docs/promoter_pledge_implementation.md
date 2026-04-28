# Promoter pledge tracking — implementation

Companion to `docs/promoter_pledge_tracking_design.md`. The design doc
covers the *what* and *why*; this doc captures the *how* now that real
scrapers + alert pipeline + frontend integration have shipped.

## What landed in this PR

| Layer | File | Status |
|---|---|---|
| BSE HTML scraper | `backend/services/promoter_pledge_service.py::fetch_from_bse` | Real — cookie-primed, 2-attempt retry, per-table heuristic parser |
| NSE JSON scraper | `backend/services/promoter_pledge_service.py::fetch_from_nse_bulk` | Real — single-call batch, primed via landing page |
| Daily ingest | `scripts/ingest_pledges.py --apply` | Real — BSE per-ticker (1 req/sec), NSE bulk fallback, idempotent UPSERT |
| GH Actions cron | `.github/workflows/promoter_pledge_daily.yml` | Daily 09:00 IST (03:30 UTC) Mon–Fri |
| Alert pipeline | `backend/services/promoter_pledge_service.py::detect_pledge_jumps` | Real — > 5pp triggers `alert_fired` notification, 7-day idempotency |
| Public API | `GET /api/v1/public/promoter-pledge/{ticker}` | Real — additive endpoint, 1h CDN cache, no auth |
| Frontend panel | `frontend/src/components/analysis/PromoterPledgePanel.tsx` | Real — 24m sparkline, badges, source link |
| Tests | `tests/test_pledge_scraper_bse.py`, `tests/test_pledge_alert.py` | 9 new tests, all passing offline |

## Source URL strategy

BSE first (per-ticker scrape), NSE bulk fallback. Both sources are
public, no API key required.

```
BSE:  https://www.bseindia.com/corporates/sastpledge.aspx?scripcode={code}
NSE:  https://www.nseindia.com/api/corporates-pledgedata?index=equities
      (cookie-prime via https://www.nseindia.com/companies-listing/corporate-filings-pledged-data)
```

BSE is preferred because it's per-ticker filterable and gives
historical depth in one page; NSE returns a recent rolling window
across all symbols, which is great for cron freshness but less useful
for backfill.

## Cookie-prime pattern

We follow the exact `requests.Session()` + landing-page priming
pattern proven in `backend/services/sebi_sast_service.py` and
`backend/services/bse_shareholding_service.py`:

```python
session = requests.Session()
session.get(_NSE_HOME, headers=_HEADERS_NSE, timeout=15)
session.get(_NSE_PLEDGE_LANDING, headers=_HEADERS_NSE, timeout=15)
resp = session.get(_NSE_PLEDGE_API, headers=_HEADERS_NSE, timeout=30)
```

Without the prime, NSE returns 401 / empty. BSE is more permissive
but a `Referer: bseindia.com` and a Mozilla UA still help avoid
sporadic 503s.

## Refresh cadence + capacity

- **Cron:** Mon–Fri 09:00 IST.
- **Capacity:** BSE per-ticker × 1 req/sec × default `--limit 200`
  ≈ 3 min wall time. NSE bulk: 1 call, ~5 s.
- **Retry envelope:** 2 attempts, exponential backoff (2s, 4s) on
  403 / 429 / 5xx.
- **Idempotency:** `UNIQUE(ticker, as_of_date)` + `ON CONFLICT DO
  UPDATE` means re-runs in the same day are safe.

## Anti-bot — production note

BSE and NSE rate-limit aggressively from non-Indian IPs.
GitHub-hosted runners egress from US data centers; in practice we
expect partial success (BSE is more forgiving than NSE) and need a
fallback path. Options in priority order:

1. **Self-hosted runner** in an AWS Mumbai (`ap-south-1`) instance
   that we can also reuse for the SEBI SAST cron.
2. **Residential proxy** (e.g. BrightData India) routed via the
   existing `requests.Session()`. ~$50/month for 5GB.
3. **Railway egress IP allowlist** — if we move the cron from GH
   Actions to Railway, we can request NSE allowlist Railway's static
   egress (long shot, but free).

The cron's coverage-summary step emits a `::warning::` if no fresh
rows landed in 24h, which is the trigger to switch to option 1 or 2.

## Alert threshold rationale

Threshold = **5 percentage points** over a 90-day rolling window.

This matches the SEBI (SAST) Reg. 31(1) materiality threshold:
acquirers / promoters must publish a fresh disclosure when their
encumbrance changes by ≥ 5pp. Our trigger is therefore
**event-driven** by construction — every alert maps to a real
regulatory filing, not a synthetic threshold we picked.

7-day per-(user,ticker) idempotency on `notifications.metadata->>
'kind' = 'promoter_pledge_jump'` so a re-running cron after a flake
doesn't double-notify.

## Frontend integration

`PromoterPledgePanel` is a self-fetching client component (the data
is rarely needed and isn't on `AnalysisResponse`, so we deliberately
keep it lazy and additive — no `StockSummary` schema change, no
`CACHE_VERSION` bump). Wired into `AnalysisBody.tsx` under the
"Quality" tab, immediately after `QualityRatios` and before
`RedFlagInsights`. Layout:

- Big number: current `pledged_pct`.
- Below: 24-month sparkline (red stroke when latest > 30%).
- Right: `HIGH PLEDGE` badge (> 30%), `RECENT CHANGE` badge (> 5pp
  in 90d).
- Footer: last-updated date + link to BSE/NSE source filing.

When `pledged_pct = null` (the common case for clean promoter
groups), the panel renders a single muted line: "No promoter-pledge
disclosure on file." It never errors loudly.

## Initial backfill

`BACKFILL_LIST` in `scripts/ingest_pledges.py` curates 50
historically-relevant tickers (RCOM, ZEEL, JINDALSTEL, ADANIENT,
ADANIPORTS, GMRINFRA, SUZLON, JPASSOCIAT, SREINFRA, RELCAPITAL, …).
Run once on prod to seed the panel with real data:

```bash
python scripts/ingest_pledges.py --source bse --tickers-from backfill_list
```

This worktree does not have `.env.local` configured, so the prod
backfill is intended to run from the GH Actions `workflow_dispatch`
or from the operator's machine with the Aiven `DATABASE_URL`. The
fixture-based seed (9 rows for RCOM / JINDALSTEL / RELIANCE /
TATASTEEL / ADANIENT) is sufficient to render the panel for those
five tickers immediately.

## Cache discipline

- Endpoint cache key: `public:promoter-pledge:{TICKER}`,
  `version_keyed=False` (the data isn't a function of the analysis
  pipeline, so it's stable across `CACHE_VERSION` bumps).
- 1h CDN `s_maxage`, 2h SWR — pledge filings are infrequent, this is
  comfortable.
- No `CACHE_VERSION` bump required — surface is purely additive.
