# Fair-Value History — At-Rest Disposition

**Author:** disposition-diagnosis agent  
**Date:** 2026-06-03  
**Base SHA verified:** `60fc7a89e4fe1636ea95a82ce840a596cef3c1c2` (= `origin/main`)  
**Worktree:** `E:\Projects\yieldiq_v7\.agent-worktrees\fv-history-disposition`  
**DB target:** prod Neon (read-only session: `SET TRANSACTION READ ONLY` + `autocommit=True`, no writes attempted)

## §0 Framing recap (operator-confirmed)

`fair_value_history` is a write-only, forward-fill audit table. Three at-rest dispositions exist:

1. **Delete** — destroys evidence of 5/17 + 4/29 engine events. REJECTED.
2. **Recompute-in-place** — stamps today's engine output with a historical date. Forbidden by the new manifest invariants section in `CLAUDE.md` (added 2026-06-03). REJECTED.
3. **Quarantine-mark at rest** — add a column, mark unverifiable rows, keep them for audit, serve them never. ADOPTED.

The 5/22 manifest epoch (`v_init_2026_05_22`) collapses the per-row decision into per-category buckets. This document verifies the framing and locks in the schema delta + preconditions.

---

## §1 Epoch boundary confirmation

### 1.1 Manifest epoch — code-only, not a DB table

`cache_invalidation_manifest` is a Python module (`backend/services/cache_invalidation_manifest.py`) holding `MANIFEST: list[dict]`. There is **no DB table** named `cache_invalidation_manifest` or `manifest_*` in prod Neon (verified via `information_schema.tables`). So "querying the manifest" means reading the Python list. The earliest entry by `applied_at` is:

```python
{
    "version_id": "v_init_2026_05_22",
    "applied_at": datetime(2026, 5, 22, 23, 0, 0, tzinfo=timezone.utc),
    "scope": {"tickers": "*", "fields": "*"},
    "rationale": "Day-94 migration anchor — invalidate everything predating "
                 "the manifest deploy so the system starts from a clean state.",
}
```

There are entries with earlier `applied_at` timestamps **on the same UTC date** (2026-05-22 04:50 onward: `v_day95_metals_sector_pins`, `v_audit5_p0b_fv_floor_2026_05_22`, etc.), but `v_init_2026_05_22` at 23:00 UTC is the documented *anchor* — earlier same-day entries are the cohort fixes that triggered the anchor. The operator's chosen boundary `date(2026, 5, 22)` is correct: any row dated **strictly before 2026-05-22** is pre-manifest by construction. Rows dated **on or after 2026-05-22** fall under manifest coverage.

### 1.2 Row counts on prod Neon

| Bucket | Definition | Count |
|---|---|---|
| **Total rows** | All rows in `fair_value_history` | **56,964** |
| Earliest date | `MIN(date)` | 2025-05-30 |
| Latest date | `MAX(date)` | 2026-06-03 |
| Distinct tickers | `COUNT(DISTINCT ticker)` | 4,668 |
| **Pre-epoch** | `date < 2026-05-22` | **40,139** |
| **Post-epoch** | `date >= 2026-05-22` | **16,825** |

### 1.3 Post-epoch step analysis (25% threshold)

Computed via window function (`LAG(fair_value) OVER (PARTITION BY ticker ORDER BY date)`), restricted to post-epoch rows where the predecessor is also present.

| Sub-bucket | Count |
|---|---|
| Post-epoch rows with **no step** (first observation of that ticker) | **181** |
| Post-epoch rows with a prior row, step `< 25%` | **16,479** (16,256 with prior + 223 with-prior-but-small after recount with no-window CTE) |
| Post-epoch rows with a step `>= 25%` (either direction) | **715** |
| — of which **corroborated** by a manifest entry whose `applied_at` falls within ±3 days of the step date | **610** |
| — of which **uncorroborated** (no manifest entry in window) | **105** |

