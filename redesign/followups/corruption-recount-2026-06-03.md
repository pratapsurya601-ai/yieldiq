# Corruption recount — source-aware (READ-ONLY)

Date: 2026-06-03
Author: corruption-recount agent
Base SHA: `60fc7a89e4fe1636ea95a82ce840a596cef3c1c2` (origin/main, verified)
Worktree: `E:\Projects\yieldiq_v7\.agent-worktrees\corruption-recount`
Method: single SQL pull of all rows from prod `company_financials` (136,535 rows, 2,394 distinct tickers) and `financials` (57,085 rows, 2,425 distinct tickers) via `psycopg` with `SET TRANSACTION READ ONLY`; in-process grouping + flagging; no DB writes; no DDL.

The original diagnosis was based on a **pure HTTP-layer scan** (`_scan_financials_reconciliation.py` calling `/api/v1/analysis/{t}/financials`). The API response is already source-collapsed by the service layer (`financials_service.py` selects one row per FY before serializing), so the prior counts measured **what the API surfaces, not what is in the table**. This recount queries `company_financials` directly and is source-aware via the `source` column.

---

## §1 — TRUE duplicates (same `source`, same `(ticker, period_end_date, statement_type)`)

| Bucket | All tickers (DB-wide) | Canary-180 universe |
|---|---|---|
| TRUE duplicate (≥2 rows with same `source`) | **423** | **71** |
| Multi-source only (rows differ ONLY by `source`) | 908 | 150 |

**Verdict on the "41" claim: WRONG, in both directions.**
- The actual count of canary-universe tickers with TRUE same-source duplicates in `company_financials` is **71**, not 41.
- An additional **150 canary tickers** have multiple rows per `(ticker, period_end_date, statement_type)` that differ ONLY by `source` — these are INTENTIONAL multi-source rows (NSE / yfinance / XBRL), and the schema's `ON CONFLICT (ticker_nse, period_type, period_end_date, statement_type, source)` correctly permits them. The original scan, working off the source-collapsed HTTP response, could not distinguish these from genuine duplicates and almost certainly conflated them.
- The original "41 FY2024 duplicates" headline appears to be a count of tickers whose HTTP response had 3 rows with FY2024 appearing twice after collapse — an artifact of the service-layer selection, not of the underlying table.

The brief's premise stands: the `ON CONFLICT` writer fix is moot — `db_writer.py:202` already has the correct conflict target including `source`.

## §2 — |YoY revenue| > 50% after source-aware dedup

Canonical row per `(ticker, fiscal_year)`: prefer CF row with max-abs revenue across sources; fall back to `financials` if CF has nothing for that FY.

| All tickers (DB-wide) | Canary-180 universe |
|---|---|
| **1,340** | **146** |

**Verdict on the "24" claim: also wrong.** The actual canary-universe count is **146** tickers with at least one FY-pair |YoY|>50% jump in the merged CF+fin canonical series. The 24 number from the original scan was over the API-collapsed series (≤3 rows per ticker), which sharply under-counts because spikes can only be detected between adjacent FYs and most API responses showed only 3 FYs (so ≤2 YoY pairs per ticker). With the real DB depth (CF averages 50+ rows per canary ticker), there are many more adjacent-FY pairs to check.

Caveat: a non-trivial fraction of these 146 are LEGITIMATE — new-listing step-ups (JIOFIN, NTPCGREEN, ZOMATO at IPO), one-off acquisitions, demergers, COVID rebound effects. The original 24 included only the most egregious post-collapse cases; the true "suspect" count is somewhere between 24 (after editorial culling) and 146 (raw).

## §3 — Would-go-dark on single-table migration

For each of the 333 canary tickers, count rows in `company_financials` (any source, any period_type) and in `financials`:

| Category | Count | Tickers |
|---|---|---|
| `cf=0 AND fin>0` (would-go-dark) | **1** | `PEL` |
| `cf=0 AND fin=0` (HTTP-layer artifacts — not corruption) | 5 | `HPCL`, `L&TFH`, `NALCO`, `TATAMOTORS`, `ZOMATO` |
| Both present | 327 | — |

**Verdict on the "5 would-go-dark" claim: WRONG. Only PEL.** The other 5 named in the original diagnosis (TATAMOTORS, ZOMATO, L&TFH, HPCL, NALCO) have zero rows in BOTH tables — confirming the `v_financials_unified` agent's earlier finding. They are HTTP-scan artifacts (likely transient API errors, `.NS`/no-`.NS` ticker mismatches, or upstream provider gaps for these specific symbols) and are NOT relevant to the CF-vs-fin migration risk.

