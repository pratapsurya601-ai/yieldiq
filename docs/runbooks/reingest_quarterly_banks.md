# Runbook: `scripts/reingest_quarterly_banks.py`

One-shot backfill of Schedule III Division I bank fields
(`interest_earned`, `interest_expended`, `other_income` =
non-interest income, `operating_expense`, `total_income`) on historical
quarterly rows of `company_financials`.

**Why this exists.** PR #747 (`fix(banks): operating_income derivation +
Schedule III Div I XBRL parser + free-tier 3y->5y cap`) added the
bank-format columns and taught `data_pipeline/xbrl/yf_fetcher.py` to
populate them when yfinance exposes the Schedule III Div I rows. The
nightly ingest fills these forward from the deploy date; this script
fills BACKWARD across already-ingested quarters that pre-date the deploy.

**When to run.** Once, after PR #747 ships. Not a cron job.

## Pre-flight

```bash
export DATABASE_URL=postgresql://...
python scripts/reingest_quarterly_banks.py \
    --since 2024-12-01 --until 2024-12-31 \
    --tickers HDFCBANK --dry-run --verbose
```

Expect one line per quarter showing `interest_earned`, `interest_expended`,
`non_interest_income`, `operating_expense`, `total_income`.

## Full backfill

```bash
python scripts/reingest_quarterly_banks.py --since 2023-01-01
```

Hits ~38 banks (the `PURE_BANK_TICKERS_FOR_DE` cohort), one yfinance
call per ticker, default sleep 1.5s between tickers. Roughly 1 minute
end-to-end.

## Resume after interruption

```bash
python scripts/reingest_quarterly_banks.py --since 2023-01-01 \
    --resume-from KOTAKBANK
```

Upserts are idempotent (`ON CONFLICT DO UPDATE`), so re-running
without `--resume-from` is also safe — it just wastes a few seconds
re-fetching tickers already processed.

## Visibility

Backfilled rows show up in the Financial Statements panel on
`/analysis/[ticker]` after the cache for that ticker invalidates. PR
#747 already shipped a manifest entry covering `operating_income` /
`ebit_margin` / `interest_coverage`; the operator may force-refresh
a specific ticker via the manifest if they don't want to wait.

## Flags

See `python scripts/reingest_quarterly_banks.py --help` for the
full list. Key ones:

| flag                 | default | purpose                                        |
| -------------------- | ------- | ---------------------------------------------- |
| `--since YYYY-MM-DD` | (req'd) | earliest `period_end` to backfill              |
| `--until YYYY-MM-DD` | today   | latest `period_end` to backfill                |
| `--tickers A,B,C`    | all 38  | restrict to a comma-separated list             |
| `--dry-run`          | off     | print, do not write                            |
| `--rate-limit-sec`   | 1.5     | sleep between yfinance ticker calls            |
| `--resume-from T`    | off     | skip tickers alphabetically before T           |
| `--verbose`          | off     | one log line per (ticker, period) before write |

## Tests

`backend/tests/test_reingest_quarterly_banks_script.py` covers
dry-run, idempotency, `--resume-from`, single-ticker failure
isolation, DATABASE_URL fail-fast, and window filtering.
