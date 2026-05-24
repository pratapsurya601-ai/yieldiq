# Phase F.3 — BSE Peercomp Akamai-block fallback runbook

**Status:** active as of 2026-05-24
**Owner:** data pipeline
**Related:** task #168 (bank XBRL Akamai block), `docs/runbooks/phase-f-backfill-runbook.md`

## Symptom

`scripts/backfill_financials_10y.py` aborts during pre-flight with:

```
pre-flight FAIL: BSE Peercomp endpoint is Akamai-blocked from this IP
(HTTP 302 → '/error_Bse.html'). See docs/runbooks/phase-f-bse-fallback.md
```

…or, with `--skip-peercomp-probe`, every ticker logs `0 rows from direct
API`, the browser fallback also returns 0 rows, and the run terminates
with `more than 50% of tickers returned 0 rows on direct API`.

Direct probe to confirm:

```
curl -sS -I -A "Mozilla/5.0" \
  "https://api.bseindia.com/BseIndiaAPI/api/Peercomp/w?scripcode=500180&type=P&annuallyquarterly=A"
```

A healthy response is HTTP 200 + JSON. An Akamai-block response is
HTTP 302 → `Location: /error_Bse.html`.

## Root cause

BSE's edge (Akamai) has tightened scrape detection across multiple
`api.bseindia.com/BseIndiaAPI/api/*` endpoints, including but not
limited to:

- `Peercomp/w` (Phase F.3 historical financials)
- the bank XBRL filing endpoints already documented in task #168

The block is **IP-range based**, not user-agent or cookie based. Both
the direct `requests` path AND the `playwright-stealth` browser
fallback (`bse_peercomp_browser.BSEBrowserClient`) fail with the same
302 from any IP that Akamai has classified as a datacentre / scraper
range. Cloud egress IPs (Railway, GitHub Actions, most VPS providers)
are blocked. Many residential ISPs in India are not.

**Do not try to defeat the Akamai block.** This was decided in
task #168 and re-confirmed 2026-05-24. The detection is well-funded
and the cat-and-mouse game is not worth the operator time.

## Workarounds (ranked by recommendation)

### 1. Skip Phase F.3 (recommended)

The 5-year financial depth already in the DB from previous BSE ingests
(`scripts/backfill_fundamentals_10y_bse.py`, run before the block
tightened) is sufficient for the current canary/top-500 use cases. The
extra 5 years that F.3 would add is nice-to-have, not load-bearing for
any FV calculation in the engine today.

Action: leave Phase F.3 unscheduled. Re-evaluate quarterly — Akamai
rules change.

### 2. yfinance fundamentals fallback

`yfinance` exposes annual + quarterly P&L / BS / CF via Yahoo Finance,
which has its own (less complete, less Indian-FY-aware) pipeline that
is NOT behind Akamai. Coverage is shallower (typically 4 annual
periods, not 10) and the field mapping differs from BSE Peercomp.

Cost: free. Limitation: depth, schema drift, occasional rate-limits.

If you go this route, add a `--source yfinance` flag to
`backfill_financials_10y.py` and a separate mapper in
`data_pipeline/sources/`. **Do not silently fall back** — the operator
should be explicit because the resulting rows have a different
provenance and quality.

### 3. EODHD (or equivalent) data subscription

`https://eodhd.com/` and similar vendors sell normalised 10-year+ NSE
+ BSE fundamentals via an HTTP API that is not behind Akamai. Costs
roughly USD 20-100/month depending on tier.

Pros: clean, deep, schema-stable. Cons: ongoing cost; new vendor
contract; another integration to maintain.

### 4. Residential proxy

Route the existing `requests` call through a residential proxy in
India (Bright Data, Smartproxy, Oxylabs). Costs roughly USD
50-300/month depending on volume.

Pros: no code changes beyond a `requests` proxies arg. Cons: ongoing
cost; legally grey for scraping; proxies get rotated/blocked too.

## Decision

**As of 2026-05-24: option 1 (skip Phase F.3).**

We accept the 5-year financial depth currently in the DB. Re-visit
when (a) Akamai rules loosen, (b) the engine grows a feature that
genuinely needs >5y of fundamentals on >100 tickers, or (c) we have
budget for option 3.

## How the pre-flight gate works

`scripts/backfill_financials_10y.py` now hits the Peercomp endpoint
for exactly ONE ticker (the first workable one in the resolved
universe) before processing the rest. The probe:

- uses `allow_redirects=False` so a 302 is observable rather than
  being silently followed to the HTML error page
- treats HTTP 302/non-200/non-JSON as "blocked" and exits with code 1
- logs the offending status code + `Location` header so the operator
  can confirm it's the Akamai pattern and not a transient outage

Override with `--skip-peercomp-probe` if you have a specific reason
to bypass it (e.g. you're running from a known-good IP and the probe
itself is flaking). Do not make this the default.
