# Runbook: Phase I bank-KPI backfill (operator)

**Workflow:** `.github/workflows/bank-kpi-backfill.yml`
**Target table:** `bank_operational_kpis` (migration 061)
**Universe:** `PURE_BANK_TICKERS_FOR_DE` -- 38 commercial banks.

The workflow is `workflow_dispatch` only (no schedule). Open
GitHub Actions -> "Bank KPI Backfill (operator)" -> Run workflow,
then choose:

- **phase:** `xbrl` | `ar` | `all`
- **top_n_banks:** clamp on the AR phase's `--max-rows`; defaults
  to 38 (the full cohort). XBRL phase always walks the full
  cohort regardless.
- **cost_cap_usd:** hard-stop for the AR phase. Default 50 USD --
  enough for ~500 AR pages at the narrow bank-ops prompt (much
  cheaper than the Phase H full-AR extractor).
- **dry_run:** default true. Always run dry-first.
- **quarters:** XBRL history depth; default 20 (~5y).

## Workflow phases

### `xbrl` (free)

Drives `scripts/ingest_bank_kpis_from_xbrl.py` over the full
38-ticker cohort. Pre-flight samples HDFCBANK / SBIN / AXISBANK
and refuses to write unless at least 4 of 6 fields populate on
at least 2 of the 3 tickers.

**As of Phase I-ingest-a Block III the real `bse_xbrl_v1` provider
is auto-registered on import** of `data_pipeline.sources.bse_bank_xbrl`.
It walks the BSE corporate-filings page via the same Playwright +
real-Chrome session that `bse_quarterly_xbrl.py` uses (Akamai bot
wall workaround), downloads each `Main_Ind_As_<code>_*.xml`, and
runs `parse_bank_xbrl` on the bytes. Standalone filings are preferred
over consolidated for the same period (consolidated bank XBRL files
zero NPA values per RBI disclosure convention).

Coverage statement (parser v1):

| Field | Source in BSE quarterly XBRL | v1 coverage |
|---|---|---|
| `gnpa_pct` | `PercentageOfGrossNpa` (decimal-encoded) | filed |
| `nnpa_pct` | `PercentageOfNpa` (decimal-encoded) | filed |
| `pcr_pct` | DERIVED `(GrossNPA - NetNPA) / GrossNPA` | derived from filed absolutes |
| `casa_pct` | NOT DISCLOSED -- schema only carries aggregate `Deposits` | always `None` (documented gap; sourced from AR-Anthropic instead) |
| `cost_to_income_pct` | DERIVED `OperatingExpenses / (InterestEarned - InterestExpended + OtherIncome)` | derived |
| `credit_deposit_pct` | DERIVED `Advances / Deposits` (OneI instant context) | derived |

Expected per-row population on a clean standalone filing: 5 of 6
(CASA is the documented gap). Consolidated filings: 3 of 6 (NPA
fields zeroed by filer, CASA gap, but CD ratio and CIR still derive).

Environments without a desktop Chrome install (CI runners,
containerised one-shots) will see `bse_xbrl_v1: fetch failed for
<TICKER>: No module named 'playwright'` or a Playwright launch
error. The pre-flight gate trips cleanly in that case. Run the
provider from a workstation with real Chrome installed, the same
constraint that `bse_quarterly_xbrl.py` documents.

### XBRL phase MUST run on an Indian residential IP (workstation)

