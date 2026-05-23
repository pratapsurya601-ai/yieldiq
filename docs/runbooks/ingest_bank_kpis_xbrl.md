# Runbook: Bank-KPI XBRL ingest (Phase I-ingest-a)

**Script:** `scripts/ingest_bank_kpis_from_xbrl.py`
**Target table:** `bank_operational_kpis` (migration 061)
**Source provider:** `data_pipeline/sources/bse_bank_xbrl.py`
**Universe:** `PURE_BANK_TICKERS_FOR_DE` (38 commercial banks)
**Cost:** zero LLM spend — XBRL is free.

## When to run

After:
- migration 061 is applied on the target Postgres, AND
- a real BSE XBRL schedule provider has been wired into
  `data_pipeline.sources.bse_bank_xbrl` (see "Wiring a provider"
  below). The default provider returns no rows and the pre-flight
  gate will refuse to proceed until a real provider is registered.

## Pre-flight gate

The script samples HDFCBANK, SBIN, AXISBANK and requires:

- at least 4 of 6 KPI fields populated on at least one quarterly
  row, for at least 2 of the 3 tickers.

If the gate fails, the script exits 2 and writes nothing. This is
deliberately stricter than the AR-extractor pre-flight (Phase H)
because the XBRL path is supposed to be deterministic — sparse
output usually means the tag map is wrong, not that filings are
missing.

## Standard invocations

```bash
# Local dry-run — exercises pre-flight and prints what would be written.
python scripts/ingest_bank_kpis_from_xbrl.py --dry-run

# 3-ticker pre-flight sample for sanity-checking the provider.
python scripts/ingest_bank_kpis_from_xbrl.py \
    --tickers HDFCBANK,SBIN,AXISBANK --dry-run

# Full 38-ticker, 20-quarter (5y) backfill, real writes.
python scripts/ingest_bank_kpis_from_xbrl.py --quarters 20

# Resume after a transient failure on, say, KOTAKBANK.
python scripts/ingest_bank_kpis_from_xbrl.py --resume-from KOTAKBANK
```

## Operator-triggered run

Use the GitHub Actions workflow
`.github/workflows/bank-kpi-backfill.yml` (Phase I-operator-workflow):
inputs `phase=xbrl`, `top_n_banks=38`, `dry_run=true` for the first
operator-facing trial, then re-run with `dry_run=false`.

## Wiring a provider

The default provider in `bse_bank_xbrl.py` is a no-op. To wire a
real BSE XBRL schedule parser without touching the CLI or the
persistence layer:

```python
from data_pipeline.sources import bse_bank_xbrl

def my_provider(ticker: str, n_quarters: int):
    # Fetch the BSE corporate-filing list for the bank, locate
    # the quarterly XBRL submissions, parse Schedule V / XVIII
    # for the six fields below, and return one
    # ParsedBankKpiRow per quarter (oldest -> newest).
    return [...]

bse_bank_xbrl.register_provider(my_provider)
```

See `bse_bank_xbrl._KPI_TAG_CANDIDATES` for the starting set of
XBRL element-tag candidates; the provider author must verify the
actual tag names against live filings before relying on them.

`ParsedBankKpiRow` fields:

| Field | Source | Notes |
|---|---|---|
| `gnpa_pct` | BSE XBRL Schedule XVIII (Asset Classification) | percent 0-100 |
| `nnpa_pct` | BSE XBRL Schedule XVIII | percent 0-100 |
| `pcr_pct`  | BSE XBRL Schedule XVIII | percent 0-100 |
| `casa_pct` | BSE XBRL Schedule V (Deposits) | percent 0-100; computable from current+savings/total_deposits |
| `cost_to_income_pct` | BSE XBRL Form A / Schedule B | percent 0-100; derivable from operating_expense / (interest_earned + non_interest_income) |
| `credit_deposit_pct` | BSE XBRL Schedule V + VII | percent 0-100; advances / deposits |

Use the `as_percent()` normaliser in the provider so the
decimal-vs-percent heuristic and the >100 / <0 guards apply
uniformly. The audit-trail field `raw_tag_hits` is optional but
strongly encouraged — it lets the operator inspect which XBRL
tags resolved per row when something looks wrong.

## Validation SQL (post-run)

```sql
-- Per-ticker coverage of the six XBRL KPIs (latest quarter).
SELECT
    ticker,
    period_end,
    (gnpa_pct IS NOT NULL)::int
        + (nnpa_pct IS NOT NULL)::int
        + (pcr_pct IS NOT NULL)::int
        + (casa_pct IS NOT NULL)::int
        + (cost_to_income_pct IS NOT NULL)::int
        + (credit_deposit_pct IS NOT NULL)::int AS fields_populated
  FROM bank_operational_kpis
 WHERE source = 'bse_xbrl'
   AND period_type = 'quarterly'
   AND period_end = (
       SELECT MAX(period_end) FROM bank_operational_kpis
        WHERE source = 'bse_xbrl' AND period_type = 'quarterly'
   )
 ORDER BY fields_populated DESC, ticker;
```

## Rollback

```sql
-- Delete rows from this source only; the AR-sourced rows
-- (source='ar_anthropic') are untouched.
DELETE FROM bank_operational_kpis WHERE source = 'bse_xbrl';
```

Or, to clear the whole table while keeping the schema:

```sql
TRUNCATE bank_operational_kpis;
```

## Failure modes

| Failure | Likely cause | Fix |
|---|---|---|
| `PRE-FLIGHT FAILED: default no-op provider active` | No real provider wired | Register one (see "Wiring a provider") |
| `pre-flight: HDFCBANK -> 0 rows` | Provider can't reach BSE / wrong base URL | Check provider network config |
| `pre-flight: ... best row has 2/6 fields` | Tag-name map is incomplete or wrong | Expand `_KPI_TAG_CANDIDATES` after inspecting live XBRL |
| `dropping out-of-range gnpa_pct=245` warnings | Provider returned raw value not normalised | Always run values through `as_percent()` |
| All UPSERTs no-op (rows present but no diff) | ON CONFLICT COALESCE preserved old values | Expected when re-running the same revision; bump source name or DELETE first to force overwrite |

## Discipline checklist

- [ ] Migration 061 applied.
- [ ] Pre-flight passed (don't `--skip-preflight` without a clear reason).
- [ ] Dry-run inspected before live run.
- [ ] No CACHE_VERSION bump (this is a write-side change to a
      table the frontend doesn't yet expose; the I-frontend PR
      handles cache invalidation via the manifest entry).
- [ ] Banned-vocab discipline N/A on this path — XBRL values are
      pure numerics with no free-text leaves.
