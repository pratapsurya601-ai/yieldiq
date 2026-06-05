# YieldIQ — root agent guidance

See `frontend/CLAUDE.md` for frontend conventions and the existing
project memory (`memory/project_yieldiq.md`, `memory/feedback_yieldiq_discipline.md`)
for product-level discipline.

## Data-fix discipline (added 2026-04-19 after re-audit)

Three rules. No exceptions.

1. **Never ship a data fix without running canary-diff first.**
   `python scripts/canary_diff.py` must exit 0 BEFORE merging any PR
   that touches: `backend/services/`, `backend/routers/`, `backend/validators/`,
   `backend/models/`, `scripts/canary_universe_180.json`,
   `scripts/canary_stocks_50.json` (legacy, still readable).
   The canary GH Actions workflow enforces this on the PR.

2. **Never bump CACHE_VERSION without a before/after snapshot.**
   Run `python scripts/snapshot_50_stocks.py` BEFORE the bump.
   Run `python scripts/canary_diff.py --diff-against latest` AFTER the
   bump. Any FV change > 15% on any of the 50 must be explained in the
   PR description.

3. **Never declare a bug "fixed" based on a single Chrome MCP test.**
   The fix is fixed when:
   - canary-diff passes 5/5 gates on all 50 stocks
   - 7 consecutive nightly canary runs are clean
   - The fix is reproducible from snapshotted inputs (`computation_inputs`
     in cache, FIX320e5d3)

These rules exist because we shipped 6 "fixes" between v32 and v35
that left 4/5 stocks in a worse state. The canary-diff harness exists
to make this kind of regression impossible to merge.

## Known-flaky CI signals — admin-merge allowed (2026-05-25)

The following checks are known to flake on PRs that do NOT touch their
respective surfaces. When a PR is otherwise green and only one of these
is red, an admin-merge is permitted:

- **canary.yml** (and `canary_diff` / `canary_sweep_weekly`) — Aiven
  Postgres rate-limits during peak nightly compute and flakes on PRs
  that don't touch `backend/services/` engine code.
- **sector-isolation** — Vercel cold-start on `/sector/[slug]` causes
  intermittent 504s; not reproducible locally.
- **dcf-regression** — known to hit a non-deterministic ordering bug
  when two test cases compute the same FV; tracked separately.
- **Vercel /sector pre-render** — Satori HTML overlay rebuild is
  retried up to 3x; first attempt flakes ~10% of the time.
- **Vercel preview build — `/search` page Suspense bailout**
  (added 2026-05-25): `/(app)/search/page.tsx` uses
  `useSearchParams()` without a `<Suspense>` boundary, which fails
  prerender on every preview deploy (and on the main branch too —
  confirmed on HEAD commit `de83aa4`). Reproduces on PRs that do
  not touch `frontend/src/app/(app)/search/**`. Tracked as a
  separate /search-suspense-fix task.

Admin-merge requires: (a) green check elsewhere, (b) the failing
signal listed above, (c) a comment on the PR identifying which flake
fired so we keep a paper trail.

## Manifest invariants (added 2026-06-03 after FV-history audit)

The `cache_invalidation_manifest` exists to record WHEN engine or
data behavior changed, so downstream gates (cache_version_check,
fair_value_history_gate, etc.) can corroborate observed differences
against a documented event. Its value rests on one property:

**Corroboration must be contemporaneous. Retroactive manifest entries
are forgery and are forbidden.**

Concretely:
- A manifest entry's `applied_at` MUST be the actual date the engine
  change was deployed. Never backdate.
- When a historical row, FV step, or cache divergence cannot be
  corroborated by an entry that already existed at the time of the
  change, the correct response is NEVER to add a backdated entry to
  make the gate go green. The correct responses are: (a) recompute
  today and let the new row pass the gate on its own merits, (b)
  quarantine-mark the unverifiable historical row at rest, or (c)
  accept the gate's red signal as informative.
- This rule is why the manifest means anything. The day someone is
  under deadline pressure and a backdated entry would turn a red
  canary green, that is exactly the day this rule earns its place.
  No exceptions, no carve-outs.

The `fair_value_history` table contains a documented pre-manifest
epoch (rows dated before `v_init_2026_05_22`) for which no
corroboration is possible by construction. Those rows are handled by
at-rest quarantine marking, not by retroactive manifest entries.

## Agent-dispatch standing rules (added 2026-06-03 after primitives stale-base + main-worktree-contamination incident)

These apply to EVERY agent dispatch — primitives, clusters,
diagnoses, fixes — without exception. Bake into the prompt template.

