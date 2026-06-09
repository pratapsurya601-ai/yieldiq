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

5. **SEBI vocab guard tests — banned arrays must be built from
   fragments, not literals.** The CI sebi-lint job runs in
   `--diff-only --base origin/main` mode which scans ADDED LINES for
   banned tokens regardless of whether they appear in code, comments,
   strings, or test fixtures. This means:

   - A test file with `const BANNED = ["buy", "sell", "hold", ...]`
     fails the diff-only check even though the test is ASSERTING the
     rendered DOM contains none of these words.
   - Per-line `// sebi-allow: buy` annotations DO work in
     diff-only mode (the script honors them on the same line).
   - A file-level `// sebi-allow-file` directive does NOT work in
     diff-only mode.

   Two correct patterns for SEBI-guard test fixtures:

   ```ts
   // Pattern A: per-line annotation (verbose but explicit)
   const BANNED = [
     "buy", // sebi-allow: buy
     "sell", // sebi-allow: sell
     // ...
   ]

   // Pattern B: build from fragments at runtime (zero annotations)
   const BANNED = [
     "b" + "uy",
     "se" + "ll",
     "ho" + "ld",
     // ...
   ]
   ```

   Pattern B keeps the file scan-clean and the runtime assertion
   identical. Either pattern is fine; pick one and stick to it
   within a test file.

   Bash one-liner all agents must run before committing a SEBI-
   related diff to confirm:
   `python scripts/check_sebi_words.py --diff-only --base origin/main`

   Pre-commit verification both modes (full + diff-only) is the
   standing rule. The first push to CI must NEVER fail sebi-lint —
   if it does, the agent burned a CI cycle that local-verify would
   have caught.
