# Annual Report (AR) Integration Plan

Owner: YieldIQ data team
Status: Phase 1 (this PR) — schema + service stubs + tests only.
Author: 2026-05-16

---

## TL;DR

Annual Reports are an **augmentation layer** on top of YieldIQ's existing
data, not a replacement. We parse them once a year per company with
Claude Sonnet, write the structured output into `company_annual_reports`,
and the analysis pipeline reads from there for things existing sources
do badly — segment data, capex commitments, auditor flags, contingent
liabilities, related-party transactions, MD&A summaries.

This PR is **scaffold only**. No PDFs are downloaded, no Claude calls
are made, no analysis paths consume the new table yet. The user reviews
this design before we spend on the PDF parsing infrastructure.

---

## Why augment, not replace

ARs are uniquely good at:

| Signal                       | Existing source                       | AR fills the gap                                          |
|------------------------------|---------------------------------------|-----------------------------------------------------------|
| Segment revenue / EBITDA     | None reliably at granularity          | Fixes conglomerate DCF (RELIANCE, ITC, ZOMATO)            |
| Forward capex commitments    | Concall (sometimes), guesswork        | MD&A is the authoritative forward-looking source          |
| Auditor going-concern flags  | None                                  | Earliest formal warning of distress                       |
| Contingent liabilities       | Partial in screener                   | Full schedule with disputes, amounts, status              |
| Related-party transactions   | Migration 017 captures filings index  | AR gives the *full* annual schedule with amounts          |
| MD&A narrative               | Concall TL;DR                         | Written, board-approved narrative — different artefact    |

ARs **cannot** replace:

* Daily prices → NSE bhavcopy
* Quarterly results → separate quarterly filings pipeline
* Live corporate actions (splits, dividends, bonus) → BSE / NSE feeds
* Insider trading → SEBI insider filings (migration 023)

The augmentation framing is important because it bounds the cost — we
don't need to reprocess ARs daily or even weekly. One pass per company
per year (plus a re-pass when an AR is republished with errata) is
enough.

---

## Three-phase rollout

### Phase 1 — schema + stubs + plan (THIS PR)

Creates:

* `data_pipeline/migrations/027_company_annual_reports.sql` — table with
  metadata columns + 5 JSONB columns for the extracted payload + a
  text column for `mda_summary` + `extractor_version` for re-runs.
* `backend/services/annual_report_service.py` — discover / download /
  extract stubs that raise `NotImplementedError` unless explicitly
  wired (so misconfigured code paths never hit a live API by accident).
  `save_ar_data` and `get_ar_for_ticker` are real and exercised by
  the tests.
* `backend/tests/test_annual_report_service.py` — verifies the stubs
  refuse to run, the save-path validates the schema, the read-path
  returns None cleanly without a DB.
* `tests/fixtures/sample_ar_zomato_fy24.json` — invented example of
  what the Claude Sonnet extractor would produce for ZOMATO FY24.
  Locks the JSON shape contract between the Phase-2 extractor and
  Phase-3 analysis consumers.

Does **not** add `anthropic` to `requirements.txt`, does **not** modify
the analysis service. CACHE_VERSION is not bumped — no scoring change.

### Phase 2 — wire the extractor (NEXT PR, only after user approves)

* Add `anthropic` to `requirements.txt` (pinned).
* Implement `discover_ar_url` against the BSE filings index (the AR
  attachment shows up under "Annual Reports" on the corporate
  announcements page) with NSE / company website as fallbacks.
* Implement `download_ar_pdf` with a real HTTP client, sensible UA,
  retry, size cap (~50 MB), and content-type check. Caller computes
  the sha256 for re-extraction detection.
* Implement `extract_ar_structured_data`:
  * System prompt embeds the schema documented at the top of
    `annual_report_service.py`.
  * Prompt caching enabled for the schema portion (saves ~$0.40 per
    extraction on Sonnet pricing).
  * Files API upload for the PDF (ARs are too big for inline).
  * Tool-use to force JSON output that matches the schema.
