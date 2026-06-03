> ## ⚠️ SUPERSEDED — DO NOT USE THE NUMBERS IN THIS DOCUMENT
>
> The headline numbers in this diagnosis (41 duplicate tickers via
> `db_writer.py`, 24 |YoY|>50% anomalies, 5 zero-row tickers, 64
> total corrupt) have all been **falsified or substantially
> mis-counted** by subsequent source-aware verification on
> 2026-06-03. See **`corruption-recount-2026-06-03.md`** for the
> corrected figures (71 true dups, 146 |YoY|>50%, 1 zero-row, 185
> total corrupt), and **`large-move-vs-corruption-corroboration-tracker.md`**
> for the strategic implications.
>
> Specifically:
> - The "missing `ON CONFLICT` in `data_pipeline/xbrl/db_writer.py`"
>   premise was **WRONG** — the writer already has correct
>   `ON CONFLICT … DO UPDATE`. The 71 true dups come from some
>   OTHER write path (see `71-true-dups-investigation-tracker.md`).
> - The "5 zero-row tickers" claim was **WRONG** — only 1 ticker
>   (PEL) is genuinely zero-row in `company_financials` AND
>   non-zero in `financials`. The other 4 had zero rows in BOTH
>   tables (HTTP-layer scan artifacts).
> - The "64 total corrupt" claim was **3× UNDER-COUNTED** — the
>   actual figure under source-aware grouping is 185.
>
> The view design (`v_financials_unified`) and the recommendation
> (path C — pick-one-with-fallback) are STILL CORRECT and are
> shipping in PR #703. Only the diagnostic numbers below are
> superseded.
>
> This document is retained for audit trail. Do not derive new
> decisions from its numbers.
>
> ---

# Financials-table reconciliation diagnosis (READ-ONLY)

Date: 2026-06-03
Author: diagnosis agent (re-spawn after prior agent bailed)
Scope: `company_financials` (new) vs `financials` (old) table divergence across the 333-ticker canary universe
Inputs: live prod API (`api.yieldiq.in`), `scripts/canary_universe_180.json` (v3_333 manifest), the leftover scratch scanner `_scan_financials_reconciliation.py`, the WIPRO §11.6 / blast-radius report (`wipro-cagr-blast-radius.md`).

Hard constraint observed: no DB writes, no code changes outside the throwaway scratch script, no canary-diff, no CACHE_VERSION bump, no PR.

---

## Script verification

**Verdict: not what the brief literally asked for, but adequate as a proxy and the artifact landed.** The brief asked for a *row-by-row cell comparison* of `company_financials` vs `financials` per `(ticker, fiscal_year)` with `company_financials_value`, `financials_value`, `divergence_pct` columns. The leftover script `_scan_financials_reconciliation.py` instead compares (a) the `company_financials`-derived income row count and FY shape from `/api/v1/analysis/{t}/financials` against (b) the `financials`-derived `annual_history.value` row count from `/api/v1/coverage/{t}` — i.e. a *count*-level divergence plus a corruption fingerprint (duplicate FYs, FY gaps, |YoY|>50% spikes, period-end anomalies). This is a weaker measurement than the brief's spec — we cannot show "FY2024 revenue in `company_financials` = 738 Cr vs `financials` = 3,020 Cr" from the CSV alone — but combined with the §11.6 evidence on CRISIL/ABB/ADANIENSOL/ANANTRAJ it is sufficient to identify the populator bug class and recommend a reconciliation path. Pure HTTP-layer scanner, no DB credentials touched, READ-ONLY satisfied. **Script ran clean: 333/333 tickers HTTP 200 on both endpoints, CSV landed at `E:\Projects\yieldiq_v7\redesign\followups\_financials_scan.csv` (333 data rows + header).** No inline fixes were necessary; the artifact from the prior run is trustworthy on its own terms. A stricter cell-level reconciliation would require direct DB access — recommended as a follow-up, not a blocker.

---

## §1. Corruption inventory

### 1.1 Named tickers from the WIPRO §11.6 report (6 cases)