1. **Base-SHA verification before first edit.** The agent runs
   `git fetch origin main && git rev-parse HEAD && git rev-parse origin/main`
   BEFORE reading or writing any file beyond what is needed to verify
   the base. Both SHAs must match. If not, recreate the branch off
   the verified fresh tip and re-verify. The base SHA goes in the
   final report verbatim.

2. **Fresh worktree, never the main repo working tree.** The agent
   creates its own `git worktree add` under
   `.agent-worktrees/<task>/` off the verified `origin/main` SHA.
   Never default into `E:\Projects\yieldiq_v7` directly — that
   worktree is shared, mutable, and frequently in a transient state
   (mid-rebase, dirty, on someone else's branch). Cost: ~200–500ms
   plus a worktree path to clean up. Benefit: deterministic
   isolation, no contamination cascades.

3. **Retire by behavior, not by filename.** When a task asks for an
   end-state invariant (e.g. "exactly one sticky scorecard surface"),
   the agent enumerates every candidate component matching the
   BEHAVIOR (grep for `position: sticky` plus scorecard-class data),
   classifies each, then proves the invariant against current main
   AFTER edits. Never retire a file because its name happens to
   match the task description.

These three exist because in one session each was violated and each
produced an incident that would have shipped broken work absent a
diff review.

4. **Migration filenames use timestamp prefixes, not sequential
   integers.** Pattern:
   `YYYYMMDDHHMM_<descriptive_name>.sql` — e.g.
   `202606031145_fair_value_history_quarantine_columns.sql`.

   Sequential integer prefixes (`076_*.sql`) generate collisions when
   parallel agents independently grab "the next slot." This is not
   hypothetical — on 2026-06-03 three parallel agents (Agent A v3
   superset, FV-history quarantine, `v_financials_unified` view) all
   claimed slot 076 simultaneously; PR #703 "won" only by being
   first to push, the others required renumbering or were killed.

   Timestamp prefixes are monotonic enough for migration-runner
   lexicographic ordering and collision-free by construction (two
   agents would have to start the same minute on the same name).
   The operator is removed from the critical path as slot allocator.

   Existing integer-prefixed migrations (`001_*.sql` through
   `076_v_financials_unified.sql` as of 2026-06-03) are NOT
   renumbered — the scheme applies to all NEW migrations from
   2026-06-03 forward. Lexicographic ordering preserves the
   integer-prefixed migrations as the earliest batch, with
   timestamp-prefixed migrations naturally sorting after them
   (`076_…` < `2026…`).

   Standing rule: any agent creating a migration file MUST use the
   timestamp prefix and MUST report the chosen filename in their
   final report. Any agent reading a brief that specifies an integer
   slot for a new migration MUST flag the brief as out-of-date and
   STOP rather than create the conflict.

5. **Read-only by default. Prod state changes require explicit
   per-action operator authorization.** (Added 2026-06-05 after a
   diagnosis agent burned an irreversible lifetime counter on the
   operator's account by clicking Save without per-action approval.)

   Diagnosis, audit, premise-validation, and code-reading tasks are
   read-only. An operator approval to "diagnose" or "investigate"
   does NOT extend to clicking destructive UI elements, submitting
   forms that create real user records, completing OAuth flows that
   mint sessions, writing to prod tables, or any action whose effect
   on production state cannot be undone without admin intervention.

   When a diagnosis appears to require a destructive action to
   complete, the agent MUST stop and request explicit authorization
   for that specific action — naming what will change, what's
   reversible, and what's not. "I'm going to click Save to capture
   the response" requires its own yes, separate from the diagnosis
   authorization that got the agent into the page.

   This applies whether the action is via Chrome MCP UI clicks, a
   curl POST, a direct DB write, or any other path to prod state.
   The mechanism doesn't matter; the irreversibility does.

   Categories that ALWAYS need per-action authorization:
   - Form submission to a backend endpoint that writes to prod
   - OAuth completion (creates auth.users rows + sessions)
   - Any UI click that decrements a counter, uses a lifetime quota,
     consumes a credit, or triggers a side-effect
   - INSERT / UPDATE / DELETE / ALTER against any prod database
   - Razorpay / payment / subscription actions of any kind
   - Email sends, push notifications, webhooks fired at third parties

   Read-only operations that DO NOT need per-action authorization:
   - Navigate, snapshot, screenshot, scroll, hover
   - Read DOM, cookies, localStorage, response headers
   - Inspect network requests AFTER they fire naturally
   - SELECT queries against prod (with SET TRANSACTION READ ONLY)
   - Read code, grep, file inspection
   - Fill form fields WITHOUT submitting them

   This rule exists because the read-only / write-prod boundary is
   the line where "let me check" silently becomes "I changed
   something you'll have to manually undo." The agent that triggered
   this rule was honest about the cost AFTER the click; the rule
   makes the honesty mandatory BEFORE.
