"use client"

/**
 * SectionForecastV2 (#sec-forecast) — the fair-value projection fan,
 * ported from the locked demo `SectionForecast.tsx` onto LIVE data.
 *
 * WHAT IS REAL (vs the demo's hardcoded FAN_RATES / FAIR_VALUE):
 *   - bear / base / bull growth rates ← scenarios.{bear,base,bull}.growth
 *     (with valuation.fcf_growth_rate as the base fallback when the
 *     scenario block is absent).
 *   - the anchor the fan grows from ← signals.headlineFairValue (the ONE
 *     canonical FV number; no direct valuation.fair_value read).
 *   - the "today" price dot ← valuation.current_price.
 *   - horizon slider (1–5y) scrubs the fan and the bear/base/bull chips.
 *
 * FRAMING (locked + SEBI): "Projection, not a promise". The fan is the
 * model's fair-value PATH under three growth assumptions — it is NOT a
 * price forecast. The "implied pace" chip is pure arithmetic (the CAGR
 * that reaching the base path from today's price would equal). Every
 * caption describes the COMPUTATION; no banned vocabulary, no verdict.
 *
 * GATING: the fan grows from the headline FV, which is a verdict-class
 * number. When `verdictLayerOn` is OFF the whole projection is suppressed
 * (a projection FROM a withheld FV would be meaningless), replaced by a
 * neutral note. The horizon slider + chart only render when ON and the FV
 * anchor + at least the base growth rate are available.
 *
 * §7.4: chart strokes ≥1.5. Tokens only. Reduced-motion snaps the cone
 * open instantly. Mobile: single column; the SVG scales to width.
 */

import { useEffect, useMemo, useState } from "react"
import { CircleDashed } from "lucide-react"

import { useInViewOnce, useReducedMotion } from "@/components/anim"
import { seg } from "@/app/demo/analysis-redesign/hooks"
import { DEMO_COLORS, TOKENS } from "@/app/demo/analysis-redesign/theme"
import { Muted, Ribbon, Section } from "@/app/demo/analysis-redesign/ui"
import { formatCurrency } from "@/lib/utils"
import type { AnalysisResponse } from "@/types/api"
import type { HeroSignals } from "@/lib/useHeroSignals"

function isNum(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v)
}

const STEPS = 40
const YEARS = 5

/** Compound a rate over `years` from a base value. */
function projectPath(base: number, rate: number, years: number): number {
  return base * Math.pow(1 + rate, years)
}

export default function SectionForecastV2({
  data,
  signals,
  verdictLayerOn,
}: {
  data: AnalysisResponse
  signals: HeroSignals
  verdictLayerOn: boolean
}) {
  const reduced = useReducedMotion()
  const { ref, inView } = useInViewOnce<HTMLElement>(0.2)
  const [h, setH] = useState(3)
  const currency = data.company?.currency ?? "INR"
  const ticker = data.company?.ticker ?? data.ticker

  // ── elapsed clock (cone clip) ───────────────────────────────────────
  const [elapsed, setElapsed] = useState(0)
  const MAX_MS = 1300
  useEffect(() => {
    if (!inView) return
    if (reduced) {
      setElapsed(MAX_MS)
      return
    }
    let raf = 0
    const t0 = performance.now()
    const step = (t: number) => {
      const e = Math.min(t - t0, MAX_MS)
      setElapsed(e)
      if (e < MAX_MS) raf = requestAnimationFrame(step)
    }
    raf = requestAnimationFrame(step)
    return () => cancelAnimationFrame(raf)
  }, [inView, reduced])

  // ── real inputs ─────────────────────────────────────────────────────
  const fv = signals.headlineFairValue // canonical FV anchor (verdict-class)
  const price = isNum(data.valuation?.current_price) ? data.valuation.current_price : null
  const sc = data.scenarios ?? null
  const baseGrowthFallback = isNum(data.valuation?.fcf_growth_rate)
    ? data.valuation.fcf_growth_rate
    : null

  // scenarios.*.growth arrive as decimals (0.11 = 11%). Fall back to the
  // engine's base FCF growth when the scenario block is absent, and derive
  // a ±band around it so the cone still has width.
  const rates = useMemo(() => {
    const base =
      isNum(sc?.base?.growth) ? sc!.base.growth : baseGrowthFallback
    if (!isNum(base)) return null
    const bear = isNum(sc?.bear?.growth) ? sc!.bear.growth : base - 0.05
    const bull = isNum(sc?.bull?.growth) ? sc!.bull.growth : base + 0.04
    // Keep the band ordered (bear ≤ base ≤ bull) even if the engine's
    // scenario growths cross (rare but possible on distressed names).
    const lo = Math.min(bear, base, bull)
    const hi = Math.max(bear, base, bull)
    return { bear: lo, base, bull: hi }
  }, [sc, baseGrowthFallback])

  const showFan = verdictLayerOn && isNum(fv) && fv! > 0 && rates !== null

  return (
    <Section
      id="sec-forecast"
      num="5b"
      title="Forecast — where the model sees fair value going"
      innerRef={ref}
      ribbon={
        <Ribbon tone="warn" icon={<CircleDashed size={13} aria-hidden="true" />}>
          Projection, not a promise
        </Ribbon>
      }
    >
      {showFan ? (
        <FanChart
          fv={fv!}
          price={price}
          rates={rates!}
          h={h}
          onHorizon={setH}
          elapsed={elapsed}
          currency={currency}
          ticker={ticker}
        />
      ) : (
        <Muted>
          The projection paths grow from the model&apos;s fair value under
          bear, base and bull growth. They appear here once the fair-value
          anchor and the scenario growth rates are published for this
          ticker.
        </Muted>
      )}
    </Section>
  )
}

