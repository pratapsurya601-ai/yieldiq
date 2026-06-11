"use client"

// I · §5 Valuation (02) — ① forest plot with agreement band, weights and
// ₹ axis ② weighted blend bar color-matched to the forest dots ③ DCF
// playground (forward/reverse, live recompute, price-vs-FV marker bar,
// clickable 5×5 sensitivity heatmap). M · the heatmap sits behind the
// Pro veil on the Free preview — fully designed, visibly previewed.
import { useState } from "react"
import { CircleDashed, Lock, SlidersHorizontal } from "lucide-react"

import {
  BLEND_COLORS,
  DISCOUNT_STEPS,
  ESTIMATORS,
  FAIR_VALUE,
  GROWTH_STEPS,
  PRICE,
  fdcf,
  impliedGrowth,
} from "./data"
import { backOut, inr, seg, useStageClock } from "./hooks"
import { DEMO_COLORS, TOKENS } from "./theme"
import { Muted, Ribbon, Section, StepNum, Subh, TwoCol } from "./ui"

const fx = (v: number) => 140 + ((v - 1650) / 500) * 396

export default function SectionValuation({ tier }: { tier: "free" | "pro" }) {
  const { ref, elapsed } = useStageClock(1800, 0.15)
  const [selRow, setSelRow] = useState<number | null>(null)
  const [mode, setMode] = useState<"fwd" | "rev">("fwd")

  return (
    <Section
      id="sec-5"
      num="5"
      title="Valuation — how we got the number"
      innerRef={ref}
      ribbon={
        <Ribbon tone="warn" icon={<CircleDashed size={13} aria-hidden="true" />}>
          Mixed (assumptions)
        </Ribbon>
      }
    >
      {/* Step 1 — forest plot */}
      <Subh>
        <StepNum n={1} />
        Five independent methods{" "}
        <span className="font-normal text-caption">— dot size = weight · tap a row</span>
      </Subh>
      <svg
        viewBox="0 0 560 232"
        width="100%"
        className="block"
        role="img"
        aria-label="Forest plot of five valuation estimators between 1910 and 2090 rupees with an agreement zone, composite at 2010 and price at 1684."
      >
        <rect
          x={fx(1910)}
          y={18}
          width={fx(2090) - fx(1910)}
          height={164}
          fill="rgba(29,158,117,0.07)"
          opacity={elapsed >= 950 ? 1 : 0}
          style={{ transition: "opacity .8s" }}
        />
        <line x1={140} x2={536} y1={182} y2={182} stroke={TOKENS.border} />
        {[1700, 1800, 1900, 2000, 2100].map((v) => (
          <g key={v}>
            <line x1={fx(v)} x2={fx(v)} y1={182} y2={186} stroke={TOKENS.border} />
            <text x={fx(v)} y={196} textAnchor="middle" fontSize={9.5} fill={TOKENS.caption} className="num">
              {inr(v)}
            </text>
          </g>
        ))}
        <line x1={fx(FAIR_VALUE)} x2={fx(FAIR_VALUE)} y1={14} y2={182} stroke={DEMO_COLORS.teal} strokeWidth={2} />
        <text x={fx(FAIR_VALUE)} y={212} textAnchor="middle" fontSize={10.5} fontWeight={500} fill={DEMO_COLORS.tealDark} className="num">
          Composite ₹2,010
        </text>
        <line x1={fx(PRICE)} x2={fx(PRICE)} y1={14} y2={182} stroke={TOKENS.caption} strokeDasharray="4 4" />
        <text x={fx(PRICE)} y={226} textAnchor="middle" fontSize={10.5} fill={TOKENS.caption} className="num">
          Price ₹1,684
        </text>
        {ESTIMATORS.map(([name, value, weight], i) => {
          const y = 34 + i * 30
          const r = (4.5 + weight * 0.17) * seg(elapsed, 150 + i * 120, 550, backOut)
          const settled = elapsed >= 150 + i * 120 + 550
          return (
            <g
              key={name}
              className="group cursor-pointer"
              role="button"
              tabIndex={0}
              aria-label={`${name} — ${inr(value)}, weight ${weight}%`}
              onClick={() => setSelRow(i)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault()
                  setSelRow(i)
                }
              }}
            >
              <rect x={8} y={y - 13} width={528} height={26} rx={6} fill="transparent" className="group-hover:fill-[var(--color-raised)]" />
              <text x={132} y={y - 1} textAnchor="end" fontSize={11} fill={TOKENS.caption}>
                {name}
              </text>
              <text x={132} y={y + 11} textAnchor="end" fontSize={9.5} fontWeight={500} fill={BLEND_COLORS[i]} className="num">
                weight {weight}%
              </text>
              <line x1={140} x2={536} y1={y} y2={y} stroke={TOKENS.border} />
              <circle
                cx={fx(value)}
                cy={y}
                r={Math.max(0, r).toFixed(1)}
                fill={BLEND_COLORS[i]}
                stroke={selRow === i ? TOKENS.ink : "none"}
                strokeWidth={selRow === i ? 2 : 0}
              />
              <text
                x={fx(value) + (4.5 + weight * 0.17) + 7}
                y={y + 4}
                fontSize={10.5}
                fontWeight={500}
                fill={TOKENS.ink}
                opacity={settled ? 1 : 0}
                style={{ transition: "opacity .4s" }}
                className="num"
              >
                {inr(value)}
              </text>
            </g>
          )
        })}
      </svg>
      <Muted className="mb-3.5 mt-0.5 min-h-[20px]">
        {selRow !== null ? (
          <>
            <span className="font-medium text-ink">{ESTIMATORS[selRow][0]}</span> —{" "}
            {ESTIMATORS[selRow][3]} · lands at {inr(ESTIMATORS[selRow][1])} with{" "}
            {ESTIMATORS[selRow][2]}% weight in the blend.
          </>
        ) : null}
      </Muted>

      {/* Step 2 — weighted blend bar */}
      <Subh>
        <StepNum n={2} />
        Blend them by reliability
      </Subh>
      <div className="mb-1 flex items-center gap-3">
        <div className="flex h-[18px] flex-1 overflow-hidden rounded-[5px]">
          {ESTIMATORS.map(([name, , weight], i) => (
            <div
              key={name}
              title={`${name} · ${weight}%`}
              style={{
                width: `${weight * seg(elapsed, 200 + i * 80, 800)}%`,
                background: BLEND_COLORS[i],
              }}
            />
          ))}
        </div>
        <div className="whitespace-nowrap">
          <span className="text-[12px] text-caption">→</span>{" "}
          <span className="num text-[17px] font-medium" style={{ color: DEMO_COLORS.tealDark }}>
            ₹2,010
          </span>
        </div>
      </div>
      <div className="mb-4 flex flex-wrap gap-3 text-[11px] text-caption">
        {ESTIMATORS.map(([name, , weight], i) => (
          <span key={name}>
            <span
              className="mr-1 inline-block h-2 w-2 rounded-[2px] align-[-1px]"
              style={{ background: BLEND_COLORS[i] }}
            />
            {name.split(" ")[0]} {weight}%
          </span>
        ))}
      </div>

      {/* Step 3 — DCF playground */}
      <div className="border-t border-border/70 pt-3.5">
        <div className="mb-3.5 flex flex-wrap items-center justify-between gap-2.5">
          <Subh className="m-0">
            <StepNum n={3} />
            <SlidersHorizontal size={14} aria-hidden="true" className="mr-1 inline align-[-2px]" />
            Stress it yourself
          </Subh>
          <div className="flex gap-1.5">
            <ModeButton on={mode === "fwd"} onClick={() => setMode("fwd")}>
              Forward DCF
            </ModeButton>
            <ModeButton on={mode === "rev"} onClick={() => setMode("rev")}>
              Reverse DCF
            </ModeButton>
          </div>
        </div>
        {mode === "fwd" ? <ForwardPanel tier={tier} /> : <ReversePanel />}
      </div>
    </Section>
  )
}

