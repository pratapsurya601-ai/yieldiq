"use client"

import { useMemo, useState } from "react"

/**
 * Interactive WACC calculator widget.
 *
 * Pure client component — no fetch, no auth, no backend touch. Lives next
 * to `page.tsx` so the parent stays an RSC and only this widget hydrates.
 *
 * Inputs:
 *   - Sector (drives default beta / cost-of-debt / tax-rate / debt-ratio)
 *   - Risk-free rate (default 7.1% — India 10y G-Sec)
 *   - Equity Risk Premium (default 7.5% — Damodaran India 2026)
 *   - Beta
 *   - Cost of Debt
 *   - Tax Rate
 *   - Debt / (Debt + Equity)
 *
 * Outputs:
 *   - Cost of Equity = Rf + β · ERP
 *   - After-tax Cost of Debt = Kd · (1 − t)
 *   - WACC = (D/V) · Kd·(1−t) + (E/V) · Ke
 *
 * Voice: descriptive, never prescriptive. Numbers render as percent
 * with two decimals. No advisory verbs anywhere.
 */

type SectorKey =
  | "IT Services"
  | "Banks"
  | "FMCG"
  | "Pharma"
  | "Auto OEM"
  | "Cement"
  | "Metals"
  | "Oil & Gas"
  | "Power Utilities"
  | "Telecom"
  | "Capital Goods"
  | "Real Estate / REITs"
  | "Consumer Discretionary"
  | "Hotels"

type SectorDefaults = {
  beta: number
  costOfDebt: number
  taxRate: number
  debtRatio: number
}

export const SECTOR_DEFAULTS: Record<SectorKey, SectorDefaults> = {
  "IT Services":          { beta: 0.85, costOfDebt: 0.075, taxRate: 0.21, debtRatio: 0.05 },
  "Banks":                { beta: 1.10, costOfDebt: 0.000, taxRate: 0.25, debtRatio: 0.00 },
  "FMCG":                 { beta: 0.70, costOfDebt: 0.078, taxRate: 0.25, debtRatio: 0.10 },
  "Pharma":               { beta: 0.95, costOfDebt: 0.080, taxRate: 0.20, debtRatio: 0.15 },
  "Auto OEM":             { beta: 1.25, costOfDebt: 0.085, taxRate: 0.25, debtRatio: 0.20 },
  "Cement":               { beta: 1.20, costOfDebt: 0.085, taxRate: 0.25, debtRatio: 0.25 },
  "Metals":               { beta: 1.40, costOfDebt: 0.090, taxRate: 0.25, debtRatio: 0.30 },
  "Oil & Gas":            { beta: 1.15, costOfDebt: 0.082, taxRate: 0.25, debtRatio: 0.25 },
  "Power Utilities":      { beta: 0.65, costOfDebt: 0.078, taxRate: 0.25, debtRatio: 0.55 },
  "Telecom":              { beta: 0.90, costOfDebt: 0.085, taxRate: 0.25, debtRatio: 0.45 },
  "Capital Goods":        { beta: 1.20, costOfDebt: 0.083, taxRate: 0.25, debtRatio: 0.20 },
  "Real Estate / REITs":  { beta: 0.75, costOfDebt: 0.082, taxRate: 0.25, debtRatio: 0.35 },
  "Consumer Discretionary": { beta: 1.10, costOfDebt: 0.082, taxRate: 0.25, debtRatio: 0.20 },
  "Hotels":               { beta: 1.30, costOfDebt: 0.088, taxRate: 0.25, debtRatio: 0.30 },
}

const SECTOR_KEYS: SectorKey[] = Object.keys(SECTOR_DEFAULTS) as SectorKey[]

const DEFAULT_RISK_FREE = 0.071
const DEFAULT_ERP = 0.075

function fmtPct(value: number, digits = 2): string {
  if (!Number.isFinite(value)) return "—"
  return `${(value * 100).toFixed(digits)}%`
}

/**
 * Clamp a number-input change into a sane range so a fat-finger doesn't
 * trash the live computation. We accept negative betas (rare but legal),
 * but every rate / ratio is bounded into [0, 1].
 */
function clamp(value: number, lo: number, hi: number): number {
  if (!Number.isFinite(value)) return lo
  return Math.max(lo, Math.min(hi, value))
}

/**
 * Parse a percent-string from a number input (the input shows 7.10, we
 * store 0.071 internally). Empty / NaN falls back to the previous value.
 */
