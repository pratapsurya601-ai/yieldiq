"use client"

// v2 · §2 Thesis — the argument. A balance beam that tilts toward the
// stronger side, impact-weighted-LESS bull/bear point lists (the real
// bulls_say / bears_say payload carries no per-point impact, so we do
// NOT fabricate impact bars), and the "Where we're honest" card off the
// Honest Card payload.
//
// PORTED from app/demo/analysis-redesign/SectionThesis.tsx. The mock
// BULL_POINTS / BEAR_POINTS / hard-coded 58-42 split / honesty copy are
// all replaced by REAL fields:
//   - bull/bear points  ← data.bulls_say / data.bears_say
//                          (fallback: bull_case_narrative / bear_case_narrative)
//   - bear-point detail ← insights.red_flags_structured[] (matched by order)
//   - balance beam      ← a SOFT tilt derived from the verdict / MoS sign.
//     There is NO real bull-vs-bear weight in the payload, so we DROP the
//     exact "58% / 42%" numbers and show only a direction + qualitative
//     label. The beam never claims a precision the data doesn't have.
//   - honesty card      ← data.honest_card (confident_facts /
//                          uncertainty_factors / invalidating_conditions)
//   - date stamp        ← data.thesis_updated
//
// Verdict gating: the beam tilt + the "net read" direction word are
// verdict-derived, so they are suppressed (beam sits level, neutral copy)
// when VERDICT_LAYER_ON is OFF or the resolver gated the verdict.
import { useState } from "react"
import { CircleCheck, CircleDashed, TriangleAlert } from "lucide-react"

import type { AnalysisResponse, RedFlag } from "@/types/api"
import type { HeroSignals } from "@/lib/useHeroSignals"

import { backOut, seg, useStageClock } from "@/app/demo/analysis-redesign/hooks"
import { TOKENS } from "@/app/demo/analysis-redesign/theme"
import { Muted, Ribbon, Section, TwoCol } from "@/app/demo/analysis-redesign/ui"

/** One thesis point — a real bullet string plus optional expandable detail. */
interface Point {
  headline: string
  detail: string | null
}

/** Turn the array bullets (or a narrative paragraph fallback) into points. */
function pointsFrom(
  bullets: string[] | null | undefined,
  narrative: string | null | undefined,
): Point[] {
  const arr = (bullets ?? []).filter((s) => typeof s === "string" && s.trim().length > 0)
  if (arr.length > 0) return arr.map((h) => ({ headline: h.trim(), detail: null }))
  // Fallback: a single narrative paragraph becomes one point.
  if (typeof narrative === "string" && narrative.trim().length > 0) {
    return [{ headline: narrative.trim(), detail: null }]
  }
  return []
}

