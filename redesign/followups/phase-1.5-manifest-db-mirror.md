# Phase 1.5 — Manifest DB Mirror (enforcement mechanism for the no-forgery invariant)

**Status:** filed 2026-06-03. Tracker only — not yet dispatched.
**Workstream:** valuation
**Priority:** ahead of cosmetic work. Does NOT block the current Phase 1 FV-history clean-data chain (gate works on rows as they are today).

---

## Why this is a P0 invariant-enforcement task, not "structural nice-to-have"

On 2026-06-03 we ratified into `CLAUDE.md` (Manifest invariants section):

> **Corroboration must be contemporaneous. Retroactive manifest entries are forgery and are forbidden.**

The FV-history at-rest disposition diagnosis (`redesign/followups/fv-history-at-rest-disposition.md`) immediately surfaced that this invariant is **enforceable only by code review**:

- The manifest is a Python literal at `backend/services/cache_invalidation_manifest.py::MANIFEST`.
- A future engineer editing a historical `applied_at` to make a step look corroborated — or appending a backdated entry to turn a red canary green — is **undetectable at the DB layer**.
- There is no audit trail, no append-only enforcement, no second source of truth.

A CLAUDE.md rule that only a human reviewer can catch is one deadline-pressured afternoon away from being violated by the exact person it is meant to stop. The whole point of the manifest is that its integrity cannot depend on everyone always being honest under pressure.

So this is not "structural fix." This is **the enforcement mechanism for the invariant that the FV-history trust feature now hinges on.**

---

## What Phase 1.5 builds

A second source of truth in Neon that the Python literal manifest is mirrored TO, with append-only semantics and server-side timestamps that cannot be backdated.

### Schema (proposed, refine when dispatched)

```sql
CREATE TABLE manifest_entries (
    id              SERIAL PRIMARY KEY,
    entry_id        TEXT NOT NULL UNIQUE,        -- e.g. 'v_init_2026_05_22'
    applied_at      DATE NOT NULL,                -- the claimed deploy date (from code literal)
    created_in_db_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),  -- server-side, cannot be set by client
    tickers         TEXT[] NOT NULL,
    fields          TEXT[] NOT NULL,
    reason          TEXT NOT NULL,
    git_sha         TEXT,                          -- commit that introduced this entry (filled by CI)
    pr_url          TEXT                           -- PR that landed this entry (filled by CI)
);

-- Append-only enforcement
CREATE OR REPLACE FUNCTION manifest_entries_no_update_delete() RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'manifest_entries is append-only — UPDATE/DELETE forbidden (operation: %)', TG_OP;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER manifest_entries_locked
    BEFORE UPDATE OR DELETE ON manifest_entries
    FOR EACH ROW EXECUTE FUNCTION manifest_entries_no_update_delete();

-- Backdating-detection constraint
ALTER TABLE manifest_entries
    ADD CONSTRAINT manifest_no_backdating
    CHECK (created_in_db_at::date >= applied_at);
-- Reasoning: applied_at can be EARLIER than created_in_db_at (entries written later than
-- their claimed deploy date are suspicious — flag for review).
-- Future enhancement: harden to <= 7 days lag when the migration backfill is complete.
```

### Wire-in

1. A startup hook (or CI job) iterates `MANIFEST` and `INSERT ... ON CONFLICT (entry_id) DO NOTHING` into `manifest_entries`. First write wins; subsequent edits to the code literal are detected as a mismatch.
2. A periodic checker (cron + admin endpoint) compares the code literal against `manifest_entries`. Any divergence raises an alert:
   - Entry in code but not in DB → new, expected (will be inserted on next startup).
   - Entry in DB but not in code → deleted from code literal = forgery attempt.
   - Same `entry_id` but different `applied_at` / `reason` → in-place edit = forgery attempt.
3. Gates (cache_version_check, fair_value_history_gate) that consult the manifest read from `manifest_entries` (DB source of truth), not from the code literal.

### What this catches

- **Deleting an entry from the code literal to remove inconvenient history** — DB still has it, divergence checker fires.
- **Editing a historical `applied_at` to make a step look corroborated** — DB has the original, divergence checker fires.
- **Appending a backdated entry to turn a red canary green** — entry's `created_in_db_at` is today, `applied_at` is in the past; backdating-detection constraint flags it for review (and the gate's corroboration window check should be tightened to compare against `created_in_db_at`, not `applied_at`, so a backdated entry simply doesn't corroborate anything older).

### What this does NOT catch

- An engineer with direct prod DB write access deleting from `manifest_entries` table. Mitigated by the append-only trigger but a determined operator with DDL rights can drop the trigger. Defense-in-depth needs: (a) the trigger, (b) row-level audit on `manifest_entries` table itself, (c) restricted DB roles for migration vs application.
- Forgery via direct DCF engine recompute (writing a "today's number on yesterday's date" row directly). That's a different category — handled at write-side by the `quarantine_reason='pre_manifest_epoch'` mark from migration 076 + the no-recompute-pre-epoch precondition on Agent A v3's migration.

---

## Sequencing notes

- This is INDEPENDENT of the Phase 1 clean-data chain (migration 076 → A v3 → gate → Agent B → Cluster D). The chain ships against the current Python-literal manifest; the literal continues to work as the source of truth for now.
- Phase 1.5 can dispatch any time AFTER Cluster D ships, ideally within the same release cycle so the invariant doesn't sit unenforced in prod.
- Dispatch shape: small focused agent, standing rules apply, ~one PR adding migration + table + trigger + startup hook + admin checker endpoint. Estimated ~500–800 LoC.

---

## Cross-references

- `CLAUDE.md` Manifest invariants section (the ratified rule this enforces)
- `redesign/followups/fv-history-at-rest-disposition.md` §7 (the escalation that surfaced the gap)
- `backend/services/cache_invalidation_manifest.py` (the code literal that becomes the secondary source after this lands)