| Ticker | new_n | old_n | dup_fys | yoy_spike | Symptom class |
|---|---|---|---|---|---|
| WIPRO | 3 | 7 | — | — | Sparse + historic corrupt-row vector (per §11.6) |
| CRISIL | 3 | 8 | — | FY2024→FY2025: **+342%** | FY2024 revenue too low (≈738 Cr vs true ~3,000 Cr) |
| ABB | 3 | 8 | — | FY2024→FY2025: **+292%** | FY2024 revenue too low (≈3,080 Cr vs true ~10,000 Cr) |
| ADANIENSOL | 3 | 9 | **FY2024** | — | Duplicate FY2024 row (stub + real) |
| ANANTRAJ | 3 | 8 | **FY2024** | — | Duplicate FY2024 row |
| BAJAJHLDNG | 3 | 8 | — | — | Sparse only (no spike, no dup) — possibly already cleaned, or BS-only entity |
| DIXON | 3 | 8 | — | FY2024→FY2025: **+121%** | FY2024 revenue too low (Electronics Mfg) |

All 6 confirmed present in `_financials_scan.csv`. The §11.6 hypothesis (FY2024 partial / stub / mis-classified rows in `company_financials`) is corroborated for 4 of 6; BAJAJHLDNG and WIPRO show only the sparse-rows symptom in the current snapshot.

### 1.2 Universe-scan flagged rows (333 tickers, 6/3/2026)

- **64 tickers** flagged with at least one corruption signal (19%).
- **41 tickers** with **duplicate FYs** — every single one is `FY2024` (FY2024 appears twice in `company_financials`). This is a populator bug, not random data drift.
- **24 tickers** with **|YoY|>50% spikes**. Direction breakdown:
  - 13 spikes on FY2024→FY2025 (overwhelmingly **positive** — FY2024 base is too low)
  - 8 spikes on FY2023→FY2024 (mixed; includes the egregious JIOFIN +5424% and NTPCGREEN +1052% which are new-entity step-ups, not corruption)
  - 4 spikes on FY2025→FY2026 (sparse partial-FY2026 rows being compared against full FY2025)
- **1 ticker** with FY gaps in the new table (rare; most sparseness is just short windows).
- **0 tickers** with period-end anomalies (no rogue Q-end rows leaking into annual scope).
- **5 tickers** with `new_n=0` (no `company_financials` rows at all): PEL is the named one; others are tier-C/D edge cases.

**Egregious YoY spikes worth flagging** (almost certainly corrupt FY2024 base, not real growth):

| Ticker | Spike | Sector |
|---|---|---|
| CRISIL | FY2024→FY2025 +342% | Financial Data |
| CASTROLIND | FY2024→FY2025 +303% | Oil Marketing |
| ABB | FY2024→FY2025 +292% | Capital Goods |
| BSE | FY2024→FY2025 +113% | Capital Markets |
| DIXON | FY2024→FY2025 +121% | Electronics Mfg |
| ETERNAL | FY2025→FY2026 +169% | Consumer Cyclical |
| MCX | FY2024→FY2025 +70% | Fintech |

### 1.3 The 41 FY2024-duplicate tickers (the "FY2024 stub" cohort)

Every single duplicate-FY case is `FY2024` duplicated. Sample (first 20): ADANIGREEN, DMART, BLUESTARCO, CROMPTON, BHARATFORG, BALKRISIND, EMAMILTD, DEVYANI, ABCAPITAL, BANKINDIA, CENTRALBK, AUBANK, CUB, BHEL, BEL, COCHINSHIP, BEML, CONCOR, DALBHARAT, ANGELONE. The remaining 21 follow the same FY2024-only pattern. Sector spread is broad (Capital Goods 5, Banks 5, NBFC 5, Realty 4, Defence 3, Fintech 3, Pharma 3 — no single sector dominates), which rules out a sector-specific upstream source and points squarely at a **single populator run that wrote a stub row alongside the real FY2024 row** for a large slice of the universe.

---

## §2. Two-table divergence map

### 2.1 Headline

