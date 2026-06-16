"use client"
/**
 * FeeImpactCalculator — the honest "fee-honesty" tool.
 *
 * Shows what a fund's expense ratio costs an investor over time and the
 * Direct-vs-Regular plan gap, using a compounding model on the USER's
 * inputs. Works without ingested TER (the user can type the ratio off
 * the factsheet); pre-fills Direct/Regular TER when the scheme's values
 * are available. Purely factual / illustrative — no advice, no
 * SEBI-guarded vocabulary.
 *
 * Two modes, one output presentation (three bars + two summary cards):
 *   - "Lump sum"     — a one-time investment compounded for N years.
 *   - "SIP (monthly)" — a constant monthly contribution, compounded as
 *      an annuity-due (contribution at the START of each month, the
 *      common Indian SIP convention).
 *
 * The fee math is identical in both modes — only the corpus formula
 * differs. Both compare three cost levels: no fees (TER 0), Direct plan
 * (Direct TER) and Regular plan (Regular TER). TER inputs are in PERCENT
 * form (e.g. 0.62 = 0.62%), matching AMFI/SEBI published figures and the
 * host page's `fmtPct` render path.
 */
import { useState } from "react"

interface Props {
  terDirect: number | null
  terRegular: number | null
}

type Mode = "lump" | "sip"

const DEFAULT_TER_DIRECT = 0.5
const DEFAULT_TER_REGULAR = 1.5
const DEFAULT_LUMP_AMOUNT = 100000
const DEFAULT_SIP_MONTHLY = 5000

function inr(n: number): string {
  // Guard against NaN / Infinity from mid-edit blank inputs so the UI
  // never renders "₹NaN".
  if (!Number.isFinite(n)) return "₹0"
  return "₹" + Math.round(n).toLocaleString("en-IN")
}

/* ─── pure fee math (exported for unit tests) ───────────────────────────
 *
 * `netReturnPct` is the post-fee annual return in PERCENT (e.g. gross 12
 * minus TER 0.62 = 11.38). All helpers tolerate blank/NaN inputs (→ 0),
 * negative net returns, and zero years without producing NaN/Infinity.
 */

/** Coerce a possibly-blank/NaN numeric input to a finite number (→ 0). */
export function safeNum(n: number): number {
  return Number.isFinite(n) ? n : 0
}

/** Lump-sum corpus at a constant net (post-fee) annual return. */
export function lumpSumFutureValue(
  amount: number,
  netReturnPct: number,
  years: number,
): number {
  const a = safeNum(amount)
  const y = Math.max(0, safeNum(years))
  const base = 1 + safeNum(netReturnPct) / 100
  // Math.pow can yield NaN for a negative base with a fractional
  // exponent; years is whole here, but guard the result regardless.
  const fv = a * Math.pow(base, y)
  return Number.isFinite(fv) ? fv : 0
}

/**
 * SIP corpus for a constant MONTHLY contribution at a constant net
 * (post-fee) annual return, using the annuity-DUE convention
 * (contribution at the start of each month).
 *
 *   i = (1 + net) ** (1/12) − 1            monthly rate from the annual net
 *   n = round(years × 12)                  number of monthly contributions
 *   FV = P × ((1 + i)^n − 1) / i × (1 + i) annuity-due closed form
 *
 * When |i| < 1e-9 the geometric series degenerates; the no-growth limit
 * FV = P × n is used to avoid a divide-by-zero.
 */
export function sipFutureValue(
  monthly: number,
  netReturnPct: number,
  years: number,
): number {
  const p = safeNum(monthly)
  const y = Math.max(0, safeNum(years))
  const n = Math.round(y * 12)
  if (n <= 0) return 0

  const annual = 1 + safeNum(netReturnPct) / 100
  // (1 + net) can be ≤ 0 only for net ≤ -100%, which the input bounds
  // (gross 0–30, TER 0–3) cannot reach; guard anyway so a fractional
  // power never returns NaN.
  if (annual <= 0) return p * n

  const i = Math.pow(annual, 1 / 12) - 1
  if (Math.abs(i) < 1e-9) return p * n

  const fv = p * ((Math.pow(1 + i, n) - 1) / i) * (1 + i)
  return Number.isFinite(fv) ? fv : 0
}