function FanChart({
  fv,
  price,
  rates,
  h,
  onHorizon,
  elapsed,
  currency,
  ticker,
}: {
  fv: number
  price: number | null
  rates: { bear: number; base: number; bull: number }
  h: number
  onHorizon: (h: number) => void
  elapsed: number
  currency: string
  ticker: string
}) {
  // Vertical domain — from a hair below the lower of {price, fv} to the
  // 5y bull terminal, padded.
  const bull5 = projectPath(fv, rates.bull, YEARS)
  const floor = Math.min(isNum(price) ? price : fv, fv) * 0.92
  const ceil = bull5 * 1.06
  const PLOT_T = 18
  const PLOT_B = 204
  const PLOT_L = 80
  const PLOT_R = 510
  const fxX = (t: number) => PLOT_L + (t / YEARS) * (PLOT_R - PLOT_L)
  const fxY = (v: number) => PLOT_T + ((ceil - v) / (ceil - floor)) * (PLOT_B - PLOT_T)

  const { bullPts, basePts, bearPts, conePts } = useMemo(() => {
    const bull: string[] = []
    const base: string[] = []
    const bear: string[] = []
    for (let i = 0; i <= STEPS; i++) {
      const t = (i / STEPS) * YEARS
      bull.push(`${fxX(t).toFixed(1)},${fxY(projectPath(fv, rates.bull, t)).toFixed(1)}`)
      base.push(`${fxX(t).toFixed(1)},${fxY(projectPath(fv, rates.base, t)).toFixed(1)}`)
      bear.push(`${fxX(t).toFixed(1)},${fxY(projectPath(fv, rates.bear, t)).toFixed(1)}`)
    }
    return {
      bullPts: bull.join(" "),
      basePts: base.join(" "),
      bearPts: bear.join(" "),
      conePts: bull.join(" ") + " " + [...bear].reverse().join(" "),
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fv, rates, ceil, floor])

  const clipW = (PLOT_R - PLOT_L) * seg(elapsed, 0, 1100)
  const bearH = projectPath(fv, rates.bear, h)
  const baseH = projectPath(fv, rates.base, h)
  const bullH = projectPath(fv, rates.bull, h)
  // implied pace to the base path from today's price (pure arithmetic).
  const pace =
    isNum(price) && price > 0 ? (Math.pow(baseH / price, 1 / h) - 1) * 100 : null
  const scrubX = fxX(h)

  // Y gridlines — three rounded levels spanning the domain.
  const gridLevels = useMemo(() => {
    const out: number[] = []
    for (let i = 1; i <= 3; i++) out.push(floor + ((ceil - floor) * i) / 4)
    return out
  }, [floor, ceil])

  const rs = (v: number) => formatCurrency(v, currency, ticker)

  return (
    <>
      <svg
        viewBox="0 0 560 248"
        width="100%"
        className="block"
        role="img"
        aria-label={`Fair-value projection fan: from ${rs(fv)} today the base path reaches about ${rs(
          projectPath(fv, rates.base, YEARS),
        )} in five years, the bull path about ${rs(bull5)} and the bear path about ${rs(
          projectPath(fv, rates.bear, YEARS),
        )}.`}
      >
        <defs>
          <clipPath id="v2FanClip">
            <rect x={PLOT_L} y={0} width={clipW.toFixed(1)} height={248} />
          </clipPath>
        </defs>

        {gridLevels.map((v, i) => (
          <g key={i}>
            <line
              x1={PLOT_L}
              x2={PLOT_R}
              y1={fxY(v)}
              y2={fxY(v)}
              stroke={TOKENS.border}
              strokeDasharray="2 5"
              strokeWidth={1.5}
            />
            <text x={PLOT_R + 6} y={fxY(v) + 3} fontSize={9.5} fill={TOKENS.caption}>
              {rs(v)}
            </text>
          </g>
        ))}

        {[0, 1, 2, 3, 4, 5].map((yr) => (
          <text key={yr} x={fxX(yr)} y={226} textAnchor="middle" fontSize={10} fill={TOKENS.caption}>
            {yr === 0 ? "now" : `+${yr}y`}
          </text>
        ))}

        <g clipPath="url(#v2FanClip)">
          <polygon points={conePts} fill="rgba(29,158,117,0.12)" />
          <polyline points={bullPts} fill="none" stroke={DEMO_COLORS.tealLight} strokeWidth={1.8} />
          <polyline points={bearPts} fill="none" stroke={DEMO_COLORS.coralLight} strokeWidth={1.8} />
          <polyline
            points={basePts}
            fill="none"
            stroke={DEMO_COLORS.teal}
            strokeWidth={2.5}
            strokeDasharray="7 5"
          />
          <text
            x={PLOT_R - 12}
            y={fxY(projectPath(fv, rates.bull, 4.82)) - 6}
            textAnchor="end"
            fontSize={10}
            fill={DEMO_COLORS.tealDeep}
          >
            Bull {(rates.bull * 100).toFixed(0)}%
          </text>
          <text
            x={PLOT_R - 12}
            y={fxY(projectPath(fv, rates.base, 4.82)) - 6}
            textAnchor="end"
            fontSize={10}
            fontWeight={500}
            fill={DEMO_COLORS.tealDark}
          >
            Base {(rates.base * 100).toFixed(0)}%
          </text>
          <text
            x={PLOT_R - 12}
            y={fxY(projectPath(fv, rates.bear, 4.82)) + 13}
            textAnchor="end"
            fontSize={10}
            fill={DEMO_COLORS.coralDark}
          >
            Bear {(rates.bear * 100).toFixed(0)}%
          </text>
        </g>

        {isNum(price) && (
          <>
            <circle cx={fxX(0)} cy={fxY(price)} r={4.5} fill={TOKENS.ink} />
            <text x={fxX(0) - 6} y={fxY(price) + 14} fontSize={10.5} fontWeight={500} fill={TOKENS.ink}>
              Price {rs(price)}
            </text>
          </>
        )}
        <circle cx={fxX(0)} cy={fxY(fv)} r={4} fill={DEMO_COLORS.teal} />
        <text x={fxX(0) - 6} y={fxY(fv) - 8} fontSize={10.5} fill={DEMO_COLORS.tealDark}>
          FV {rs(fv)}
        </text>

        <g>
          <line
            x1={scrubX}
            x2={scrubX}
            y1={14}
            y2={PLOT_B + 6}
            stroke={TOKENS.caption}
            strokeDasharray="3 3"
            strokeWidth={1.5}
          />
          <circle cx={scrubX} cy={fxY(baseH)} r={3.5} fill={DEMO_COLORS.teal} />
        </g>
      </svg>

      <div className="mb-2 mt-2.5 flex items-center gap-2.5">
        <label htmlFor="v2-hz" className="whitespace-nowrap text-[12.5px] text-caption">
          Horizon
        </label>
        <input
          id="v2-hz"
          type="range"
          min={1}
          max={5}
          step={1}
          value={h}
          onChange={(e) => onHorizon(Number(e.target.value))}
          className="flex-1 accent-[var(--color-brand)]"
        />
        <span className="min-w-[30px] text-[12.5px] font-medium text-ink">{h}y</span>
      </div>

      <div className="flex flex-wrap gap-2">
        <HorizonChip label="Bear" value={rs(bearH)} color={DEMO_COLORS.coralDark} />
        <HorizonChip label="Base" value={rs(baseH)} color={DEMO_COLORS.tealDark} />
        <HorizonChip label="Bull" value={rs(bullH)} color={DEMO_COLORS.tealDeep} />
        {pace !== null && (
          <HorizonChip
            label="Implied pace to base"
            value={`~${pace.toFixed(1)}% / yr`}
            color={TOKENS.ink}
            grow
          />
        )}
      </div>

      <Muted className="mt-2 text-[11.5px]">
        The fan is the model&apos;s fair-value paths under bear (
        {(rates.bear * 100).toFixed(0)}%), base ({(rates.base * 100).toFixed(0)}%) and bull (
        {(rates.bull * 100).toFixed(0)}%) growth. &quot;Implied pace&quot; is arithmetic — what
        reaching the base path from today&apos;s price would equal per year — not a price forecast.
      </Muted>
    </>
  )
}

function HorizonChip({
  label,
  value,
  color,
  grow = false,
}: {
  label: string
  value: string
  color: string
  grow?: boolean
}) {
  return (
    <div className="rounded-lg bg-raised px-1.5 py-2 text-center" style={{ flex: grow ? 1.6 : 1 }}>
      <span className="text-[11.5px] text-caption">{label}</span>
      <b className="mt-px block text-[15px] font-medium" style={{ color }}>
        {value}
      </b>
    </div>
  )
}