function ModeButton({ on, onClick, children }: { on: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={on}
      className={`rounded-full border px-3.5 py-1.5 text-[12.5px] transition-colors ${
        on
          ? "border-tone-info-bd bg-tone-info-bg text-tone-info-fg"
          : "border-border bg-surface text-caption hover:border-caption/60"
      }`}
    >
      {children}
    </button>
  )
}

function ForwardPanel({ tier }: { tier: "free" | "pro" }) {
  const [g, setG] = useState(5)
  const [d, setD] = useState(12)
  const f = fdcf(g, d)
  const mos = Math.round(((f - PRICE) / f) * 100)
  const under = mos >= 0

  const lo = (Math.min(PRICE, f) / 2800) * 100
  const hi = (Math.max(PRICE, f) / 2800) * 100

  const nearest = (arr: number[], v: number) => arr.reduce((a, b) => (Math.abs(b - v) < Math.abs(a - v) ? b : a))
  const curG = nearest(GROWTH_STEPS, g)
  const curD = nearest(DISCOUNT_STEPS, d)

  return (
    <TwoCol align="start">
      <div>
        <SliderRow id="demo-grw" label="Terminal growth" min={3} max={7} step={0.5} value={g} onChange={setG} out={`${g.toFixed(1)}%`} />
        <SliderRow id="demo-dsc" label="Discount rate" min={10} max={14} step={0.5} value={d} onChange={setD} out={`${d.toFixed(1)}%`} />
        <div className="mb-2.5 mt-1 flex items-baseline gap-2.5">
          <div>
            <div className="text-[11.5px] text-caption">Your fair value</div>
            <div className="num text-[28px] font-medium text-ink">{inr(f)}</div>
          </div>
          <div
            className={`rounded-full px-2.5 py-[3px] text-[13px] ${
              under ? "bg-tone-good-bg text-tone-good-fg" : "bg-tone-warn-bg text-tone-warn-fg"
            }`}
          >
            {under ? `${mos}% undervalued` : `${Math.abs(mos)}% overvalued`}
          </div>
        </div>
        {/* Price-vs-FV marker bar */}
        <div className="relative h-[22px] overflow-hidden rounded-md bg-raised">
          <div
            className="absolute bottom-0 top-0"
            style={{
              left: `${lo}%`,
              width: `${hi - lo}%`,
              background: under ? "var(--color-tone-good-bg)" : "rgba(216,90,48,0.18)",
            }}
          />
          <div className="absolute bottom-0 top-0 w-0.5 bg-caption" style={{ left: "60.1%" }} />
          <div className="absolute bottom-0 top-0 w-[2.5px] bg-ink transition-[left] duration-200" style={{ left: `${(f / 2800) * 100}%` }} />
        </div>
        <Muted className="mt-1 text-[11px]">
          Grey tick = price ₹1,684 · black marker = your fair value · shaded gap = your margin
        </Muted>
      </div>

      <div>
        <div className={tier === "free" ? "relative overflow-hidden rounded-lg" : undefined}>
          <div className={tier === "free" ? "pointer-events-none opacity-40" : undefined} aria-hidden={tier === "free"}>
            <div className="mb-1.5 text-center text-[11.5px] text-caption">
              Sensitivity — growth (rows) × discount (cols) · click a cell
            </div>
            <div className="grid gap-[3px]" style={{ gridTemplateColumns: "34px repeat(5, 1fr)" }}>
              <div className="py-1 text-center text-[10px] text-caption">g\d</div>
              {DISCOUNT_STEPS.map((dd) => (
                <div key={dd} className="num py-1 text-center text-[10px] text-caption">
                  {dd}%
                </div>
              ))}
              {[...GROWTH_STEPS].reverse().map((gg) => (
                <HeatRow key={gg} g={gg} curG={curG} curD={curD} onPick={(ng, nd) => { setG(ng); setD(nd) }} />
              ))}
            </div>
            <Muted className="mt-1.5 text-center text-[11px]">
              Green = below fair value at that assumption · your cell is ringed
            </Muted>
          </div>
          {tier === "free" && (
            <div className="absolute inset-0 flex items-center justify-center bg-border/70">
              <div className="max-w-[280px] rounded-lg border border-border bg-raised px-4 py-3.5 text-center shadow-sm">
                <Lock size={22} aria-hidden="true" className="mx-auto text-warning" />
                <div className="mb-1 mt-1.5 text-[13.5px] font-medium text-ink">
                  Stress-test the fair value yourself
                </div>
                <Muted className="mb-2.5 text-[11.5px]">Live sliders · 25-cell sensitivity · reverse DCF</Muted>
                <button
                  type="button"
                  className="rounded-lg border border-tone-warn-bd px-3 py-1.5 text-[12.5px] text-tone-warn-fg transition-colors hover:bg-tone-warn-bg"
                >
                  Unlock with Pro
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </TwoCol>
  )
}

function HeatRow({
  g,
  curG,
  curD,
  onPick,
}: {
  g: number
  curG: number
  curD: number
  onPick: (g: number, d: number) => void
}) {
  return (
    <>
      <div className="num py-1 text-center text-[10px] text-caption">{g}%</div>
      {DISCOUNT_STEPS.map((d) => {
        const fv = fdcf(g, d)
        const m = (fv - PRICE) / fv
        const bg =
          m >= 0
            ? `rgba(29,158,117,${(0.12 + Math.min(m * 1.8, 0.5)).toFixed(3)})`
            : `rgba(216,90,48,${(0.12 + Math.min(-m * 1.8, 0.5)).toFixed(3)})`
        const ringed = g === curG && d === curD
        return (
          <button
            key={d}
            type="button"
            onClick={() => onPick(g, d)}
            className="num cursor-pointer rounded px-0.5 py-1.5 text-center text-[10px] text-ink transition-transform hover:scale-[1.08]"
            style={{
              background: bg,
              outline: ringed ? `2px solid ${TOKENS.ink}` : "none",
              outlineOffset: -2,
            }}
          >
            ₹{Math.round(fv / 10) * 10}
          </button>
        )
      })}
    </>
  )
}

function ReversePanel() {
  const [p, setP] = useState(PRICE)
  const g = impliedGrowth(p)
  const note =
    g < 5
      ? "below our 5.0% base case, which is why HDFCBANK reads undervalued."
      : g > 5
        ? "above our 5.0% base case."
        : "in line with our base case."
  return (
    <TwoCol>
      <div>
        <SliderRow id="demo-rpr" label="Price you'd pay" min={1300} max={2400} step={20} value={p} onChange={setP} out={inr(p)} outWidth={54} />
        <div className="mt-2">
          <div className="text-[11.5px] text-caption">Market-implied terminal growth</div>
          <div className="num text-[28px] font-medium text-ink">{g.toFixed(1)}%</div>
        </div>
        <Muted className="mt-1.5">
          At {inr(p)} the market prices ~{g.toFixed(1)}% terminal growth — {note}
        </Muted>
      </div>
      <Muted>
        Drag the price to see what growth the market is paying for at that level, versus our 5.0%
        base case.
      </Muted>
    </TwoCol>
  )
}

function SliderRow({
  id,
  label,
  min,
  max,
  step,
  value,
  onChange,
  out,
  outWidth = 40,
}: {
  id: string
  label: string
  min: number
  max: number
  step: number
  value: number
  onChange: (v: number) => void
  out: string
  outWidth?: number
}) {
  return (
    <div className="mb-2.5 flex items-center gap-2.5">
      <label htmlFor={id} className="w-[104px] text-[12.5px] text-caption">
        {label}
      </label>
      <input
        id={id}
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="flex-1 accent-[var(--color-brand)]"
      />
      <span className="num text-[12.5px] font-medium text-ink" style={{ minWidth: outWidth }}>
        {out}
      </span>
    </div>
  )
}
