"use client"

/**
 * EditorialHero — Morningstar-grade 3-column hero for /analysis/[ticker].
 *
 *   ┌─────────────────────┬──────────────────────┬─────────────┐
 *   │ Verdict narrative   │   THE PRISM          │  ScoreCard  │
 *   │ (4/12)              │   (5/12)             │  (3/12)     │
 *   └─────────────────────┴──────────────────────┴─────────────┘
 *
 * Receives ALL data as props — no client-side fetches here. Parent page
 * does one server-side fetch of /api/v1/prism/<ticker> so the entire
 * above-the-fold content renders SSR (protects LCP).
 *
 * The Prism component itself (owned by Agent Phi2) is imported lazily
 * with a skeleton fallback so this file keeps building even while that
 * component is in flight.
 */

import dynamic from "next/dynamic"
import { useState } from "react"

import Prism from "@/components/prism/Prism"
import ScoreCard from "@/components/analysis/ScoreCard"
import { verdictColor } from "@/lib/prism"
import type {
  PillarKey,
  PrismData,
  PrismMode,
  VerdictBand,
} from "@/components/prism/types"
import { formatCurrency, formatPct } from "@/lib/utils"

// Lazy-load so visitors who never click "Tell me the story" don't pay
// the narrator's bundle cost.
const PrismNarrator = dynamic(
  () => import("@/components/prism/PrismNarrator"),
  { ssr: false },
)

export interface EditorialHeroProps {
  /** Prism payload — contains verdict, pillars, refraction. */
  data: PrismData
  /** Fair value in company currency. */
  fairValue: number
  /** Current price in company currency. */
  currentPrice: number
  /** Margin of safety (0-100, signed). */
  marginOfSafety: number
  /** Moat tier — "Wide" | "Narrow" | "None". */
  moat: string
  currency: string
  /** Legacy YieldIQ score 0-100. */
  score100: number
  grade: string
  /** Optional sector-rank pair for the ScoreCard bar. */
  sectorRank?: { rank: number; total: number } | null
  /** Monthly score trend, oldest first. */
  trend12m?: number[]
  /** Market cap in crores (INR). */
  marketCapCr?: number | null
  /** True when DCF inputs aren't reliable — shows a Data Limited banner instead of verdict. */
  dataLimited?: boolean
}

function bandCaption(band: VerdictBand): string {
  switch (band) {
    case "deepValue":
      return "Deep Value Region"
    case "undervalued":
      return "Undervalued Region"
    case "fair":
      return "Fair Value Region"
    case "overvalued":
      return "Overvalued Region"
    case "expensive":
      return "Expensive Region"
    default:
      return "Fair Value Region"
  }
}

function titleCase(s: string): string {
  return s.replace(/\w\S*/g, (t) => t.charAt(0).toUpperCase() + t.substr(1).toLowerCase())
}

/** The three cells share style; small helper keeps JSX flat. */
function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-[10px] uppercase tracking-[0.15em] text-caption">{label}</dt>
      <dd className="font-mono tabular-nums text-lg font-semibold text-ink">{value}</dd>
    </div>
  )
}

export default function EditorialHero({
  data,
  fairValue,
  currentPrice,
  marginOfSafety,
  moat,
  currency,
  score100,
  grade,
  sectorRank,
  trend12m,
  marketCapCr,
  dataLimited,
}: EditorialHeroProps) {
  const defaultMode: PrismMode = "spectrum"
  const color = verdictColor(data.verdict_band)
  const [highlightedPillar, setHighlightedPillar] =
    useState<PillarKey | null>(null)

  return (
    <section
      className="bg-bg rounded-2xl border border-border p-5 md:p-6"
      aria-label="Valuation summary"
    >
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 lg:gap-8">
        {/* ══════════════════════════════════════════════════════════
            Column 1 — Verdict narrative (mobile: 3rd)
            ══════════════════════════════════════════════════════════ */}
        <div className="lg:col-span-4 order-3 lg:order-1 flex flex-col gap-3">
          <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-caption">
            YieldIQ Prism · Verdict
          </p>

          <div className="flex items-center gap-2">
            <span
              aria-hidden
              className="inline-block w-2.5 h-2.5 rounded-full"
              style={{ background: color }}
            />
            <span className="text-[11px] uppercase tracking-[0.15em] text-body">
              {bandCaption(data.verdict_band)}
            </span>
          </div>

          {/* Serif headline — the verdict as an editorial title. We do NOT
              fabricate longer prose here (SEBI). The verdict label from the
              Prism payload is the canonical display string. */}
          <h2
            className="font-editorial text-3xl leading-tight text-ink font-semibold"
            style={{ fontVariationSettings: "'opsz' 48" }}
          >
            {titleCase(data.verdict_label)}
          </h2>

          {/* 2x2 metrics */}
          <dl className="grid grid-cols-2 gap-x-6 gap-y-3 mt-1">
            <Stat
              label="Fair Value"
              value={fairValue > 0 ? formatCurrency(fairValue, currency) : "—"}
            />
            <Stat
              label="Current Price"
              value={currentPrice > 0 ? formatCurrency(currentPrice, currency) : "—"}
            />
            {!dataLimited && (
              <div>
                <dt className="text-[10px] uppercase tracking-[0.15em] text-caption">
                  Margin of Safety
                </dt>
                <dd
                  className={`font-mono tabular-nums text-lg font-semibold ${
                    marginOfSafety >= 0 ? "text-success" : "text-danger"
                  }`}
                >
                  {marginOfSafety > 80 ? "+80%+" : formatPct(marginOfSafety)}
                </dd>
              </div>
            )}
            <Stat label="Moat" value={moat || "—"} />
          </dl>

          <p className="text-[11px] text-caption leading-relaxed mt-2">
            {data.disclaimer}
          </p>
        </div>

        {/* ══════════════════════════════════════════════════════════
            Column 2 — The Prism (mobile: 2nd)
            ══════════════════════════════════════════════════════════ */}
        <div className="lg:col-span-5 order-2 lg:order-2 flex flex-col items-center">
          <div className="relative">
            <Prism
              data={data}
              size={340}
              defaultMode={defaultMode}
              highlightedPillar={highlightedPillar}
            />
          </div>
          <p className="mt-3 text-[11px] text-caption leading-snug text-center max-w-[30ch]">
            Every stock has a Signature. Unfold it into a Spectrum to see how it
            refracts.
          </p>
          <div className="mt-4 w-full max-w-[34ch]">
            <PrismNarrator
              data={data}
              onHighlight={setHighlightedPillar}
            />
          </div>
        </div>

        {/* ══════════════════════════════════════════════════════════
            Column 3 — ScoreCard (mobile: 1st — most valuable at a glance)
            ══════════════════════════════════════════════════════════ */}
        <div className="lg:col-span-3 order-1 lg:order-3">
          <ScoreCard
            score100={score100}
            grade={grade}
            trend12m={trend12m}
            sectorRank={sectorRank ?? null}
            refractionIndex={data.refraction_index}
            marketCapCr={marketCapCr ?? null}
          />
        </div>
      </div>
    </section>
  )
}
