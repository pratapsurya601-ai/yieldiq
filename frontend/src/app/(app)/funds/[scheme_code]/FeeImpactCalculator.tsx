"use client"
/**
 * FeeImpactCalculator — the honest "fee-honesty" tool.
 *
 * Shows what a fund's expense ratio costs an investor over time and the
 * Direct-vs-Regular plan gap, using a lump-sum compounding model on the
 * USER's inputs. Works without ingested TER (the user can type the ratio
 * off the factsheet); pre-fills Direct/Regular TER when the scheme's
 * values are available. Purely factual / illustrative — no advice, no
 * SEBI-guarded vocabulary.
 */
import { useState } from "react"

interface Props {
  terDirect: number | null
  terRegular: number | null
}

const DEFAULT_TER_DIRECT = 0.5
const DEFAULT_TER_REGULAR = 1.5

function inr(n: number): string {
  return "₹" + Math.round(n).toLocaleString("en-IN")
}

/** Lump-sum corpus at a constant net (post-fee) annual return. */
function corpus(amount: number, netReturnPct: number, years: number): number {
  return amount * Math.pow(1 + netReturnPct / 100, years)
}

export default function FeeImpactCalculator({ terDirect, terRegular }: Props) {
  const [amount, setAmount] = useState(100000)
  const [years, setYears] = useState(10)
  const [gross, setGross] = useState(12)
  const [terD, setTerD] = useState(terDirect ?? DEFAULT_TER_DIRECT)
  const [terR, setTerR] = useState(terRegular ?? DEFAULT_TER_REGULAR)

  const gZero = corpus(amount, gross, years)
  const gDirect = corpus(amount, gross - terD, years)
  const gRegular = corpus(amount, gross - terR, years)

  const dragDirect = Math.max(0, gZero - gDirect)
  const gap = Math.max(0, gDirect - gRegular) // Direct keeps this much more than Regular
  const max = Math.max(gZero, 1)
  const barPct = (v: number) => `${Math.max(2, (v / max) * 100).toFixed(1)}%`

  const prefilled = terDirect != null && terRegular != null

  return (
    <section className="rounded-lg border border-border bg-raised p-4">
      <h2 className="mb-1 text-base font-semibold text-ink">Fee impact calculator</h2>
      <p className="mb-4 text-xs text-caption">
        What the expense ratio costs over time, and the Direct-vs-Regular plan gap.{" "}
        {prefilled
          ? "Pre-filled with this scheme's expense ratios — adjust any input."
          : "This scheme's expense ratios aren't on file yet; enter them from the factsheet (typical Direct ~0.5%, Regular ~1.5%)."}
      </p>

      <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-3">
        <NumField label="Investment (₹)" value={amount} onChange={setAmount} step={10000} min={1000} />
        <NumField label="Years" value={years} onChange={setYears} step={1} min={1} max={40} />
        <NumField label="Assumed return %" value={gross} onChange={setGross} step={0.5} min={0} max={30} />
        <NumField label="Direct TER %" value={terD} onChange={setTerD} step={0.05} min={0} max={3} />
        <NumField label="Regular TER %" value={terR} onChange={setTerR} step={0.05} min={0} max={3} />
      </div>

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
        actual returns and fees vary. Direct plans carry no distributor commission. Not advice.
      </p>
    </section>
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