function pctToFrac(raw: string, prev: number, lo = 0, hi = 1): number {
  if (raw.trim() === "") return prev
  const n = Number(raw)
  if (!Number.isFinite(n)) return prev
  return clamp(n / 100, lo, hi)
}

function fracToPctStr(frac: number, digits = 2): string {
  return (frac * 100).toFixed(digits)
}

type NumberFieldProps = {
  id: string
  label: string
  hint?: string
  value: string
  onChange: (next: string) => void
  step?: number
  min?: number
  max?: number
  suffix?: string
}

function NumberField({
  id,
  label,
  hint,
  value,
  onChange,
  step = 0.01,
  min = 0,
  max = 100,
  suffix = "%",
}: NumberFieldProps) {
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {label}
      </label>
      <div className="relative">
        <input
          id={id}
          type="number"
          inputMode="decimal"
          step={step}
          min={min}
          max={max}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="w-full rounded-md border border-border bg-card px-3 py-2 pr-10 font-mono text-sm text-foreground focus:border-foreground focus:outline-none focus:ring-1 focus:ring-foreground"
        />
        <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-xs text-muted-foreground">
          {suffix}
        </span>
      </div>
      {hint ? <p className="text-xs text-muted-foreground">{hint}</p> : null}
    </div>
  )
}

function BreakdownRow({
  label,
  value,
  detail,
}: {
  label: string
  value: string
  detail?: string
}) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-2.5 border-b border-border last:border-b-0">
      <div className="flex flex-col">
        <span className="text-sm text-foreground">{label}</span>
        {detail ? (
          <span className="text-xs text-muted-foreground">{detail}</span>
        ) : null}
      </div>
      <span className="font-mono text-sm font-semibold text-foreground">{value}</span>
    </div>
  )
}

