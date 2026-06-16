"use client"

/**
 * SectionRiskV2 (#sec-risk) — "Risk — what could break the thesis", on
 * REAL data.
 *
 * PORTED from app/demo/analysis-redesign/SectionRisk.tsx, but the demo's
 * 2-D likelihood × impact matrix is DELIBERATELY NOT reproduced: the
 * payload has no likelihood coordinate for a red flag, only a severity.
 * Fabricating an x-position would be inventing data. Instead the flags
 * render as a 1-D SEVERITY-RANKED strip (critical → warning → info),
 * dot size by severity — honest to exactly what the backend provides.
 *
 * Data — both fields ship on the base `getAnalysis` payload already
 * loaded by AnalysisBodyV2 (there is no separate risk endpoint), so this
 * section consumes `data` directly rather than firing its own query.
 * IntersectionObserver gating is still present, but only to defer the
 * reveal animations until scrolled into view — the dot pop-in via
 * `useStageClock` and the worry-score `CountUp` both fire on first view,
 * never on mount. No network fan-out happens here.
 *   - worry index ← data.worry_index { score, tier, headline,
 *                                      contributors[]{label, score, detail} }
 *   - risk dots   ← data.insights.red_flags_structured[]
 *                       { severity, title, why_it_matters }
 *     severity → impact axis (critical highest).
 *
 * SEBI: the worry-index `headline`, each contributor `label`/`detail`,
 * and each flag's `title`/`why_it_matters` are backend-sourced strings
 * (already SEBI-vetted server-side) rendered dynamically. Every static
 * label here is descriptive ("Risk map", "Worry index", "impact").
 */

import { useMemo, useState } from "react"
import { CircleDashed } from "lucide-react"

import type { AnalysisResponse, RedFlag } from "@/types/api"
import { CountUp } from "@/components/anim"

import { DEMO_COLORS, TOKENS } from "@/app/demo/analysis-redesign/theme"
import { backOut, seg, useStageClock } from "@/app/demo/analysis-redesign/hooks"
import { Muted, Ribbon, Section, Subh, TwoCol } from "@/app/demo/analysis-redesign/ui"

/** Worry-index tier → ribbon tone + descriptive (non-advisory) label. */
function tierRibbon(
  tier: string | undefined,
): { tone: "good" | "warn" | "info"; label: string } {
  switch (tier) {
    case "sleep_well":
      return { tone: "good", label: "Calm" }
    case "normal":
      return { tone: "info", label: "Normal" }
    case "watch_closely":
      return { tone: "warn", label: "Watch closely" }
    case "read_bears":
      return { tone: "warn", label: "Read the bears" }
    case "significant_concerns":
      return { tone: "warn", label: "Elevated" }
    default:
      return { tone: "info", label: "—" }
  }
}

/** Severity → impact rank (3 = highest), dot radius, and colour. */
function severityMeta(sev: RedFlag["severity"]): { rank: number; r: number; color: string; word: string } {
  switch (sev) {
    case "critical":
      return { rank: 3, r: 9, color: DEMO_COLORS.coral, word: "High impact" }
    case "warning":
      return { rank: 2, r: 7, color: DEMO_COLORS.amber, word: "Medium impact" }
    default:
      return { rank: 1, r: 6, color: DEMO_COLORS.gray, word: "Low impact" }
  }
}

export default function SectionRiskV2({ data }: { data: AnalysisResponse }) {
  const worry = data.worry_index ?? null
  const flags = data.insights?.red_flags_structured ?? []
  const ribbon = tierRibbon(worry?.tier)

  return (
    <Section
      id="sec-risk"
      num="06"
      title="Risk — what could break the thesis"
      ribbon={
        worry ? (
          <Ribbon tone={ribbon.tone} icon={<CircleDashed size={13} aria-hidden="true" />}>
            {ribbon.label}
          </Ribbon>
        ) : undefined
      }
    >
      <TwoCol align="start">
        {/* Left — severity-ranked risk strip (1-D; NO fabricated likelihood) */}
        <div>
          <Subh>Risk map — ranked by impact</Subh>
          {flags.length > 0 ? (
            <RiskStrip flags={flags} />
          ) : (
            <Muted className="py-2">No structured red flags surfaced for this company.</Muted>
          )}
        </div>

        {/* Right — worry index + contributor legend */}
        <div>
          {worry ? (
            <WorryPanel worry={worry} ribbonLabel={ribbon.label} />
          ) : (
            <Muted>The worry index is still being computed for this company.</Muted>
          )}
        </div>
      </TwoCol>
    </Section>
  )
}

/* ================================================================== */
/*  1-D severity-ranked risk strip                                    */
/* ================================================================== */

const SX0 = 50
const SX1 = 320
const SY = 150 // baseline for the dots
const STOP = 20

