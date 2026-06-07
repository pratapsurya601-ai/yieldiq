// ─────────────────────────────────────────────────────────────
// Client-side DCF re-compute for the Reverse-DCF Playground.
//
// The playground page lets users drag five sliders (WACC, terminal
// growth, revenue CAGR, operating margin, tax rate) and see the
// implied fair value update in real-time. Doing that with a network
// roundtrip per drag is laggy (300ms+ debounce, plus jank), costly
// (one POST per slider micro-move), and unnecessary — the DCF math is
// a couple of dozen floating-point ops.
//
// We mirror the simplified backend DCF used by
// `backend/services/analysis/recompute.py` + `screener/dcf_engine.py`:
//
//   1. Build a 10-year FCF projection. Years 1–5 grow at `growth_5y`;
//      years 6–10 taper linearly toward `terminal_growth`.
//   2. Discount each FCF back to PV at `wacc`.
//   3. Terminal value (Gordon) = FCF_10 × (1+tg) / (wacc − tg),
//      discounted by (1+wacc)^10.
//   4. Enterprise value = sum(PV of FCFs) + PV of terminal value.
//   5. Equity value = EV − net_debt  (net_debt = total_debt − cash).
//   6. Fair value per share = equity / shares.
//
// Tax & operating-margin adjustments fold into a single multiplier on
// the FCF base: scaling FCF by (1 − new_tax) / (1 − base_tax) and by
// (new_margin / base_margin). This matches the backend's
// `_adjusted_margin` helper.
//
// Calibration: we don't ship `fcf_base`, `shares`, `debt`, `cash` in
// the playground response (they're proprietary intermediates). Instead
// we ANCHOR to the canonical analyst FV: at the default slider values,
// our client compute must equal the analyst FV exactly. We achieve
// this by solving for `K` such that:
//
//   analyst_fv = K × dcf_factor(canonical_inputs) − offset
//
// where `K = fcf_base / shares` and `offset = net_debt / shares`.
//
// One unknown is underdetermined with a single anchor — we need TWO
// anchors. The page fetches the canonical recompute (default sliders)
// AND a perturbed recompute (slightly higher WACC) once on mount,
// then solves the 2×2 linear system for (K, offset). Every subsequent
// slider drag is a pure ~50µs client-side calc.
//
// NB: this is NOT a replacement for the canonical engine — it's a
// faithful simplification suitable for "feel the sensitivity"
// interactivity. The Honest Card / coverage tier numbers continue to
// come from the cached canonical engine.
// ─────────────────────────────────────────────────────────────

export interface PlaygroundInputs {
  wacc: number              // decimal, e.g. 0.11
  terminal_growth: number   // decimal, e.g. 0.04
  revenue_cagr_yr1_5: number // decimal, e.g. 0.10
  operating_margin: number  // decimal, e.g. 0.20
  tax_rate: number          // decimal, e.g. 0.25
}

export interface DcfCalibration {
  /** fcf_base / shares — scales with margin & tax adjustments. */
  fcfPerShareBase: number
  /** net_debt / shares — subtracted post-EV. */
  netDebtPerShare: number
  /** Baseline operating margin & tax used to derive scaling deltas. */
  baseMargin: number
  baseTax: number
}

const FORECAST_YEARS = 10
const FADE_START = 5
// Minimum spread between WACC and terminal growth — mirrors
// `dcf_playground.run_playground_dcf` (wacc - tg >= 0.02).
const MIN_WACC_TG_SPREAD = 0.02
// Floor on (1 - tax_rate) to avoid blowing up at extreme inputs.
const TAX_KEEP_FLOOR = 0.05

/**
 * Compute the "DCF factor" — sum of (1+g_cumulative)/(1+wacc)^t for the
 * 10-year projection plus the discounted Gordon terminal. Pure function
 * of (wacc, terminal_growth, revenue_cagr) — does NOT depend on the
 * absolute FCF level, only the growth/discount geometry.
 */