/** Total contributed under a SIP over the horizon (P × months). */
export function sipTotalInvested(monthly: number, years: number): number {
  const p = safeNum(monthly)
  const n = Math.round(Math.max(0, safeNum(years)) * 12)
  if (n <= 0) return 0
  return p * n
}

/** Corpus dispatcher for the active mode. */
function corpusForMode(
  mode: Mode,
  amount: number,
  netReturnPct: number,
  years: number,
): number {
  return mode === "sip"
    ? sipFutureValue(amount, netReturnPct, years)
    : lumpSumFutureValue(amount, netReturnPct, years)
}

export default function FeeImpactCalculator({ terDirect, terRegular }: Props) {
  const [mode, setMode] = useState<Mode>("lump")
  const [lumpAmount, setLumpAmount] = useState(DEFAULT_LUMP_AMOUNT)
  const [sipMonthly, setSipMonthly] = useState(DEFAULT_SIP_MONTHLY)
  const [years, setYears] = useState(10)
  const [gross, setGross] = useState(12)
  const [terD, setTerD] = useState(terDirect ?? DEFAULT_TER_DIRECT)
  const [terR, setTerR] = useState(terRegular ?? DEFAULT_TER_REGULAR)

  const isSip = mode === "sip"
  const amount = isSip ? sipMonthly : lumpAmount
  const setAmount = isSip ? setSipMonthly : setLumpAmount

  const gZero = corpusForMode(mode, amount, gross, years)
  const gDirect = corpusForMode(mode, amount, gross - terD, years)
  const gRegular = corpusForMode(mode, amount, gross - terR, years)

  const dragDirect = Math.max(0, gZero - gDirect)
  const gap = Math.max(0, gDirect - gRegular) // Direct keeps this much more than Regular
  const totalInvested = isSip
    ? sipTotalInvested(sipMonthly, years)
    : safeNum(lumpAmount)
  const max = Math.max(gZero, 1)
  const barPct = (v: number) => `${Math.max(2, (safeNum(v) / max) * 100).toFixed(1)}%`

  const prefilled = terDirect != null && terRegular != null
  const amountLabel = isSip ? "Monthly SIP (₹)" : "Investment (₹)"

  return (
    <section className="rounded-lg border border-border bg-raised p-4">
      <h2 className="mb-1 text-base font-semibold text-ink">Fee impact calculator</h2>
      <p className="mb-3 text-xs text-caption">
        What the expense ratio costs over time, and the Direct-vs-Regular plan gap.{" "}
        {prefilled
          ? "Pre-filled with this scheme's expense ratios — adjust any input."
          : "This scheme's expense ratios aren't on file yet; enter them from the factsheet (typical Direct ~0.5%, Regular ~1.5%)."}
      </p>

      {/* ── Mode toggle: Lump sum | SIP (monthly) ──────────────────────── */}
      <div
        role="radiogroup"
        aria-label="Investment mode"
        className="mb-4 inline-flex rounded-md border border-border bg-surface p-0.5"
      >
        <ModeButton
          label="Lump sum"
          active={!isSip}
          onClick={() => setMode("lump")}
        />
        <ModeButton
          label="SIP (monthly)"
          active={isSip}
          onClick={() => setMode("sip")}
        />
      </div>

      <div className="mb-2 grid grid-cols-2 gap-3 sm:grid-cols-3">
        <NumField
          label={amountLabel}
          value={amount}
          onChange={setAmount}
          step={isSip ? 500 : 10000}
          min={isSip ? 100 : 1000}
        />
        <NumField label="Years" value={years} onChange={setYears} step={1} min={1} max={40} />
        <NumField label="Assumed return %" value={gross} onChange={setGross} step={0.5} min={0} max={30} />
        <NumField label="Direct TER %" value={terD} onChange={setTerD} step={0.05} min={0} max={3} />
        <NumField label="Regular TER %" value={terR} onChange={setTerR} step={0.05} min={0} max={3} />
      </div>

      {isSip ? (
        <p className="mb-4 text-[11px] text-caption" data-testid="fee-total-invested">
          Total invested over {years}{years === 1 ? " year" : " years"}:{" "}
          <span className="num font-medium text-ink">{inr(totalInvested)}</span>
        </p>
      ) : null}

      <div className="space-y-2">
        <Bar label="No fees" pct={barPct(gZero)} color="var(--color-caption)" valueText={inr(gZero)} />
        <Bar label="Direct plan" pct={barPct(gDirect)} color="var(--color-success)" valueText={inr(gDirect)} />
        <Bar label="Regular plan" pct={barPct(gRegular)} color="var(--color-warning)" valueText={inr(gRegular)} />
      </div>

      <div className="mt-4 grid grid-cols-1 gap-2 sm:grid-cols-2">
        <Stat label={`Fee drag · Direct, ${years}y`} value={inr(dragDirect)} tone="warn" />
        <Stat label="Direct keeps more than Regular" value={inr(gap)} tone="good" />
      </div>

      <p className="mt-3 text-[11px] leading-relaxed text-caption">
        Illustrative only — assumes a constant {gross}% gross return and the expense ratios above held flat;
        actual returns and fees vary.{" "}
        {isSip
          ? "Monthly mode models a constant monthly contribution made at the start of each month. "
          : ""}
        Direct plans carry no distributor commission. Not advice.
      </p>
    </section>
  )
}

