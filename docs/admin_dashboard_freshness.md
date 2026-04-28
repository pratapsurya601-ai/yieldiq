# Admin: ratio_history freshness — quick SQL

Drop these into the Neon SQL editor any time you want a real-time
view of how stale `ratio_history` is. Read-only — safe to run on prod.

## How many tickers have stale rows right now?

```sql
WITH latest AS (
    SELECT DISTINCT ON (rh.ticker)
        rh.ticker,
        rh.period_end
    FROM ratio_history rh
    JOIN stocks s ON s.ticker = rh.ticker
    WHERE s.is_active = TRUE
    ORDER BY rh.ticker, rh.period_end DESC
)
SELECT
    COUNT(*) FILTER (WHERE (CURRENT_DATE - period_end) > 90) AS stale_n,
    COUNT(*) FILTER (WHERE (CURRENT_DATE - period_end) BETWEEN 30 AND 90) AS warming,
    COUNT(*) FILTER (WHERE (CURRENT_DATE - period_end) <= 30) AS fresh_n,
    COUNT(*) AS total_active_with_rows
FROM latest;
```

## Which sectors are most affected?

```sql
WITH latest AS (
    SELECT DISTINCT ON (rh.ticker)
        rh.ticker,
        rh.period_end,
        s.sector
    FROM ratio_history rh
    JOIN stocks s ON s.ticker = rh.ticker
    WHERE s.is_active = TRUE
    ORDER BY rh.ticker, rh.period_end DESC
)
SELECT
    sector,
    COUNT(*) AS total,
    COUNT(*) FILTER (WHERE (CURRENT_DATE - period_end) > 90) AS stale_n,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE (CURRENT_DATE - period_end) > 90)
        / NULLIF(COUNT(*), 0),
        1
    ) AS stale_pct
FROM latest
GROUP BY sector
ORDER BY stale_pct DESC NULLS LAST
LIMIT 20;
```

## Active tickers with NO ratio_history rows at all

```sql
SELECT s.ticker
FROM stocks s
LEFT JOIN ratio_history rh ON rh.ticker = s.ticker
WHERE s.is_active = TRUE AND rh.ticker IS NULL
ORDER BY s.ticker;
```

## Sub-1 P/E remnants (pre-#126 `_normalize_pct` artifact)

```sql
WITH latest AS (
    SELECT DISTINCT ON (ticker)
        ticker, period_end, pe_ratio
    FROM ratio_history
    ORDER BY ticker, period_end DESC
)
SELECT *
FROM latest
WHERE pe_ratio IS NOT NULL
  AND pe_ratio > 0
  AND pe_ratio < 1.0
ORDER BY pe_ratio ASC
LIMIT 50;
```

## Hyper-percent ROE/ROCE

```sql
WITH latest AS (
    SELECT DISTINCT ON (ticker)
        ticker, period_end, roe, roce
    FROM ratio_history
    ORDER BY ticker, period_end DESC
)
SELECT ticker, period_end, roe, roce
FROM latest
WHERE roe > 100 OR roce > 100
ORDER BY GREATEST(COALESCE(roe,0), COALESCE(roce,0)) DESC
LIMIT 50;
```

## When did the weekly cron last run?

```sql
-- Look at the most recent commit in docs/maintenance_history/ on main.
-- Or run from the shell:
--   git log --oneline -- docs/maintenance_history/ | head -5
```
