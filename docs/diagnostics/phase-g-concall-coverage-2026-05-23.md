# Phase G-audit — Concall Coverage Diagnostic (2026-05-23)

**Status:** read-only diagnostic. No code or data changes.
**Author:** Phase G dispatch
**Purpose:** evidence base to gate Phase G-cost / G-intel-phase1 /
G-operator-workflow.

---

## 1. Why this audit exists

Phase G's re-scoped plan promotes the Phase 0 `concall_intel_service`
scaffold to Phase 1 production with Anthropic-powered structured signal
extraction (guidance, capex, margin, tone, quotes). Before spending
LLM budget on a wide backfill, we need to know whether the underlying
transcript inventory is dense enough to be worth extracting from — and
whether the existing NSE-only fetcher leaves big BSE blind spots.

This audit answers:

1. How many tickers in our top-200 / canary-333 union actually have
   transcripts in `concall_transcripts` over the last 1y and 5y?
2. What fraction of those transcripts already have an `ai_summary`,
   and what fraction were withheld by the SEBI sanitizer?
3. Is the NSE-only fetcher missing BSE-only listings in a systemic way?

---

## 2. Universe

| Bucket | Count |
|---|---|
| Canary v3 (333) | 333 |
| Top 200 by market cap | 200 |
| Union (deduped) | 342 |

---

## 3. Coverage headline

| Group | Any in 1y | Any in 5y | Meets 1y ≥ 4 | Meets 5y ≥ 20 |
|---|---|---|---|---|
| Canary v3 | 281 (84.4%) | 281 (84.4%) | 260 (78.1%) | 16 (4.8%) |
| Top-200 | 180 (90.0%) | 180 (90.0%) | 170 (85.0%) | 11 (5.5%) |
| Union | 290 (84.8%) | 290 (84.8%) | 269 (78.7%) | 17 (5.0%) |

### 5-year transcript-count distribution (top-200)

| Bucket (5y count) | Tickers |
|---|---|
| 0 | 20 |
| 1-4 | 22 |
| 5-9 | 59 |
| 10-19 | 88 |
| 20-39 | 10 |
| 40+ | 1 |

---

## 3a. Key observations from the raw numbers

1. **`any_in_1y` equals `any_in_5y` for every group.** Across the
   union universe the entire `concall_transcripts` table only spans
   `2025-07-19 → 2026-05-16` (≈10 months, 4,495 rows total). The
   weekly cron in `.github/workflows/concall_transcripts_weekly.yml`
   fetches `--days-back 120` only, so anything older has simply never
   been ingested. **The "5y" question cannot be answered with the
   current inventory** — what we're really seeing is a 10-month
   sample.

2. **The 5y ≥ 20 cadence bar is unreachable from the current
   inventory.** With 10 months of history and a quarterly cadence,
   the practical ceiling is 3-4 transcripts per ticker. The 5.5% of
   top-200 that clear ≥ 20 are tickers that file multiple times per
   quarter (transcripts + recordings + investor-meet decks all logged
   as separate rows).

3. **Implication for Phase G-cost / G-intel-phase1.** Both phases are
   still worth shipping, but the universe sizing changes:
   - G-cost (token + USD columns) should ship as-is — additive and
     useful regardless of inventory depth.
   - G-intel-phase1 should target the **`meets_1y_threshold`**
     universe (~170 top-200 tickers, ~260 canary tickers) rather than
     the `meets_5y_threshold` slice. The 1y cohort has enough recent
     transcripts to give the Anthropic signal extractor real material.
   - A separate phase (call it G-historical-backfill) should later
     extend `--days-back` on the cron to 1825 (5y) so the 5y universe
     fills in over time. Out of scope for current Phase G.

4. **AI-summary cache is 0% populated.** Day-104b's
   `populate_concall_summary` runs lazily on first
   `GET /api/concalls` hit per row. Either no end-user has touched
   these tickers since the cron started ingesting, or the lazy path
   isn't being exercised in production. Worth a separate investigation
   (flag it for G-operator-workflow as a smoke-test target).