function ModeButton({
  label,
  active,
  onClick,
}: {
  label: string
  active: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={active}
      onClick={onClick}
      className={
        "rounded px-3 py-1 text-xs font-medium transition-colors focus:outline-none focus:ring-1 focus:ring-caption " +
        (active
          ? "bg-raised text-ink shadow-sm"
          : "text-caption hover:text-ink")
      }
    >
      {label}
    </button>
  )
}

function NumField({
  label,
  value,
  onChange,
  step,
  min,
  max,
}: {
  label: string
  value: number
  onChange: (n: number) => void
  step: number
  min: number
  max?: number
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-[11px] font-medium text-caption">{label}</span>
      <input
        type="number"
        value={Number.isFinite(value) ? value : ""}
        step={step}
        min={min}
        max={max}
        onChange={(e) => {
          const n = parseFloat(e.target.value)
          onChange(Number.isFinite(n) ? n : 0)
        }}
        className="num w-full rounded-md border border-border bg-surface px-2.5 py-1.5 text-sm text-ink focus:border-caption focus:outline-none focus:ring-1 focus:ring-caption"
      />
    </label>
  )
}

function Bar({
  label,
  pct,
  color,
  valueText,
}: {
  label: string
  pct: string
  color: string
  valueText: string
}) {
  return (
    <div className="flex items-center gap-3">
      <div className="w-24 shrink-0 text-[12px] text-caption">{label}</div>
      <div className="relative h-6 flex-1 overflow-hidden rounded-md bg-surface">
        <div className="h-full rounded-md" style={{ width: pct, background: color }} />
      </div>
      <div className="num w-28 shrink-0 text-right text-[12.5px] font-medium text-ink">{valueText}</div>
    </div>
  )
}

function Stat({ label, value, tone }: { label: string; value: string; tone: "good" | "warn" }) {
  const cls = tone === "good" ? "text-success" : "text-warning"
  return (
    <div className="rounded-md border border-border/60 bg-surface px-3 py-2">
      <div className="text-[11px] text-caption">{label}</div>
      <div className={`num mt-0.5 text-lg font-semibold ${cls}`}>{value}</div>
    </div>
  )
}