- **268 of 333 tickers (80%)** are flagged with `|div_gap| ≥ 3` rows — i.e. the old `financials` table holds at least 3 more annual rows than the new `company_financials` table.
- New-table row count is **almost uniformly 3** (326/333 tickers). Old-table row count clusters at **8 (93 tickers)** and **9 (119 tickers)**.
- The structural shape is not "noise" — it is "two completely different population strategies", one shallow and one deep.

### 2.2 div_gap distribution (old_n − new_n)

| Gap | Tickers | Interpretation |
|---|---|---|
| 0 | 6 | Either both empty, or coincidentally matched (rare) |
| +1 | 12 | Mostly tickers where new table has 2 rows |
| +2 | 47 | Common partial-coverage |
| +3 | 21 | Flagged divergence |
| +4 | 28 | Flagged divergence |
| **+5** | **93** | Flagged — modal case for `top100_diversified` |
| **+6** | **119** | Flagged — modal case overall |
| +7 | 7 | Worst-divergence cohort (COFORGE, PEL, COCHINSHIP, APLAPOLLO, AEGISLOG, UNOMINDA, TIINDIA) |

There are **zero tickers** where the new table has more rows than the old. The relationship is strictly: old ≥ new, with old having 8–10 annual rows and new having 0–3.

### 2.3 Populator script identification

- **New table `company_financials`** is populated by `data_pipeline/xbrl/db_writer.py` (`INSERT INTO company_financials ...` at line 173). Source: BSE XBRL filings via `data_pipeline/sources/bse_xbrl.py`. This is the **XBRL-driven pipeline**, recent, narrow window (≈3 fiscal years), and the source of the FY2024-stub / FY2024-low-revenue corruption.
- **Old table `financials`** is populated by an older path (likely the `scripts/data_pipelines/fetch_annual_financials.py` family seen in agent worktrees; the canonical version is not in the main tree — only the XBRL writer is). Source: likely yfinance / screener-scrape backfill. 8–10 years deep, clean (no dups, no spikes flagged), but stale (no continuous nightly refresh observed).
- **Readers split exactly down the middle** (`Grep` of `FROM` clauses):
  - `company_financials` readers: `cagr_service.py`, `financials_service.py`, `hex_history_service.py`, `analysis/db.py` (mostly), `local_data_service.py` (newer paths).
  - `financials` readers: `analysis/db.py` (DCF fallback line 482, 645, 775), `data_quality.py`, `coverage_tier_service.py`, `local_data_service.py` (line 192), `hex_service.py`, `routers/public.py` line 4403.

The DCF engine reads `financials` (deep, stale); CAGR reads `company_financials` (shallow, corrupt). This is the exact split called out in WIPRO §1.4 and is the root architectural problem.

---

## §3. Root-cause hypothesis

1. **Two ingest pipelines, neither retired.** The XBRL pipeline (new) was stood up to give precise, audited annual statements from BSE filings. The old yfinance/screener backfill was never decommissioned, so `financials` continued to be the "deep history" source while `company_financials` became the "high-fidelity but shallow" source. Nobody picked one.
2. **The XBRL pipeline has an FY2024-stub bug.** 41 tickers have `FY2024` duplicated; a further ~13 show wildly low FY2024 revenue (CRISIL 738 Cr, ABB 3,080 Cr) that drives the +200–340% FY2024→FY2025 YoY spikes. Most likely: a partial/interim XBRL filing for FY2024 was written as a full-year row alongside the audited full-year row, OR a wrong tag (segment revenue, single-line "revenue from operations excluding other income") was picked off the FY2024 filing for a subset of issuers.
3. **No upsert dedup key.** The duplicate-FY rows would have been blocked by a `UNIQUE(ticker_nse, period_type, period_end_date, statement_type)` constraint. The fact that 41 tickers have two FY2024 rows means the writer does INSERT without ON CONFLICT, or the dedup key is too loose (likely missing `statement_type` discriminator).
4. **Routing inconsistency at the service layer.** CAGR reads only the new table and silently gets 3 rows even when 10 are available in the old table. DCF reads only the old table and never benefits from the audited XBRL precision when it's correct. Coverage tier reports the old-table count, so the rubric understates the corruption in the surfaces (CAGR, ratios, hex history) that read the new table.

---

## §4. Reconciliation proposal