export default function Calculator() {
  const [sector, setSector] = useState<SectorKey>("IT Services")
  const defaults = SECTOR_DEFAULTS[sector]

  // Inputs are stored as fractions internally and rendered as
  // percent-strings in the input box. This keeps the live computation
  // numerically clean while letting the user type "7.1" rather than
  // "0.071".
  const [riskFreeStr, setRiskFreeStr] = useState(fracToPctStr(DEFAULT_RISK_FREE, 2))
  const [erpStr, setErpStr] = useState(fracToPctStr(DEFAULT_ERP, 2))
  const [betaStr, setBetaStr] = useState(defaults.beta.toFixed(2))
  const [costOfDebtStr, setCostOfDebtStr] = useState(fracToPctStr(defaults.costOfDebt, 2))
  const [taxRateStr, setTaxRateStr] = useState(fracToPctStr(defaults.taxRate, 2))
  const [debtRatioStr, setDebtRatioStr] = useState(fracToPctStr(defaults.debtRatio, 2))

  // When the user changes sector, reset the sector-dependent inputs to
  // that sector's defaults — but keep risk-free + ERP untouched, those
  // are global parameters not sector-specific.
  function changeSector(next: SectorKey) {
    const d = SECTOR_DEFAULTS[next]
    setSector(next)
    setBetaStr(d.beta.toFixed(2))
    setCostOfDebtStr(fracToPctStr(d.costOfDebt, 2))
    setTaxRateStr(fracToPctStr(d.taxRate, 2))
    setDebtRatioStr(fracToPctStr(d.debtRatio, 2))
  }

  const riskFree = pctToFrac(riskFreeStr, DEFAULT_RISK_FREE, 0, 1)
  const erp = pctToFrac(erpStr, DEFAULT_ERP, 0, 1)
  const beta = useMemo(() => {
    const n = Number(betaStr)
    if (!Number.isFinite(n)) return defaults.beta
    return clamp(n, -5, 5)
  }, [betaStr, defaults.beta])
  const costOfDebt = pctToFrac(costOfDebtStr, defaults.costOfDebt, 0, 1)
  const taxRate = pctToFrac(taxRateStr, defaults.taxRate, 0, 1)
  const debtRatio = pctToFrac(debtRatioStr, defaults.debtRatio, 0, 1)

  // Core WACC math.
  const costOfEquity = riskFree + beta * erp
  const afterTaxCostOfDebt = costOfDebt * (1 - taxRate)
  const equityRatio = 1 - debtRatio
  const wacc =
    debtRatio * afterTaxCostOfDebt + equityRatio * costOfEquity

  return (
    <section className="mt-10 rounded-2xl border border-border bg-card p-6 md:p-8">
      <div className="grid gap-8 md:grid-cols-2">
        {/* ── Inputs ───────────────────────────────────────────── */}
        <div className="flex flex-col gap-5">
          <div>
            <h2 className="font-serif text-xl text-foreground">Inputs</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Pick a sector to load calibrated defaults. Every field is
              editable — your numbers replace the defaults live.
            </p>
          </div>

          {/* Sector selector */}
          <div className="flex flex-col gap-1.5">
            <label
              htmlFor="sector-select"
              className="text-xs font-semibold uppercase tracking-wide text-muted-foreground"
            >
              Sector
            </label>
            <select
              id="sector-select"
              value={sector}
              onChange={(e) => changeSector(e.target.value as SectorKey)}
              className="w-full rounded-md border border-border bg-card px-3 py-2 text-sm text-foreground focus:border-foreground focus:outline-none focus:ring-1 focus:ring-foreground"
            >
              {SECTOR_KEYS.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
            <p className="text-xs text-muted-foreground">
              Sets beta, cost of debt, tax rate, and debt-ratio defaults.
            </p>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <NumberField
              id="rf-input"
              label="Risk-free rate"
              hint="India 10y G-Sec yield"
              value={riskFreeStr}
              onChange={setRiskFreeStr}
            />
            <NumberField
              id="erp-input"
              label="Equity risk premium"
              hint="Damodaran India 2026"
              value={erpStr}
              onChange={setErpStr}
            />
            <NumberField
              id="beta-input"
              label="Beta"
              hint="Sensitivity to the market"
              value={betaStr}
              onChange={setBetaStr}
              step={0.05}
              min={-5}
              max={5}
              suffix="x"
            />
            <NumberField
              id="kd-input"
              label="Cost of debt"
              hint="Pre-tax interest rate"
              value={costOfDebtStr}
              onChange={setCostOfDebtStr}
            />
            <NumberField
              id="tax-input"
              label="Tax rate"
              hint="Statutory corporate rate"
              value={taxRateStr}
              onChange={setTaxRateStr}
            />
            <NumberField
              id="dv-input"
              label="Debt / (Debt + Equity)"
              hint="Capital structure weight"
              value={debtRatioStr}
              onChange={setDebtRatioStr}
            />
          </div>
        </div>

        {/* ── Output + Breakdown ───────────────────────────────── */}
        <div className="flex flex-col gap-5">
          <div>
            <h2 className="font-serif text-xl text-foreground">Result</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              WACC updates as you type. The breakdown below shows each
              piece feeding the final number.
            </p>
          </div>

          {/* Headline WACC */}
          <div className="rounded-xl border border-border bg-muted/30 p-6 text-center">
            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              WACC ({sector})
            </p>
            <p
              data-testid="wacc-output"
              className="mt-2 font-serif text-5xl font-semibold text-foreground"
            >
              {fmtPct(wacc, 2)}
            </p>
            <p className="mt-2 text-xs text-muted-foreground">
              Weighted-average cost of capital — the discount rate used in
              DCF valuation.
            </p>
          </div>

          {/* Component breakdown */}
          <div className="rounded-xl border border-border bg-card p-5">
            <h3 className="mb-2 text-sm font-semibold text-foreground">
              How we arrived at {fmtPct(wacc, 2)}
            </h3>
            <BreakdownRow
              label="Cost of equity (Ke)"
              detail={`Rf + β · ERP = ${fmtPct(riskFree, 2)} + ${beta.toFixed(2)} · ${fmtPct(erp, 2)}`}
              value={fmtPct(costOfEquity, 2)}
            />
            <BreakdownRow
              label="After-tax cost of debt"
              detail={`Kd · (1 − t) = ${fmtPct(costOfDebt, 2)} · (1 − ${fmtPct(taxRate, 2)})`}
              value={fmtPct(afterTaxCostOfDebt, 2)}
            />
            <BreakdownRow
              label="Equity weight (E/V)"
              detail={`1 − D/V = 1 − ${fmtPct(debtRatio, 2)}`}
              value={fmtPct(equityRatio, 2)}
            />
            <BreakdownRow
              label="Debt weight (D/V)"
              value={fmtPct(debtRatio, 2)}
            />
            <BreakdownRow
              label="Final WACC"
              detail="(D/V · after-tax Kd) + (E/V · Ke)"
              value={fmtPct(wacc, 2)}
            />
          </div>
        </div>
      </div>
    </section>
  )
}
