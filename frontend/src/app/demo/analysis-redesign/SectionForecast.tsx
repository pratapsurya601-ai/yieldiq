"use client"

// I · §5b Forecast (03) — fair-value projection fan (cone clips open),
// horizon slider with bear/base/bull + implied-pace chips. Framing
// locked: "Projection, not a promise"; implied pace is arithmetic.
import { useMemo, useState } from "react"
import { CircleDashed } from "lucide-react"

import { FAIR_VALUE, FAN_RATES, PRICE, fanPath } from "./data"
import { inr, seg, useStageClock } from "./hooks"
import { DEMO_COLORS, TOKENS } from "./theme"
import { Muted, Ribbon, Section } from "./ui"

const STEPS = 40
const fxX = (t: number) => 80 + (t / 5) * 430
const fxY = (v: number) => 18 + ((4200 - v) / 2700) * 186

export default function SectionForecast() {
  const { ref, elapsed } = useStageClock(1300, 0.2)
  const [h, setH] = useState(3)

  const { bullPts, basePts, bearPts, conePts } = useMemo(() => {
    const bull: string[] = []
    const base: string[] = []
    const bear: string[] = []
    for (let i = 0; i <= STEPS; i++) {
      const t = (i / STEPS) * 5
      bull.push(`${fxX(t).toFixed(1)},${fxY(fanPath(FAN_RATES.bull, t)).toFixed(1)}`)
      base.push(`${fxX(t).toFixed(1)},${fxY(fanPath(FAN_RATES.base, t)).toFixed(1)}`)
      bear.push(`${fxX(t).toFixed(1)},${fxY(fanPath(FAN_RATES.bear, t)).toFixed(1)}`)
    }
    return {
      bullPts: bull.join(" "),
      basePts: base.join(" "),
      bearPts: bear.join(" "),
      conePts: bull.join(" ") + " " + [...bear].reverse().join(" "),
    }
  }, [])

  const clipW = 436 * seg(elapsed, 0, 1100)
  const bear = fanPath(FAN_RATES.bear, h)
  const base = fanPath(FAN_RATES.base, h)
  const bull = fanPath(FAN_RATES.bull, h)
  const pace = (Math.pow(base / PRICE, 1 / h) - 1) * 100
  const scrubX = fxX(h)

  return (
    <Section
      id="sec-5b"
      num="5b"
      title="Forecast — where the model sees fair value going"
      innerRef={ref}
      ribbon={
        <Ribbon tone="warn" icon={<CircleDashed size={13} aria-hidden="true" />}>
          Projection, not a promise
        </Ribbon>
      }
    >
      <svg
        viewBox="0 0 560 248"
        width="100%"
        className="block"
        role="img"
        aria-label="Fair-value projection fan: from 2010 rupees today the base path reaches about 3390 in five years, the bull path about 4040 and the bear path about 2690; current price is 1684."
      >
        <defs>
          <clipPath id="demoFanClip">
            <rect x={80} y={0} width={clipW.toFixed(1)} height={248} />
          </clipPath>
        </defs>
        {[2000, 3000, 4000].map((v) => (
          <g key={v}>
            <line x1={80} x2={516} y1={fxY(v)} y2={fxY(v)} stroke={TOKENS.border} strokeDasharray="2 5" />
            <text x={522} y={fxY(v) + 3} fontSize={9.5} fill={TOKENS.caption} className="num">
              ₹{(v / 1000).toFixed(0)}k
            </text>
          </g>
        ))}
        {[0, 1, 2, 3, 4, 5].map((yr) => (
          <text key={yr} x={fxX(yr)} y={226} textAnchor="middle" fontSize={10} fill={TOKENS.caption}>
            {yr === 0 ? "now" : `+${yr}y`}
          </text>
        ))}
        <g clipPath="url(#demoFanClip)">
          <polygon points={conePts} fill="rgba(29,158,117,0.12)" />
          <polyline points={bullPts} fill="none" stroke={DEMO_COLORS.tealLight} strokeWidth={1.8} />
          <polyline points={bearPts} fill="none" stroke={DEMO_COLORS.coralLight} strokeWidth={1.8} />
          <polyline points={basePts} fill="none" stroke={DEMO_COLORS.teal} strokeWidth={2.5} strokeDasharray="7 5" />
          <text x={498} y={fxY(fanPath(FAN_RATES.bull, 4.82)) - 6} textAnchor="end" fontSize={10} fill={DEMO_COLORS.tealDeep}>
            Bull 15%
          </text>
          <text x={498} y={fxY(fanPath(FAN_RATES.base, 4.82)) - 6} textAnchor="end" fontSize={10} fontWeight={500} fill={DEMO_COLORS.tealDark}>
            Base 11%
          </text>
          <text x={498} y={fxY(fanPath(FAN_RATES.bear, 4.82)) + 13} textAnchor="end" fontSize={10} fill={DEMO_COLORS.coralDark}>
            Bear 6%
          </text>
        </g>
        <circle cx={fxX(0)} cy={fxY(PRICE)} r={4.5} fill={TOKENS.ink} />
        <text x={fxX(0) - 6} y={fxY(PRICE) + 14} fontSize={10.5} fontWeight={500} fill={TOKENS.ink} className="num">
          Price ₹1,684
        </text>
        <circle cx={fxX(0)} cy={fxY(FAIR_VALUE)} r={4} fill={DEMO_COLORS.teal} />
        <text x={fxX(0) - 6} y={fxY(FAIR_VALUE) - 8} fontSize={10.5} fill={DEMO_COLORS.tealDark} className="num">
          FV ₹2,010
        </text>
        <g>
          <line x1={scrubX} x2={scrubX} y1={14} y2={210} stroke={TOKENS.caption} strokeDasharray="3 3" />
          <circle cx={scrubX} cy={fxY(base)} r={3.5} fill={DEMO_COLORS.teal} />
        </g>
      </svg>

      <div className="mb-2 mt-2.5 flex items-center gap-2.5">
        <label htmlFor="demo-hz" className="whitespace-nowrap text-[12.5px] text-caption">
          Horizon
        </label>
        <input
          id="demo-hz"
          type="range"
          min={1}
          max={5}
          step={1}
          value={h}
          onChange={(e) => setH(Number(e.target.value))}
          className="flex-1 accent-[var(--color-brand)]"
        />
        <span className="num min-w-[30px] text-[12.5px] font-medium text-ink">{h}y</span>
      </div>

      <div className="flex flex-wrap gap-2">
        <HorizonChip label="Bear" value={inr(bear)} color={DEMO_COLORS.coralDark} />
        <HorizonChip label="Base" value={inr(base)} color={DEMO_COLORS.tealDark} />
        <HorizonChip label="Bull" value={inr(bull)} color={DEMO_COLORS.tealDeep} />
        <HorizonChip label="Implied pace to base" value={`~${pace.toFixed(1)}% / yr`} color={TOKENS.ink} grow />
      </div>

      <Muted className="mt-2 text-[11.5px]">
        Fan = the model&apos;s fair-value paths under bear (6%), base (11%) and bull (15%) growth.
        &quot;Implied pace&quot; is arithmetic — what reaching the base path from today&apos;s ₹1,684
        would equal per year — not a price forecast.
      </Muted>
    </Section>
  )
}

function HorizonChip({ label, value, color, grow = false }: { label: string; value: string; color: string; grow?: boolean }) {
  return (
    <div className="rounded-lg bg-raised px-1.5 py-2 text-center" style={{ flex: grow ? 1.6 : 1 }}>
      <span className="text-[11.5px] text-caption">{label}</span>
      <b className="num mt-px block text-[15px] font-medium" style={{ color }}>
        {value}
      </b>
    </div>
  )
}
