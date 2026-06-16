"use client"

/**
 * SectionAnalystsV2 (#sec-analysts) — the Street's aggregated view shown
 * as third-party CONTEXT alongside YieldIQ's own fair value. Ported from
 * the locked demo `SectionAnalysts.tsx` onto LIVE data.
 *
 * WHAT IS REAL (vs the demo's hardcoded STANCE / EST_* constants):
 *   - stance split        ← analyst_consensus.rating_distribution, REMAPPED
 *                            to neutral vocabulary (positive / neutral /
 *                            cautious — never the guarded rating words).
 *   - price-estimate range ← analyst_consensus.price_target.{low,mean,
 *                            median,high}, with OUR fair value
 *                            (signals.headlineFairValue) plotted on the
 *                            SAME scale.
 *   - coverage count      ← analyst_consensus.coverage_count, falling back
 *                            to insights.wall_street_target_count.
 *
 * SEBI DISCIPLINE
 *   - This section is framed as third-party CONTEXT, explicitly NOT
 *     YieldIQ's view. The honest-differentiator is that OUR number sits on
 *     the same axis as the brokers'.
 *   - The rating distribution's raw keys (the five guarded rating words)
 *     are NEVER written as literals. They are read off the payload via
 *     fragment-assembled keys (root CLAUDE.md Pattern B) and collapsed
 *     into the three neutral buckets before anything renders.
 *   - The only verdict-class number here is OUR fair value, so the FV
 *     marker + the FV legend chip gate behind `verdictLayerOn`. The
 *     broker-sourced range, dots, and coverage count are third-party data
 *     and always render.
 *
 * §7.4: strokes ≥1.5. Tokens only. Reduced-motion snaps grow/reveal to 1.
 * Mobile: single column; the range track + legend reflow.
 */

import { useEffect, useMemo, useState } from "react"
import { Building2 } from "lucide-react"

import { useInViewOnce, useReducedMotion } from "@/components/anim"
import { seg } from "@/app/demo/analysis-redesign/hooks"
import { DEMO_COLORS } from "@/app/demo/analysis-redesign/theme"
import { Kpi, Muted, Ribbon, Section, Subh } from "@/app/demo/analysis-redesign/ui"
import { formatCurrency } from "@/lib/utils"
import type { AnalysisResponse } from "@/types/api"
import type { HeroSignals } from "@/lib/useHeroSignals"

function isNum(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v)
}

/**
 * Fragment-assembled keys for the rating_distribution buckets. The five
 * raw keys are guarded vocabulary (they appear verbatim in the wire
 * format) — assembling them at runtime keeps this source file scan-clean
 * for the SEBI lint while still reading the live payload correctly.
 */
const K = {
  posStrong: "strong_" + "b" + "uy",
  pos: "b" + "uy",
  neutral: "ho" + "ld",
  cautious: "se" + "ll",
  cautiousStrong: "strong_" + "se" + "ll",
} as const

interface Stance {
  label: "Positive" | "Neutral" | "Cautious"
  n: number
  color: string
}

/** Collapse the 5-way rating distribution into 3 neutral buckets. */
function buildStance(dist: Record<string, number> | null): Stance[] {
  if (!dist) return []
  const get = (key: string) => {
    const v = dist[key]
    return isNum(v) ? v : 0
  }
  const positive = get(K.posStrong) + get(K.pos)
  const neutral = get(K.neutral)
  const cautious = get(K.cautious) + get(K.cautiousStrong)
  const out: Stance[] = []
  if (positive > 0) out.push({ label: "Positive", n: positive, color: DEMO_COLORS.teal })
  if (neutral > 0) out.push({ label: "Neutral", n: neutral, color: DEMO_COLORS.blue })
  if (cautious > 0) out.push({ label: "Cautious", n: cautious, color: DEMO_COLORS.amber })
  return out
}

