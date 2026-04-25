# Corporate-actions ticker alias registry

Config-driven map of renamed / demerged / delisted NSE listings, consulted by
both the ingest pipeline and the analysis read path. Designed so that an
Indian corporate action (demerger, rename, spin-off, delisting) never again
silently breaks ingest with 404 noise from Yahoo.

## Where it lives

| Layer | Path |
|---|---|
| Config (ops-editable) | `config/ticker_aliases.yaml` |
| Loader + resolver | `data_pipeline/ticker_aliases.py` |
| Ingest gate (XBRL fetch) | `data_pipeline/xbrl/yf_fetcher.py` |
| Ingest gate (supplement) | `data_pipeline/sources/yfinance_supplement.py` |
| Read-path gate | `backend/routers/analysis.py` (top of `get_analysis`) |
| DB migration | `scripts/migrate_ticker_aliases.sql` |
| Tests | `tests/test_ticker_aliases.py` |

## Schema

Each top-level key is an NSE symbol (uppercase). Fields:

```yaml
<NSE_SYMBOL>:
  status: active | renamed | demerged | demerged_pending | delisted
  effective_date: YYYY-MM-DD          # when the action took effect
  former_symbol: STR                  # (renamed) old NSE code
  fetch_symbol: STR                   # explicit Yahoo symbol override
  successors:                         # (demerged / demerged_pending / delisted)
    - ticker: STR
      share_ratio: FLOAT
      fetch_symbol: STR | null        # null when listing hasn't happened yet
  note: STR                           # citation / human context
```

### Status semantics

| Status | Ingest behavior | Read-path behavior |
|---|---|---|
| `active` | Fetch using `fetch_symbol` or default `.NS` | Normal analysis |
| `renamed` | Fetch using `fetch_symbol` | Normal analysis |
| `demerged` | Iterate successors (any with `fetch_symbol`) | Return redirect payload |
| `demerged_pending` | Skip silently (INFO log) | Return pending payload |
| `delisted` | Skip silently (INFO log) | Return terminal payload |

## Adding a new mapping

When NSE/BSE announces a corporate action, ops-only PR:

1. Add an entry to `config/ticker_aliases.yaml`. Include the `note` field
   citing the source (press release URL, NSE circular number, etc.).
2. If it's a rename affecting existing rows in `company_financials` or
   `financials`, extend `scripts/migrate_ticker_aliases.sql` with an
   analogous `UPDATE ... WHERE ticker = '<OLD>' AND NOT EXISTS (...)`
   block. The pattern is idempotent — re-running does nothing.
3. Run the dry-run first:
   ```
   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -v dryrun=1 \
        -f scripts/migrate_ticker_aliases.sql
   ```
4. Apply with `-v dryrun=0`.
5. Verify canary-diff before merging — `backend/routers/analysis.py` is
   one of the canary-enforced paths (see root `CLAUDE.md` §1).

## Read-path contract

For a ticker whose status is `demerged`, `demerged_pending`, or `delisted`,
the analysis endpoint returns **HTTP 200** with a payload that is *not*
`AnalysisResponse`. The frontend branches on the distinct top-level
`result_kind` discriminator:

```json
{
  "result_kind": "corporate_action_redirect",
  "status": "demerged_pending",
  "ticker": "TATAMOTORS",
  "successors": [
    {"ticker": "TMPV", "share_ratio": 1.0, "fetch_symbol": null},
    {"ticker": "TMCV", "share_ratio": 1.0, "fetch_symbol": null}
  ],
  "effective_date": "2026-03-01",
  "note": "..."
}
```

`AnalysisResponse` itself is unchanged — any existing field matcher in the
frontend keeps working. The new payload is a *sibling* shape distinguished
by `result_kind`.

## Degradation

The system is designed to fail open:

- **No config file** → loader returns `{}`, every ticker treated as active.
  You see a single INFO log line on boot.
- **Malformed YAML** → same, plus an ERROR log with the parse error.
- **PyYAML missing** → same, plus a WARNING.
- **Forgot to add a mapping** → ticker behaves exactly as before this
  system existed: the pipeline hits Yahoo, Yahoo 404s, the ticker's
  fundamentals row stays stale. The fix is to add the mapping, not to
  rewrite code.

## Testing discipline

- Unit tests live in `tests/test_ticker_aliases.py`. Each test writes a
  temporary YAML and sets `YIELDIQ_TICKER_ALIASES_PATH` so tests never
  depend on the checked-in config.
- The router read-path gate has an integration-shaped test that asserts
  the payload shape is stable — change that test deliberately if you
  change the frontend contract.
- Per root `CLAUDE.md` §1, any change touching `backend/routers/analysis.py`
  or `backend/services/` requires a green `python scripts/canary_diff.py`
  run BEFORE merge.

## Current entries (as of 2026-04-25)

| Ticker | Status | Note |
|---|---|---|
| `TATAMOTORS` | `demerged_pending` | Q1 2026 split into TM-PV / TM-CV; successor NSE symbols not yet listed |
| `LTIM` | `renamed` | Mindtree → LTIMindtree (2022-11-14) |
| `HDFC` | `delisted` | Merged into HDFC Bank (2023-07-13) |
| `VEDL` | `active` | 6-way demerger scheme pending NCLT; placeholder for future flip |
| `ETERNAL` | `renamed` | Zomato → Eternal (2024-11-20) |