* CI: a small test extracts a known small PDF (a dummy AR shipped in
  `tests/fixtures/`) and asserts the resulting shape, but skips if
  `ANTHROPIC_API_KEY` is unset (so CI doesn't pay per run).

### Phase 3 — backfill + wire into analysis

* Worker job (Railway, off-hours): backfill top 200 tickers by
  market cap. Cost: ~$120 one-time (see below).
* Nightly job: re-check the BSE filings index for new ARs.
* `analysis_service` reads `get_ar_for_ticker(t)` and:
  * Surfaces a "Segment view" panel for tickers with >=2 segments.
  * Uses segment EBITDA in conglomerate DCF (RELIANCE, ITC, ZOMATO,
    L&T) so the bull/bear case isn't blended into a single rate.
  * Feeds auditor flags into the risk pillar (red flag → cap on
    quality score).
  * Feeds contingent liabilities >5% of equity into the risk pillar.
  * Feeds related-party transactions into the governance score.
* Canary diff is required for Phase 3 (analysis paths change). Phase 1
  and Phase 2 don't change scoring so canary doesn't gate them.

---

## Cost estimates (Sonnet pricing, May 2026)

Per AR extraction, assuming a 200-page PDF (~600 KB of text after
parsing, ~150K input tokens, ~3K output tokens) with prompt caching
on the system prompt:

* Input (uncached): ~150K * $3/Mtok = $0.45
* Output: ~3K * $15/Mtok = $0.045
* Cached schema (~5K tokens at 10%): negligible
* **Per-AR cost: ~$0.50**

| Scope                          | Tickers | One-time | Annual recurring |
|--------------------------------|---------|----------|------------------|
| Realistic (top 200 by mcap)    | 200     | $100     | $100 / year      |
| Aggressive (top 500)           | 500     | $250     | $250 / year      |
| Full coverage (all NSE ~5000)  | 5000    | $2,500   | $2,500 / year    |

The user's earlier $15K / $3K figures assumed a more expensive model
and ~3x input tokens (no prompt caching). With Sonnet + caching, the
realistic top-200 scope is roughly **$120 one-time, $24/year** when you
factor in re-extractions for republished ARs (~20% rate).

Recommendation: start with top 50 (sanity check the extractor) → top
200 (real coverage) → expand only if user demand justifies.

---

## What stays proprietary, what could be open-sourced

* **Proprietary:** the extractor prompt + schema, the analysis-side
  integration (how segment data feeds the conglomerate DCF, the
  auditor-flag → risk-cap rule).
* **Open-sourcable (if we ever want to):** the BSE filings index
  scraper for discovering AR URLs. This is generic infrastructure
  and there is no moat in keeping it private.

---

## User decision points

Before Phase 2 ships:

1. **Which tickers to prioritize?** Default proposal: top 200 by market
   cap, biased toward conglomerates (RELIANCE, ITC, L&T, M&M, ZOMATO,
   ADANIENT) where the segment data has the highest analytical value.
2. **When to spend the PDF parsing budget?** $120 is small but it's a
   real spend. Recommend running it after Phase 2 lands and we've
   sanity-checked 3-5 extractions manually for hallucination rate.
3. **Re-extraction policy?** Default proposal: re-extract only when
   `ar_pdf_sha256` changes (i.e. the AR was republished). Don't
   re-extract on prompt changes unless we bump `extractor_version`
   and want to diff.
4. **Failure mode for hallucination?** If Claude returns numbers that
   don't tie to the printed financials, we need a sanity check. Cheap
   version: cross-check segment_revenue_sum vs total_revenue from the
   existing financials pipeline; flag if delta > 5%.

Open questions parked for later:

* Should we store the AR PDF bytes too (for audit replay)? Probably
  yes, in S3, but not in this scaffold PR.
* Do we want a UI affordance for users to upload an AR manually
  (source='manual') for tickers we don't backfill? Probably yes,
  Phase 3+.
