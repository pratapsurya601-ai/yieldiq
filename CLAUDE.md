# YieldIQ — root agent guidance

See `frontend/CLAUDE.md` for frontend conventions and the existing
project memory (`memory/project_yieldiq.md`, `memory/feedback_yieldiq_discipline.md`)
for product-level discipline.

## Data-fix discipline (added 2026-04-19 after re-audit)

Three rules. No exceptions.

1. **Never ship a data fix without running canary-diff first.**
   `python scripts/canary_diff.py` must exit 0 BEFORE merging any PR
   that touches: `backend/services/`, `backend/routers/`, `backend/validators/`,
   `backend/models/`, `scripts/canary_stocks_50.json`.
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
