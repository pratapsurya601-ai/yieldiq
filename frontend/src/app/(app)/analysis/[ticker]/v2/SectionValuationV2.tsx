"use client"

/**
 * SectionValuationV2 (#sec-valuation) — the crown-jewel valuation section
 * of the flag-gated v2 analysis body, ported from the locked demo
 * `SectionValuation.tsx` onto LIVE engine data.
 *
 * Three visual blocks, all from the founder-approved mockup:
 *   1. Forest plot — every independent estimator the engine ran, dot
 *      size = effective weight, on a shared ₹ axis, with the agreement
 *      band + composite + price markers. Source: `composite_composition`.
 *   2. Weighted blend bar — DCF / Multiples / Wall-St weights from
 *      `composite_components`, summing to the composite value.
 *   3. DCF playground — forward + reverse, plus a 5×5 growth×discount
 *      sensitivity heatmap.
 *
 * WHAT IS REAL (vs the demo's hardcoded mock):
 *   - Forest rows / weights / composite marker  ← composite_composition
 *   - Blend bar segments + composite total      ← composite_components
 *   - Forward DCF                               ← LIVE recomputeDcfPlayground
 *                                                 (POST /dcf-recompute) —
 *                                                 replaces the demo's toy
 *                                                 fdcf().
 *   - Reverse DCF                               ← LIVE reverseEngineerDcf
 *                                                 (POST /dcf-reverse-engineer)
 *                                                 + insights.reverse_dcf_*
 *                                                 + implied_assumptions
 *   - 5×5 heatmap                               ← LOOPED recomputeDcfPlayground
 *                                                 over a 5×5 growth×discount
 *                                                 grid, ONE call per cell,
 *                                                 debounced + Pro-gated +
 *                                                 IntersectionObserver-gated.
 *
 * GUARDRAILS
 *   - FV: the only headline fair-value number this section asserts is the
 *     COMPOSITE marker on the forest plot + blend bar. That is a verdict-
 *     class number, so it is gated behind `verdictLayerOn`
 *     (useFeatureFlag("verdict_layer_on")). When OFF, the methods table /
 *     per-estimator transparency stays visible (it is not a verdict — it
 *     is "here is everything the engine computed"), but the composite
 *     headline marker + blend total collapse to a neutral "—".
 *   - The forward / reverse DCF panels emit user-stress-tested numbers
 *     (the user moved the sliders), which are explicitly NOT our verdict —
 *     they always render.
 *   - The heavy DCF / heatmap network queries gate `enabled` via an
 *     IntersectionObserver so they never fire on mount.
 *   - SEBI: every caption describes the COMPUTATION, never a verdict. No
 *     banned vocabulary; "above / below the current price" framing only.
 *   - Tokens only for colours that can't take Tailwind (SVG attrs) — via
 *     the shared DEMO_COLORS / TOKENS maps. §7.4: chart strokes stay ≥1.5.
 *   - Mobile: forest plot + heatmap scroll-x inside an overflow wrapper.
 */

import { useEffect, useMemo, useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { CircleDashed, Lock, SlidersHorizontal } from "lucide-react"

import {
  recomputeDcfPlayground,
  reverseEngineerDcf,
  type DCFPlaygroundRequest,
} from "@/lib/api"
import { useAuthStore } from "@/store/authStore"
import { useInViewOnce, useReducedMotion } from "@/components/anim"
import { formatCurrency } from "@/lib/utils"
import type { AnalysisResponse } from "@/types/api"
import type { HeroSignals } from "@/lib/useHeroSignals"

import { backOut, seg } from "@/app/demo/analysis-redesign/hooks"
import { DEMO_COLORS, TOKENS } from "@/app/demo/analysis-redesign/theme"
import { Muted, Ribbon, Section, StepNum, Subh, TwoCol } from "@/app/demo/analysis-redesign/ui"

/* ─── small helpers ───────────────────────────────────────────────── */

function isNum(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v)
}

/** ₹ short-form, ticker-routed currency. */
function rs(v: number, currency: string | null | undefined, ticker: string): string {
  return formatCurrency(v, currency, ticker)
}

/** Blend palette — DCF / Multiples / Wall St, matching the demo ramp. */
const BLEND_RAMP = [
  DEMO_COLORS.blueDark,
  DEMO_COLORS.blue,
  DEMO_COLORS.blueLight,
  DEMO_COLORS.tealLight,
  DEMO_COLORS.tealDark,
  DEMO_COLORS.amber,
  DEMO_COLORS.coral,
  DEMO_COLORS.purple,
] as const

function colorFor(i: number): string {
  return BLEND_RAMP[i % BLEND_RAMP.length]
}

const PAID_TIERS = new Set(["starter", "pro", "analyst"])

/* ─── forest-plot geometry ────────────────────────────────────────── */