export default function SectionThesisV2({
  data,
  signals,
  verdictLayerOn,
}: {
  data: AnalysisResponse
  signals: HeroSignals
  /** VERDICT_LAYER_ON — false levels the beam + neutralises the net-read. */
  verdictLayerOn: boolean
}) {
  const { ref, elapsed } = useStageClock(1600, 0.2)

  const showVerdict = verdictLayerOn && !signals.verdictGated && !signals.dataLimited

  // ── Bull / bear points (REAL) ──────────────────────────────────────
  const bullPoints = pointsFrom(data.bulls_say, data.bull_case_narrative)
  const bearPoints = pointsFrom(data.bears_say, data.bear_case_narrative)

  // Attach structured red-flag detail to bear points, matched by order
  // (the bear bullets and the red flags are both severity-ordered). Only
  // attaches real `why_it_matters` copy; never invents a detail string.
  const redFlags: RedFlag[] = data.insights?.red_flags_structured ?? []
  const bearWithDetail: Point[] = bearPoints.map((p, i) => {
    const rf = redFlags[i]
    const detail = rf?.why_it_matters || rf?.explanation || null
    return { headline: p.headline, detail: detail && detail.trim() ? detail.trim() : null }
  })

  const hasThesis = bullPoints.length > 0 || bearWithDetail.length > 0

  // ── Soft balance-beam tilt (NO real bull/bear weight in payload) ────
  // Direction comes from the verdict tier; magnitude is a fixed, modest
  // lean — we deliberately DROP any precise percentage. trueMos (signed
  // cushion below fair value) drives the SIGN only.
  const mos = signals.trueMos
  const leanDir =
    showVerdict && mos != null && Number.isFinite(mos)
      ? mos > 4
        ? 1 // bull side heavier (undervalued)
        : mos < -4
          ? -1 // bear side heavier (overvalued)
          : 0 // balanced
      : 0
  // Beam angle: ±5° lean, eased in. Zero when gated → sits level.
  const TILT = 5
  const angle = -leanDir * TILT * seg(elapsed, 0, 1500, backOut)

  // Net-read copy — qualitative, SEBI-neutral, assembled per direction.
  const netRead =
    !showVerdict || leanDir === 0
      ? "Net read — weigh both sides; the gap is the swing factor"
      : leanDir > 0
        ? "Net read — leans constructive; the bear points are the swing factor"
        : "Net read — leans cautious; the bull points are the swing factor"

  // Ribbon tone — qualitative balance of the two lists, no number.
  const ribbonLabel =
    bullPoints.length > 0 && bearWithDetail.length > 0
      ? "Two-sided"
      : bullPoints.length > 0
        ? "Constructive"
        : bearWithDetail.length > 0
          ? "Cautious"
          : "Limited"

  const honest = data.honest_card ?? null
  const dateStamp = data.thesis_updated || null

  return (
    <Section
      id="sec-thesis"
      num="2"
      title="Thesis — the argument"
      innerRef={ref}
      ribbon={
        <Ribbon tone="warn" icon={<CircleDashed size={13} aria-hidden="true" />}>
          {ribbonLabel}
        </Ribbon>
      }
    >
      {dateStamp && <Muted className="-mt-1.5 mb-2 text-[11.5px]">Updated {dateStamp}</Muted>}

      {/* Balance beam — direction only, no fabricated split. */}
      <div className="text-center">
        <svg
          viewBox="0 0 560 132"
          width="100%"
          style={{ maxWidth: 560 }}
          className="mx-auto block"
          role="img"
          aria-label={
            leanDir > 0
              ? "Balance beam leaning toward the bull side."
              : leanDir < 0
                ? "Balance beam leaning toward the bear side."
                : "Balance beam sitting level between bull and bear."
          }
        >
          <g transform={`rotate(${angle.toFixed(2)} 280 62)`}>
            <line
              x1={130}
              y1={62}
              x2={430}
              y2={62}
              stroke={TOKENS.caption}
              strokeWidth={3}
              strokeLinecap="round"
            />
            <g>
              <rect x={108} y={26} width={86} height={30} rx={7} fill="var(--color-tone-good-bg)" />
              <text
                x={151}
                y={45}
                textAnchor="middle"
                fontSize={12.5}
                fontWeight={500}
                fill="var(--color-tone-good-fg)"
              >
                Bull case
              </text>
              <line x1={151} y1={56} x2={151} y2={62} stroke={TOKENS.caption} strokeWidth={2} />
            </g>
            <g>
              <rect x={366} y={26} width={86} height={30} rx={7} fill="var(--color-tone-warn-bg)" />
              <text
                x={409}
                y={45}
                textAnchor="middle"
                fontSize={12.5}
                fontWeight={500}
                fill="var(--color-tone-warn-fg)"
              >
                Bear case
              </text>
              <line x1={409} y1={56} x2={409} y2={62} stroke={TOKENS.caption} strokeWidth={2} />
            </g>
          </g>
          <polygon points="266,96 294,96 280,64" fill={TOKENS.caption} />
          <line x1={180} y1={96} x2={380} y2={96} stroke={TOKENS.border} strokeWidth={1.5} />
          <text x={280} y={122} textAnchor="middle" fontSize={12} fill={TOKENS.caption}>
            {netRead}
          </text>
        </svg>
      </div>

      {hasThesis ? (
        <>
          <Muted className="mb-1 mt-2.5 text-[11.5px]">
            Tap a bear point for why it matters
          </Muted>

          <TwoCol align="stretch">
            <div className="rounded-lg bg-raised px-3.5 pb-3 pt-2.5">
              <div className="mb-1.5 text-[13px] font-medium text-success">Bull case</div>
              {bullPoints.length > 0 ? (
                <PointList points={bullPoints} kind="bull" />
              ) : (
                <Muted>No bull points surfaced for this company yet.</Muted>
              )}
            </div>
            <div className="rounded-lg bg-raised px-3.5 pb-3 pt-2.5">
              <div className="mb-1.5 text-[13px] font-medium text-warning">Bear case</div>
              {bearWithDetail.length > 0 ? (
                <PointList points={bearWithDetail} kind="bear" />
              ) : (
                <Muted>No bear points surfaced for this company yet.</Muted>
              )}
            </div>
          </TwoCol>
        </>
      ) : (
        <Muted className="mt-3">
          The structured bull and bear case is still being assembled for this company.
        </Muted>
      )}

      {/* Where we're honest — the Honest Card payload. */}
      {honest &&
      (honest.confident_facts?.length ||
        honest.uncertainty_factors?.length ||
        honest.invalidating_conditions?.length) ? (
        <div className="mt-3 rounded-lg border border-dashed border-border px-3.5 py-3 text-[12.5px] leading-relaxed">
          <div className="mb-1.5 font-medium text-ink">Where we&apos;re honest</div>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            {honest.confident_facts?.length > 0 && (
              <HonestColumn
                label="Most confident"
                tone="good"
                items={honest.confident_facts}
              />
            )}
            {honest.uncertainty_factors?.length > 0 && (
              <HonestColumn
                label="Least confident"
                tone="warn"
                items={honest.uncertainty_factors}
              />
            )}
            {honest.invalidating_conditions?.length > 0 && (
              <HonestColumn
                label="What would change the read"
                tone="info"
                items={honest.invalidating_conditions}
              />
            )}
          </div>
        </div>
      ) : null}
    </Section>
  )
}

