"use client"

// H · §4b Quarterly results & earnings (03) — beat/miss pearl timeline
// (dot size = surprise), last-quarter scorecard vs estimates, and the
// next-earnings countdown card (static 38 days; buttons are no-ops).
import { BellPlus, CalendarDays, CircleCheck, Eye, Mic } from "lucide-react"

import { EARNINGS_COUNTDOWN_DAYS, QUARTERS } from "./data"
import { seg, useStageClock } from "./hooks"
import { DEMO_COLORS, TOKENS } from "./theme"
import { DemoButton, Kpi, Muted, Ribbon, Section, Subh, TwoCol } from "./ui"

const ZERO_Y = 84

export default function SectionQuarterly() {
  const { ref, elapsed } = useStageClock(2200, 0.2)
  const countdown = Math.round(EARNINGS_COUNTDOWN_DAYS * seg(elapsed, 0, 1100))

  return (
    <Section
      id="sec-4b"
      num="4b"
      title="Quarterly results & earnings"
      innerRef={ref}
      ribbon={
        <Ribbon tone="good" icon={<CircleCheck size={13} aria-hidden="true" />}>
          6 of 8 beats
        </Ribbon>
      }
    >
      <TwoCol align="start">
        <div>
          <Subh>
            Profit vs estimates — last 8 quarters{" "}
            <span className="font-normal text-caption">· dot above the line = beat</span>
          </Subh>
          <svg
            viewBox="0 0 560 178"
            width="100%"
            className="block"
            role="img"
            aria-label="Beat and miss timeline: six beats and two misses across the last eight quarters, latest quarter beat estimates by 1.8 percent."
          >
            <line x1={30} x2={540} y1={ZERO_Y} y2={ZERO_Y} stroke={TOKENS.border} />
            <text x={30} y={ZERO_Y - 8} fontSize={9.5} fill={TOKENS.caption}>
              met estimates
            </text>
            {QUARTERS.map(([label, surprise], i) => {
              const x = 58 + i * 66
              const off = (surprise / 4) * 52
              const beat = surprise >= 0
              const rise = seg(elapsed, 150 + i * 110, 450)
              const y = ZERO_Y - off * rise
              const r = (3 + Math.abs(surprise) * 1.4) * rise
              const settled = elapsed >= 150 + i * 110 + 450
              const c = beat ? DEMO_COLORS.teal : DEMO_COLORS.coral
              return (
                <g key={label}>
                  <line x1={x} x2={x} y1={ZERO_Y} y2={y.toFixed(1)} stroke={c} strokeWidth={1.6} opacity={0.55} />
                  <circle cx={x} cy={y.toFixed(1)} r={r.toFixed(1)} fill={c}>
                    <title>{`${label} — profit ${beat ? "beat estimates by" : "missed estimates by"} ${Math.abs(surprise).toFixed(1)}%`}</title>
                  </circle>
                  <text
                    x={x}
                    y={ZERO_Y - off + (beat ? -12 : 20)}
                    textAnchor="middle"
                    fontSize={9.5}
                    fontWeight={500}
                    fill={beat ? DEMO_COLORS.tealDark : DEMO_COLORS.coralDark}
                    opacity={settled ? 1 : 0}
                    style={{ transition: "opacity .4s" }}
                    className="num"
                  >
                    {(beat ? "+" : "") + surprise.toFixed(1)}%
                  </text>
                  <text x={x} y={164} textAnchor="middle" fontSize={9} fill={TOKENS.caption}>
                    {label}
                  </text>
                </g>
              )
            })}
          </svg>

          <Subh className="mt-3">Last quarter — Q1 FY26 scorecard</Subh>
          <div className="flex flex-wrap gap-2">
            <Kpi
              className="flex-1"
              label="NII"
              value={<span className="text-[15px]">₹31.4k cr</span>}
              sub={<span className="text-success">est 30.8 ✓</span>}
            />
            <Kpi
              className="flex-1"
              label="Net profit"
              value={<span className="text-[15px]">₹17.2k cr</span>}
              sub={<span className="text-success">est 16.9 ✓</span>}
            />
            <Kpi
              className="flex-1"
              label="NIM"
              value={<span className="text-[15px]">3.6%</span>}
              sub={<span className="text-caption">est 3.6 —</span>}
            />
          </div>
        </div>

        <div>
          <div className="rounded-lg bg-raised px-4 py-3.5">
            <div className="mb-2.5 flex items-center gap-2.5">
              <div className="flex h-10 w-10 items-center justify-center rounded-[9px] bg-tone-info-bg">
                <CalendarDays size={21} aria-hidden="true" className="text-tone-info-fg" />
              </div>
              <div>
                <div className="text-[13.5px] font-medium text-ink">Q2 FY26 results</div>
                <div className="text-[11.5px] text-caption">Saturday, 19 July 2026</div>
              </div>
            </div>
            <div className="mb-3 flex items-baseline gap-1.5">
              <span className="num text-[30px] font-medium text-ink">{countdown}</span>
              <Muted>days to go</Muted>
            </div>
            <div className="flex gap-2">
              <DemoButton className="flex-1 text-[12px]">
                <BellPlus size={13} aria-hidden="true" /> Remind me
              </DemoButton>
              <DemoButton className="flex-1 text-[12px]">
                <Eye size={13} aria-hidden="true" /> What to watch
              </DemoButton>
            </div>
          </div>
          <Muted className="mt-2.5">
            <Mic size={14} aria-hidden="true" className="mr-1 inline align-[-2px]" />
            Watch for: deposit growth vs credit (the CD-ratio thread), NIM direction as borrowings
            reprice, and any word on subsidiary value-unlock.
          </Muted>
        </div>
      </TwoCol>
    </Section>
  )
}