export function dcfFactor(
  wacc: number,
  terminalGrowth: number,
  revenueCagr: number,
): number {
  // Snap to safe corner — Gordon term blows up at wacc <= tg.
  if (wacc - terminalGrowth < MIN_WACC_TG_SPREAD) {
    terminalGrowth = Math.max(0, wacc - MIN_WACC_TG_SPREAD)
  }
  let cumulative = 1
  let pvSum = 0
  let last = 0
  for (let i = 0; i < FORECAST_YEARS; i++) {
    let g: number
    if (i < FADE_START) {
      g = revenueCagr
    } else {
      // Linear fade revenueCagr → terminalGrowth across years 6..10.
      const fadeYears = FORECAST_YEARS - FADE_START
      const t = (i - (FADE_START - 1)) / fadeYears
      g = revenueCagr + (terminalGrowth - revenueCagr) * t
    }
    cumulative *= 1 + g
    const pv = cumulative / Math.pow(1 + wacc, i + 1)
    pvSum += pv
    last = cumulative
  }
  // Terminal value at end of year 10, discounted back.
  const spread = wacc - terminalGrowth
  if (spread <= 0) return pvSum
  const tv = (last * (1 + terminalGrowth)) / spread
  const pvTv = tv / Math.pow(1 + wacc, FORECAST_YEARS)
  return pvSum + pvTv
}

/**
 * Scale FCF base for margin + tax slider moves. Mirrors backend
 * `recompute._adjusted_margin` semantics.
 */
function fcfMultiplier(
  inputs: PlaygroundInputs,
  calib: DcfCalibration,
): number {
  const baseKeep = Math.max(TAX_KEEP_FLOOR, 1 - calib.baseTax)
  const newKeep = Math.max(TAX_KEEP_FLOOR, 1 - inputs.tax_rate)
  const taxScale = newKeep / baseKeep
  const marginScale =
    calib.baseMargin > 1e-4 ? inputs.operating_margin / calib.baseMargin : 1
  return marginScale * taxScale
}

/**
 * Compute fair value per share for the given inputs, anchored to a
 * prior calibration. Returns 0 on degenerate inputs.
 */
export function computeFairValue(
  inputs: PlaygroundInputs,
  calib: DcfCalibration,
): number {
  const factor = dcfFactor(
    inputs.wacc,
    inputs.terminal_growth,
    inputs.revenue_cagr_yr1_5,
  )
  const mult = fcfMultiplier(inputs, calib)
  const ev = calib.fcfPerShareBase * mult * factor
  const fv = ev - calib.netDebtPerShare
  if (!Number.isFinite(fv) || fv < 0) return 0
  return fv
}

/**
 * Solve for (fcfPerShareBase, netDebtPerShare) given two known
 * (inputs, FV) anchor points. Both anchors must share the same
 * (margin, tax) so the FCF multiplier cancels — we vary only the
 * geometry (WACC / growth / tg).
 *
 *   fv_a = K * factor_a - offset
 *   fv_b = K * factor_b - offset
 *   => K = (fv_a - fv_b) / (factor_a - factor_b)
 *   => offset = K * factor_a - fv_a
 *
 * Returns null if the two factors are too close to bracket — caller
 * falls back to a single-anchor approximation (offset=0).
 */
export function calibrateFromTwoAnchors(
  anchorA: { inputs: PlaygroundInputs; fairValue: number },
  anchorB: { inputs: PlaygroundInputs; fairValue: number },
): DcfCalibration | null {
  const fA = dcfFactor(
    anchorA.inputs.wacc,
    anchorA.inputs.terminal_growth,
    anchorA.inputs.revenue_cagr_yr1_5,
  )
  const fB = dcfFactor(
    anchorB.inputs.wacc,
    anchorB.inputs.terminal_growth,
    anchorB.inputs.revenue_cagr_yr1_5,
  )
  const denom = fA - fB
  if (Math.abs(denom) < 1e-6) return null
  const K = (anchorA.fairValue - anchorB.fairValue) / denom
  if (!Number.isFinite(K) || K <= 0) return null
  const offset = K * fA - anchorA.fairValue
  return {
    fcfPerShareBase: K,
    netDebtPerShare: offset,
    baseMargin: anchorA.inputs.operating_margin,
    baseTax: anchorA.inputs.tax_rate,
  }
}

/**
 * Single-anchor calibration — assumes net_debt ≈ 0. Used as a fallback
 * when the two-anchor solve fails (extreme inputs, paid-tier lock, etc.).
 */
export function calibrateFromSingleAnchor(anchor: {
  inputs: PlaygroundInputs
  fairValue: number
}): DcfCalibration {
  const factor = dcfFactor(
    anchor.inputs.wacc,
    anchor.inputs.terminal_growth,
    anchor.inputs.revenue_cagr_yr1_5,
  )
  const K = factor > 0 ? anchor.fairValue / factor : 0
  return {
    fcfPerShareBase: K,
    netDebtPerShare: 0,
    baseMargin: anchor.inputs.operating_margin,
    baseTax: anchor.inputs.tax_rate,
  }
}