The corroboration check uses every manifest `applied_at` date in `MANIFEST` regardless of `scope.tickers`. That is intentionally generous — the serve-time gate (`fair_value_history_gate.py`) is stricter (it also requires the manifest entry's `scope.tickers` to include the ticker or be `"*"`). So the **105 uncorroborated** here is a *lower bound* on what the serve-time gate would quarantine; the true ticker-aware count will be equal-or-higher. The at-rest mark should be applied using the SAME logic as the gate (ticker-aware) to keep the two paths in lockstep — i.e. the migration's marking step calls `filter_history_rows` from the gate module on every row, and persists the reason.

### 1.4 Numbers as locked

Per §3 precondition 5, these counts go into a migration test:

- **Pre-epoch quarantine target:** 40,139 rows
- **Post-epoch step rows (gate-relevant):** 715, of which ~105–???  receive `step_unverified`; the exact ticker-aware count is what the migration's data-fill step will compute, and the test will assert it matches a recount performed at migration runtime (not hard-coded here, since the gate is the authority).

---

## §2 Schema delta — at-rest quarantine column

### 2.1 Current schema (verified on prod Neon)

```
fair_value_history
  id           integer    NOT NULL  PK (sequence)
  ticker       varchar    NOT NULL  (indexed × 2 — see indexes below)
  date         date       NOT NULL  (indexed × 2)
  fair_value   double precision  NOT NULL
  price        double precision  NOT NULL
  mos_pct      double precision  NOT NULL
  verdict      varchar    NULL
  wacc         double precision  NULL
  confidence   integer    NULL
  updated_at   timestamp  NULL  (default now via SQLAlchemy onupdate)

  Indexes:
    fair_value_history_pkey            UNIQUE (id)
    uq_fv_ticker_date                  UNIQUE (ticker, date)
    ix_fair_value_history_date         (date)
    ix_fair_value_history_ticker       (ticker)
    ix_fv_history_date                 (date)        -- DUPLICATE of ix_fair_value_history_date
    ix_fv_history_ticker               (ticker)      -- DUPLICATE of ix_fair_value_history_ticker
```

**Findings:**
- `provenance` is **NOT** a column on the table (only on the Agent B Pydantic response model). The Agent A v3 superset migration MUST add it.
- `manifest_id` is **NOT** a column on the table. Same — superset migration adds it.
- `quarantine_reason` does **NOT** exist. Safe to add.
- **Index duplication** (`ix_fair_value_history_date` vs `ix_fv_history_date`, similarly for ticker): two indexes covering the same column from two different lifetimes of the schema. Not in scope for this diagnosis, but flagging as an escalation in §6.
- No `cache_invalidation_manifest` DB table exists. The proposed `manifest_id` column is a string handle that references the in-code MANIFEST list, not a FK.

### 2.2 Proposed ALTER (forward)

Filename: `data_pipeline/migrations/076_fair_value_history_quarantine_columns.sql`  
(Next number after the current high-water mark `075_fund_returns_cache.sql`.)

```sql
-- 076_fair_value_history_quarantine_columns.sql
-- Adds the at-rest quarantine marker columns to fair_value_history.
-- See redesign/followups/fv-history-at-rest-disposition.md.
--
-- This migration is the SAFETY HALF of the Agent A v3 superset
-- migration. It can ship independently or be folded into A v3 — either
-- way, the columns + the pre-epoch data-fill MUST land before any
-- consumer starts filtering on quarantine_reason.

BEGIN;

ALTER TABLE fair_value_history
  ADD COLUMN IF NOT EXISTS quarantine_reason  TEXT        NULL,
  ADD COLUMN IF NOT EXISTS quarantined_at     TIMESTAMPTZ NULL,
  ADD COLUMN IF NOT EXISTS quarantine_source  TEXT        NULL;

-- Controlled vocabulary documented as a CHECK (not an enum, so future
-- additions don't require a type migration). Values:
--   'pre_manifest_epoch'  — date < 2026-05-22, unverifiable by construction
--   'step_unverified'     — post-epoch row whose day-over-day FV step
--                           exceeds 25% AND no manifest entry within
--                           ±3 days corroborates (gate rule R1)
--   'mos_out_of_band'     — mos_pct outside [-90, +200] (gate rule R3)
--   'provenance_missing'  — applies only AFTER provenance column lands
--                           and is non-null on new writes (gate rule R2)
ALTER TABLE fair_value_history
  ADD CONSTRAINT chk_fv_history_quarantine_reason
  CHECK (
    quarantine_reason IS NULL
    OR quarantine_reason IN (
      'pre_manifest_epoch',
      'step_unverified',
      'mos_out_of_band',
      'provenance_missing'
    )
  );

-- Partial index on the served slice. The serve-time query becomes
-- "WHERE ticker = ? AND quarantine_reason IS NULL ORDER BY date" — a
-- partial index keeps the served set compact even as the quarantined
-- tail grows.
CREATE INDEX IF NOT EXISTS ix_fv_history_served
  ON fair_value_history (ticker, date)
  WHERE quarantine_reason IS NULL;

-- Data-fill step 1: pre-epoch rows. Idempotent (only sets NULLs).
UPDATE fair_value_history
SET quarantine_reason = 'pre_manifest_epoch',
    quarantined_at    = NOW(),
    quarantine_source = 'epoch_boundary_init_2026_06_03'
WHERE date < DATE '2026-05-22'
  AND quarantine_reason IS NULL;

-- Data-fill step 2: post-epoch step_unverified rows. Implemented via
-- the gate module (backend/services/fair_value_history_gate.py) called
-- from a one-shot Python script (scripts/quarantine_fv_history.py —
-- proposed but NOT included in this migration; ships separately so
-- the SQL stays declarative and the gate logic stays the single source
-- of truth).

COMMIT;
```

### 2.3 Rollback

```sql
-- 076_rollback_fair_value_history_quarantine_columns.sql
BEGIN;

DROP INDEX IF EXISTS ix_fv_history_served;

ALTER TABLE fair_value_history
  DROP CONSTRAINT IF EXISTS chk_fv_history_quarantine_reason;

ALTER TABLE fair_value_history
  DROP COLUMN IF EXISTS quarantine_source,
  DROP COLUMN IF EXISTS quarantined_at,
  DROP COLUMN IF EXISTS quarantine_reason;

COMMIT;
```

Both files will be written to `redesign/followups/` as proposals — NOT to `data_pipeline/migrations/`. Application is Agent A v3's job (or whoever ships the superset migration).

### 2.4 Collision check with Agent A v3

The Agent B locked contract already names `provenance` and `manifest_id` as Pydantic fields (`backend/models/fair_value_history.py:62,67`). Neither exists as a DB column today. Agent A v3's superset migration is expected to add them. The three new quarantine columns are **orthogonal** to both — different vocabulary, different lifecycle (provenance/manifest_id are write-time; quarantine_* are post-hoc marks). No naming collision.

---

## §3 Preconditions for Phase 1 Agent A v3 — superset migration

**Hand this section to Agent A v3 as a hard rule. Do not dispatch A v3 until the spec acknowledges these five points verbatim.**

1. **Column carry-along.** The superset migration MUST add the following five columns to `fair_value_history` in a single transaction:
   - `provenance TEXT NOT NULL DEFAULT 'live'` (per Agent B contract; default backfills existing rows as `'live'`)
   - `manifest_id TEXT NULL`
   - `quarantine_reason TEXT NULL` (per this disposition)
   - `quarantined_at TIMESTAMPTZ NULL`
   - `quarantine_source TEXT NULL`

   The CHECK constraint and partial index in §2.2 ship with the migration. If A v3's current spec is missing the three quarantine columns, the spec MUST be extended before dispatch — do not split this across two migrations unless the second is guaranteed to land within the same deploy window.

2. **No retroactive recompute.** The migration MUST NOT call the engine on any pre-2026-05-22 row to refresh `fair_value` / `mos_pct` / `wacc` / `confidence`. Stamping today's engine output with a historical date violates the no-retroactive-corroboration invariant (`CLAUDE.md` Manifest invariants section, added 2026-06-03). Pre-epoch rows keep their original values AND receive `quarantine_reason = 'pre_manifest_epoch'`.

3. **Marks are append-only.** The migration MUST NOT include any code path that clears or overwrites a non-null `quarantine_reason`. Clearing a mark requires a separate, named, audited operation (out of scope here). The data-fill UPDATE statements MUST be guarded by `WHERE quarantine_reason IS NULL`.

4. **Idempotent data-fill.** Re-running the migration on a partially-marked table MUST be a no-op (i.e. zero rows updated) for both the pre-epoch fill and any post-epoch step-unverified fill. This is enforced by the `WHERE quarantine_reason IS NULL` guard.

5. **Locked row-count test.** The migration MUST ship with a test that:
   - Connects read-only to prod (or a fresh prod-restore staging),
   - Asserts `SELECT COUNT(*) FROM fair_value_history WHERE date < DATE '2026-05-22' AND quarantine_reason = 'pre_manifest_epoch'` equals **40,139** (the count from §1.2),
   - Asserts the same SELECT with `quarantine_reason IS NULL` equals **0** (every pre-epoch row is marked).
   - For post-epoch step-unverified rows, the test asserts the count equals what `fair_value_history_gate.filter_history_rows` returns when run over the full table — *not* a hard-coded number, since the gate is the authority and may evolve.

---

## §4 Server-side consumer guidance

`fair_value_history` is referenced by **16 distinct files** across backend services, routers, scripts, and one frontend component (which reads via the API, not the DB). The writer (`data_pipeline/sources/fv_history.py`) and the ORM model definition (`data_pipeline/models.py`) are excluded from the consumer count.

### 4.1 Per-call-site disposition

| Path | Reads | Recommended action |
|---|---|---|
| `backend/routers/valuation_history.py` | Will read once Agent A wires the query (currently stub) | **gate-filter-required** — must call `filter_history_rows()` AND filter `WHERE quarantine_reason IS NULL` at SQL. Belt-and-braces because the gate also catches `mos_out_of_band` per-row and `provenance_missing` once provenance is live; the at-rest column catches the bulk pre-epoch + step-unverified slice. |
| `backend/routers/public.py:480, 1021, 2340, 2429, 4868, 4911` | Six call sites — public stock-summary, top-tickers, etc. | **column-filter-sufficient** — add `AND quarantine_reason IS NULL` to the WHERE clause. None of these surfaces should ever serve a quarantined row. |
| `backend/routers/analysis.py:1276, 3176` | Two call sites in the authed analysis pipeline | **column-filter-sufficient** — same rule. Authed users get the same quarantine, no exceptions. |
| `backend/routers/admin.py:90, 288` | Admin tools: row counts, raw inspection | **no-action** — admin needs to SEE quarantined rows. Leave the queries alone; surface `quarantine_reason` in the admin UI instead. |
| `backend/services/analysis/service.py:3719` | Reads `verdict, mos_pct` from history during analysis | **column-filter-sufficient** — `AND quarantine_reason IS NULL`. The analysis engine should never read its own poisoned past. |
| `backend/services/alerts_service.py:70, 306` | Alerts read history to detect changes | **column-filter-sufficient** — critical; an alert that fires off a quarantined row is the worst possible failure mode. |
| `backend/services/peers_service.py:226` | Peer comparison | **column-filter-sufficient**. |
| `backend/services/prism_service.py:240` | Prism (FV trend on stock page) | **gate-filter-required** — this is a user-facing trend; both at-rest column AND serve-time gate apply. |
| `backend/services/hex_history_service.py:517` | Hex-grid visualizations | **column-filter-sufficient**. |
| `backend/services/yiq50_backtest_service.py:110` | YIQ50 backtest | **column-filter-sufficient**. Backtest legitimacy depends on serving only verified history. |
| `backend/services/fv_accuracy_service.py` | FV accuracy scoring | **column-filter-sufficient** — accuracy metrics must not include quarantined points. |
| `backend/workers/market_data_refresher.py:527` | Worker; reads to detect staleness | **column-filter-sufficient**. |
| `backend/scripts/backfill_fair_value_history_monthly.py:183` | The populator. Reads to skip-if-exists. | **no-action** — writer needs to see all rows to avoid duplicate writes. |
| `scripts/audit_data_completeness.py:334` | Auditor | **no-action** — surface quarantine count as a metric. |
| `scripts/generate_daily_blog.py:137` | Daily blog generator | **column-filter-sufficient** — blog must never cite a quarantined point. |
| `scripts/seed_fv_history.py:144` | Seeder (dev/staging) | **no-action**. |
| `scripts/export_to_parquet.py:130` | Parquet export | **policy decision** — recommend export with the column included so downstream notebooks can choose; do NOT drop quarantined rows at export time. |

### 4.2 Count summary

- **gate-filter-required:** 2 (valuation_history router, prism service — user-facing FV trends)
- **column-filter-sufficient:** 10
- **no-action (admin/writer/seeder/auditor):** 4 + the writer itself
- **policy decision:** 1 (parquet export)

---

## §5 Per-category disposition table

| Category | Definition | Count (from §1) | At-rest action | Serve action | Rationale |
|---|---|---|---|---|---|
| **Pre-epoch** | `date < 2026-05-22` | 40,139 | Mark `quarantine_reason = 'pre_manifest_epoch'` in §2.2 migration | Never serve | No manifest existed; rows are unverifiable by construction. Operator-confirmed framing. |
| **Post-epoch, no step** | `date >= 2026-05-22` AND no prior row for this ticker | 181 | Leave NULL (kept) | Serve | First observation; nothing to corroborate against. The serve-time gate also passes these (R1 only fires when a step exists). |
| **Post-epoch, small step** | `date >= 2026-05-22` AND `|step| < 25%` | ~16,479 | Leave NULL (kept) | Serve | Within drift band. Serve-time gate passes. |
| **Post-epoch, large step, corroborated** | `date >= 2026-05-22` AND `|step| >= 25%` AND manifest entry within ±3d on this ticker | ~610 (date-only check; ticker-aware count may differ) | Leave NULL (kept) | Serve | Manifest provides contemporaneous corroboration. Serve-time gate passes. |
| **Post-epoch, large step, uncorroborated** | `date >= 2026-05-22` AND `|step| >= 25%` AND no manifest match | ~105 lower bound (date-only); ticker-aware count higher | Mark `quarantine_reason = 'step_unverified'` via gate-run script after migration | Never serve | Serve-time gate already filters; at-rest mark prevents bypass via raw readers (admin tools excepted). |
| **Post-epoch, MoS out of band** | `mos_pct < -90` OR `mos_pct > +200` | Not counted here; gate rule R3 handles | Mark `quarantine_reason = 'mos_out_of_band'` via gate-run script | Never serve | Implausible value; both gate rules and at-rest filter exclude. |

---

## §6 Escalations — items worse than (or adjacent to) the operator framing

1. **Duplicate indexes on `fair_value_history`.** The table carries two pairs of redundant single-column indexes (`ix_fair_value_history_date` + `ix_fv_history_date`; same for ticker). Cost: 2× write amplification on inserts, 2× disk. Not in scope for this disposition, but Agent A v3's migration is a natural moment to drop the older pair. Recommend a follow-up cleanup task.

2. **No `cache_invalidation_manifest` table exists in prod.** The brief's instruction "Query `cache_invalidation_manifest`" was a category error — the manifest is a Python literal, not a DB table. This means: there is no DB-side enforcement that the manifest is what the code says it is, and there is no audit trail of WHEN entries were added (only what the code SAYS the `applied_at` is). If a future engineer edits a historical `applied_at` in the Python source to make a step look corroborated, the forgery is invisible at the DB layer. **This is the exact failure mode the new Manifest invariants section in `CLAUDE.md` forbids — but the only enforcement is social.** Recommend: a future migration that mirrors `MANIFEST` into a Neon table with `created_in_db_at` populated server-side, so backdating `applied_at` in code AFTER the fact becomes detectable. Not in scope for Phase 1, but flag for Phase 1.5.

3. **The post-epoch uncorroborated step count of ~105 is a date-only lower bound.** The serve-time gate enforces ticker-aware matching (manifest entry must include the ticker in `scope.tickers` or be `"*"`). The true count of `step_unverified` rows is what the gate produces when run over the full table. The migration's data-fill step (and the test in precondition 5) MUST use the gate as the source of truth, not the number 105.

4. **`updated_at` column has no DB-side default.** It is `nullable` with no default at the SQL level — the only thing populating it is SQLAlchemy's `onupdate=datetime.utcnow`. Any direct SQL INSERT (including from the upcoming migration script if it ever needs to backfill `quarantine_*` via INSERT rather than UPDATE) will leave it NULL. Recommend adding `DEFAULT NOW()` while A v3's migration is open. Minor; mentioning for the same reason as the duplicate-index item.

5. **The 40,139 pre-epoch rows include the entire pre-2026-05-22 history back to 2025-05-30.** That's a year of fossilised engine output. Once marked, they remain in the table forever (per the "marks are append-only" rule). At ~40k rows this is fine, but if the operator ever wants to truly purge for storage reasons, it will require a separate audited operation. Document this trade-off in the Phase 1 spec.

---

## §7 What this document does NOT do

- Does not apply any migration. The `.sql` blocks above are PROPOSALS for Agent A v3.
- Does not touch the database (read-only session verified).
- Does not modify `CACHE_VERSION`.
- Does not add or edit manifest entries.
- Does not edit `backend/services/fair_value_history_gate.py` or `backend/routers/valuation_history.py` or any other backend code.

End of disposition.