function RiskStrip({ flags }: { flags: RedFlag[] }) {
  const { ref, elapsed } = useStageClock<HTMLDivElement>(1400, 0.2)
  const [active, setActive] = useState<number | null>(null)

  // Sort highest-impact first; stable within a severity band.
  const ranked = useMemo(() => {
    return flags
      .map((f, i) => ({ f, i, meta: severityMeta(f.severity) }))
      .sort((a, b) => b.meta.rank - a.meta.rank)
  }, [flags])

  const n = ranked.length
  // Even horizontal spread; vertical position by impact rank (higher
  // impact sits higher) — a single honest axis, not a 2-D grid.
  const xOf = (idx: number) => (n === 1 ? (SX0 + SX1) / 2 : SX0 + (idx / (n - 1)) * (SX1 - SX0))
  const yOf = (rank: number) => SY - ((rank - 1) / 2) * (SY - STOP - 20)

  return (
    <div ref={ref}>
      <svg
        viewBox="0 0 350 200"
        width="100%"
        style={{ maxWidth: 380 }}
        className="block"
        role="img"
        aria-label="Red flags ranked by impact; higher-impact items sit higher."
      >
        {/* impact axis only — no likelihood axis is drawn (none exists) */}
        <line x1={SX0} y1={SY} x2={SX1} y2={SY} stroke={TOKENS.border} />
        <line x1={SX0} y1={STOP} x2={SX0} y2={SY} stroke={TOKENS.border} />
        <text
          x={34}
          y={(STOP + SY) / 2}
          textAnchor="middle"
          fontSize={10}
          fill={TOKENS.caption}
          transform={`rotate(-90 34 ${(STOP + SY) / 2})`}
        >
          impact →
        </text>
        {/* tinted high-impact zone */}
        <rect x={SX0} y={STOP} width={SX1 - SX0} height={(SY - STOP) / 3} fill="rgba(216,90,48,0.07)" />
        <text x={SX1} y={STOP + 12} textAnchor="end" fontSize={9.5} fill={DEMO_COLORS.coralDark}>
          higher impact
        </text>

        {ranked.map((item, idx) => {
          const x = xOf(idx)
          const y = yOf(item.meta.rank)
          const r = item.meta.r * seg(elapsed, 200 + idx * 130, 450, backOut)
          const isActive = active === item.i
          const short = shortLabel(item.f.title)
          return (
            <g
              key={item.f.flag || item.f.title}
              style={{ cursor: "pointer" }}
              role="button"
              tabIndex={0}
              aria-label={`${item.f.title}, ${item.meta.word}`}
              onClick={() => setActive(isActive ? null : item.i)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault()
                  setActive(isActive ? null : item.i)
                }
              }}
            >
              <circle
                cx={x}
                cy={y}
                r={Math.max(0, r).toFixed(1)}
                fill={item.meta.color}
                opacity={0.85}
                stroke={isActive ? TOKENS.ink : "none"}
                strokeWidth={isActive ? 2.5 : 0}
              >
                <title>{`${item.f.title} — ${item.meta.word}`}</title>
              </circle>
              <text x={x} y={y - item.meta.r - 4} textAnchor="middle" fontSize={9.5} fill={TOKENS.caption}>
                {short}
              </text>
            </g>
          )
        })}
      </svg>

      {/* Tap-to-expand detail — backend why_it_matters string (dynamic). */}
      {active !== null && flags[active] && (
        <div
          className="mt-2 rounded-lg border-l-[3px] bg-raised px-3 py-2 text-[12px] leading-relaxed text-ink"
          style={{ borderLeftColor: severityMeta(flags[active].severity).color }}
        >
          <span className="font-medium">{flags[active].title}</span>
          {flags[active].why_it_matters && (
            <span className="text-caption"> — {flags[active].why_it_matters}</span>
          )}
        </div>
      )}
    </div>
  )
}

/* ================================================================== */
/*  Worry index + contributor legend                                  */
/* ================================================================== */

type WorryIndex = NonNullable<AnalysisResponse["worry_index"]>

function WorryPanel({ worry, ribbonLabel }: { worry: WorryIndex; ribbonLabel: string }) {
  // Tone the number by tier severity.
  const numColor =
    worry.tier === "significant_concerns" || worry.tier === "read_bears" || worry.tier === "watch_closely"
      ? "text-warning"
      : worry.tier === "sleep_well"
        ? "text-success"
        : "text-ink"

  // Top contributors, highest (weight × score) first.
  const contributors = useMemo(() => {
    return [...(worry.contributors ?? [])]
      .filter((c) => c.label)
      .sort((a, b) => b.weight * b.score - a.weight * a.score)
      .slice(0, 5)
  }, [worry.contributors])

  // Dot colour by the contributor's own 0-100 score.
  const dotColor = (score: number): string => {
    if (score >= 66) return DEMO_COLORS.coral
    if (score >= 33) return DEMO_COLORS.amber
    return DEMO_COLORS.teal
  }

  return (
    <div>
      <div className="mb-1 flex items-baseline gap-2">
        {/* CountUp handles in-view trigger + reduced-motion snap + SSR. */}
        <CountUp to={Math.round(worry.score)} className={`num text-[24px] font-medium ${numColor}`} />
        <Muted>worry index · {ribbonLabel.toLowerCase()}</Muted>
      </div>
      {worry.headline && <Muted className="mb-2 text-body">{worry.headline}</Muted>}
      {contributors.length > 0 && (
        <div className="text-[12.5px] leading-[1.9] text-caption">
          {contributors.map((c) => (
            <div key={c.component || c.label}>
              <span
                className="mr-1.5 inline-block h-2 w-2 rounded-full align-middle"
                style={{ background: dotColor(c.score) }}
                aria-hidden="true"
              />
              {c.label}
              {c.detail ? <span className="text-caption/80"> — {c.detail}</span> : null}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

/** Trim a flag title for the SVG dot label. */
function shortLabel(title: string): string {
  const t = title.trim()
  return t.length > 16 ? t.slice(0, 15) + "…" : t
}
