# Weekly `ratio_history` maintenance — design notes

## Why this exists

The 2026-04-28 launch audit found that 9 tickers (JUSTDIAL, EMAMILTD,
NATCOPHARM, SANOFI, ZYDUSLIFE, MAYURUNIQ, HCLTECH, WIPRO, TECHM)
silently surfaced 60-91% MoS on the analysis page because peer-cap
read NULL/sub-1 P/E values from `ratio_history`. PR #126 fixed
`_normalize_pct` for new writes, but **old rows persist forever
without active maintenance**.

A tactical 9-ticker rebuild ran on 2026-04-28. This doc describes the
self-healing replacement: a weekly cron that audits the entire active
universe and rebuilds anything still flagged.

## Frequency: weekly (not daily, not monthly)

| Cadence | Pros | Cons |
|---|---|---|
| Daily | Always-fresh | Wastes Neon writes; collides with `ratio_history_daily.yml` builder | 
| **Weekly** | **Catches XBRL backfill drift quickly; cheap** | **None at this scale** |
| Monthly | Minimum cost | Up to 30 days of stale peer-cap inputs in production |

Weekly is the sweet spot — the daily builder
(`ratio_history_daily.yml`) keeps NEW filings flowing in; this weekly
maintenance script catches OLD rows that never got revisited.

## Maintenance window — Sundays 02:00 IST

Cron: `30 20 * * 6` (UTC) = 02:00 IST Sunday morning.

- Indian markets closed (NSE Sunday holiday).
- Asia open is 5+ hours away.
- US close is 4+ hours behind us.
- No competing scheduled jobs in this window
  (checked against `alerts_evaluator_hourly.yml`,
  `cache_warmup_top500.yml`, `parquet_export_nightly.yml`).

## Capacity

- ~3,000 active tickers (`stocks WHERE is_active=TRUE`).
- Throttle: `--rate 2` → 2 tickers/sec to avoid hammering Neon.
- ~10-20% expected to be flagged in any given week.
- Per-rebuild: ~0.5s (subprocess overhead) + builder runtime.
- **Estimated total runtime: ~25 minutes** for a full sweep when 100%
  of tickers need rebuild; realistic sweep with ~15% flag rate runs
  in 5-10 minutes.

`timeout-minutes: 90` in the workflow gives 3.5x buffer.

## Cost

- Neon Launch plan: writes are free up to plan limits.
- Workers/CI: GitHub Actions free-tier minutes. ~25min/week ×
  4 weeks = 100 min/mo, well under the public-repo allowance.

## Failure-mode playbook

1. **Cron run failed.** GH Actions auto-opens an issue (label:
   `ops, ratio-history, auto-opened`) with link + triage steps.
2. **<10% rebuilds failed.** Script exits 0; flagged in CSV;
   typically clears next week as XBRL data lands.
3. **>10% rebuilds failed.** Script exits 1 → issue auto-opened.
   Triage:
   - Check Neon connection + recent migrations.
   - Confirm `financials` table has rows for the ticker.
   - Re-run via `workflow_dispatch` with `apply=true`.
4. **Whole workflow disabled / forgotten for weeks.** The PR
   staleness check (`ratio_staleness_check.yml`) surfaces a
   warning on any PR touching `backend/services/` once
   >100 tickers are stale. Non-blocking but loud.

## First-run procedure

1. Wait until Monday morning IST (low traffic, full team available).
2. Open Actions → "Ratio History — Weekly Maintenance".
3. Click `Run workflow`. Inputs:
   - `apply`: `false` (dry-run for first run, just to see scope)
   - `limit`: `0`
   - `rate`: `2`
4. Inspect the `weekly_ratio_maintenance_*.csv` artifact.
5. If flagged count looks reasonable (<500), re-run with
   `apply: true`.
6. Confirm the post-run audit shows the flagged set shrinking;
   verify `docs/maintenance_history/ratio_history_<date>.csv`
   was committed by the bot.
7. Let the Sunday cron take over from then on.

## Extension hooks

- **Slack notification on failure**: add a `slack-action@v2` step
  in the failure branch. Out of scope for this PR.
- **Per-sector reports**: the SQL in
  `docs/admin_dashboard_freshness.md` can be extended with a
  GROUP BY `sector` join.
- **Rate auto-tuning**: if Neon p99 latency rises during the
  maintenance window, drop `--rate` to 1.

## Discipline reminders

- `--apply` is opt-in; default is dry-run.
- Never bumps CACHE_VERSION (this is a data-correctness fix at
  a layer below the cache).
- Never duplicates `rebuild_ratio_history.py` logic — shells out to it.
- Never runs the full 3000-ticker sweep as part of a PR.
