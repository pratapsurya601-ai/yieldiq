/**
 * tax-india.ts — pure helpers for Indian equity capital-gains math.
 *
 * Rules encoded (FY 2025-26 baseline, retail equity / equity-MF):
 *   - Holding period < 12 months  → STCG  → 15% flat on gain
 *   - Holding period ≥ 12 months  → LTCG  → 10% on gain ABOVE the
 *                                            ₹1,00,000 annual exemption
 *   - Health & Education Cess     → 4% surcharge on the tax amount
 *
 * Scope notes (intentionally narrow):
 *   - Only listed-equity / equity-oriented MF rates. Debt-MF, real
 *     estate, gold, unlisted equity, slab-rate scenarios are NOT
 *     modelled — they would require separate routines and slab inputs.
 *   - Surcharge tiers (10/15/25/37%) on income >₹50L are ignored at
 *     this layer; cess is the only surcharge applied. Caller can wrap
 *     these helpers with their own surcharge layer if needed.
 *   - LTCG exemption is per-financial-year and applies to the SUM of
 *     all eligible gains — these helpers treat the ₹1L bucket as a
 *     single-position approximation. A portfolio-aware reducer can
 *     allocate the exemption across positions externally.
 *
 * Every function is pure, side-effect free, and synchronous so it can
 * be reused from React event handlers, server-side renders, and unit
 * tests without environment plumbing.
 */

/** Long-term threshold for listed equity / equity MF, in months. */
export const LTCG_THRESHOLD_MONTHS = 12

/** Short-term capital-gains rate on listed equity (flat). */
export const STCG_RATE = 0.15

/** Long-term capital-gains rate above the annual exemption. */
export const LTCG_RATE = 0.10

/** Health & Education Cess applied on the computed tax. */
export const CESS_RATE = 0.04

/** Annual LTCG exemption for listed equity / equity MF, in rupees. */
export const LTCG_ANNUAL_EXEMPTION_INR = 100_000

/** Classification of a holding's tax regime under listed-equity rules. */
export type HoldingRegime = "stcg" | "ltcg"

/** Breakdown of a single capital-gains computation. */
export interface TaxBreakdown {
  /** Capital gain in rupees (negative when there is a capital loss). */
  gain: number
  /** Regime applied: short-term or long-term. */
  regime: HoldingRegime
  /** Portion of the gain that is taxable after the LTCG exemption. */
  taxableGain: number
  /** Base tax before cess. */
  baseTax: number
  /** Health & Education Cess on baseTax. */
  cess: number
  /** Total tax = baseTax + cess. Zero when gain ≤ 0 or exemption covers it. */
  totalTax: number
  /** Net proceeds after tax = exitValue − totalTax (entry cost recovered). */
  netGain: number
  /** Effective tax rate on the gain (totalTax / gain). Zero when gain ≤ 0. */
  effectiveRate: number
}

/** Classify a holding period in months into STCG vs LTCG. */
export function classifyHolding(holdingMonths: number): HoldingRegime {
  if (!Number.isFinite(holdingMonths) || holdingMonths < 0) return "stcg"
  return holdingMonths >= LTCG_THRESHOLD_MONTHS ? "ltcg" : "stcg"
}

/**
 * Compute capital-gains tax for a single round-trip on listed equity.
 *
 * @param entryValue   total acquisition cost (₹). Per-share entry × qty.
 * @param exitValue    total realisation (₹). Per-share exit × qty.
 * @param holdingMonths integer or fractional months held.
 * @param opts.exemptionUsed
 *                     ₹ already consumed from the ₹1L LTCG exemption
 *                     by other positions this FY. Defaults to 0.
 */
export function computeCapitalGainsTax(
  entryValue: number,
  exitValue: number,
  holdingMonths: number,
  opts: { exemptionUsed?: number } = {},
): TaxBreakdown {
  const gain = (Number.isFinite(exitValue) ? exitValue : 0) - (Number.isFinite(entryValue) ? entryValue : 0)
  const regime = classifyHolding(holdingMonths)

  // A capital loss produces zero tax under both regimes. Set-off and
  // carry-forward rules apply but are a portfolio-level matter, not
  // a per-position one. We surface the loss in `gain` so the caller
  // can render it but never charge tax on it.
  if (gain <= 0) {
    return {
      gain,
      regime,
      taxableGain: 0,
      baseTax: 0,
      cess: 0,
      totalTax: 0,
      netGain: gain,
      effectiveRate: 0,
    }
  }

  let taxableGain: number
  let baseTax: number

  if (regime === "stcg") {
    taxableGain = gain
    baseTax = gain * STCG_RATE
  } else {
    const exemptionUsed = Math.max(0, opts.exemptionUsed ?? 0)
    const exemptionRemaining = Math.max(
      0,
      LTCG_ANNUAL_EXEMPTION_INR - exemptionUsed,
    )
    taxableGain = Math.max(0, gain - exemptionRemaining)
    baseTax = taxableGain * LTCG_RATE
  }

  const cess = baseTax * CESS_RATE
  const totalTax = baseTax + cess
  const netGain = gain - totalTax
  const effectiveRate = totalTax / gain

  return {
    gain,
    regime,
    taxableGain,
    baseTax,
    cess,
    totalTax,
    netGain,
    effectiveRate,
  }
}

/**
 * Compute the post-tax return on invested capital as a fraction
 * (e.g. 0.18 = 18%). When entryValue is 0 or negative, returns 0
 * rather than ±Infinity.
 */
export function postTaxReturn(
  entryValue: number,
  exitValue: number,
  holdingMonths: number,
  opts: { exemptionUsed?: number } = {},
): number {
  if (!Number.isFinite(entryValue) || entryValue <= 0) return 0
  const { netGain } = computeCapitalGainsTax(
    entryValue,
    exitValue,
    holdingMonths,
    opts,
  )
  return netGain / entryValue
}

/**
 * Compute pre-tax return as a fraction. Mirrors `postTaxReturn` so
 * callers can render the pair side-by-side.
 */
export function preTaxReturn(entryValue: number, exitValue: number): number {
  if (!Number.isFinite(entryValue) || entryValue <= 0) return 0
  return (exitValue - entryValue) / entryValue
}

/**
 * Annualise a holding-period return.
 *
 *   annualised = (1 + r) ^ (12 / months) − 1
 *
 * When `holdingMonths` ≤ 0 we return `r` unchanged rather than
 * propagating NaN/Inf — the caller is responsible for hiding the
 * annualised value in degenerate inputs.
 */
export function annualiseReturn(r: number, holdingMonths: number): number {
  if (!Number.isFinite(r)) return 0
  if (!Number.isFinite(holdingMonths) || holdingMonths <= 0) return r
  return Math.pow(1 + r, 12 / holdingMonths) - 1
}

/**
 * Format a fractional rate (e.g. 0.1234) as a signed percentage
 * string with one decimal place. "+12.3%" / "-4.5%" / "0.0%".
 * Kept here so the calculator UI and the helper math share one
 * canonical format and stay testable from a single import.
 */
export function formatRate(r: number, decimals = 1): string {
  if (!Number.isFinite(r)) return "—"
  const pct = r * 100
  const sign = pct > 0 ? "+" : ""
  return `${sign}${pct.toFixed(decimals)}%`
}
