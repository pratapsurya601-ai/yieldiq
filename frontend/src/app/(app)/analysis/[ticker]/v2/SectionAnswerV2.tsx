"use client"

// v2 · §1 The Answer detail (id="sec-answer-detail") — the deeper
// companion to the DecisionBoxV2 spine (id="sec-answer"). A semicircle
// valuation gauge (needle swings to the
// REAL discount with a back-ease overshoot, the landed arc pulses) +
// vertical price ladder (bear / price / fair value / bull off raw
// valuation fields) + a tap-to-open 5-pillar confidence dot-matrix.
//
// PORTED from app/demo/analysis-redesign/SectionAnswer.tsx. The mock
// NEEDLE_TARGET / hard-coded ladder rungs / CONFIDENCE_PILLARS imports
// are replaced by REAL signals + valuation fields. Nothing is fabricated:
// a rung that has no real number is dropped, a pillar with a null score
// renders an empty (dimmed) dot row, and the whole verdict layer (needle
// position, "X% undervalued" caption, gauge landing) is gated behind
// VERDICT_LAYER_ON exactly like DecisionBoxV2 — OFF collapses to the
// SEBI-neutral under-review state with the verdict numbers suppressed
// from the DOM (never hidden-but-present).
import { useState } from "react"
import { CircleCheck, CircleDashed } from "lucide-react"

import type { AnalysisResponse } from "@/types/api"
import type { HeroSignals } from "@/lib/useHeroSignals"
import { formatCurrency } from "@/lib/utils"
import { useReducedMotion } from "@/components/anim"

import { backOut, seg, useStageClock } from "@/app/demo/analysis-redesign/hooks"
import { DEMO_COLORS, TOKENS } from "@/app/demo/analysis-redesign/theme"
import { Muted, Section, Subh, TwoCol } from "@/app/demo/analysis-redesign/ui"

/* ------------------------------------------------------------------ */
/*  Confidence pillars — five 0-100 backend scores rendered as 1-5     */
/*  dot rows. Each maps a real field; null → a dimmed (empty) row so   */
/*  the matrix stays honest about which engine had no signal.          */
/* ------------------------------------------------------------------ */

interface PillarRow {
  name: string
  /** 0-100 backend score, or null when the field is absent / non-finite. */
  pct: number | null
  /** Filled-dot count 0-5, derived from `pct`. */
  score: number
  why: string
}

/** 0-100 → 0-5 filled dots (ceil so a real positive score lights ≥1 dot). */
function dots5(pct: number | null): number {
  if (pct == null || !Number.isFinite(pct)) return 0
  const clamped = Math.max(0, Math.min(100, pct))
  return Math.max(0, Math.min(5, Math.round(clamped / 20)))
}

function pillarRow(name: string, pct: number | null | undefined, why: string): PillarRow {
  const v = typeof pct === "number" && Number.isFinite(pct) ? pct : null
  return { name, pct: v, score: dots5(v), why }
}

/** Round a 0-100 score for the inline caption, or em-dash when absent. */
function pctLabel(pct: number | null): string {
  return pct == null ? "—" : `${Math.round(pct)}%`
}

