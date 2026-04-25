# Formula Source of Truth

Status: introduced 2026-04-25 in `feat/formula-source-of-truth`.
Owner: backend/services/analysis.

## The bug class this eliminates

On 2026-04-25 a TITAN tooltip rendered a 130% Margin of Safety while
the backend returned 56%. Cause:

| Layer | Formula |
|-------|---------|
| Frontend tooltip (`metric_explanations.ts`) | `(Fair Value − Current Price) ÷ Fair Value × 100` |
| Backend (`screener/dcf_engine.py`, `service.py`) | `(Fair Value − Current Price) ÷ Current Price × 100` |

Both strings looked plausible. There was no automated check that the
documented formula matched the executed one. The same drift shape hit
the Piotroski "9 signals" tooltip vs the bank-mode 4-signal code, the
YieldIQ Score weights, and others.

## The fix

Each metric is defined ONCE in `backend/services/analysis/formulas.py`
as a `FormulaSpec`:

```python
@dataclass
class FormulaSpec:
    key: str
    label: str
    formula: str       # tooltip-rendered string
    explanation: str   # one-sentence body
    compute: Callable  # backend call site
    inputs: list[str]
    units: str = "percent"
    sector_note: str | None = None
```

Three guarantees:

1. **Backend uses `compute`.** Production callers (`service.py`,
   `ratios_service.py`) route through `FORMULAS_BY_KEY[...].compute(...)`
   — the SAME function whose `formula` string the user sees.
2. **API ships the `formula` string.** `AnalysisResponse.formulas`
   carries `{key: FormulaInfo}` for every registered spec. The
   frontend tooltip prefers this over the hard-coded mirror in
   `lib/metric_explanations.ts`.
3. **CI enforces parity.**
   `backend/tests/test_formula_consistency.py` parses each
   algebraic `formula` string with a sandboxed `eval`, evaluates it
   with deterministic example inputs, and asserts equality with
   `compute(**inputs)`. Non-algebraic specs (Piotroski sum, Moat
   weighted blend, DCF) get custom assertions.

## Tooltip rendering precedence

`<MetricTooltip metricKey="…">`:

1. `data.formulas[metricKey].formula` — backend, **always wins**.
2. `METRIC_EXPLANATIONS[metricKey].formula` — fallback, used only
   when the response carries no `formulas` block (pre-PR cached
   payloads).
3. If neither is present, the `?` icon is hidden.

The `<FormulasProvider value={data.formulas}>` wrapper in
`AnalysisBody.tsx` makes `data.formulas` available to every nested
tooltip without prop drilling.

## Adding a new metric

1. Define a `FormulaSpec` in `backend/services/analysis/formulas.py`.
2. Append it to `ALL_FORMULAS`.
3. Add an example input row in
   `backend/tests/test_formula_consistency.py::EXAMPLES`.
4. If the formula string introduces a new variable name (e.g.
   "Operating Cash Flow"), add it to `SYMBOL_MAP` in that test.
5. If the metric is non-algebraic (sum-of-signals, weighted blend,
   piecewise / engine-internal), write a custom assertion next to
   the existing `test_piotroski_compute_sums_signals` style helpers
   instead of relying on the generic algebraic check.
6. Wire backend callers to invoke `FORMULAS_BY_KEY[...].compute(...)`
   instead of inline arithmetic.
7. The `formulas` field is auto-populated on every response — no
   per-metric router work needed.

## When to bump CACHE_VERSION

**Only if a `compute` callable actually changes the numerical output
it returns.** Editing the `formula` string for clarity, or moving
where `compute` is invoked from, must NOT change cached numbers and
therefore must NOT bump `CACHE_VERSION`. The whole point of this
module is byte-identical backend behaviour with documented formulas.

If you do change a `compute`:

1. Run `python scripts/snapshot_50_stocks.py` BEFORE the bump.
2. Bump `CACHE_VERSION`.
3. Run `python scripts/canary_diff.py --diff-against latest` AFTER.
4. Explain any FV change > 15% on any of the 50 in the PR description.

(Per `CLAUDE.md` §2.)

## Metrics covered in v1

`margin_of_safety`, `fair_value`, `roe`, `roce`, `piotroski_score`,
`moat_score`, `yieldiq_score`, `grade`, `eps_diluted`, `debt_to_equity`.

## Follow-up batches (not yet covered)

The remaining 20+ metrics in `metric_explanations.ts`
(`debt_ebitda`, `interest_coverage`, `current_ratio`, `asset_turnover`,
`ev_ebitda`, `pe_ratio`, `pb_ratio`, `market_cap`, `revenue_cagr_3y`,
`revenue_cagr_5y`, `dividend_yield`, `promoter_holding`, `wacc`,
`cost_to_income`, `nim`, `car`, `nnpa`, `casa`, `advances_yoy`,
`deposits_yoy`, `pat_yoy_bank`, `roa`) still rely on the hard-coded
mirror. The pattern for migrating each one is in this file plus the
v1 PR (`feat/formula-source-of-truth`).