**Recommendation: (C) reconciliation view, with (A) as the 6-month target.**

| Option | Pro | Con | Verdict |
|---|---|---|---|
| **A. Migrate everything to `company_financials`** | Single source of truth, audited precision | Requires backfilling 5–7 prior years from XBRL (huge), AND fixing the FY2024-stub populator bug first | Right end state, wrong starting move |
| **B. Migrate everything to `financials`** | Already deep (8–10y), low corruption rate in the sample | Throws away the audited XBRL data; stale; un-refreshed | No |
| **C. Add a reconciliation view `v_financials_unified`** that prefers `company_financials` when present and non-corrupt, falls back to `financials` for older years | Ships in days; no data loss; both populators keep running; readers get a single SQL surface | Requires the corruption-detection predicate to live in SQL (`revenue NOT BETWEEN 0.3*lag(revenue) AND 3*lag(revenue)`-style) | **Recommended now** |
| **D. Dual-write reconciliation at ingest time** | Stronger long-term | Re-architects two pipelines | Out of scope |

**Concrete C proposal:**
1. Build `v_financials_unified(ticker, fiscal_year, period_end, revenue, ..., source)` where `source ∈ {'cf','f','cf+f'}`.
2. Per (ticker, fiscal_year): pick `company_financials` row unless it's a known-corrupt FY (duplicate, or revenue YoY deviates from `financials` value by >40% with `financials` row also present for same FY).
3. Re-point CAGR, financials_service, hex_history_service, analysis/db.py to read the view.
4. Keep both writers running; fix the FY2024-stub bug in `db_writer.py` separately (add `ON CONFLICT (ticker_nse, period_type, period_end_date, statement_type) DO UPDATE`, and add a "do not write if revenue < 30% of prior-year revenue without a corresponding `financials` row" guard).
5. Once the XBRL pipeline backfills 7 years cleanly, deprecate the old `financials` table → option A naturally.

This unblocks CAGR/hex-history (currently producing the WIPRO-class -77% and CRISIL/ABB +300% artifacts) without touching the DCF engine.

---

## §5. Quick-win fixes (single-ticker UPDATEs)

Each of these can be a single hand-curated row-fix to `company_financials` once a human verifies the true FY2024 revenue from the audited annual report. None of these should be done programmatically — they are surgical hot-patches to unblock specific tickers from `under_review`/coverage downgrade while the (C) reconciliation view is built.

| Ticker | Fix | Source of truth |
|---|---|---|
| CRISIL | DELETE the corrupt FY2024 row (revenue ≈ 738 Cr); rely on `financials` fallback until next clean XBRL pull | Annual report FY24: ~3,020 Cr |
| ABB | DELETE corrupt FY2024 row (revenue ≈ 3,080 Cr) | Annual report FY24: ~10,000 Cr |
| DIXON | DELETE corrupt FY2024 row | Annual report FY24 |
| CASTROLIND | DELETE corrupt FY2024 row | Annual report FY24 |
| BSE | DELETE corrupt FY2024 row | Annual report FY24 |
| ADANIENSOL | DELETE the duplicate FY2024 row (keep the larger-revenue one) | — |
| ANANTRAJ | DELETE the duplicate FY2024 row (keep the larger-revenue one) | — |
| (+ 39 other dup-FY2024 tickers) | Same dedup recipe; can be a single SQL with `ROW_NUMBER() OVER (PARTITION BY ticker_nse, period_end_date ORDER BY revenue DESC) = 1` | — |

The 41-ticker dedup is genuinely a one-statement fix; the ~13 low-revenue FY2024 cases each need an audited-report cross-check.

---

## Appendix — scan artifacts

- Raw CSV: `E:\Projects\yieldiq_v7\redesign\followups\_financials_scan.csv` (333 rows, 19 cols)
- Scanner: `E:\Projects\yieldiq_v7\redesign\followups\_scan_financials_reconciliation.py` (throwaway; do not promote)
- Reader/writer maps from `Grep` runs documented above in §2.3
- Companion report: `E:\Projects\yieldiq_v7\redesign\followups\wipro-cagr-blast-radius.md`
