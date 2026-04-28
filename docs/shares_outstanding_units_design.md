# `shares_outstanding` units — design + remediation

**Status:** in flight (2026-04-27)
**Owner:** data team
**Branch:** `wkt/fund-b-shares-outstanding`
**Triggered by:** PR #136 (peer-cap agent) — discovered mixed units while
implementing the unit-free peer cap formulation.

---

## TL;DR

- `financials.shares_outstanding` is *supposed* to be in **lakhs** (per
  `data_pipeline/models.py:107` comment and the converter
  `_to_lakhs(...)` in `data_pipeline/sources/yfinance_supplement.py:682`).
- In practice, **a non-trivial fraction of rows are stored in crore**
  (or some other unit). E.g. observed:
  - TCS: `36180` — plausible as **lakh** (~3.6 B shares ≈ correct, real
    value is ~362 cr = 36,200 lakh)
  - EMAMILTD: `4365` — plausible as **lakh** (~436 M shares ≈ matches
    real ~43.6 cr = 4,365 lakh)
  - But other rows have values 100× off, suggesting some import path
    wrote crore-units into the lakh-typed column.
- Every consumer of `shares_outstanding` (DCF, peer caps, EPS-style
  ratios) silently produces a 100×-off answer for the wrong-unit half
  of the universe.
- `peer_cap_service` (PR #136) sidesteps this entirely by using a
  unit-free formulation; that's the right tactical fix but the data
  quality bug is real.

## Where the bug came from

The most likely insertion path:

1. `yfinance_supplement.fetch_and_store_yfinance` reads
   `ticker_obj.info["sharesOutstanding"]` — yfinance returns a **raw
   share count** (e.g. 3.62e9 for TCS).
2. `_to_lakhs(value)` divides by `1e5`, yielding lakhs. Correct.
3. Other ingest paths (XBRL backfill, BSE, manual imports) sometimes
   read shares already pre-scaled to crore in the source filing and
   write the crore-scaled number into the same column without
   re-scaling. The column is typed `Float` with no constraint, so the
   bad row is accepted.

The XBRL backfill scripts (`scripts/backfill_fundamentals_nse_xbrl.py`,
`scripts/backfill_fundamentals_10y_bse.py`) are the prime suspects for
the crore-scaled writes.

## Standard going forward

**Canonical unit: raw share count** (integer-valued float).

Reasons to switch from lakhs to raw:

1. The `marketCap`, `totalRevenue`, `freeCashflow`, `ebitda` API
   responses already return **raw rupees** (see `_cr_to_raw` /
   `_lakhs_to_raw` in `data_pipeline/pipeline.py`). Storing
   `shares_outstanding` as raw lets a future schema unify on a single
   "raw count" convention and removes the lakh→raw conversion at the
   API boundary.
2. The lakh storage caused the bug — any downstream consumer that
   forgets `*100_000` produces a 100×-off ratio. With raw, a
   single-shot sanity check (`> 1e6`) catches every wrong-unit row
   without requiring the consumer to know which unit.
3. Postgres `BIGINT` / `DOUBLE PRECISION` handles 1e10 without
   precision loss; no storage downside.

### Conversion table

| Source          | Stored value | Conversion to raw                       |
| --------------- | ------------ | --------------------------------------- |
| Raw count       | `N`          | `N`                                     |
| Lakhs           | `L`          | `L * 100_000` (i.e. `L * 1e5`)          |
| Crore           | `C`          | `C * 10_000_000` (i.e. `C * 1e7`)       |
| Thousands       | `K`          | `K * 1_000`                             |
| Millions        | `M`          | `M * 1_000_000`                         |

### Detection rule (used by audit + guards)

For an Indian listed company:

```
expected_market_cap_raw = current_price * raw_share_count
ratio = expected_market_cap_raw / (market_cap_cr * 1e7)
```

- `0.85 < ratio < 1.15` → unit is **raw** (canonical).
- `ratio ≈ 1/100` → stored value is in **lakh** (multiply by 1e5).
- `ratio ≈ 1/10_000` → stored value is in **crore** (multiply by 1e7).
- otherwise → unknown; flag for manual review.

## Migration plan

1. **Audit (this PR):** `scripts/audit_shares_outstanding_units.py`
   produces a CSV of `(ticker, period_end, stored_value, inferred_unit,
   suggested_raw)` tuples for every row in `financials`.
2. **Schema (this PR):**
   `data_pipeline/migrations/020_shares_outstanding_normalize.sql`
   adds a `shares_outstanding_raw` column (idempotent). The old
   `shares_outstanding` column stays in place during the transition so
   running services do not break.
3. **Backfill (ops, not in this PR):** ops runs
   `python scripts/normalize_shares_outstanding.py --apply` against
   prod (off-hours) — populates `shares_outstanding_raw` for every row
   the auditor can classify with confidence.
4. **Cutover (later PR):** consumers switch to read
   `shares_outstanding_raw`. Validation guards (added in this PR) keep
   the old column readable but log a warning every time a value
   `< 1_000_000` is observed (which would mean somebody wrote lakh into
   the raw column).
5. **Drop (later PR):** after one clean canary week, the lakh column
   is dropped.

## Validation guard pattern

Every consumer of `shares_outstanding_raw` that computes a ratio
should sanity-check the value before division:

```python
def _shares_or_warn(ticker: str, raw_shares: float | None) -> float | None:
    if raw_shares is None or raw_shares <= 0:
        return None
    if raw_shares < 1_000_000:
        logger.warning(
            "shares_outstanding_raw=%s for %s looks like lakh-units, "
            "skipping ratio computation",
            raw_shares, ticker,
        )
        return None
    return float(raw_shares)
```

Smallest plausible NSE-listed company has ~10 lakh shares
(1_000_000 raw). Anything below that is almost certainly a unit
error, not a tiny float.

## Why `peer_cap_service` does not need this

`peer_cap_service` (PR #136) computes peer-relative market cap caps
via:

```
cap_i / cap_peer = (price_i * shares_i) / (price_peer * shares_peer)
```

If `shares_i` and `shares_peer` are *consistently mis-scaled by the
same factor*, the ratio is unaffected. The service explicitly
documents this and does not consume `shares_outstanding` as an
absolute count. Future readers should not "fix" that service to use
the raw column — the unit-free formulation is intentional defensive
coding against exactly this class of bug.

## Files in this PR

- `scripts/audit_shares_outstanding_units.py` — read-only auditor.
- `scripts/normalize_shares_outstanding.py` — `--dry-run` default
  upserter.
- `data_pipeline/migrations/020_shares_outstanding_normalize.sql` —
  idempotent schema change.
- `tests/test_shares_outstanding_normalization.py` — synthetic
  fixture exercising the unit detector.
- `docs/shares_outstanding_units_design.md` — this doc.

## Files NOT in this PR

- `backend/services/peer_cap_service.py` — left untouched; see
  rationale above.
- No `CACHE_VERSION` bump; this is a backfill, not a formula change.
- No production migration — that's an ops step.
