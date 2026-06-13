"use client"

// Dividends — a NEW dedicated income section (on-brand for YieldIQ). Yield,
// payout ratio, ex-date, streak and free-cash cover as scannable KPIs, plus a
// factual "how each ₹100 of earnings is used" coverage bar and a plain read.
// Deliberately a DIFFERENT visual from the §4 dividend-growth staircase so no
// chart shape repeats (architecture §7.3). Mock data only; SSR-safe.
import { Coins } from "lucide-react"

import { seg, useStageClock } from "./hooks"
import { DEMO_COLORS } from "./theme"
import { Kpi, Muted, Ribbon, Section } from "./ui"

const PAYOUT_PCT = 22 // share of earnings paid out as dividend

export default function SectionDividends() {
  const { ref, elapsed } = useStageClock(900, 0.15)
  const paid = PAYOUT_PCT * seg(elapsed, 0, 700)
  const paidR = Math.round(paid)

  return (
    <Section
      id="sec-dividends"
      title="Dividends"
      innerRef={ref}
      ribbon={
        <Ribbon tone="good" icon={<Coins size={13} aria-hidden="true" />}>
          14 straight years
        </Ribbon>
      }
    >
      <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3 lg:grid-cols-6">
        <Kpi label="Dividend yield" value="1.1%" />
        <Kpi label="Payout ratio" value="22%" />
        <Kpi label="FY25 dividend" value="₹22" sub="/sh" />
        <Kpi label="Free-cash cover" value="4.5×" />
        <Kpi label="Paid since" value="2011" />
        <Kpi label="Next ex-date" value="16 May" />
      </div>

      {/* Payout coverage bar — a different shape from the §4 growth staircase */}
      <div className="mt-4">
        <div className="mb-1.5 flex flex-wrap items-center justify-between gap-2 text-[12px] text-caption">
          <span>How each ₹100 of earnings is used</span>
          <span className="num">
            {paidR}% paid · {100 - paidR}% retained
          </span>
        </div>
        <div className="flex h-6 overflow-hidden rounded-md border border-border/60">
          <div style={{ width: `${paid}%`, background: DEMO_COLORS.teal, transition: "width .3s ease" }} />
          <div className="flex-1 bg-raised" />
        </div>
        <div className="mt-1.5 flex flex-wrap gap-4 text-[11.5px] text-caption">
          <span className="inline-flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-[2px]" style={{ background: DEMO_COLORS.teal }} aria-hidden="true" />
            Paid to shareholders
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-[2px] border border-border bg-raised" aria-hidden="true" />
            Retained to grow the book
          </span>
        </div>
      </div>

      <Muted className="mt-3 text-[12px]">
        ₹22 per share in FY25 — about a fifth of earnings, with the rest retained to fund loan growth.
        Free cash flow covers the payout roughly 4.5×, and the dividend has been paid every year since
        2011.
      </Muted>
    </Section>
  )
}
