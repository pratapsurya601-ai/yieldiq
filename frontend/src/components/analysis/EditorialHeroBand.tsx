"use client"

/**
 * EditorialHeroBand — Stage-2 redesign (spec §5 hybrid demotion of the
 * legacy 3-column EditorialHero).
 *
 * Purpose: preserve the Wikipedia-style brand-texture imagery (the Prism
 * + Signature/Spectrum toggle + caption + counter chips) WITHOUT
 * re-emitting any verdict / FV / discount / score data above the fold.
 *
 * The single source of truth for verdict / FV / discount / worry / score
 * is <HonestHero>. This band sits BELOW the hero and carries:
 *   - The Prism visual (Signature ↔ Spectrum toggle lives inside Prism)
 *   - The one-line "Every stock has a Signature..." brand caption
 *   - The Prism narrative caption (factual numeric description)
 *   - The risk / positive-signal counter chips
 *   - The MosAlertChip ("Notify me when discount reaches..." control)
 *   - PrismNarrator ("Tell me the story")
 *   - The tap-to-explain PillarExplainer sheet
 *
 * What is INTENTIONALLY dropped vs the old EditorialHero:
 *   - Verdict pill, FV stat, MoS/Discount stat, Buffett MoS chip
 *   - Score / Grade / Sector rank / Moat chips
 *   - "Under Review" guard headline (HonestHero owns this)
 *   - Value-trap caveat banner (HonestHero owns this)
 *   - Bull / Bear narrative blocks
 *   - The disclaimer paragraph (lives in ModelDisclaimer / freshness widget)
 *
 * Width gating (spec §5 hybrid):
 *   - ≥1280  : full band, Prism centered, full caption + chips
 *   - 1024–1279 : slim band, Prism only (caption + chips hidden)
 *   - <1024  : hidden (mobile keeps MobileScoreStrip + HonestHero only;
 *             the Prism imagery is not part of the mobile budget)
 */

import dynamic from "next/dynamic"
import { useMemo, useState } from "react"

import Prism from "@/components/prism/Prism"
import PillarExplainer from "@/components/prism/PillarExplainer"
import {
  axesFromPillars,
  generatePrismNarrative,
} from "@/lib/prismNarrative"
import type {
  PillarKey,
  PrismData,
  PrismMode,
} from "@/components/prism/types"
import { timeAgo } from "@/lib/dataFreshness"

// Lazy-load — same pattern as the old EditorialHero so the bundle
// budget on first paint is unchanged.
const MosAlertChip = dynamic(
  () => import("@/components/analysis/MosAlertChip"),
  { ssr: false },
)
const PrismNarrator = dynamic(
  () => import("@/components/prism/PrismNarrator"),
  { ssr: false },
)

export interface EditorialHeroBandProps {
  /** Prism payload — contains verdict, pillars, refraction. */
  data: PrismData
  /** Fair value in company currency. */
  fairValue: number
  /** Current price in company currency. */
  currentPrice: number
  /** Signed (FV-CP)/CP*100 — passed through to MosAlertChip only. */
  marginOfSafety: number
  currency: string
  /** Red flags array — drives the counter chips. */
  redFlags?: ReadonlyArray<{ flag?: string; severity?: string }> | null
  /** Suppress everything when the page is in a data-limited state. */
  dataLimited?: boolean
}