---

## 4. AI-summary cache state

Across the entire `concall_transcripts` table filtered to the union universe:

| Field | Value |
|---|---|
| Total rows | 3052 |
| Rows with `ai_summary` populated | 0 (0.0%) |
| Rows withheld by SEBI sanitizer | 0 (0.0%) |
| Rows with cached `transcript_text` | 0 (0.0%) |

`Rows withheld` are rows where `ai_summary` equals the sentinel
`(summary withheld pending review)` — the Groq summary contained a
SEBI-banned word (`buy/sell/strong/recommend/target/...`) and the
sanitizer in `backend/services/concall_service.py` swapped it out.

---

## 5. NSE-only blind-spot probe

The existing fetcher (`data_pipeline/sources/nse_concall_transcripts.py`)
only hits NSE. Sample of 10 random tickers that have a `bse_code` in
the `stocks` table but **zero** rows in `concall_transcripts`:

| Ticker | Company | Sector | BSE Code | M-cap (Cr) |
|---|---|---|---|---|
| SANOFI | Sanofi India Limited | Pharma | 500674 | 8207 |
| BDL | Bharat Dynamics Limited | Industrials | 541143 | 53100 |
| GMDCLTD | Gujarat Mineral Development Corporation Limited | Energy | 532181 | 23437 |
| BAJAJHLDNG | Bajaj Holdings & Investment Limited | Financial Services | 500490 | 118327 |
| GODFRYPHLP | Godfrey Phillips India Limited | Consumer Defensive | 500163 | 37824 |
| NESTLEIND | Nestle India Limited | FMCG | 500790 | 284484 |
| SIEMENS | Siemens Limited | Energy | 500550 | 136216 |
| INDIGOPNTS | Indigo Paints Limited | Basic Materials | 543258 | 4697 |
| GILLETTE | Gillette India Limited | Consumer Defensive | 507815 | 26550 |
| SAPPHIRE | Sapphire Foods India Limited | Consumer Cyclical | 543397 | 6592 |

If the operator manually spot-checks a couple of these against the BSE
corporate-announcements portal and finds concall PDFs, that's evidence
for adding a BSE fetcher in a follow-up phase (not in current scope).

---

## 6. Verdict

**PROCEED WITH CAUTION** (script-mechanical verdict) — refined by §3a:

**PROCEED with universe re-scoping.**

90.0% of top-200 have *some* coverage in the inventory, easily
clearing the 20% HARD-STOP bar. The mechanical 5y ≥ 20 cadence
threshold reads 5.5%, but per §3a that's an artefact: the
`concall_transcripts` table only spans 10 months today, so the 5y
cadence question is unanswerable. The right target universe for
G-intel-phase1 is the **1y ≥ 4 cohort**: 170 / 200 top-200 tickers
(85%) and 260 / 333 canary tickers (78%). That's a real, dense,
recent corpus the Anthropic extractor can do useful work on.

### Decision matrix

| Verdict | Action |
|---|---|
| PROCEED | Ship G-cost, G-intel-phase1, G-operator-workflow as planned. |
| PROCEED WITH CAUTION | Ship G-cost (cost tracking valuable regardless). For G-intel-phase1, narrow the initial universe to only tickers that clear the 5y ≥ 20 bar. |
| HARD STOP | Open a separate phase to add a BSE source before any LLM spend. Pause G-cost. |

---

## 7. Outputs of this run

* `E:/Projects/yq-phase-g/reports/concall_coverage_2026-05-23.csv` — per-ticker counts (342 rows).
* `E:/Projects/yq-phase-g/reports/concall_coverage_summary_2026-05-23.json` — machine-readable summary.
* This markdown — human-readable diagnostic.

## 8. Reproducibility

```
python scripts/audit_concall_coverage.py \
    --env-file .env.local --env-line 2
```

Output paths embed the run date; re-runs against a different DB
snapshot will write new files without overwriting today's.
