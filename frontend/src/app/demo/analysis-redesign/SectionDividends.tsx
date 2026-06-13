"use client"

// Dividends — a dedicated income section (on-brand for YieldIQ). A scannable
// KPI strip, an animated payout DONUT, and a 14-year payment-STREAK strip (the
// reliability signal income investors look for), plus a plain read. Both
// visuals are deliberately DIFFERENT shapes from the §4 dividend-growth
// staircase, so no chart repeats (architecture §7.3). Mock data only; SSR-safe.
import { Coins } from "lucide-react"

import { seg, useStageClock } from "./hooks"
import { DEMO_COLORS, TOKENS } from "./theme"
import { Kpi, Muted, Ribbon, Section, TwoCol } from "./ui"

const PAYOUT_PCT = 22
const RING_R = 46
const RING_C = 2 * Math.PI * RING_R // circumference of the donut ring
const STREAK_YEARS = 14

export default function SectionDividends() {
  const { ref, elapsed } = useStageClock(1000, 0.15)
  // The teal arc fills to the payout share as the section enters view.
  const arc = ((RING_C * PAYOUT_PCT) / 100) * seg(elapsed, 120, 700)

  return (
    <Section
      id="sec-dividends"
      title="Dividends"
      innerRef={ref}
      ribbon={
        <Ribbon tone="good" icon={<Coins size={13} aria-hidden="true" />}>
          14 straight years · never cut
        </Ribbon>
      }
    >
      <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3 lg:grid-cols-6">
        <Kpi label="Dividend yield" value="1.1%" />
        <Kpi label="Payout ratio" value="22%" />
        <Kpi label="FY25 dividend" value="₹22" sub="/sh" />
        <Kpi label="5-yr growth" value="+236%" valueClass="text-success" />
        <Kpi label="Free-cash cover" value="4.5×" />
        <Kpi label="Next ex-date" value="16 May" />
      </div>

      <TwoCol align="stretch" className="mt-3.5">
        {/* Payout donut */}
        <div className="flex items-center gap-4 rounded-lg border border-border/60 bg-raised px-4 py-3">
          <svg
            viewBox="0 0 120 120"
            width={88}
            height={88}
            className="shrink-0"
            role="img"
            aria-label="Payout donut: 22% paid to shareholders, 78% retained."
          >
            <circle cx={60} cy={60} r={RING_R} fill="none" stroke={DEMO_COLORS.tealFaint} strokeWidth={14} />
            <circle
              cx={60}
              cy={60}
              r={RING_R}
              fill="none"
              stroke={DEMO_COLORS.teal}
              strokeWidth={14}
              strokeDasharray={`${arc.toFixed(1)} ${(RING_C - arc).toFixed(1)}`}
              strokeLinecap="round"
              transform="rotate(-90 60 60)"
            />
            <text x={60} y={57} textAnchor="middle" fontSize={22} fontWeight={500} fill={TOKENS.ink} className="num">
              22%
            </text>
            <text x={60} y={75} textAnchor="middle" fontSize={10.5} fill={TOKENS.caption}>
              payout
            </text>
          </svg>
          <div className="text-[12px] leading-relaxed">
            <div className="flex items-center gap-1.5">
              <span className="h-2.5 w-2.5 rounded-[2px]" style={{ background: DEMO_COLORS.teal }} aria-hidden="true" />
              <span className="text-ink">22% to shareholders</span>
            </div>
            <div className="mt-1 flex items-center gap-1.5">
              <span className="h-2.5 w-2.5 rounded-[2px]" style={{ background: DEMO_COLORS.tealFaint }} aria-hidden="true" />
              <span className="text-caption">78% reinvested to grow the book</span>
            </div>
          </div>
        </div>

        {/* 14-year payment streak */}
        <div className="rounded-lg border border-border/60 bg-raised px-4 py-3">
          <div className="mb-2 text-[12.5px] font-medium text-ink">Paid every year for 14 years</div>
          <div className="flex items-end gap-[3px]">
            <span className="mr-1 self-center text-[9px] text-caption">&apos;12</span>
            {Array.from({ length: STREAK_YEARS }).map((_, i) => (
              <span
                key={i}
                className="h-[18px] flex-1 rounded-[2px]"
                style={{
                  background: DEMO_COLORS.teal,
                  opacity: 0.45 + (i / (STREAK_YEARS - 1)) * 0.55,
                }}
                aria-hidden="true"
              />
            ))}
            <span className="ml-1 self-center text-[9px] text-caption">&apos;25</span>
          </div>
          <Muted className="mt-2 text-[11.5px]">
            Annual payer through two market cycles — the payout itself has grown each year (₹6.5 → ₹22/sh).
          </Muted>
        </div>
      </TwoCol>

      <Muted className="mt-3 text-[12px]">
        ₹22 per share in FY25 — about a fifth of earnings, with the rest reinvested to fund loan growth.
        Free cash flow covers the payout roughly 4.5×, so there&apos;s room to keep raising it.
      </Muted>
    </Section>
  )
}
