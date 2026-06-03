# Large-move-vs-corruption detection: unify on corroboration, not magnitude

**Status:** filed 2026-06-03. Tracker only. NOT urgent, NOT blocking — strategic.
**Workstream:** valuation
**Priority:** ahead of cosmetic work. Sibling to Phase 1.5 (manifest DB mirror) — both are "make a recurring per-layer invariant structural instead of per-layer band-aid."

---

## The recurring false-positive class

The system has no principled way to distinguish "real large move" from "corrupt large move." A 400% IPO-year revenue jump and a 400% unit-error spike look IDENTICAL to a magnitude threshold. Every layer that tries to make this call has independently reinvented the same false-positive:

1. **`backend/services/cagr_service.py::_SANITY_ABS_CAP = 100`** — admits any CAGR with `|pct| <= 100`. Catches obvious unit bugs; can't catch the WIPRO -77% artifact and also can't reject legitimate ±90% cyclical swings. Per the WIPRO §11.6 diagnosis (`wipro-cagr-blast-radius.md`), the cap is doing essentially no work (p99=85%, max=98%, never fires) AND would false-reject 9 real names if tightened to 75%.

2. **`fair_value_history_gate.py` step check (≥25% day-over-day FV move requires manifest corroboration)** — uses corroboration. This is the right pattern. The 2026-05-17 and 2026-04-29 events are caught precisely because they have no contemporaneous manifest entry.

3. **`v_financials_unified.cf_is_corrupt` flag** — current rule: ≥1 |YoY| > 50% pair in canonical series OR ≥1 true duplicate. Per the 2026-06-03 source-aware re-count (`corruption-recount-2026-06-03.md`), this rule produces 146 flags in canary, of which a non-trivial fraction (JIOFIN, NTPCGREEN, ZOMATO IPOs) are LEGITIMATE large moves. Will over-flag.

4. **`isHealthyScenarioSpread` / `has_suspect_growth_inputs` in `frontend/src/lib/scenarios.ts`** — uses `_NEAR_CAP_THRESHOLD = 75.0` to gate scenario placement. Same magnitude-based heuristic. Will over-flag legitimate cyclical names with real ±75% growth.

Pattern: **four layers, four magnitude thresholds, four sources of false positives in the same direction (legitimate IPO/cyclical → looks corrupt → demoted).**

## The honest fix

Move all four to a corroboration-first rule. **A large move is legitimate when it is corroborated by an independent source; suspect otherwise.** Sources of corroboration include:

- **A second data table** agreeing (the `v_financials_unified` pattern — but extended: don't just pick one row, USE the disagreement signal — when two sources disagree by >X%, that's the actual corruption tell, not the magnitude of the move in any single source).
- **A corporate-action record** (the corp_actions table already exists; IPOs, splits, bonus issues land here).
- **A filing event** (BSE/NSE timeline shows an event date matching the financial period).
- **A manifest entry** (the FV-history gate's existing mechanism, extended to data layer).
- **A peer-cohort signal** (if the entire sector moved 60% the same year — sector-wide commodity shock — that's corroboration; if one ticker moved 60% alone, suspect).

The FV-history gate has already built the pattern. The strategic move is to recognize it as a SHARED PRIMITIVE and apply it to the other three layers.

## What this work looks like

1. **A `large_move_corroboration_service`** at `backend/services/` exposing one function: `is_corroborated(ticker, metric, from_value, to_value, period) -> CorroborationVerdict` returning `Literal['corroborated', 'uncorroborated', 'insufficient_evidence']` + a reason payload.
2. **The four current heuristics rewired to call it** — `_SANITY_ABS_CAP` becomes a fallback for truly extreme cases (|pct| > 1000% etc.); the primary rule is corroboration. Same for `cf_is_corrupt`, the gate step-check, and `has_suspect_growth_inputs`.
3. **Each rewiring runs through canary-diff** — verify that legitimate IPO/cyclical names un-flag and genuine corruption stays flagged.

## Sequencing

- **Not in Phase 1's critical path.** The FV-history gate's step check works as-is; the other three layers' false positives are tolerable in the short term (they fail-safe — over-flag is a soft error, lost trust on legitimate names is the cost).
- **Sequence AFTER:** PR #703 merges, consumer-rewiring PR merges (so the architecture has `v_financials_unified` as the read layer + the FV-history gate is live + the consumer surfaces all flow through the new column-filter). Then this work has clean attach points.
- **Sequence BEFORE:** any further "tighten the cap" / "tighten the threshold" PR. Those PRs are how the false-positive class survives — each tightening trades one false negative for several false positives. The strategic fix retires the whole tradeoff.

## What this is NOT

- Not a fix for any specific user-facing bug today. The current heuristics are tolerable; this is structural debt that gets paid down to retire a recurring pattern.
- Not blocking the redesign. Cluster D ships with the existing heuristics; this work happens after.

## Cross-references

- `redesign/followups/wipro-cagr-blast-radius.md` (the `_SANITY_ABS_CAP` discovery that revealed the pattern)
- `redesign/followups/fv-history-event-2026-05-17.md` (the gate's corroboration mechanism — the existing-correct example)
- `redesign/followups/corruption-recount-2026-06-03.md` (the `cf_is_corrupt` over-flag risk on IPO names)
- `redesign/spec.md` §4 (`isHealthyScenarioSpread` / `has_suspect_growth_inputs` predicates — the 4th layer)
- `redesign/followups/phase-1.5-manifest-db-mirror.md` (sibling structural tracker)