> **Operational caveat — 2026-05-24, task #168.**
>
> Even with Chromium installed (PR #605) and headed Chrome wrapped
> in `xvfb-run` (PR #606) so that `BSE XBRL client ready — Akamai
> cookies warmed` logs cleanly, **the BSE filings page returns
> zero parseable XBRL anchors when fetched from a GitHub Actions
> runner.** Repro: workflow run `26339597662` produced the canonical
> failure footprint:
>
> ```
> INFO BSE XBRL client ready — Akamai cookies warmed
> INFO pre-flight: HDFCBANK -> 0 rows, best row has 0/6 KPI fields
> INFO pre-flight: SBIN     -> 0 rows, best row has 0/6 KPI fields
> INFO pre-flight: AXISBANK -> 0 rows, best row has 0/6 KPI fields
> ERROR PRE-FLIGHT FAILED ...
> ```
>
> Root cause: Akamai Bot Manager fingerprints the data-center egress
> ASN (GitHub Actions hosted runners terminate in Azure regions such
> as `northcentralus`). The challenge page is served instead of the
> SPA, so `_XBRL_HREF_RE` finds no `Main_Ind_As_<code>_*.xml` links
> and `list_quarterly_xbrl_urls` returns `[]`. The warmup log line is
> printed unconditionally after the warmup loop and does NOT
> indicate that Akamai actually accepted the session — verified by
> reading `data_pipeline/sources/bse_quarterly_xbrl.py` lines 187-200.
>
> This is consistent with the module docstring's original warning
> (`bse_quarterly_xbrl.py` lines 62-67): *"this module will NOT work
> as-is in GH Actions `ubuntu-latest` headless ... the production
> assumption is local execution on a workstation with real Chrome."*
>
> **Supported execution model:**
>
> 1. `phase=xbrl` — run on the operator workstation
>    (`python scripts/ingest_bank_kpis_from_xbrl.py --tickers all-banks
>    --quarters 20`) against the production `DATABASE_URL`. The
>    workstation needs: a real Indian residential / ISP IP, Playwright,
>    and desktop Chrome installed. Total runtime ~20-25 min for the
>    full 38-ticker cohort.
> 2. `phase=ar`  — run from the GH Actions workflow (Anthropic-only,
>    no browser dependency, runs cleanly on Azure runners).
>
> The bank-kpi GH workflow's `xbrl` and `all` paths are left in
> place for parity with the other backfill workflows but they will
> always fail pre-flight on hosted runners until one of the following
> is in place:
>   - a self-hosted GH runner on an Indian residential / VPS IP, OR
>   - a Cloudflare Worker / lightweight reverse proxy on an Indian
>     PoP that forwards filings-page requests, OR
>   - a daily local `cron` / Task Scheduler entry on the operator
>     workstation that runs the XBRL phase and writes to Neon.
>
> No client-side fix to `bse_bank_xbrl.py` /
> `bse_quarterly_xbrl.py` can defeat IP-based blocking — additional
> warmup hops, header tweaks, or stealth patches do not change the
> egress ASN that Akamai filters on.

Populates these six fields with `source='bse_xbrl'`:

- `gnpa_pct`, `nnpa_pct`, `pcr_pct`
- `casa_pct` (always NULL -- schema gap), `cost_to_income_pct`, `credit_deposit_pct`

### `ar` (Anthropic-backed; cost-capped)

Drives `scripts/extract_bank_ops_from_ar.py` over the rows in
`company_annual_reports` whose ticker is in the cohort. Per-AR
spend ~$0.05-$0.10 with the narrow 800-token output cap; default
$30 cost cap permits ~300-600 ARs per run.

Populates these three operational fields with `source='ar_anthropic'`:

- `branches_total`, `branches_tier1`, `branches_tier2`, `branches_tier3`
- `atms_total`
- `customers_millions`

The pre-flight gate trips at >50% extraction failures in the first
5 rows (mirror of the Phase H AR-signals extractor).

### `all`

Runs `xbrl` then `ar` sequentially. Cleanest single-button option
once a real XBRL provider is wired -- one operator click fills
both halves of the table over the 38-bank cohort.

## Standard operator flows

### First-time smoke test

1. Inputs: `phase=xbrl`, `top_n_banks=38`, `dry_run=true`,
   `quarters=8`.
2. Expect: pre-flight FAIL diagnostic identifying the missing
   provider. No DB writes.
3. Wire a real provider, then re-run with `dry_run=false`.

### AR-only run (XBRL provider not yet wired)

1. Inputs: `phase=ar`, `top_n_banks=10` (start small),
   `cost_cap_usd=5`, `dry_run=true`.
2. Inspect dry-run log: confirm only bank tickers in the candidate
   list; spend estimate well under cap.
3. Re-run with `dry_run=false` and the same caps to populate the
   first ten banks' branches / ATMs / customers.

### Full backfill (both phases)

After XBRL provider is wired and a 3-bank sample run is clean:

1. Inputs: `phase=all`, `top_n_banks=38`, `cost_cap_usd=50`,
   `dry_run=false`, `quarters=20`.
2. Expected runtime: 15-30 min for xbrl (free), 30-60 min for ar
   (cost-bounded).
3. Validate with the SQL below.

## Validation SQL

```sql
-- Coverage matrix across the 38-ticker cohort -- which banks have
-- which subset of the nine KPI columns populated for their most
-- recent annual row?
WITH latest AS (
    SELECT DISTINCT ON (ticker)
        ticker,
        period_end,
        branches_total IS NOT NULL AS has_branches,
        atms_total     IS NOT NULL AS has_atms,
        customers_millions IS NOT NULL AS has_customers,
        gnpa_pct       IS NOT NULL AS has_gnpa,
        nnpa_pct       IS NOT NULL AS has_nnpa,
        pcr_pct        IS NOT NULL AS has_pcr,
        casa_pct       IS NOT NULL AS has_casa,
        cost_to_income_pct  IS NOT NULL AS has_c2i,
        credit_deposit_pct  IS NOT NULL AS has_c2d
      FROM bank_operational_kpis
     WHERE period_type IN ('annual', 'quarterly')
     ORDER BY ticker, period_end DESC
)
SELECT ticker, period_end,
       has_branches, has_atms, has_customers,
       has_gnpa, has_nnpa, has_pcr,
       has_casa, has_c2i, has_c2d
  FROM latest
 ORDER BY ticker;
```

```sql
-- Source-of-truth split: which path filled how many rows in the
-- last 30 days?
SELECT source, COUNT(*) AS rows_inserted,
       COUNT(DISTINCT ticker) AS distinct_banks
  FROM bank_operational_kpis
 WHERE extracted_at >= now() - INTERVAL '30 days'
 GROUP BY source
 ORDER BY rows_inserted DESC;
```

## Rollback

```sql
-- Drop everything from one source only (the other path's
-- contributions stay):
DELETE FROM bank_operational_kpis WHERE source = 'bse_xbrl';
DELETE FROM bank_operational_kpis WHERE source = 'ar_anthropic';

-- Or wipe the whole table (keeps the schema; safe re-run target):
TRUNCATE bank_operational_kpis;
```

After truncation the frontend `BankKpiPanel` will self-hide on
every bank ticker again -- the panel only renders when there's at
least one populated field or quarterly point in the response.

## Failure-mode table

| Failure | Likely cause | Fix |
|---|---|---|
| `PRE-FLIGHT FAILED: default no-op XBRL provider active` | Someone called `reset_to_default_provider()` or set `BSE_BANK_XBRL_NO_AUTOREGISTER=1`. | Drop the env var / restart the process; the real provider auto-registers on import. |
| `bse_xbrl_v1: fetch failed for <TICKER>: No module named 'playwright'` | Running on a CI runner / container without Playwright + real-Chrome installed. | Move execution to a workstation with desktop Chrome (same constraint as `bse_quarterly_xbrl.py`); see the dependencies section of that module's docstring. |
| `pre-flight: <TICKER> -> 0 rows, best row has 0/6 KPI fields` for all 3 pre-flight tickers, immediately after `Akamai cookies warmed` (no nav-fail / non-200 log line in between) | Akamai is serving the bot-challenge page to the data-center egress IP (e.g. GH Actions Azure runner). The XBRL anchor regex matches nothing in the challenge HTML. | Re-run the XBRL phase from an operator workstation on an Indian residential / ISP IP. See the "XBRL phase MUST run on an Indian residential IP" section above. No code change defeats IP-ASN filtering. |
| `bse_xbrl_v1: no BSE code for <TICKER>` | Ticker not in the hard-coded fallback map and `bse_securities_master.get_bse_code` returned None. | Add the BSE code to `_FALLBACK` in `data_pipeline/sources/bse_bank_xbrl.py` or load the securities master before running. |
| `pre-flight: best row has 2/6 KPI fields` | Tag-name map incomplete in provider | Expand `_KPI_TAG_CANDIDATES` after sampling live XBRL |
| `dropping out-of-range gnpa_pct=245` | Provider returned a raw / unnormalised value | Always pass values through `as_percent()` in the provider |
| `PRE-FLIGHT FAILED: 3/5 (60%) extraction failures` (ar phase) | AR PDF URLs are stale or pypdf can't parse | Inspect the failing `ar_id`s in `company_annual_reports`; consider re-ingesting AR URLs from NSE feed |
| `ANTHROPIC_API_KEY not set` | Repo secret missing | Add `ANTHROPIC_API_KEY` at repo level (Settings -> Secrets) |
| `COST CAP HIT` (ar phase) | Cumulative spend exceeded `cost_cap_usd` | Re-run with `--resume-from-id=<last_id>` or raise cap |
| `no resolvable period_end for ar_id=...` | LLM didn't extract a date and `fiscal_year` is NULL on the AR row | Backfill `fiscal_year` upstream, then re-run with `--resume-from-id` |
| Frontend panel doesn't show on /analysis/HDFCBANK after a successful run | Stale browser cache | Hard-reload; the manifest entry `v_phase_i_bank_kpis_2026_05_26` should drop the cached row, but the frontend `staleTime: 6h` may delay refetch |

## Discipline checklist

- [ ] Migration 061 applied to the target Postgres.
- [ ] XBRL provider registered (or `phase=ar` selected) -- otherwise
      pre-flight FAILS by design.
- [ ] First run was `dry_run=true`.
- [ ] AR phase: `cost_cap_usd` set deliberately, not left at
      a value high enough to drain the Anthropic budget.
- [ ] No CACHE_VERSION bump (the v_phase_i_bank_kpis manifest
      entry handles invalidation surgically).
- [ ] Validation SQL ran post-backfill.