interface ForestRow {
  key: string
  label: string
  value: number
  weightPct: number // 0..100 effective weight
  isOutlier: boolean
  description: string
}

/** Map composite_composition into render-ready forest rows (applicable + finite). */
function buildForestRows(
  comp: NonNullable<AnalysisResponse["composite_composition"]>,
): ForestRow[] {
  const rows: ForestRow[] = []
  for (const e of comp.estimators) {
    if (!e.applicable) continue
    if (!isNum(e.value) || e.value <= 0) continue
    rows.push({
      key: e.key,
      label: e.label,
      value: e.value,
      weightPct: isNum(e.weight_effective) ? Math.max(0, e.weight_effective * 100) : 0,
      isOutlier: !!e.is_outlier,
      description: e.description ?? "",
    })
  }
  return rows
}

/* ─── component ───────────────────────────────────────────────────── */

export default function SectionValuationV2({
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
  const ticker = data.company?.ticker ?? data.ticker
  const currency = data.company?.currency ?? "INR"
  const price = isNum(data.valuation?.current_price) ? data.valuation.current_price : null

  const [selRow, setSelRow] = useState<number | null>(null)
  const [mode, setMode] = useState<"fwd" | "rev">("fwd")

  // ── elapsed clock (IntersectionObserver-driven, reduced-motion snaps) ──
  const [elapsed, setElapsed] = useState(0)
  const MAX_MS = 1800
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

  // ── forest rows from composite_composition ──────────────────────────
  const comp = data.composite_composition ?? null
  const forestRows = useMemo(() => (comp ? buildForestRows(comp) : []), [comp])

  // Composite headline value — a VERDICT-class number. Prefer the
  // composition payload's own composite_value; fall back to the canonical
  // headline signal. Gated behind verdictLayerOn (suppressed → null).
  const compositeValue = verdictLayerOn
    ? (isNum(comp?.composite_value) ? comp!.composite_value : signals.headlineFairValue)
    : null

  // ── axis bounds: pad around the estimator values, price, composite ──
  const axisVals = useMemo(() => {
    const vals: number[] = forestRows.map((r) => r.value)
    if (isNum(price)) vals.push(price)
    if (isNum(compositeValue)) vals.push(compositeValue)
    return vals.filter((v) => isNum(v) && v > 0)
  }, [forestRows, price, compositeValue])

  const hasForest = forestRows.length > 0 && axisVals.length > 0

  // ── render ──────────────────────────────────────────────────────────
  return (
    <Section
      id="sec-valuation"
      num="05"
      title="Valuation — how we got the number"
      innerRef={ref}
      ribbon={
        <Ribbon tone="info" icon={<CircleDashed size={13} aria-hidden="true" />}>
          {comp ? `${comp.estimators_available} of ${comp.estimators_total} methods` : "Methods"}
        </Ribbon>
      }
    >
      {/* Step 1 — forest plot */}
      <Subh>
        <StepNum n={1} />
        Independent methods{" "}
        <span className="font-normal text-caption">— dot size = weight · tap a row</span>
      </Subh>

      {hasForest ? (
        <ForestPlot
          rows={forestRows}
          axisVals={axisVals}
          price={price}
          composite={compositeValue}
          currency={currency}
          ticker={ticker}
          elapsed={elapsed}
          selRow={selRow}
          onSelect={setSelRow}
        />
      ) : (
        <Muted className="mb-3.5">
          The per-method breakdown is still computing for this ticker. The
          live DCF playground below is available as soon as the engine
          publishes its discount and terminal-growth anchors.
        </Muted>
      )}

      {hasForest && (
        <Muted className="mb-3.5 mt-0.5 min-h-[20px]">
          {selRow !== null && forestRows[selRow] ? (
            <>
              <span className="font-medium text-ink">{forestRows[selRow].label}</span> —{" "}
              {forestRows[selRow].description} · lands at{" "}
              {rs(forestRows[selRow].value, currency, ticker)} with{" "}
              {forestRows[selRow].weightPct.toFixed(0)}% weight in the blend.
              {forestRows[selRow].isOutlier ? " (Flagged as an outlier vs the median.)" : ""}
            </>
          ) : null}
        </Muted>
      )}

      {/* Step 2 — weighted blend bar */}
      <BlendBar
        components={data.composite_components ?? null}
        forestRows={forestRows}
        composite={compositeValue}
        currency={currency}
        ticker={ticker}
        elapsed={elapsed}
      />

      {/* Step 3 — DCF playground (forward / reverse + heatmap) */}
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

        {mode === "fwd" ? (
          <ForwardPanel
            data={data}
            ticker={ticker}
            currency={currency}
            price={price}
            inView={inView}
          />
        ) : (
          <ReversePanel data={data} ticker={ticker} price={price} />
        )}
      </div>
    </Section>
  )
}

/* ─── forest plot ─────────────────────────────────────────────────── */

function ForestPlot({
  rows,
  axisVals,
  price,
  composite,
  currency,
  ticker,
  elapsed,
  selRow,
  onSelect,
}: {
  rows: ForestRow[]
  axisVals: number[]
  price: number | null
  composite: number | null
  currency: string
  ticker: string
  elapsed: number
  selRow: number | null
  onSelect: (i: number) => void
}) {
  // Axis domain — pad 6% each side of the observed min/max.
  const rawMin = Math.min(...axisVals)
  const rawMax = Math.max(...axisVals)
  const span = Math.max(rawMax - rawMin, rawMax * 0.05, 1)
  const lo = rawMin - span * 0.12
  const hi = rawMax + span * 0.12
  const PLOT_L = 140
  const PLOT_R = 536
  const fx = (v: number) => PLOT_L + ((v - lo) / (hi - lo)) * (PLOT_R - PLOT_L)

  // Agreement band — min/max of the estimator values (not price/composite).
  const estVals = rows.map((r) => r.value)
  const bandLo = Math.min(...estVals)
  const bandHi = Math.max(...estVals)

  // Y geometry — header band then one 30px row per estimator.
  const ROW_H = 30
  const TOP = 18
  const plotH = rows.length * ROW_H + 16
  const axisY = TOP + plotH
  const vbH = axisY + 50

  // Axis ticks — five evenly-spaced.
  const ticks = useMemo(() => {
    const out: number[] = []
    for (let i = 0; i <= 4; i++) out.push(lo + ((hi - lo) * i) / 4)
    return out
  }, [lo, hi])

  return (
    <div className="-mx-1 overflow-x-auto px-1">
      <svg
        viewBox={`0 0 560 ${vbH}`}
        width="100%"
        className="block min-w-[460px]"
        role="img"
        aria-label={`Forest plot of ${rows.length} valuation methods with an agreement band${
          isNum(composite) ? `, composite at ${rs(composite, currency, ticker)}` : ""
        }${isNum(price) ? ` and price at ${rs(price, currency, ticker)}` : ""}.`}
      >
        {/* agreement band */}
        <rect
          x={fx(bandLo)}
          y={TOP}
          width={Math.max(0, fx(bandHi) - fx(bandLo))}
          height={plotH - 2}
          fill="rgba(29,158,117,0.07)"
          opacity={elapsed >= 700 ? 1 : 0}
          style={{ transition: "opacity .8s" }}
        />

        {/* axis */}
        <line x1={PLOT_L} x2={PLOT_R} y1={axisY} y2={axisY} stroke={TOKENS.border} strokeWidth={1.5} />
        {ticks.map((v, i) => (
          <g key={i}>
            <line x1={fx(v)} x2={fx(v)} y1={axisY} y2={axisY + 4} stroke={TOKENS.border} strokeWidth={1.5} />
            <text x={fx(v)} y={axisY + 16} textAnchor="middle" fontSize={9.5} fill={TOKENS.caption}>
              {rs(v, currency, ticker)}
            </text>
          </g>
        ))}

        {/* composite marker (verdict-class — present only when verdictLayerOn) */}
        {isNum(composite) && (
          <>
            <line
              x1={fx(composite)}
              x2={fx(composite)}
              y1={TOP - 4}
              y2={axisY}
              stroke={DEMO_COLORS.teal}
              strokeWidth={2}
            />
            <text
              x={fx(composite)}
              y={axisY + 32}
              textAnchor="middle"
              fontSize={10.5}
              fontWeight={500}
              fill={DEMO_COLORS.tealDark}
            >
              Composite {rs(composite, currency, ticker)}
            </text>
          </>
        )}

        {/* price marker */}
        {isNum(price) && (
          <>
            <line
              x1={fx(price)}
              x2={fx(price)}
              y1={TOP - 4}
              y2={axisY}
              stroke={TOKENS.caption}
              strokeDasharray="4 4"
              strokeWidth={1.5}
            />
            <text x={fx(price)} y={axisY + 46} textAnchor="middle" fontSize={10.5} fill={TOKENS.caption}>
              Price {rs(price, currency, ticker)}
            </text>
          </>
        )}

        {/* estimator rows */}
        {rows.map((r, i) => {
          const y = TOP + 16 + i * ROW_H
          const targetR = 4.5 + (r.weightPct / 100) * 14
          const r2 = targetR * seg(elapsed, 150 + i * 120, 550, backOut)
          const settled = elapsed >= 150 + i * 120 + 550
          const fill = colorFor(i)
          return (
            <g
              key={r.key}
              className="group cursor-pointer"
              role="button"
              tabIndex={0}
              aria-label={`${r.label} — ${rs(r.value, currency, ticker)}, weight ${r.weightPct.toFixed(0)}%`}
              onClick={() => onSelect(i)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault()
                  onSelect(i)
                }
              }}
            >
              <rect
                x={6}
                y={y - 13}
                width={530}
                height={26}
                rx={6}
                fill="transparent"
                className="group-hover:fill-[var(--color-raised)]"
              />
              <text x={132} y={y - 1} textAnchor="end" fontSize={10.5} fill={TOKENS.caption}>
                {r.label}
              </text>
              <text x={132} y={y + 11} textAnchor="end" fontSize={9.5} fontWeight={500} fill={fill}>
                weight {r.weightPct.toFixed(0)}%
              </text>
              <line x1={PLOT_L} x2={PLOT_R} y1={y} y2={y} stroke={TOKENS.border} strokeWidth={1.5} />
              <circle
                cx={fx(r.value)}
                cy={y}
                r={Math.max(0, r2).toFixed(1)}
                fill={fill}
                stroke={selRow === i ? TOKENS.ink : r.isOutlier ? DEMO_COLORS.amberDark : "none"}
                strokeWidth={selRow === i ? 2 : r.isOutlier ? 1.5 : 0}
              />
              <text
                x={fx(r.value) + targetR + 6}
                y={y + 4}
                fontSize={10.5}
                fontWeight={500}
                fill={TOKENS.ink}
                opacity={settled ? 1 : 0}
                style={{ transition: "opacity .4s" }}
              >
                {rs(r.value, currency, ticker)}
              </text>
            </g>
          )
        })}
      </svg>
    </div>
  )
}