export default function SectionAnswerV2({
  data,
  signals,
  verdictLayerOn,
}: {
  data: AnalysisResponse
  signals: HeroSignals
  /** VERDICT_LAYER_ON — false suppresses needle position + verdict caption. */
  verdictLayerOn: boolean
}) {
  const { ref, elapsed, reduced } = useStageClock(2000, 0.2)
  const [cfOpen, setCfOpen] = useState(false)

  const valuation = data.valuation
  const price = valuation.current_price
  const headlineFv = signals.headlineFairValue
  const discount = signals.discount // signed upside % (price→FV)

  // Verdict layer is "on" only when the flag is set AND the resolver did
  // not gate the verdict (low confidence / wide band / data limited).
  const showVerdict = verdictLayerOn && !signals.verdictGated && !signals.dataLimited
  const showGauge = showVerdict && discount != null && Number.isFinite(discount)

  // ── Five confidence pillars (REAL 0-100 fields) ────────────────────
  const cc = data.composite_composition ?? null
  const pillars: PillarRow[] = [
    pillarRow(
      "Data quality",
      valuation.data_quality_score,
      "Completeness and freshness of the filed inputs.",
    ),
    pillarRow(
      "Model fit",
      valuation.model_confidence_score,
      "How well the engine suits this kind of business.",
    ),
    pillarRow(
      "Valuation stability",
      valuation.valuation_stability_score,
      "How little the fair value has moved recently.",
    ),
    pillarRow(
      "Sensitivity",
      valuation.confidence_sensitivity,
      "Share of perturbed runs that keep the same read.",
    ),
    pillarRow(
      "Estimator agreement",
      valuation.confidence_composite_agreement,
      "How tightly the estimators cluster together.",
    ),
  ]
  // Composite 0-100 of the available pillars — drives the "why?" chip
  // tone. Average of the real (non-null) pillar scores; null when none.
  const realPillars = pillars.filter((p) => p.pct != null)
  const confComposite =
    realPillars.length > 0
      ? realPillars.reduce((s, p) => s + (p.pct as number), 0) / realPillars.length
      : null
  const confTone: "good" | "info" =
    confComposite != null && confComposite >= 60 ? "good" : "info"
  const confChipLabel =
    confComposite == null
      ? "Confidence pending"
      : confComposite >= 70
        ? "High confidence"
        : confComposite >= 50
          ? "Moderate confidence"
          : "Limited confidence"

  // ── Estimator-agreement caption (REAL consensus tally) ─────────────
  // Prefer cross_engine_consensus (directional vote tally); fall back to
  // composite_composition (estimators available / total). Drop entirely
  // when neither is present rather than fabricate a fraction.
  const consensus = data.cross_engine_consensus ?? null
  const agreeCount =
    typeof consensus?.direction_agreement_count === "number"
      ? consensus.direction_agreement_count
      : typeof cc?.estimators_available === "number"
        ? cc.estimators_available
        : null
  const agreeTotal =
    typeof consensus?.total_estimators === "number"
      ? consensus.total_estimators
      : typeof cc?.estimators_total === "number"
        ? cc.estimators_total
        : null
  const showAgreement =
    agreeCount != null && agreeTotal != null && agreeTotal > 0 && agreeCount >= 0

  // ── Gauge geometry (needle position from the REAL discount) ────────
  // Map the signed upside % onto the arc: 0% upside → centre (50, "Fair"),
  // +50% → far undervalued end, −50% → far overvalued end. Clamped so the
  // needle never leaves the dial.
  const needleTarget = showGauge
    ? Math.max(2, Math.min(98, 50 + (discount as number)))
    : 50
  const needleV = needleTarget * seg(elapsed, 0, 1300, backOut)
  const a = Math.PI - (needleV / 100) * Math.PI
  const nx = 85 + 60 * Math.cos(a)
  const ny = 85 - 60 * Math.sin(a)

  // Green (undervalued) arc pulse on landing; mirrors the demo timing.
  let arcW = 12
  if (elapsed > 1300 && elapsed <= 1470) arcW = 12 + 4 * ((elapsed - 1300) / 170)
  else if (elapsed > 1470 && elapsed <= 1870) arcW = 16 - 4 * ((elapsed - 1470) / 400)
  const landed = elapsed > 1300

  // ── Price ladder (REAL rungs) ──────────────────────────────────────
  // Build only the rungs that have a real, finite, positive number. The
  // "Now" (price) rung is always shown when price > 0; the FV rung is
  // gated by the verdict layer (FV is a verdict-derived number).
  type Rung = { key: string; label: string; v: number; kind: "fv" | "bull" | "bear" }
  const rungs: Rung[] = []
  if (showVerdict && headlineFv != null && headlineFv > 0) {
    rungs.push({ key: "fv", label: "Fair", v: headlineFv, kind: "fv" })
  }
  if (valuation.bull_case > 0 && Number.isFinite(valuation.bull_case)) {
    rungs.push({ key: "bull", label: "Bull", v: valuation.bull_case, kind: "bull" })
  }
  if (valuation.bear_case > 0 && Number.isFinite(valuation.bear_case)) {
    rungs.push({ key: "bear", label: "Bear", v: valuation.bear_case, kind: "bear" })
  }
  const hasPrice = price > 0 && Number.isFinite(price)

  // Vertical scale across every visible value (rungs + price). The SVG
  // rail spans y∈[18, 220]; map the value range onto that band, padded.
  const ladderVals = [...rungs.map((r) => r.v), ...(hasPrice ? [price] : [])]
  const vMin = ladderVals.length ? Math.min(...ladderVals) : 0
  const vMax = ladderVals.length ? Math.max(...ladderVals) : 1
  const span = vMax - vMin || 1
  const RAIL_TOP = 30
  const RAIL_BOT = 208
  const yFor = (v: number): number =>
    RAIL_BOT - ((v - vMin) / span) * (RAIL_BOT - RAIL_TOP)

  const fmt = (v: number): string =>
    formatCurrency(v, data.company.currency, data.company.ticker)

  // "Now" marker climbs into place on the same stage clock.
  const priceY = hasPrice ? yFor(price) : RAIL_BOT
  const climb = reduced ? 1 : seg(elapsed, 0, 1300)
  const priceYAnim = RAIL_BOT - (RAIL_BOT - priceY) * climb

  // Margin-of-safety caption under the ladder — only when the true MoS is
  // a real number AND the verdict layer is on.
  const showMosCaption =
    showVerdict && signals.trueMos != null && Number.isFinite(signals.trueMos)

  return (
    <Section
      id="sec-answer-detail"
      num="1"
      title="The answer — where price sits"
      innerRef={ref}
      highlight
      ribbon={
        <button
          type="button"
          onClick={() => setCfOpen((v) => !v)}
          aria-expanded={cfOpen}
          className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-[3px] text-[11px] ${
            confTone === "good"
              ? "bg-tone-good-bg text-tone-good-fg"
              : "bg-tone-info-bg text-tone-info-fg"
          }`}
        >
          {confTone === "good" ? (
            <CircleCheck size={13} aria-hidden="true" />
          ) : (
            <CircleDashed size={13} aria-hidden="true" />
          )}
          {confChipLabel} · why?
        </button>
      }
    >
      {/* Confidence depth — 5-pillar dot-matrix (one engine per chip). */}
      <div
        className="overflow-hidden transition-[max-height] duration-300 ease-out"
        style={{ maxHeight: cfOpen ? 340 : 0 }}
      >
        <div className="pb-1.5 pt-0.5">
          {pillars.map((p, pi) => (
            <div key={p.name} className="flex items-center gap-2.5 py-[5px] text-[12.5px]">
              <span className="w-[150px] shrink-0 text-caption">{p.name}</span>
              <span className="flex shrink-0 gap-[3px]">
                {Array.from({ length: 5 }, (_, di) => (
                  <ConfidenceDot key={di} on={di < p.score} open={cfOpen} order={pi * 5 + di} />
                ))}
              </span>
              <span className="num hidden w-[42px] shrink-0 text-[11.5px] text-caption sm:block">
                {pctLabel(p.pct)}
              </span>
              <span className="hidden text-[11.5px] text-caption md:block">{p.why}</span>
            </div>
          ))}
        </div>
        <Muted className="border-t border-border/70 pb-3 pt-2 text-[11.5px]">
          Five pillars, each a 0–100 engine score shown here as five dots. A dimmed
          row means that engine had no signal for this company — never a guess.
        </Muted>
      </div>

      <TwoCol>
        {/* Valuation gauge */}
        <div className="text-center">
          <Subh>Valuation gauge</Subh>
          {showGauge ? (
            <>
              <svg
                viewBox="0 0 170 112"
                width="100%"
                style={{ maxWidth: 240 }}
                className="mx-auto block"
                role="img"
                aria-label={`Valuation gauge needle settling at ${Math.round(
                  discount as number,
                )} percent ${(discount as number) >= 0 ? "below" : "above"} fair value.`}
              >
                <path
                  d="M15,85 A70,70 0 0 1 63.4,18.4"
                  fill="none"
                  stroke={DEMO_COLORS.coral}
                  strokeWidth={12}
                  strokeLinecap="round"
                  opacity={0.8}
                />
                <path
                  d="M63.4,18.4 A70,70 0 0 1 106.6,18.4"
                  fill="none"
                  stroke={DEMO_COLORS.amber}
                  strokeWidth={12}
                />
                <path
                  d="M106.6,18.4 A70,70 0 0 1 155,85"
                  fill="none"
                  stroke={DEMO_COLORS.teal}
                  strokeWidth={arcW}
                  strokeLinecap="round"
                  style={{ transition: "stroke-width .1s" }}
                />
                <line
                  x1={85}
                  y1={85}
                  x2={nx.toFixed(1)}
                  y2={ny.toFixed(1)}
                  stroke={TOKENS.ink}
                  strokeWidth={2.5}
                  strokeLinecap="round"
                />
                <circle cx={85} cy={85} r={5} fill={TOKENS.ink} />
                <text
                  x={85}
                  y={106}
                  textAnchor="middle"
                  fontSize={12}
                  fontWeight={500}
                  fill={(discount as number) >= 0 ? DEMO_COLORS.tealDark : DEMO_COLORS.coralDark}
                  opacity={landed ? 1 : 0}
                  style={{ transition: "opacity .4s" }}
                  className="num"
                >
                  {Math.abs(Math.round(discount as number))}%{" "}
                  {(discount as number) >= 0 ? "below fair value" : "above fair value"}
                </text>
              </svg>
              <div className="mx-auto flex max-w-[240px] justify-between px-2 text-[11px] text-caption">
                <span>Above FV</span>
                <span>Fair</span>
                <span>Below FV</span>
              </div>
            </>
          ) : (
            <div className="flex min-h-[140px] flex-col items-center justify-center">
              <span className="num text-[34px] font-medium leading-none text-caption">—</span>
              <Muted className="mt-1.5">
                {signals.dataLimited
                  ? "Fair value pending more data."
                  : "Estimate under review."}
              </Muted>
            </div>
          )}
        </div>

        {/* Price ladder */}
        <div className="text-center">
          <Subh>Price ladder</Subh>
          {rungs.length > 0 || hasPrice ? (
            <svg
              viewBox="0 0 240 238"
              width="100%"
              style={{ maxWidth: 250 }}
              className="mx-auto block"
              role="img"
              aria-label="Vertical price ladder showing where the current price sits against the bear, fair value and bull rungs."
            >
              <line x1={70} y1={RAIL_TOP - 12} x2={70} y2={RAIL_BOT + 12} stroke={TOKENS.border} strokeWidth={2} />

              {/* Margin-of-safety shaded gap between price and fair value. */}
              {showVerdict && headlineFv != null && headlineFv > 0 && hasPrice && (
                <rect
                  x={64}
                  y={Math.min(yFor(headlineFv), priceY)}
                  width={12}
                  height={Math.max(0, Math.abs(yFor(headlineFv) - priceY))}
                  rx={3}
                  fill="rgba(29,158,117,0.22)"
                />
              )}

              {rungs.map((r) => {
                const y = yFor(r.v)
                const isFv = r.kind === "fv"
                const stroke =
                  r.kind === "fv"
                    ? DEMO_COLORS.teal
                    : r.kind === "bull"
                      ? DEMO_COLORS.tealFaint
                      : DEMO_COLORS.coralLight
                return (
                  <g key={r.key}>
                    <line
                      x1={58}
                      y1={y}
                      x2={82}
                      y2={y}
                      stroke={stroke}
                      strokeWidth={isFv ? 3.5 : 3}
                    />
                    <text
                      x={92}
                      y={y + 4}
                      fontSize={isFv ? 12 : 11.5}
                      fontWeight={isFv ? 500 : 400}
                      fill={isFv ? DEMO_COLORS.tealDark : TOKENS.caption}
                      className="num"
                    >
                      {r.label} {fmt(r.v)}
                    </text>
                  </g>
                )
              })}

              {hasPrice && (
                <g transform={`translate(0,${(priceYAnim - priceY).toFixed(1)})`}>
                  <circle cx={70} cy={priceY} r={6} fill={TOKENS.ink} />
                  <text
                    x={58}
                    y={priceY + 4}
                    fontSize={12}
                    fontWeight={500}
                    fill={TOKENS.ink}
                    textAnchor="end"
                    className="num"
                  >
                    Now {fmt(price)}
                  </text>
                </g>
              )}
            </svg>
          ) : (
            <div className="flex min-h-[140px] items-center justify-center">
              <Muted>Price ladder pending more data.</Muted>
            </div>
          )}
          {showMosCaption ? (
            <Muted className="num text-[11.5px]">
              The shaded gap is your {Math.round(signals.trueMos as number)}% margin of
              safety below fair value.
            </Muted>
          ) : (
            <Muted className="text-[11.5px]">
              {showVerdict
                ? "Bear, fair value and bull rungs frame the current price."
                : "Fair value rung returns when the estimate is available."}
            </Muted>
          )}
        </div>
      </TwoCol>

      {showAgreement && (
        <Muted className="mt-2 num">
          {agreeCount} of {agreeTotal} estimators point the same direction.{" "}
          <JumpLink target="sec-valuation">Method breakdown →</JumpLink>
        </Muted>
      )}
    </Section>
  )
}

function ConfidenceDot({ on, open, order }: { on: boolean; open: boolean; order: number }) {
  const reduced = useReducedMotion()
  const filled = on && open
  return (
    <span
      className="inline-block h-[11px] w-[11px] rounded-full border-[1.5px] transition-colors duration-300"
      style={{
        borderColor: DEMO_COLORS.teal,
        background: filled ? DEMO_COLORS.teal : "transparent",
        transitionDelay: filled && !reduced ? `${order * 45}ms` : "0ms",
      }}
      aria-hidden="true"
    />
  )
}

function JumpLink({ target, children }: { target: string; children: React.ReactNode }) {
  const reduced = useReducedMotion()
  return (
    <button
      type="button"
      className="cursor-pointer text-[12px] text-tone-info-fg hover:underline"
      onClick={() =>
        document
          .getElementById(target)
          ?.scrollIntoView({ behavior: reduced ? "auto" : "smooth", block: "start" })
      }
    >
      {children}
    </button>
  )
}
