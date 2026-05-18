# Corporate-actions structural overlay — Phase-A design

**Status:** Landed (skeleton on `main`; Phase B + C land in
`feat/hdfc-merger-growth-truncation`).
**Author:** YieldIQ data-quality
**Original draft date:** 2026-05-17
**Re-landed on main:** 2026-05-18 (this file was referenced from
`backend/services/corporate_actions_service.py` and Phase-A
migrations 041/012 but never made it to `main` — see the
"Provenance" section below).
**Related:**
* `backend/services/corporate_actions_service.py`
* `data_pipeline/migrations/041_corporate_actions_structural.sql`
* `db/migrations/012_corporate_actions_structural.sql`
* `docs/design/hdfc-merger-growth-normalization.md` (Phase B + C
  application of this design to the HDFCBANK use case).

---

## Provenance

This document was referenced from the Phase-A source comments
(`backend/services/corporate_actions_service.py:22`) but was missing
from `main` — it lived only on the unmerged branch
`feat/corporate-actions-overlay-phase-a-ddl`. The branch's HEAD does
not actually carry the file either (`git show
origin/feat/corporate-actions-overlay-phase-a-ddl:docs/design/corporate-actions-overlay.md`
errors with "path … does not exist"), so this doc has been
reconstructed from the source comments, the migration headers and
the Phase-B/C design doc rather than copied verbatim. Future readers
who locate the original draft on a long-lived branch should diff
against this file and merge the deltas.

---

## 1. Why this exists

Indian listed companies routinely undergo structural transactions —
mergers, demergers, schemes of arrangement, material acquisitions —
that produce overnight discontinuities in reported financials.
The naive year-over-year and CAGR computations downstream of
`backend.services.ratios_service` read these discontinuities as
organic growth (the most visible example: HDFCBANK reporting a
~30% revenue CAGR because the July 2023 HDFC Ltd reverse merger
roughly doubled FY24 interest income).

The fix is **not** to re-state the financials — pro-forma rows are
high-burden and brittle across re-filings. The fix is to make the
growth pipeline aware of structural events so that the CAGR base /
end is restricted to a comparable window. This is the structural-
overlay pattern.

---

## 2. Schema (Phase A)

`corporate_actions` already exists for dividends / splits / bonuses
(populated by `fetch_corporate_actions.py` and
`backfill_corporate_actions_yf.py`). Phase A extends it with:

| Column        | Type           | Required for structural rows? |
| ------------- | -------------- | ----------------------------- |
| `multiplier`  | `NUMERIC(12,6)` | optional                     |
| `source_url`  | `TEXT`         | **yes** (CHECK constraint)   |
| `source_doc`  | `TEXT`         | **yes**                      |
| `notes`       | `TEXT`         | optional                     |

A CHECK constraint `ck_structural_sourced` enforces that every row
whose `action_type` is in the structural set carries both a
`source_url` and a `source_doc`. Non-structural rows (dividends /
splits / bonuses) are unaffected — they may continue to have NULL
in these columns. The constraint is added inside a DO-block so
re-applying the migration is idempotent.

Structural `action_type` values:

* `MERGER`
* `REVERSE_MERGER`
* `DEMERGER`
* `SCHEME_OF_ARRANGEMENT`
* `MATERIAL_ACQUISITION`

These are reflected in
`corporate_actions_service.STRUCTURAL_ACTION_TYPES` and kept in
lockstep with the CHECK constraint.

The natural-key index `uq_corporate_actions_natural_key
(ticker, ex_date, action_type)` introduced in
`010_corporate_actions_quality_rank.sql` continues to apply — there
can be at most one structural row per (ticker, ex_date, action_type)
combination.

---

## 3. Service surface (Phase A)

`backend/services/corporate_actions_service.py` exposes three public
functions:

* `get_actions(ticker, action_type=None, since=None) -> list[dict]`
  Plain query helper. Defensive — returns `[]` on any DB error or
  missing engine.
* `has_structural_break(ticker, window_years=3) -> bool`
  True iff a structural-type row exists for the ticker with
  `ex_date` inside the trailing `window_years` window.
* `compute_cagr_structural_aware(ticker, field, years, series,
  latest_period_end=None) -> Optional[float]`
  Phase-A: falls through to `ratios_service.compute_revenue_cagr`
  for every ticker (no seed rows exist).
  Phase-C (see hdfc-merger-growth-normalization.md): truncates
  `series` past the merger fiscal year and returns the CAGR over
  the post-break tail, or `None` when the tail is too short.

The Phase-A skeleton's design intent is "behaviour-neutral until
seeded": until Phase B rows land, every caller sees the same number
the legacy pipeline returned.

---

## 4. Phases

* **Phase A** — DDL only. Migrations 010/012/041 + Python skeleton.
  Landed on `main`.
* **Phase B** — Seed structural rows for the bank cohort (HDFCBANK,
  AXISBANK, INDUSINDBK, IDFCFIRSTB, KOTAKBANK) via migration
  `042_seed_structural_mergers.sql` (mirror `013_*.sql`).
* **Phase C** — Wire `compute_cagr_structural_aware` into the
  analysis pipeline (`backend/services/analysis/service.py:2062`)
  and implement the post-break truncation branch.

Phases B and C land together in
`feat/hdfc-merger-growth-truncation` — see
`docs/design/hdfc-merger-growth-normalization.md` for the
HDFCBANK-specific rollout, acceptance criteria, and the canary /
CACHE_VERSION discipline notes.

---

## 5. Forward work

* Replace the curated `RECENT_MERGER_BANKS` set in
  `screener/piotroski.py` with a query against `corporate_actions`
  (single source of truth).
* Extend the overlay to PAT / EBITDA / ROA CAGR — the
  `compute_cagr_structural_aware(field=...)` argument is already
  shaped for this; the call-sites just need swapping.
* Per-action-type policy table — today the truncation gate treats
  all five structural types equivalently; a `MATERIAL_ACQUISITION`
  smaller than ~5% of the loan book / revenue arguably should not
  truncate, while a `DEMERGER` should also reset the *historical*
  base (not the trailing tail). Open question 8.3 in the
  Phase-B/C design doc.
