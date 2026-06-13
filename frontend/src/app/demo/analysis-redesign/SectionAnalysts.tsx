"use client"

// Analyst coverage — the Street's aggregated view, shown as third-party
// CONTEXT alongside YieldIQ's own fair value (the honest-differentiator
// juxtaposition: our number sits on the same scale as the brokers'). A
// stance split + a price-estimate range with our FV marked. Attributed
// broker data, deliberately NOT YieldIQ's own call — and reframed to
// neutral vocabulary (positive/neutral/cautious, "estimate" not the
// guarded words). Mock data only; SSR-safe.
import { Building2 } from "lucide-react"

import { FAIR_VALUE, PRICE } from "./data"
import { seg, useStageClock } from "./hooks"
import { DEMO_COLORS } from "./theme"
import { Kpi, Muted, Ribbon, Section, Subh } from "./ui"

// Aggregated broker stance (mock) — reframed from rating labels to a
// neutral split so the section carries no guarded vocabulary.
const STANCE = [
  { label: "Positive", n: 21, color: DEMO_COLORS.teal },
  { label: "Neutral", n: 9, color: DEMO_COLORS.blue },
  { label: "Cautious", n: 3, color: DEMO_COLORS.amber },
]
const BROKERS = STANCE.reduce((sum, s) => sum + s.n, 0)

// 12-month price estimates (mock), rupees per share.
const EST_LOW = 1760
const EST_MEAN = 2090
const EST_HIGH = 2420

// Track bounds.
const LO = 1640
const HI = 2460
const pos = (v: number) => ((v - LO) / (HI - LO)) * 100

const VALUES: { color: string; k: string; v: string }[] = [
  { color: "var(--color-caption)", k: "Today", v: "₹1,684" },
  { color: DEMO_COLORS.blue, k: "Low est.", v: "₹1,760" },
  { color: DEMO_COLORS.teal, k: "YieldIQ FV", v: "₹2,010" },
  { color: DEMO_COLORS.blueDark, k: "Street mean", v: "₹2,090" },
  { color: DEMO_COLORS.blue, k: "High est.", v: "₹2,420" },
]

export default function SectionAnalysts() {
  const { ref, elapsed } = useStageClock(1200, 0.15)
  const grow = seg(elapsed, 80, 800)
  const reveal = seg(elapsed, 360, 600)

  return (
    <Section
      id="sec-analysts"
      title="The Street's view — analyst coverage"
      innerRef={ref}
      ribbon={
        <Ribbon tone="info" icon={<Building2 size={13} aria-hidden="true" />}>
          {BROKERS} brokers covering
        </Ribbon>
      }
    >
      {/* Stance split */}
      <div className="mb-1.5 flex items-end justify-between">
        <span className="text-[12.5px] font-medium text-ink">How {BROKERS} brokers read it</span>
        <span className="text-[11.5px] text-caption">aggregated · updated 9 Jun</span>
      </div>
      <div className="flex h-[26px] overflow-hidden rounded-lg">
        {STANCE.map((s) => (
          <div key={s.label} style={{ width: `${((s.n / BROKERS) * 100 * grow).toFixed(1)}%`, background: s.color }} />
        ))}
      </div>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1.5 text-[11.5px]">
        {STANCE.map((s) => (
          <span key={s.label} className="inline-flex items-center gap-1.5 text-caption">
            <span className="h-2.5 w-2.5 rounded-[2px]" style={{ background: s.color }} aria-hidden="true" />
            {s.label} <span className="num font-medium text-ink">{s.n}</span>
          </span>
        ))}
      </div>

      {/* Price-estimate range with our fair value on the same scale */}
      <Subh className="mt-4">12-month price estimate vs our fair value</Subh>
      <div className="rounded-lg border border-border/60 bg-raised px-5 pb-4 pt-9">
        <div className="relative h-2">
          {/* neutral full track */}
          <div className="absolute inset-x-0 top-0 h-2 rounded-full bg-border/60" aria-hidden="true" />
          {/* low -> high broker range band */}
          <div
            className="absolute top-0 h-2 rounded-full"
            style={{
              left: `${pos(EST_LOW)}%`,
              width: `${((pos(EST_HIGH) - pos(EST_LOW)) * grow).toFixed(1)}%`,
              background: DEMO_COLORS.blueLight,
            }}
            aria-hidden="true"
          />
          {/* low / mean / high dots */}
          <Dot leftPct={pos(EST_LOW)} color={DEMO_COLORS.blue} />
          <Dot leftPct={pos(EST_MEAN)} color={DEMO_COLORS.blueDark} big />
          <Dot leftPct={pos(EST_HIGH)} color={DEMO_COLORS.blue} />
          {/* current price tick */}
          <span
            className="absolute -top-1.5 h-5 w-px"
            style={{ left: `${pos(PRICE)}%`, background: "var(--color-caption)" }}
            aria-hidden="true"
          />
          {/* YieldIQ fair value — emphasized marker + callout above */}
          <div
            className="absolute -top-[30px] whitespace-nowrap"
            style={{ left: `${pos(FAIR_VALUE)}%`, transform: "translateX(-50%)", opacity: reveal }}
          >
            <span className="rounded-full bg-tone-good-bg px-2 py-[2px] text-[10.5px] font-medium text-tone-good-fg">
              YieldIQ FV ₹2,010
            </span>
          </div>
          <span
            className="absolute -top-[5px] z-[1] h-[18px] w-[18px] rounded-full border-[3px]"
            style={{
              left: `${pos(FAIR_VALUE)}%`,
              transform: "translateX(-50%)",
              background: DEMO_COLORS.teal,
              borderColor: "var(--color-surface)",
            }}
            aria-hidden="true"
          />
        </div>
        <div className="mt-4 flex flex-wrap gap-x-4 gap-y-1.5 text-[11.5px]">
          {VALUES.map((x) => (
            <span key={x.k} className="inline-flex items-center gap-1.5 text-caption">
              <span className="h-2.5 w-2.5 rounded-full" style={{ background: x.color }} aria-hidden="true" />
              {x.k} <span className="num font-medium text-ink">{x.v}</span>
            </span>
          ))}
        </div>
      </div>

      {/* KPIs */}
      <div className="mt-4 grid grid-cols-2 gap-2.5 sm:grid-cols-4">
        <Kpi label="Brokers covering" value={String(BROKERS)} />
        <Kpi label="Street mean" value="₹2,090" />
        <Kpi label="Estimate range" value="₹1,760–2,420" />
        <Kpi label="YieldIQ fair value" value="₹2,010" valueClass="text-success" />
      </div>

      <Muted className="mt-3">
        Aggregated from {BROKERS}{" "}broker estimates and shown for context — this is the Street&apos;s view, not
        YieldIQ&apos;s. Our own fair value (₹2,010) lands just under the Street mean (₹2,090); both sit above
        today&apos;s ₹1,684.
      </Muted>
    </Section>
  )
}

function Dot({ leftPct, color, big = false }: { leftPct: number; color: string; big?: boolean }) {
  const d = big ? 12 : 9
  return (
    <span
      className="absolute rounded-full border-2"
      style={{
        left: `${leftPct}%`,
        top: `${(8 - d) / 2}px`,
        height: d,
        width: d,
        background: color,
        borderColor: "var(--color-surface)",
        transform: "translateX(-50%)",
      }}
      aria-hidden="true"
    />
  )
}