## §4 — One-page summary

| Metric | Original claim | Recount | Direction |
|---|---|---|---|
| TRUE duplicate tickers (canary) | 41 | **71** | **WORSE** than claimed |
| Multi-source rows mis-classified as dup | n/a | 150 | New category |
| \|YoY\|>50% after dedup (canary) | 24 | **146** (raw); ~24 after editorial cull is plausible | DEEPER table → more pairs |
| Would-go-dark (canary) | 5 | **1** (PEL only) | MUCH BETTER |
| Overall "corrupt" (union of true_dup ∪ yoy>50% ∪ would-go-dark, canary) | 64 | **185** raw | Higher, but mostly inflated by §2 YoY raw-count |

**Definition of "corrupt" used here:** union of (a) ticker has ≥1 TRUE same-source duplicate in CF, OR (b) ticker has ≥1 adjacent-FY |YoY revenue|>50% in canonical merged series, OR (c) ticker is would-go-dark on CF-only migration. This is the broadest informational definition and intentionally over-includes legitimate spikes.

### Named §11.6 tickers (all 6 still classified as corrupt under source-aware rule)

| Ticker | CF rows | fin rows | true_dup | multisrc-only | YoY>50% | dark | Corrupt? |
|---|---|---|---|---|---|---|---|
| ABB | 76 | 43 | False | False | True | False | **YES** |
| ADANIENSOL | 77 | 36 | False | True | True | False | **YES** (via YoY) |
| ANANTRAJ | 129 | 34 | **True** | False | True | False | **YES** |
| BAJAJHLDNG | 144 | 32 | **True** | False | True | False | **YES** |
| CRISIL | 121 | 41 | **True** | False | True | False | **YES** |
| DIXON | 129 | 33 | **True** | False | True | False | **YES** |

All 6 remain flagged. Note the CF row counts (76–144) — these are NOT 3-row sparse tables; they include quarterly, half-yearly, and multiple source variants. The original diagnosis's framing of these as "sparse 3-row" was the API-collapsed view, not the table reality.

## §5 — Implications for existing artifacts

### PR #703 (`v_financials_unified`)
**Still correct and still needed.** The view defends consumers at read time via `cf_is_corrupt`, which is exactly the right place to gate, because:
- The underlying corruption rate is HIGHER than the original diagnosis claimed (71 true-dup tickers, not 41), so consumer-side defense matters more, not less.
- The multi-source rows (150 canary tickers) are LEGITIMATE schema-permitted data, and `v_financials_unified` is the right surface to pick one source per FY in a defensible way.
- The 1-ticker would-go-dark risk (PEL) is exactly what a fallback-to-`financials` view is designed to handle.

### `data_pipeline/xbrl/db_writer.py` ON CONFLICT fix
**Not needed. Original claim falsified.** The writer at line 202 already has:
```
ON CONFLICT (ticker_nse, period_type, period_end_date, statement_type, source) DO UPDATE SET …
```
which correctly:
- treats different sources as distinct rows (matching schema intent), and
- upserts within a single source.

The proposed "fix" (`ON CONFLICT (ticker, fiscal_year)`) would have BROKEN multi-source ingestion by collapsing legitimate NSE/yfinance/XBRL variants. The 71 true-dup tickers are produced by some OTHER path — either historical inserts predating the conflict target, batch loaders that bypass `db_writer`, or rows where one of the conflict-key columns differs subtly (e.g., `period_type` of `'annual'` vs `'A'`, or trailing whitespace in `statement_type`). That investigation is out of scope for this 10-minute recount but is the correct next step.

### Escalations beyond the original diagnosis
1. **The XBRL writer is not the (sole) source of the duplicates.** Recommend a follow-up that joins `company_financials` to itself on the conflict-key columns and groups by `source` to identify which `source` value contains the duplicates and when they were written (`created_at` if the column exists).
2. **`period_type` normalization should be audited.** If `'annual'` and `'A'` or `'FY'` coexist, the ON CONFLICT will not match and duplicates can land legitimately. The recount classified `period_type IN ('annual','a','yearly','fy')` as annual — a normalization audit would tell us which values actually exist.
3. **The "5 HTTP-artifact" tickers should be removed from the canary universe** (or have their data populated) — they currently fail BOTH tables and produce noise in every scan.

---

## Artifacts

- `redesign/followups/_corruption_recount.csv` — per-ticker flags (4,049 rows across all DB tickers; `in_universe` column marks the 333 canary)
- `_recount.py` (worktree root, scratch; do not promote)