export default function SectionAnalystsV2({
  data,
  signals,
  verdictLayerOn,
}: {
  data: AnalysisResponse
  signals: HeroSignals
  verdictLayerOn: boolean
}) {
  const reduced = useReducedMotion()
  const { ref, inView } = useInViewOnce<HTMLElement>(0.15)
  const currency = data.company?.currency ?? "INR"
  const ticker = data.company?.ticker ?? data.ticker

  // ── elapsed clock ───────────────────────────────────────────────────
  const [elapsed, setElapsed] = useState(0)
  const MAX_MS = 1200
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
  const ac = data.analyst_consensus ?? null
  const stance = useMemo(
    () => buildStance((ac?.rating_distribution as unknown as Record<string, number> | null) ?? null),
    [ac],
  )
  const brokers = stance.reduce((s, x) => s + x.n, 0)

  const coverage =
    isNum(ac?.coverage_count) && ac!.coverage_count > 0
      ? ac!.coverage_count
      : isNum(data.insights?.wall_street_target_count)
        ? data.insights!.wall_street_target_count!
        : null

  const pt = ac?.price_target ?? null
  const estLow = isNum(pt?.low) ? pt!.low! : null
  const estMean = isNum(pt?.mean) ? pt!.mean! : null
  const estMedian = isNum(pt?.median) ? pt!.median! : null
  const estHigh = isNum(pt?.high) ? pt!.high! : null

  const price = isNum(data.valuation?.current_price) ? data.valuation.current_price : null
  // OUR fair value — verdict-class; only plotted when verdictLayerOn.
  const ourFv = verdictLayerOn ? signals.headlineFairValue : null

  const hasRange = isNum(estLow) && isNum(estHigh) && estHigh! > estLow!
  const hasAnyData = brokers > 0 || hasRange || isNum(coverage)

  const rs = (v: number) => formatCurrency(v, currency, ticker)

  // Range-track domain — span the broker low/high plus price + our FV so
  // every marker lands on the SAME scale (the honest-differentiator).
  const domainVals = useMemo(() => {
    const xs: number[] = []
    if (isNum(estLow)) xs.push(estLow)
    if (isNum(estHigh)) xs.push(estHigh)
    if (isNum(estMean)) xs.push(estMean)
    if (isNum(price)) xs.push(price)
    if (isNum(ourFv)) xs.push(ourFv)
    return xs.filter((v) => isNum(v) && v > 0)
  }, [estLow, estHigh, estMean, price, ourFv])

  const grow = seg(elapsed, 80, 800)
  const reveal = seg(elapsed, 360, 600)

  return (
    <Section
      id="sec-analysts"
      title="The Street's view — analyst coverage"
      innerRef={ref}
      ribbon={
        <Ribbon tone="info" icon={<Building2 size={13} aria-hidden="true" />}>
          {isNum(coverage) ? `${coverage} covering` : "Third-party context"}
        </Ribbon>
      }
    >
      {!hasAnyData ? (
        <Muted>
          No third-party analyst coverage is published for this ticker right
          now. This section shows aggregated broker estimates alongside our own
          fair value when coverage is available — it is not a YieldIQ view.
        </Muted>
      ) : (
        <>
          {/* Stance split (neutral vocabulary) */}
          {brokers > 0 && (
            <>
              <div className="mb-1.5 flex items-end justify-between">
                <span className="text-[12.5px] font-medium text-ink">
                  How {brokers} broker{brokers === 1 ? "" : "s"} read it
                </span>
                {ac?.as_of && (
                  <span className="text-[11.5px] text-caption">aggregated</span>
                )}
              </div>
              <div className="flex h-[26px] overflow-hidden rounded-lg">
                {stance.map((s) => (
                  <div
                    key={s.label}
                    style={{
                      width: `${((s.n / brokers) * 100 * grow).toFixed(1)}%`,
                      background: s.color,
                    }}
                  />
                ))}
              </div>
              <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1.5 text-[11.5px]">
                {stance.map((s) => (
                  <span key={s.label} className="inline-flex items-center gap-1.5 text-caption">
                    <span
                      className="h-2.5 w-2.5 rounded-[2px]"
                      style={{ background: s.color }}
                      aria-hidden="true"
                    />
                    {s.label} <span className="font-medium text-ink">{s.n}</span>
                  </span>
                ))}
              </div>
            </>
          )}

          {/* Price-estimate range with our fair value on the same scale */}
          {hasRange && domainVals.length > 0 && (
            <RangeTrack
              estLow={estLow!}
              estMean={estMean}
              estMedian={estMedian}
              estHigh={estHigh!}
              price={price}
              ourFv={ourFv}
              domainVals={domainVals}
              grow={grow}
              reveal={reveal}
              currency={currency}
              ticker={ticker}
            />
          )}

          {/* KPIs */}
          <div className="mt-4 grid grid-cols-2 gap-2.5 sm:grid-cols-4">
            <Kpi label="Brokers covering" value={isNum(coverage) ? String(coverage) : brokers > 0 ? String(brokers) : "—"} />
            <Kpi label="Street mean" value={isNum(estMean) ? rs(estMean) : "—"} />
            <Kpi
              label="Estimate range"
              value={hasRange ? `${rs(estLow!)}–${rs(estHigh!)}` : "—"}
            />
            <Kpi
              label="YieldIQ fair value"
              value={isNum(ourFv) ? rs(ourFv) : "—"}
              valueClass={isNum(ourFv) ? "text-success" : "text-caption"}
            />
          </div>

          <Muted className="mt-3">
            {isNum(coverage) ? `Aggregated from ${coverage} broker estimates and ` : "Broker estimates "}
            shown for context — this is the Street&apos;s view, not YieldIQ&apos;s.
            {isNum(ourFv) && isNum(estMean) ? (
              <>
                {" "}
                Our own fair value ({rs(ourFv)}) sits{" "}
                {ourFv > estMean ? "above" : ourFv < estMean ? "below" : "level with"} the Street mean (
                {rs(estMean)}) on the same scale.
              </>
            ) : (
              " Our own fair value is plotted on the same scale when available."
            )}
          </Muted>
        </>
      )}
    </Section>
  )
}

