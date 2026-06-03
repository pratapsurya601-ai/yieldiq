# Phase 1 quarantine-fill migration — operator prod-apply playbook

**Audience:** operator (irreversible-on-prod step) + the eventual fill-migration agent (must encode these assertions IN the migration).
**Status:** playbook authored 2026-06-03. The fill migration itself has NOT been written yet — it dispatches AFTER Agent A v3's superset schema is PROD-APPLIED-AND-VERIFIED, not after it merges.

---

## Why a playbook (not just a checklist)

The fill migration marks **exactly 40,139 pre-epoch rows** (rows where `date < '2026-05-22'`) with `quarantine_reason = 'pre_manifest_epoch'`, in a single transaction against production. It is the single most data-consequential manual step in the entire FV-history clean-data chain. The migration count was computed by the disposition agent against current prod state (`fv-history-at-rest-disposition.md` §1).

A migration that marks 40,140 or 39,998 rows means the epoch boundary logic drifted between when the count was computed (2026-06-03) and when the migration is applied. A migration that marks 40,139 *in total* but with the wrong distribution (some post-epoch rows marked, some pre-epoch missed) would pass a bare total-count check while silently corrupting the at-rest defense.

Both classes of error must fail loud, in-transaction, before `COMMIT`.

---

## Agent-side requirements (fill migration spec)

When the fill migration is dispatched, its spec MUST require the migration to include:

### 1. Total-count assertion
```sql
DO $$
DECLARE
    expected_pre_epoch INT := 40139;  -- baseline from fv-history-at-rest-disposition.md §1 (2026-06-03)
    actual_pre_epoch INT;
BEGIN
    SELECT COUNT(*) INTO actual_pre_epoch
    FROM fair_value_history
    WHERE date < '2026-05-22' AND quarantine_reason IS NULL;
    -- Note: this counts UNMARKED pre-epoch rows BEFORE the UPDATE.
    -- If the migration is re-run, this will be 0 (idempotent).

    IF actual_pre_epoch != expected_pre_epoch THEN
        RAISE EXCEPTION 'Pre-epoch row count drift: expected %, found % (boundary or population changed since 2026-06-03)',
            expected_pre_epoch, actual_pre_epoch;
    END IF;
END $$;
```

Operator may need to adjust `expected_pre_epoch` if days pass between the disposition diagnosis and the fill apply — the disposition agent should be re-run if the gap is > a few days. Default to "if you're applying within 14 days of 2026-06-03, the count should still be 40,139 ± 0 (the table doesn't backfill historical rows)."

### 2. Post-epoch contamination assertion (CRITICAL — the one the operator's playbook addition catches)
```sql
DO $$
DECLARE
    contaminated_post_epoch INT;
BEGIN
    -- Run this AFTER the UPDATE, BEFORE COMMIT.
    SELECT COUNT(*) INTO contaminated_post_epoch
    FROM fair_value_history
    WHERE date >= '2026-05-22'
      AND quarantine_reason = 'pre_manifest_epoch';

    IF contaminated_post_epoch > 0 THEN
        RAISE EXCEPTION 'Post-epoch contamination: % rows dated >= 2026-05-22 were marked pre_manifest_epoch (boundary logic wrong)',
            contaminated_post_epoch;
    END IF;
END $$;
```

A migration that marks 40,139 rows total but with one row on the wrong side of the boundary indicates the WHERE clause used `<=` instead of `<` or off-by-one on the date. The total-count check alone won't catch it.

### 3. Total-row-count audit (catch broader drift)
```sql
DO $$
DECLARE
    total_rows INT;
    expected_total INT := 56964;  -- baseline from disposition diagnosis 2026-06-03
BEGIN
    SELECT COUNT(*) INTO total_rows FROM fair_value_history;
    IF abs(total_rows - expected_total) > 200 THEN
        -- 200-row drift tolerance: the table grows by ~daily-cron writes;
        -- a few days of normal ingestion should be < 200 new rows.
        RAISE WARNING 'fair_value_history row count drifted: expected ~%, found % (verify before COMMIT)',
            expected_total, total_rows;
    END IF;
END $$;
```

Warning, not exception — table growth is expected. But a drift of thousands signals something else happened to the table between baseline and apply.

### 4. Migration must be wrapped in an explicit transaction
Not relying on implicit per-statement transactions or autocommit. Explicit `BEGIN; … ; COMMIT;` so the operator can `ROLLBACK` if any assertion fires.