export default function EditorialHeroBand({
  data,
  fairValue,
  currentPrice: _currentPrice,
  marginOfSafety,
  currency,
  redFlags,
  dataLimited,
}: EditorialHeroBandProps) {
  const defaultMode: PrismMode = "spectrum"
  const [highlightedPillar, setHighlightedPillar] =
    useState<PillarKey | null>(null)
  const [explainerAxis, setExplainerAxis] = useState<PillarKey | null>(null)

  const narrative = useMemo(
    () => generatePrismNarrative(axesFromPillars(data.pillars)),
    [data.pillars],
  )

  const flags = redFlags ?? []
  const redFlagsCount = flags.filter(
    (f) => f && (f as { severity?: string }).severity !== "info",
  ).length
  const positivesCount = flags.filter(
    (f) => f && (f as { severity?: string }).severity === "info",
  ).length

  const refreshAgo = timeAgo(data.computed_at)

  return (
    <>
      <section
        // Spec §5 hybrid: hidden below 1024 (mobile drops the imagery
        // budget), slim band 1024-1279 (Prism only), full band >=1280.
        className="hidden lg:block bg-bg rounded-2xl border border-border p-4 md:p-6"
        aria-label="Prism visual"
        data-testid="editorial-hero-band"
      >
        <div className="flex flex-col items-center">
          <div className="relative w-full max-w-[340px] mx-auto">
            <Prism
              data={data}
              size={340}
              defaultMode={defaultMode}
              highlightedPillar={highlightedPillar}
              onPillarTap={setExplainerAxis}
            />
          </div>

          {/* Full-band only (>=1280). Slim band (1024-1279) hides the
              text + chip clutter — Prism speaks for itself. */}
          <div className="hidden xl:flex xl:flex-col xl:items-center xl:w-full">
            <p className="mt-3 text-[11px] text-caption leading-snug text-center max-w-[30ch]">
              Every stock has a Signature. Unfold it into a Spectrum to see how it
              refracts.
            </p>

            <p
              data-testid="prism-narrative-caption"
              className="mt-2 italic text-sm text-caption leading-snug text-center max-w-prose"
            >
              {narrative}
            </p>

            {(redFlagsCount > 0 || positivesCount > 0) && (
              <div
                data-testid="prism-counter-chips"
                className="mt-2 flex items-center justify-center gap-2"
                aria-label="Risk and positive-signal counts"
              >
                {redFlagsCount > 0 && (
                  <span
                    data-testid="prism-red-flag-chip"
                    className="inline-flex items-center gap-1 rounded-full border border-amber-300 bg-tone-warn-bg px-2 py-0.5 text-[11px] font-medium text-amber-900 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-200"
                    title={`${redFlagsCount} red flag${redFlagsCount === 1 ? "" : "s"}`}
                  >
                    <span aria-hidden>⚠</span>
                    {redFlagsCount}
                  </span>
                )}
                {positivesCount > 0 && (
                  <span
                    data-testid="prism-positive-chip"
                    className="inline-flex items-center gap-1 rounded-full border border-emerald-300 bg-tone-good-bg px-2 py-0.5 text-[11px] font-medium text-emerald-900 dark:border-emerald-900 dark:bg-emerald-950/30 dark:text-emerald-200"
                    title={`${positivesCount} positive signal${positivesCount === 1 ? "" : "s"}`}
                  >
                    <span aria-hidden>★</span>
                    {positivesCount}
                  </span>
                )}
              </div>
            )}

            {refreshAgo && (
              <p className="mt-1.5 text-[10px] text-caption leading-snug text-center">
                Last refresh: {refreshAgo} &middot; Sources: NSE &middot; BSE &middot; SEBI
              </p>
            )}

            <div className="mt-4 w-full max-w-[34ch]">
              <PrismNarrator
                data={data}
                onHighlight={setHighlightedPillar}
              />
            </div>

            {/* MosAlertChip — "Notify me when discount reaches..." control.
                Preserved per brief: this is the only place users can wire
                up a price-alert from the hero region. Hidden when data is
                limited (the discount itself isn't meaningful then) and
                when FV is non-positive. */}
            {!dataLimited &&
              fairValue > 0 &&
              Number.isFinite(marginOfSafety) && (
                <div className="mt-3">
                  <MosAlertChip
                    ticker={data.ticker}
                    fairValue={fairValue}
                    currency={currency}
                    currentMos={marginOfSafety}
                  />
                </div>
              )}
          </div>
        </div>
      </section>

      <PillarExplainer
        open={explainerAxis !== null}
        axis={explainerAxis}
        data={data}
        onClose={() => setExplainerAxis(null)}
      />
    </>
  )
}