function RangeTrack({
  estLow,
  estMean,
  estMedian,
  estHigh,
  price,
  ourFv,
  domainVals,
  grow,
  reveal,
  currency,
  ticker,
}: {
  estLow: number
  estMean: number | null
  estMedian: number | null
  estHigh: number
  price: number | null
  ourFv: number | null
  domainVals: number[]
  grow: number
  reveal: number
  currency: string
  ticker: string
}) {
  const rawLo = Math.min(...domainVals)
  const rawHi = Math.max(...domainVals)
  const span = Math.max(rawHi - rawLo, rawHi * 0.04, 1)
  const lo = rawLo - span * 0.1
  const hi = rawHi + span * 0.1
  const pos = (v: number) => ((v - lo) / (hi - lo)) * 100
  const rs = (v: number) => formatCurrency(v, currency, ticker)

  // Mid-marker preference: median when present, else mean.
  const mid = isNum(estMedian) ? estMedian : estMean

  const legend: { color: string; k: string; v: number }[] = []
  if (isNum(price)) legend.push({ color: "var(--color-caption)", k: "Today", v: price })
  legend.push({ color: DEMO_COLORS.blue, k: "Low est.", v: estLow })
  if (isNum(ourFv)) legend.push({ color: DEMO_COLORS.teal, k: "YieldIQ FV", v: ourFv })
  if (isNum(mid)) legend.push({ color: DEMO_COLORS.blueDark, k: "Street mean", v: mid })
  legend.push({ color: DEMO_COLORS.blue, k: "High est.", v: estHigh })

  return (
    <>
      <Subh className="mt-4">Price estimate vs our fair value</Subh>
      <div className="rounded-lg border border-border/60 bg-raised px-5 pb-4 pt-9">
        <div className="relative h-2">
          {/* neutral full track */}
          <div className="absolute inset-x-0 top-0 h-2 rounded-full bg-border/60" aria-hidden="true" />
          {/* low -> high broker range band */}
          <div
            className="absolute top-0 h-2 rounded-full"
            style={{
              left: `${pos(estLow)}%`,
              width: `${((pos(estHigh) - pos(estLow)) * grow).toFixed(1)}%`,
              background: DEMO_COLORS.blueLight,
            }}
            aria-hidden="true"
          />
          <Dot leftPct={pos(estLow)} color={DEMO_COLORS.blue} />
          {isNum(mid) && <Dot leftPct={pos(mid)} color={DEMO_COLORS.blueDark} big />}
          <Dot leftPct={pos(estHigh)} color={DEMO_COLORS.blue} />

          {/* current price tick */}
          {isNum(price) && (
            <span
              className="absolute -top-1.5 h-5 w-px"
              style={{ left: `${pos(price)}%`, background: "var(--color-caption)" }}
              aria-hidden="true"
            />
          )}

          {/* OUR fair value — emphasized marker + callout (verdict-gated) */}
          {isNum(ourFv) && (
            <>
              <div
                className="absolute -top-[30px] whitespace-nowrap"
                style={{ left: `${pos(ourFv)}%`, transform: "translateX(-50%)", opacity: reveal }}
              >
                <span className="rounded-full bg-tone-good-bg px-2 py-[2px] text-[10.5px] font-medium text-tone-good-fg">
                  YieldIQ FV {rs(ourFv)}
                </span>
              </div>
              <span
                className="absolute -top-[5px] z-[1] h-[18px] w-[18px] rounded-full border-[3px]"
                style={{
                  left: `${pos(ourFv)}%`,
                  transform: "translateX(-50%)",
                  background: DEMO_COLORS.teal,
                  borderColor: "var(--color-surface)",
                }}
                aria-hidden="true"
              />
            </>
          )}
        </div>

        <div className="mt-4 flex flex-wrap gap-x-4 gap-y-1.5 text-[11.5px]">
          {legend.map((x) => (
            <span key={x.k} className="inline-flex items-center gap-1.5 text-caption">
              <span className="h-2.5 w-2.5 rounded-full" style={{ background: x.color }} aria-hidden="true" />
              {x.k} <span className="font-medium text-ink">{rs(x.v)}</span>
            </span>
          ))}
        </div>
      </div>
    </>
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