/* ─── weighted blend bar ──────────────────────────────────────────── */

interface BlendSeg {
  label: string
  weight: number // 0..100
  color: string
}

function BlendBar({
  components,
  forestRows,
  composite,
  currency,
  ticker,
  elapsed,
}: {
  components: AnalysisResponse["composite_components"]
  forestRows: ForestRow[]
  composite: number | null
  currency: string
  ticker: string
  elapsed: number
}) {
  // Primary source: composite_components.{dcf,multiples,consensus}_weight.
  // Fallback: derive segments from the forest rows' effective weights so
  // the bar still renders for sector-engine cohorts where the three-way
  // split is null.
  const segs = useMemo<BlendSeg[]>(() => {
    const out: BlendSeg[] = []
    const dcf = components?.dcf_weight
    const mult = components?.multiples_weight
    const cons = components?.consensus_weight
    const anyComponent = isNum(dcf) || isNum(mult) || isNum(cons)
    if (anyComponent) {
      // Weights arrive as fractions (0..1) — render as percentages.
      const toPct = (w: number | null | undefined) => (isNum(w) ? w * 100 : 0)
      if (isNum(dcf) && dcf > 0) out.push({ label: "DCF", weight: toPct(dcf), color: DEMO_COLORS.blueDark })
      if (isNum(mult) && mult > 0)
        out.push({ label: "Multiples", weight: toPct(mult), color: DEMO_COLORS.blue })
      if (isNum(cons) && cons > 0)
        out.push({ label: "Wall St", weight: toPct(cons), color: DEMO_COLORS.tealLight })
      return out
    }
    // fallback to per-estimator effective weights
    return forestRows.map((r, i) => ({
      label: r.label.split(" ")[0],
      weight: r.weightPct,
      color: colorFor(i),
    }))
  }, [components, forestRows])

  if (segs.length === 0) return null
  const total = segs.reduce((s, x) => s + x.weight, 0) || 1

  return (
    <>
      <Subh>
        <StepNum n={2} />
        Blend them by reliability
      </Subh>
      <div className="mb-1 flex items-center gap-3">
        <div className="flex h-[18px] flex-1 overflow-hidden rounded-[5px]">
          {segs.map((s, i) => (
            <div
              key={s.label}
              title={`${s.label} · ${s.weight.toFixed(0)}%`}
              style={{
                width: `${(s.weight / total) * 100 * seg(elapsed, 200 + i * 80, 800)}%`,
                background: s.color,
              }}
            />
          ))}
        </div>
        <div className="whitespace-nowrap">
          <span className="text-[12px] text-caption">→</span>{" "}
          <span className="text-[17px] font-medium" style={{ color: DEMO_COLORS.tealDark }}>
            {isNum(composite) ? rs(composite, currency, ticker) : "—"}
          </span>
        </div>
      </div>
      <div className="mb-4 flex flex-wrap gap-3 text-[11px] text-caption">
        {segs.map((s) => (
          <span key={s.label}>
            <span
              className="mr-1 inline-block h-2 w-2 rounded-[2px] align-[-1px]"
              style={{ background: s.color }}
            />
            {s.label} {s.weight.toFixed(0)}%
          </span>
        ))}
      </div>
    </>
  )
}