function HonestColumn({
  label,
  tone,
  items,
}: {
  label: string
  tone: "good" | "warn" | "info"
  items: string[]
}) {
  const dot =
    tone === "good"
      ? "bg-success"
      : tone === "warn"
        ? "bg-warning"
        : "bg-tone-info-fg"
  return (
    <div>
      <div className="mb-1 text-[11.5px] font-medium uppercase tracking-wide text-caption">
        {label}
      </div>
      <ul className="space-y-1">
        {items.map((it, i) => (
          <li key={i} className="flex items-start gap-1.5 text-[12px] leading-relaxed text-ink">
            <span className={`mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ${dot}`} aria-hidden="true" />
            <span>{it}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

function PointList({ points, kind }: { points: Point[]; kind: "bull" | "bear" }) {
  const [open, setOpen] = useState<number | null>(null)
  const color = kind === "bull" ? TOKENS.success : TOKENS.warning
  const Icon = kind === "bull" ? CircleCheck : TriangleAlert

  return (
    <div>
      {points.map((p, i) => {
        const expandable = !!p.detail
        return (
          <button
            key={`${p.headline}-${i}`}
            type="button"
            aria-expanded={expandable ? open === i : undefined}
            disabled={!expandable}
            onClick={() => expandable && setOpen(open === i ? null : i)}
            className={`-mx-1.5 block w-[calc(100%+12px)] rounded-md px-1.5 py-1 text-left transition-colors ${
              expandable ? "cursor-pointer hover:bg-surface" : "cursor-default"
            }`}
          >
            <span className="flex items-start gap-2 text-[12.5px] leading-snug text-ink">
              <Icon size={16} aria-hidden="true" className="mt-px shrink-0" style={{ color }} />
              <span className="flex-1">{p.headline}</span>
            </span>
            {expandable && (
              <span
                className="block overflow-hidden pl-6 text-[11.5px] leading-relaxed text-caption transition-[max-height] duration-300"
                style={{ maxHeight: open === i ? 80 : 0 }}
              >
                {p.detail}
              </span>
            )}
          </button>
        )
      })}
    </div>
  )
}
