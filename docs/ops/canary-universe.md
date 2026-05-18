# Canary universe — maintenance guide

The canary universe is the stock list the merge-gate harness
(`scripts/canary_diff.py`) and the reconciliation gate
(`scripts/reconciliation_canary_gate.py`) sweep on every PR and on the
daily 08:00 IST cron. Bigger universe = more failure modes the harness
can catch.

## Files

| File                                  | Stocks | Schema | Default? | Status                          |
| ------------------------------------- | -----: | ------ | -------- | ------------------------------- |
| `scripts/canary_universe_180.json`    |    180 | v2     | yes      | Active                          |
| `scripts/canary_stocks_50.json`       |     50 | v1     | no       | Legacy — still readable         |

The harness auto-detects which schema it has been pointed at, so both
files stay valid. New work should target the v2 file.

## v2 schema

```jsonc
{
  "_meta": {
    "version": 2,
    "universe_version": "v2_180",
    "as_of": "2026-05-18",
    "buckets": { /* names -> human description */ },
    "fields": { /* metric -> unit doc */ },
    "review_cadence": "Quarterly"
  },
  "buckets": {
    "top100_diversified": [ /* tickers */ ],
    "banks": [ /* ... */ ],
    "psu_utilities": [ /* ... */ ],
    "cyclicals": [ /* ... */ ],
    "pharma": [ /* ... */ ]
  },
  "stocks": [
    {
      "symbol": "RELIANCE",
      "sector": "Conglomerate",
      "bucket": "top100_diversified",
      "mcap_tier": "large",
      "canary_bounds": { "roe": [0.07, 0.14], /* ... */ }
    },
    /* ... 179 more ... */
  ]
}
```

`canary_bounds` ranges are in DECIMAL form. The harness converts API
percent fields (roe, roce, mos) to decimal before comparing — see
`scripts/canary_diff.py::_to_decimal` and the unit-reconciliation block
above `_GATE4_PERCENT_FIELDS` for the authoritative mapping.

## Buckets

| Bucket                | Count | What it covers                                                    |
| --------------------- | ----: | ----------------------------------------------------------------- |
| `top100_diversified`  |   100 | Largecap diversified — IT, FMCG, Auto, Internet, NBFC, Insurance, |
|                       |       | Realty, Capital Goods, Retail, Consumer Durables                  |
| `banks`               |    20 | Private + PSU + small finance banks                               |
| `psu_utilities`       |    20 | Power, oil marketing, defence PSU, capital-goods PSU, railways    |
| `cyclicals`           |    20 | Metals, cement, realty (super-cyclicals)                          |
| `pharma`              |    20 | Pharma + healthcare (hospitals)                                   |

The buckets are designed so the reconciliation gate can scope a run to a
single sector when triaging a sector-specific regression (e.g. a pharma
FCF formula change).

## CLI

Run against the full 180 universe:
```bash
python scripts/canary_diff.py
```

Scope to one bucket (faster — useful for sector-specific PRs):
```bash
python scripts/canary_diff.py --bucket pharma
python scripts/canary_diff.py --bucket banks
python scripts/canary_diff.py --bucket cyclicals
python scripts/canary_diff.py --bucket psu_utilities
python scripts/canary_diff.py --bucket top100_diversified
```

Run against the legacy 50-stock file (rare — only for re-creating
historical baselines):
```bash
python scripts/canary_diff.py --stocks scripts/canary_stocks_50.json
```

## Fetch-failure budget

The fetch-failure budget scales at ~4% of universe size (rounded up,
floor 2):

| Universe size | Default budget |
| ------------- | -------------: |
|  20 (bucket)  |              2 |
|  50 (legacy)  |              2 |
| 180 (v2 full) |              7 |

Override with `CANARY_MAX_FETCH_FAILURES=N` to pin the budget regardless
of universe size.

Gate-violation thresholds remain ZERO — the canary is binary
(pass / fail). The budget is only for fetch-side flakes (Railway
cold-starts etc.), not for arithmetic / data-quality violations.

## Adding a ticker

1. Add an entry under `stocks` with `symbol`, `sector`, `bucket`,
   `mcap_tier`, and a complete `canary_bounds` dict. Null any bound
   the harness should skip (e.g. `debt_to_equity` on banks).
2. Append the symbol to the matching bucket list under `buckets`.
3. Run `python scripts/canary_diff.py --bucket <bucket>` to verify the
   new ticker doesn't blow gate 4 (canary_bounds) on production data.
   If it does, widen the bounds OR null them — bounds should be wide
   enough to absorb normal year-on-year drift but tight enough to catch
   unit bugs.
4. Run `pytest tests/test_canary_diff.py` + `python
   scripts/canary_gate_selftest.py` — both must pass.

## Removing a ticker

1. Delete the entry from `stocks`.
2. Delete the symbol from the matching bucket list under `buckets`.
3. If the ticker was a known-broken entry (e.g. a demerger successor
   with no live data), prefer adding it to `KNOWN_BROKEN_TICKERS` in
   `scripts/canary_diff.py` rather than removing it — that way it
   stays in the universe but is excluded from gate failures.

## Maintenance cadence

| Cadence  | Action                                                            |
| -------- | ----------------------------------------------------------------- |
| Quarterly | Review the universe. Replace tickers that have been delisted,    |
|          | demerged, or moved out of the relevant Nifty sub-index. Add 1-2   |
|          | rising mid-caps per bucket to keep coverage current.              |
| On rename | Update the symbol in BOTH `stocks` and the matching bucket list. |
| On reclass | Move the ticker between buckets (`stocks[*].bucket` +            |
|          | the two bucket lists) when its sector designation changes.        |

The quarterly review should produce a `universe_version` bump (`v2_180`
-> `v2_180_q3_26` etc.) and a refreshed `as_of` date — these are
captured in `_meta`. Keep historical universe files around (do not
delete `canary_stocks_50.json`) so old canary reports can be re-played
against the universe they were originally measured against.

## Bucket representation (review when bumping `as_of`)

As of the 2026-05-18 v2 launch, sector representation in the 180 universe
is:

| Bucket               | Share | Notes                                                      |
| -------------------- | ----: | ---------------------------------------------------------- |
| `top100_diversified` |   56% | Heavy on IT, FMCG, Auto — under-represents Realty (3) and  |
|                      |       | Aviation (1). Consider adding LODHA, BRIGADE, SPICEJET on  |
|                      |       | next review.                                               |
| `banks`              |   11% | Good private/PSU mix. Slight over-rep of tiny PSU banks    |
|                      |       | (CENTRALBK, IDBI) that may be reverse-merged.              |
| `psu_utilities`      |   11% | Defence (5/20) over-rep vs power (3/20). Acceptable for    |
|                      |       | now — defence is the most active scoring area.             |
| `cyclicals`          |   11% | Cement-heavy (8/20). Consider trimming to 6 cement + 2     |
|                      |       | more chemicals/sugar on next review.                       |
| `pharma`             |   11% | Good APIs + branded mix. Hospitals (APOLLOHOSP/MAXHEALTH)  |
|                      |       | are sector-adjacent but bucketed here for valuation        |
|                      |       | similarity (R&D opex / regulated pricing).                 |

When these proportions drift (e.g. via delisting), rebalance during the
quarterly review and bump `universe_version`.