### 5. Idempotent re-runnable
Re-running the migration after a successful first apply must be a no-op (no rows changed, all assertions pass with 0 unmarked pre-epoch rows). The `quarantine_reason IS NULL` clause in the UPDATE WHERE handles this.

---

## Operator prod-apply ceremony

When you receive the fill-migration PR + it's reviewed + merged, before applying to prod:

### Step 1 — Staging copy
Neon branch off prod, restore-from-the-latest-snapshot. **Run the entire migration against the staging branch first.** The migration's own `RAISE EXCEPTION` assertions fail loud here if anything is wrong.

### Step 2 — Inside-transaction sample check on staging
After the migration's assertions pass on staging but before `COMMIT` (use `psql --set ON_ERROR_ROLLBACK=interactive`):
```sql
-- Boundary sanity (eyeball, don't automate):
SELECT date, COUNT(*) FILTER (WHERE quarantine_reason IS NULL) AS unmarked,
                     COUNT(*) FILTER (WHERE quarantine_reason = 'pre_manifest_epoch') AS marked
  FROM fair_value_history
 WHERE date BETWEEN '2026-05-19' AND '2026-05-25'
 GROUP BY date
 ORDER BY date;
```

Expected output:
- `2026-05-19`, `2026-05-20`, `2026-05-21` → unmarked=0, marked=N
- `2026-05-22`, `2026-05-23`, `2026-05-24`, `2026-05-25` → unmarked=N, marked=0

If any 2026-05-22+ row is `marked > 0`, or any pre-5/22 row is `unmarked > 0`, the boundary logic is wrong. ROLLBACK, fix, re-derive.

### Step 3 — Eyeball 5 random tickers on staging
```sql
-- For 5 random tickers, show how the quarantine landed across their history:
WITH sample AS (
    SELECT DISTINCT ticker FROM fair_value_history
    ORDER BY random() LIMIT 5
)
SELECT t.ticker, MIN(h.date) AS earliest, MAX(h.date) AS latest,
       COUNT(*) FILTER (WHERE quarantine_reason IS NOT NULL) AS marked_count,
       COUNT(*) FILTER (WHERE quarantine_reason IS NULL) AS kept_count
  FROM sample t JOIN fair_value_history h ON h.ticker = t.ticker
 GROUP BY t.ticker
 ORDER BY t.ticker;
```

For each sample ticker: marked rows should all be pre-2026-05-22, kept rows should all be post-2026-05-22. Eyeball.

### Step 4 — COMMIT on staging, verify post-commit query identical to pre-COMMIT sample
Sanity that nothing changed across the commit boundary.

### Step 5 — Apply to prod
Same migration, same transaction model, all assertions fire in prod too. ROLLBACK if any assertion exceptions. Note the operator's session ID + timestamp in the eventual manifest entry that records this migration's apply.

### Step 6 — Post-apply verification on prod
```sql
SELECT quarantine_reason, COUNT(*)
  FROM fair_value_history
 GROUP BY quarantine_reason
 ORDER BY quarantine_reason NULLS FIRST;
```

Expected:
- `NULL` → 16,825 rows (16,479 post-epoch small-step + 181 post-epoch no-step + 165 post-epoch step ≥25% rows that the FILL migration leaves for the gate to filter at serve-time — adjust based on what the fill migration actually does for post-epoch step rows)
- `pre_manifest_epoch` → 40,139 rows

Sum should equal the total `fair_value_history` row count.

---

## What this playbook does NOT cover

- Post-epoch uncorroborated-step marking. The fill migration handles only `pre_manifest_epoch` rows. Post-epoch `step_unverified` marking is a separate migration that MUST call the FV-history gate (`fair_value_history_gate.filter_history_rows`) to determine which rows to mark — it MUST NOT hard-code the 105 lower-bound number from the disposition diagnosis (which is a date-only ticker-blind lower bound; the actual count is higher and only the gate's full ticker-aware rule can compute it). That's a separate playbook when the time comes.
- Cluster D dispatch. Cluster D waits for: this migration applied + the post-epoch fill migration applied + the gate merged + Agent B endpoint live. See `redesign/spec.md` §14.

## Cross-references

- `redesign/followups/fv-history-at-rest-disposition.md` (the 40,139 baseline, the schema delta, the precondition)
- `redesign/followups/fv-history-event-2026-05-17.md` (why the epoch boundary is 2026-05-22)
- `CLAUDE.md` data-fix discipline (the rules this playbook operationalizes for the highest-stakes apply step in the chain)
