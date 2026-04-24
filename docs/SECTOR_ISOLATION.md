# Sector Isolation — the merge gate above canary-diff

## The problem this prevents

Between YieldIQ v32 and v35 we shipped six "fixes" that left 4 of 5 stocks
in a worse state. The root cause was invisible to the per-ticker canary:
each fix was scoped in the author's head to one sector (e.g. "adjust
regulated-utility WACC"), but the code path was shared with every other
sector, so the change silently cascaded.

PR #69 is the modern re-enactment:

| Stock       | Intended scope     | Actual shift                 |
| ----------- | ------------------ | ---------------------------- |
| NTPC        | regulated utility  | FV +8% (intended)            |
| SHREECEM    | cement (not scoped)| FV -71% (regression)         |
| AMBUJACEM   | cement (not scoped)| FV -35% (regression)         |
| BHARTIARTL  | telecom (not scoped)| score +16 (suspicious)      |

The per-ticker canary reported `investigate` on each of these, but had no
way to frame the finding as "three out of three Cement stocks moved the
same way — that is not drift, that is leakage."

The sector-isolation gate operates one layer above canary-diff. It
aggregates the canary-50 by sector, diffs each sector's median FV,
median yieldiq-score, and median MoS against a committed baseline
(`scripts/sector_snapshot.json`), and requires PR authors to *declare*
which sectors they meant to touch.

## How to declare sector-scope on a PR

Add a single line anywhere in the PR body:

```
sector-scope: Cement, Banks
```

Use the sector labels from `scripts/canary_stocks_50.json` (case-
insensitive). Valid examples:

```
sector-scope: Cement
sector-scope: Banks, NBFC, Insurance
sector-scope: Utilities
```

For a change that legitimately cuts across every sector (e.g. a
framework refactor to the yieldiq-score weights), use the wildcard:

```
sector-scope: *
```

The wildcard is auditable — every wildcard PR is visible in `git log`
and every one of them is expected to move the baseline, so rebaselining
right after merge is the norm.

## Thresholds

| Metric        | Drift that counts as a "shift" |
| ------------- | ------------------------------ |
| median FV     | greater than 5%                |
| median score  | greater than 3 points          |
| median MoS    | advisory only (informational)  |

A sector with fewer than 2 tickers carrying valid data is reported as
`insufficient_data` and does NOT gate — we never block a merge because
one illiquid stock dropped out of the feed.

## What to do when the gate fails unexpectedly

1. **Read the table.** The CI comment shows every sector, its status,
   the drift on each metric, and whether that sector was declared in
   the PR body. Unexpected shifts are the only thing that fails the
   gate.

2. **Run locally with verbose output:**

   ```bash
   export CANARY_API_BASE=https://api.yieldiq.in
   export CANARY_AUTH_TOKEN=<admin jwt>
   python scripts/sector_isolation_check.py --verbose
   ```

3. **Triage per-ticker.** Inside a shifted sector, run the existing
   canary-diff to see which individual stocks moved:

   ```bash
   python scripts/canary_diff.py
   ```

   Then inspect the offending tickers via `/api/v1/analysis/<TICKER>.NS`
   to find the upstream cause.

4. **Decide.** One of:

   - **It is a bug.** Fix it. The gate stays red until the sector
     medians return to baseline.
   - **The shift is intentional and in scope.** Add the sector to the
     `sector-scope:` line in the PR body. Push. Gate re-runs and passes.
   - **The shift is intentional and cross-sector.** Use
     `sector-scope: *`. Plan to rebaseline post-merge (see below).

## Rebaselining after an intentional change

Rebaselining is a deliberate, human-in-the-loop action. It is NOT a
merge gate escape hatch. Do it *after* the PR merges, once per-ticker
triage on every shifted sector has confirmed the new numbers are
correct.

```bash
python scripts/update_sector_snapshot.py \
  --reason "PR #71 Cement WACC refresh — per-ticker triage: SHREECEM +8%, ULTRACEMCO +6%, AMBUJACEM +4%, all expected from new WACC table"
```

The script will:

1. Fetch the current canary-50 from production.
2. Check the existing baseline. If there are unexpected shifts (i.e.
   sectors that moved but are not covered by any explanation), it
   refuses to overwrite. Use `--force` *only* for initial seeding or
   emergency rebaselines, and cite the triage in `--reason`.
3. Append `{"at": ..., "reason": ..., "commit": ...}` to the snapshot's
   changelog. This history is committed and reviewable.
4. Atomically replace `scripts/sector_snapshot.json`.

Commit the new `sector_snapshot.json` as its own PR (or as part of the
follow-up PR) so reviewers can see the baseline move.

## Design notes

- **Sector taxonomy:** the human-readable `sector` label on
  `scripts/canary_stocks_50.json` is canonical for this gate. The
  analysis service internally uses `models.industry_wacc.detect_sector`
  (which returns snake_case keys like `regulated_utility`) for WACC
  selection, but PR authors write English and a curated label list is
  stabler than a code-derived one. A shift in a `detect_sector` bucket
  still manifests as per-ticker drift inside the canary bucket.

- **Composition with canary-diff:** `sector_isolation_check.py` imports
  the canary-diff harness for HTTP, field extraction, verdict-aware
  skipping, and state collection. It does not duplicate any fetching.

- **Runtime budget:** under three minutes. Shares the same 50-ticker
  fetch that canary-diff does. Can reuse a canary snapshot via
  `--state-from scripts/snapshots/<file>.json`.