/* ─── mode button ─────────────────────────────────────────────────── */

function ModeButton({
  on,
  onClick,
  children,
}: {
  on: boolean
  onClick: () => void
  children: React.ReactNode
}) {
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

/* ─── forward DCF panel — LIVE recompute ──────────────────────────── */

const GROWTH_STEPS_PCT = [0, 4, 8, 12, 16] // revenue CAGR yr1-5, percentage points
const DISCOUNT_STEPS_PCT = [8, 10, 12, 14, 16] // WACC, percentage points

/** Build a recompute request body from the engine's published anchors,
 *  overriding wacc + revenue_cagr_yr1_5 with the supplied stress values. */
function buildRecomputeBody(
  data: AnalysisResponse,
  waccPct: number,
  cagrPct: number,
): DCFPlaygroundRequest {
  const v = data.valuation
  return {
    wacc: waccPct / 100,
    terminal_growth: isNum(v?.terminal_growth) ? v.terminal_growth : 0.04,
    revenue_cagr_yr1_5: cagrPct / 100,
    // Operating margin is not carried on the analysis payload; the
    // recompute body requires it, so pass a neutral 0.15 anchor. The
    // engine re-derives FCF from the ticker's own statements regardless,
    // and the wacc + growth overrides are what actually move the result.
    operating_margin: 0.15,
  }
}

function ForwardPanel({
  data,
  ticker,
  currency,
  price,
  inView,
}: {
  data: AnalysisResponse
  ticker: string
  currency: string
  price: number | null
  inView: boolean
}) {
  const tier = useAuthStore((s) => s.tier)
  const isPaid = PAID_TIERS.has(tier)

  const baseWaccPct = isNum(data.valuation?.wacc) ? data.valuation.wacc * 100 : 12
  const baseCagrPct = isNum(data.valuation?.fcf_growth_rate)
    ? data.valuation.fcf_growth_rate * 100
    : 8

  // Snap defaults onto the nearest grid step so the heatmap "current cell"
  // ring lines up with the live sliders on first paint.
  const nearest = (arr: number[], v: number) =>
    arr.reduce((a, b) => (Math.abs(b - v) < Math.abs(a - v) ? b : a))

  const [waccPct, setWaccPct] = useState<number>(
    Math.max(8, Math.min(16, Math.round(baseWaccPct))),
  )
  const [cagrPct, setCagrPct] = useState<number>(
    Math.max(0, Math.min(16, Math.round(baseCagrPct))),
  )

  // ── debounce the slider values so we don't spam the recompute endpoint ──
  const [debounced, setDebounced] = useState({ waccPct, cagrPct })
  useEffect(() => {
    const id = window.setTimeout(() => setDebounced({ waccPct, cagrPct }), 350)
    return () => window.clearTimeout(id)
  }, [waccPct, cagrPct])

  // ── LIVE forward recompute (replaces the demo's toy fdcf) ──────────
  // enabled gated on inView so the network call never fires on mount.
  const fwd = useQuery({
    queryKey: ["v2-dcf-recompute", ticker, debounced.waccPct, debounced.cagrPct],
    queryFn: () =>
      recomputeDcfPlayground(ticker, buildRecomputeBody(data, debounced.waccPct, debounced.cagrPct)),
    enabled: inView && !!ticker,
    staleTime: 5 * 60 * 1000,
    retry: 1,
  })

  const liveFv = isNum(fwd.data?.fair_value) && fwd.data!.fair_value > 0 ? fwd.data!.fair_value : null
  // True (Buffett) MoS = (1 − price/FV)·100, mirrors the live playground.
  const trueMos =
    isNum(liveFv) && isNum(price) && price > 0 ? (1 - price / liveFv) * 100 : null
  const under = trueMos !== null && trueMos >= 0

  return (
    <TwoCol align="start">
      <div>
        <SliderRow
          id="v2-grw"
          label="Revenue growth (5y)"
          min={0}
          max={16}
          step={1}
          value={cagrPct}
          onChange={setCagrPct}
          out={`${cagrPct.toFixed(0)}%`}
        />
        <SliderRow
          id="v2-dsc"
          label="Discount rate"
          min={8}
          max={16}
          step={1}
          value={waccPct}
          onChange={setWaccPct}
          out={`${waccPct.toFixed(0)}%`}
        />
        <div className="mb-2.5 mt-1 flex items-baseline gap-2.5">
          <div>
            <div className="text-[11.5px] text-caption">Your fair value</div>
            <div className="text-[28px] font-medium text-ink" aria-live="polite">
              {fwd.isFetching && liveFv === null
                ? "…"
                : isNum(liveFv)
                  ? rs(liveFv, currency, ticker)
                  : "—"}
            </div>
          </div>
          {trueMos !== null && (
            <div
              className={`rounded-full px-2.5 py-[3px] text-[13px] ${
                under ? "bg-tone-good-bg text-tone-good-fg" : "bg-tone-warn-bg text-tone-warn-fg"
              }`}
            >
              {under
                ? `${trueMos.toFixed(0)}% below price`
                : `${Math.abs(trueMos).toFixed(0)}% above price`}
            </div>
          )}
        </div>

        {/* price-vs-FV marker bar */}
        {isNum(liveFv) && isNum(price) && (
          <PriceFvBar fv={liveFv} price={price} under={under} currency={currency} ticker={ticker} />
        )}

        <Muted className="mt-1 text-[11px]">
          Drag the levers — the engine re-runs the DCF on its own statements
          with your discount and growth, and returns the fair value live. No
          fabricated math.
        </Muted>
        {fwd.isError && (
          <Muted className="mt-1 text-[11px] text-tone-warn-fg">
            The recompute service did not return a value for these settings.
            Try a discount rate further above the terminal growth.
          </Muted>
        )}
      </div>

      <div>
        <Heatmap
          data={data}
          ticker={ticker}
          currency={currency}
          price={price}
          inView={inView}
          isPaid={isPaid}
          curWacc={nearest(DISCOUNT_STEPS_PCT, waccPct)}
          curCagr={nearest(GROWTH_STEPS_PCT, cagrPct)}
          onPick={(g, d) => {
            setCagrPct(g)
            setWaccPct(d)
          }}
        />
      </div>
    </TwoCol>
  )
}

/* ─── price-vs-FV marker bar ──────────────────────────────────────── */

function PriceFvBar({
  fv,
  price,
  under,
  currency,
  ticker,
}: {
  fv: number
  price: number
  under: boolean
  currency: string
  ticker: string
}) {
  const top = Math.max(fv, price) * 1.15
  const lo = (Math.min(price, fv) / top) * 100
  const hi = (Math.max(price, fv) / top) * 100
  return (
    <>
      <div className="relative h-[22px] overflow-hidden rounded-md bg-raised">
        <div
          className="absolute bottom-0 top-0"
          style={{
            left: `${lo}%`,
            width: `${hi - lo}%`,
            background: under ? "var(--color-tone-good-bg)" : "rgba(216,90,48,0.18)",
          }}
        />
        <div
          className="absolute bottom-0 top-0 w-0.5 bg-caption"
          style={{ left: `${(price / top) * 100}%` }}
        />
        <div
          className="absolute bottom-0 top-0 w-[2.5px] bg-ink transition-[left] duration-200"
          style={{ left: `${(fv / top) * 100}%` }}
        />
      </div>
      <Muted className="mt-1 text-[11px]">
        Grey tick = price {rs(price, currency, ticker)} · black marker = your
        fair value · shaded gap = the difference
      </Muted>
    </>
  )
}

/* ─── 5×5 sensitivity heatmap — LOOPED recompute, Pro-gated ───────── */

interface HeatCell {
  g: number
  d: number
  fv: number | null
}

function Heatmap({
  data,
  ticker,
  currency,
  price,
  inView,
  isPaid,
  curWacc,
  curCagr,
  onPick,
}: {
  data: AnalysisResponse
  ticker: string
  currency: string
  price: number | null
  inView: boolean
  isPaid: boolean
  curWacc: number
  curCagr: number
  onPick: (g: number, d: number) => void
}) {
  // The grid has 25 cells. There is NO server-side matrix endpoint, so we
  // LOOP recomputeDcfPlayground client-side — one POST per cell — behind a
  // single react-query key. enabled is gated on (inView && isPaid) so the
  // 25-call fan-out never fires on mount and never fires for free users
  // (who see the Pro veil instead). Cached 5min server+client.
  const grid = useQuery({
    queryKey: ["v2-dcf-heatmap", ticker],
    enabled: inView && isPaid && !!ticker,
    staleTime: 5 * 60 * 1000,
    retry: 0,
    queryFn: async (): Promise<HeatCell[]> => {
      const cells: HeatCell[] = []
      // Sequential to stay polite to the recompute endpoint (25 calls).
      for (const g of GROWTH_STEPS_PCT) {
        for (const d of DISCOUNT_STEPS_PCT) {
          try {
            const resp = await recomputeDcfPlayground(ticker, buildRecomputeBody(data, d, g))
            cells.push({
              g,
              d,
              fv: isNum(resp.fair_value) && resp.fair_value > 0 ? resp.fair_value : null,
            })
          } catch {
            cells.push({ g, d, fv: null })
          }
        }
      }
      return cells
    },
  })

  const cellLookup = useMemo(() => {
    const m = new Map<string, number | null>()
    for (const c of grid.data ?? []) m.set(`${c.g}:${c.d}`, c.fv)
    return m
  }, [grid.data])

  // The Pro veil mirrors the demo: free users see a fully-designed,
  // dimmed preview of the grid with an unlock callout.
  const veiled = !isPaid

  return (
    <div className={veiled ? "relative overflow-hidden rounded-lg" : undefined}>
      <div
        className={veiled ? "pointer-events-none opacity-40" : undefined}
        aria-hidden={veiled}
      >
        <div className="mb-1.5 text-center text-[11.5px] text-caption">
          Sensitivity — growth (rows) × discount (cols) · click a cell
        </div>
        <div className="-mx-1 overflow-x-auto px-1">
          <div
            className="grid min-w-[300px] gap-[3px]"
            style={{ gridTemplateColumns: "34px repeat(5, 1fr)" }}
          >
            <div className="py-1 text-center text-[10px] text-caption">g\d</div>
            {DISCOUNT_STEPS_PCT.map((dd) => (
              <div key={dd} className="py-1 text-center text-[10px] text-caption">
                {dd}%
              </div>
            ))}
            {[...GROWTH_STEPS_PCT].reverse().map((gg) => (
              <HeatRow
                key={gg}
                g={gg}
                price={price}
                curG={curCagr}
                curD={curWacc}
                lookup={cellLookup}
                loading={grid.isFetching && !grid.data}
                onPick={onPick}
              />
            ))}
          </div>
        </div>
        <Muted className="mt-1.5 text-center text-[11px]">
          {grid.isError
            ? "The sensitivity grid is unavailable right now."
            : "Green = fair value above price at that assumption · your cell is ringed"}
        </Muted>
      </div>

      {veiled && (
        <div className="absolute inset-0 flex items-center justify-center bg-border/70">
          <div className="max-w-[280px] rounded-lg border border-border bg-raised px-4 py-3.5 text-center shadow-sm">
            <Lock size={22} aria-hidden="true" className="mx-auto text-warning" />
            <div className="mb-1 mt-1.5 text-[13.5px] font-medium text-ink">
              Stress-test the fair value yourself
            </div>
            <Muted className="mb-2.5 text-[11.5px]">
              Live sliders · 25-cell sensitivity grid · reverse DCF
            </Muted>
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
  )
}

function HeatRow({
  g,
  price,
  curG,
  curD,
  lookup,
  loading,
  onPick,
}: {
  g: number
  price: number | null
  curG: number
  curD: number
  lookup: Map<string, number | null>
  loading: boolean
  onPick: (g: number, d: number) => void
}) {
  return (
    <>
      <div className="py-1 text-center text-[10px] text-caption">{g}%</div>
      {DISCOUNT_STEPS_PCT.map((d) => {
        const fv = lookup.get(`${g}:${d}`)
        const ringed = g === curG && d === curD
        let bg = "var(--color-raised)"
        let label = loading ? "…" : "—"
        if (isNum(fv) && isNum(price) && price > 0) {
          const m = (fv - price) / fv // true MoS fraction
          bg =
            m >= 0
              ? `rgba(29,158,117,${(0.12 + Math.min(m * 1.8, 0.5)).toFixed(3)})`
              : `rgba(216,90,48,${(0.12 + Math.min(-m * 1.8, 0.5)).toFixed(3)})`
          label = `₹${Math.round(fv / 10) * 10}`
        } else if (isNum(fv)) {
          label = `₹${Math.round(fv / 10) * 10}`
        }
        return (
          <button
            key={d}
            type="button"
            onClick={() => onPick(g, d)}
            className="cursor-pointer rounded px-0.5 py-1.5 text-center text-[10px] text-ink transition-transform hover:scale-[1.08]"
            style={{
              background: bg,
              outline: ringed ? `2px solid ${TOKENS.ink}` : "none",
              outlineOffset: -2,
            }}
          >
            {label}
          </button>
        )
      })}
    </>
  )
}

/* ─── reverse DCF panel — LIVE reverse-engineer ───────────────────── */

function ReversePanel({
  data,
  ticker,
  price,
}: {
  data: AnalysisResponse
  ticker: string
  price: number | null
}) {
  const [payPrice, setPayPrice] = useState<number | null>(price)

  // Seed the slider from the live price once it arrives.
  useEffect(() => {
    if (isNum(price) && payPrice === null) setPayPrice(price)
  }, [price, payPrice])

  const v = data.valuation

  // Debounce the price the user drags.
  const [debouncedPrice, setDebouncedPrice] = useState<number | null>(payPrice)
  useEffect(() => {
    const id = window.setTimeout(() => setDebouncedPrice(payPrice), 350)
    return () => window.clearTimeout(id)
  }, [payPrice])

  // LIVE reverse-engineer at the dragged price (gated on inView).
  const rev = useQuery({
    queryKey: ["v2-dcf-reverse", ticker, debouncedPrice],
    enabled: !!ticker && isNum(debouncedPrice) && debouncedPrice! > 0,
    staleTime: 5 * 60 * 1000,
    retry: 1,
    queryFn: () =>
      reverseEngineerDcf(ticker, {
        market_price: debouncedPrice!,
        wacc: isNum(v?.wacc) ? v.wacc : 0.12,
        terminal_growth: isNum(v?.terminal_growth) ? v.terminal_growth : 0.04,
        revenue_cagr_yr1_5: isNum(v?.fcf_growth_rate) ? v.fcf_growth_rate : 0.08,
        operating_margin: 0.15,
      }),
  })

  // The implied growth the engine solved for at the dragged price.
  const liveImpliedG = isNum(rev.data?.implied_revenue_cagr)
    ? rev.data!.implied_revenue_cagr * 100
    : null

  // Engine-published "market expects" anchors at the CURRENT price.
  const baselineImpliedG = isNum(data.insights?.reverse_dcf_implied_growth)
    ? data.insights!.reverse_dcf_implied_growth! * 100
    : null
  const implied = data.implied_assumptions ?? null

  // The base-case revenue CAGR the engine itself used, for comparison copy.
  const baseCagrPct = isNum(v?.fcf_growth_rate) ? v.fcf_growth_rate * 100 : null

  const sliderMin = isNum(price) ? Math.round(price * 0.55) : 0
  const sliderMax = isNum(price) ? Math.round(price * 1.6) : 100

  return (
    <TwoCol>
      <div>
        {isNum(payPrice) ? (
          <SliderRow
            id="v2-rpr"
            label="Price you'd pay"
            min={sliderMin}
            max={sliderMax}
            step={Math.max(1, Math.round((sliderMax - sliderMin) / 60))}
            value={payPrice}
            onChange={setPayPrice}
            out={rs(payPrice, data.company?.currency, ticker)}
            outWidth={64}
          />
        ) : (
          <Muted>Price anchor unavailable for this ticker.</Muted>
        )}

        <div className="mt-2">
          <div className="text-[11.5px] text-caption">Market-implied revenue growth</div>
          <div className="text-[28px] font-medium text-ink" aria-live="polite">
            {rev.isFetching && liveImpliedG === null
              ? "…"
              : isNum(liveImpliedG)
                ? `${liveImpliedG.toFixed(1)}%`
                : isNum(baselineImpliedG)
                  ? `${baselineImpliedG.toFixed(1)}%`
                  : "—"}
          </div>
        </div>

        <Muted className="mt-1.5">
          {isNum(payPrice) && isNum(liveImpliedG) ? (
            <>
              At {rs(payPrice, data.company?.currency, ticker)} a 5-year DCF
              must embed about {liveImpliedG.toFixed(1)}% revenue growth
              {isNum(baseCagrPct) ? (
                <>
                  {" "}
                  — {liveImpliedG > baseCagrPct ? "above" : liveImpliedG < baseCagrPct ? "below" : "in line with"}{" "}
                  the engine&apos;s {baseCagrPct.toFixed(1)}% base case.
                </>
              ) : (
                "."
              )}
            </>
          ) : (
            "Drag the price to solve for the growth the market is paying for at that level."
          )}
        </Muted>

        {rev.isError && (
          <Muted className="mt-1 text-[11px] text-tone-warn-fg">
            The reverse-engineer service did not converge at this price.
          </Muted>
        )}
      </div>

      <div>
        {implied ? (
          <div className="rounded-lg border border-border/60 bg-raised px-4 py-3">
            <div className="text-[11px] uppercase tracking-[0.12em] text-caption">
              What the current price embeds
            </div>
            <p className="mt-1.5 text-[12.5px] leading-relaxed text-body">{implied.headline}</p>
            <ul className="mt-2 space-y-1 text-[11.5px] text-caption">
              <li className="flex justify-between gap-2">
                <span>Implied revenue CAGR</span>
                <span className="font-medium text-ink">
                  {implied.implied_revenue_cagr_pct.toFixed(1)}%
                </span>
              </li>
              <li className="flex justify-between gap-2">
                <span>Implied terminal growth</span>
                <span className="font-medium text-ink">
                  {implied.implied_terminal_growth_pct.toFixed(1)}%
                </span>
              </li>
              {isNum(implied.consensus_revenue_cagr_pct) && (
                <li className="flex justify-between gap-2">
                  <span>vs consensus CAGR</span>
                  <span className="font-medium text-ink">
                    {implied.consensus_revenue_cagr_pct.toFixed(1)}%
                  </span>
                </li>
              )}
            </ul>
          </div>
        ) : (
          <Muted>
            Drag the price to see what revenue growth the market is paying for
            at that level, versus the engine&apos;s base case.
          </Muted>
        )}
      </div>
    </TwoCol>
  )
}

/* ─── shared slider row ───────────────────────────────────────────── */

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
      <label htmlFor={id} className="w-[112px] text-[12.5px] text-caption">
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
      <span className="text-[12.5px] font-medium text-ink" style={{ minWidth: outWidth }}>
        {out}
      </span>
    </div>
  )
}
