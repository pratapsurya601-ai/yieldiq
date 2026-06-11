"use client"

/**
 * IntrinsicValueSection — "1. INTRINSIC VALUE", the first numbered
 * section of the analysis page (feat/intrinsic-value-thesis-redesign).
 *
 * Composition (top to bottom):
 *   - Big centered numbered heading. REUSES the shared
 *     <NumberedSectionHeader> (per the agent-partition hard rule it is
 *     NOT modified) — the centering + brand-blue numeral are applied by
 *     a wrapper with arbitrary-variant utilities only.
 *   - <IntrinsicHero> — the 5-second answer: huge gap numeral
 *     ("53.7% below intrinsic value") + the SEBI-templated narrative
 *     sentence with the exact rupee figures in bold ink.
 *   - <ValuationRangeStrip> — single bear→bull gradient band with the
 *     base-case IV marker inside it and the market-price marker (which
 *     may sit outside the band). Self-hides without scenario bounds.
 *   - <ScenarioCards> — Bear / Base / Bull per-share values, signed %
 *     vs price, and assumption detail on hover/focus. Self-hides
 *     without scenarios.
 *   - "Based on N methods" rows (DCF / Peer Multiples / sector
 *     estimator) + the italic one-line reconciliation note — unchanged
 *     from the previous revision — alongside <ConfidenceGauge> (arc +
 *     pillar mini-bars, links to the #section-confidence disclosure).
 *   - <ValuationDrivers> — sector-aware "What drives this reading"
 *     strip (banks read bank-native fields). Self-hides under 2 cards.
 *
 * RETIRED in this revision: <IntrinsicValueCard> (the right-rail huge
 * IV figure + Discount/Premium badge + two-bar IV-vs-price chart).
 * Behavior-wise, the headline treatment moved into <IntrinsicHero>
 * (which now owns `intrinsicValueGapPct`) and the IV-vs-price
 * comparison moved into <ValuationRangeStrip>. No other mount of the
 * card existed (verified by import grep at retire time).
 *
 * Scenario-duplication contract: the per-scenario VALUES render here
 * (ScenarioCards); the standalone "VALUATION SCENARIOS" numbered
 * section further down the page keeps ONLY the 5-year projection fan
 * (<FVProjectionFan>) — its duplicate bear/base/bull TrustStrip is
 * retired in AnalysisBody.tsx as part of this change.
 *
 * Canonical-FV contract: `intrinsicValue` is the headline FV
 * (signals.headlineFairValue). The DCF-specific figure arrives via the
 * `dcfValue` prop strictly for the DCF method row — the caller owns the
 * lint annotation for that read.
 *
 * data_limited: template [D] renders inside IntrinsicHero; the strip,
 * scenario cards, methods rows, reconciliation, gauge, and drivers are
 * all suppressed (no fabricated zeros).
 *
 * degraded (WIPRO-clamp class): the caller passes `degradedContent`
 * (DegradedScenarioCard et al.) which replaces the body — the numbered
 * heading stays so the section numbering never gaps.
 */

import * as React from "react"
import { Calculator, Landmark, Scale, type LucideIcon } from "lucide-react"

import IntrinsicHero from "@/components/analysis/intrinsic/IntrinsicHero"
import ValuationRangeStrip from "@/components/analysis/intrinsic/ValuationRangeStrip"
import ScenarioCards from "@/components/analysis/intrinsic/ScenarioCards"
import ConfidenceGauge, {
  type ConfidenceGaugePillars,
} from "@/components/analysis/intrinsic/ConfidenceGauge"
import ValuationDrivers from "@/components/analysis/intrinsic/ValuationDrivers"
import NumberedSectionHeader from "@/components/analysis/NumberedSectionHeader"
import { cn, formatCurrency } from "@/lib/utils"
import type {
  AnalysisResponse,
  QualityOutput,
  ScenariosOutput,
} from "@/types/api"

export interface IntrinsicValueSectionProps {
  /** Canonical ticker (suffix ok) — INR override for formatCurrency. */
  ticker: string
  /** Bare display ticker for prose + aria labels. */
  displayTicker: string
  companyName: string
  currency: string
  /** Canonical headline FV (composite-or-DCF). Null on data-limited. */
  intrinsicValue: number | null
  currentPrice: number | null
  /** DCF-only estimate for the DCF method row. Null hides the row. */
  dcfValue?: number | null
  /** Peer-multiples estimate (payload.multiples_based_fv). */
  multiplesValue?: number | null
  multiplesMethod?: "pe" | "pb" | "ev_ebitda" | null
  /** Sector-routed estimator (payload.sector_specific_fv / _label). */
  sectorSpecificValue?: number | null
  sectorSpecificLabel?: string | null
  /** Bear/base/bull cases — feeds the range strip + scenario cards. */
  scenarios?: ScenariosOutput | null
  /** Overall model confidence 0-100 (valuation.confidence_score). */
  confidence?: number | null
  /** Per-pillar confidence scores for the gauge mini-bars. */
  confidencePillars?: ConfidenceGaugePillars | null
  /** Quality block — feeds the sector-aware drivers strip. */
  quality?: QualityOutput | null
  sectorMedians?: AnalysisResponse["sector_medians"]
  /** insights.fcf_yield (percent) for the non-bank cash driver card. */
  fcfYield?: number | null
  dataLimited?: boolean
  /** WIPRO-clamp class state — body is replaced by `degradedContent`. */
  degraded?: boolean
  degradedContent?: React.ReactNode
  /** Centered slot under the heading — e.g. the gated verdict pill. */
  headingExtra?: React.ReactNode
  className?: string
}

const MULTIPLES_METHOD_LABEL: Record<string, string> = {
  pe: "Peer Multiples (P/E)",
  pb: "Peer Multiples (P/B)",
  ev_ebitda: "Peer Multiples (EV/EBITDA)",
}

interface MethodRow {
  key: "dcf" | "multiples" | "sector"
  label: string
  value: number
  icon: LucideIcon
}

const finite = (v: number | null | undefined): v is number =>
  v != null && Number.isFinite(v)

export default function IntrinsicValueSection({
  ticker,
  displayTicker,
  companyName,
  currency,
  intrinsicValue,
  currentPrice,
  dcfValue,
  multiplesValue,
  multiplesMethod,
  sectorSpecificValue,
  sectorSpecificLabel,
  scenarios,
  confidence,
  confidencePillars,
  quality,
  sectorMedians,
  fcfYield,
  dataLimited = false,
  degraded = false,
  degradedContent,
  headingExtra,
  className,
}: IntrinsicValueSectionProps) {
  const limited =
    dataLimited || intrinsicValue == null || !(intrinsicValue > 0)

  const fmt = (v: number) => formatCurrency(v, currency, ticker)

  const usable = (v: number | null | undefined): v is number =>
    v != null && Number.isFinite(v) && v > 0

  const methodRows: MethodRow[] = []
  if (!limited) {
    if (usable(dcfValue)) {
      methodRows.push({ key: "dcf", label: "DCF", value: dcfValue, icon: Calculator })
    }
    if (usable(multiplesValue)) {
      methodRows.push({
        key: "multiples",
        label:
          (multiplesMethod && MULTIPLES_METHOD_LABEL[multiplesMethod]) ??
          "Peer Multiples",
        value: multiplesValue,
        icon: Scale,
      })
    }
    if (usable(sectorSpecificValue)) {
      methodRows.push({
        key: "sector",
        label: sectorSpecificLabel || "Sector Model",
        value: sectorSpecificValue,
        icon: Landmark,
      })
    }
  }

  // ConfidenceGauge self-hides on all-null input, but we also need to
  // know up-front whether the methods/gauge row earns its grid at all.
  const gaugeHasData =
    !limited &&
    (finite(confidence) ||
      finite(confidencePillars?.model_confidence) ||
      finite(confidencePillars?.data_quality) ||
      finite(confidencePillars?.valuation_stability))

  return (
    <section
      data-testid="intrinsic-value-section"
      aria-label={`${displayTicker} intrinsic value`}
      className={className}
    >
      {/* Centered AlphaSpread-style heading. The shared header renders
          left-aligned with a muted numeral; this wrapper centers it and
          paints the "1." brand-blue via arbitrary variants WITHOUT
          modifying the shared component (partition hard rule 5). */}
      <div className="text-center [&_p]:mx-auto [&_h2>span]:text-brand [&_h2>span]:opacity-100">
        <NumberedSectionHeader
          number={1}
          title="INTRINSIC VALUE"
          caption="What the model estimates one share is worth under the base case, and how the current market price compares."
        />
      </div>

      {headingExtra && (
        <div className="-mt-2 mb-5 flex items-center justify-center gap-2 flex-wrap">
          {headingExtra}
        </div>
      )}

      {degraded ? (
        degradedContent ?? null
      ) : (
        <div className="min-w-0">
          {/* ── Headline gap numeral + SEBI-templated narrative ───── */}
          <IntrinsicHero
            ticker={ticker}
            displayTicker={displayTicker}
            companyName={companyName}
            currency={currency}
            intrinsicValue={limited ? null : intrinsicValue}
            currentPrice={currentPrice}
            confidence={limited ? null : confidence}
            dataLimited={limited}
          />

          {/* ── Bear→bull range strip (self-hides without bounds) ─── */}
          {!limited && (
            <ValuationRangeStrip
              ticker={ticker}
              currency={currency}
              bear={scenarios?.bear?.iv ?? null}
              bull={scenarios?.bull?.iv ?? null}
              intrinsicValue={intrinsicValue}
              currentPrice={currentPrice}
              className="mt-8"
            />
          )}

          {/* ── Bear / Base / Bull scenario value cards ───────────── */}
          {!limited && (
            <ScenarioCards
              ticker={ticker}
              currency={currency}
              scenarios={scenarios}
              currentPrice={currentPrice}
              className="mt-8"
            />
          )}

          {/* ── Methods rows + reconciliation | confidence gauge ──── */}
          {(methodRows.length > 0 || gaugeHasData) && (
            <div
              className={cn(
                "mt-8 grid grid-cols-1 gap-5 md:items-start",
                methodRows.length > 0 && gaugeHasData
                  ? "md:grid-cols-[minmax(0,1fr)_minmax(280px,360px)] md:gap-8"
                  : "md:grid-cols-1",
              )}
            >
              {methodRows.length > 0 && (
                <div className="min-w-0">
                  <div data-testid="iv-methods">
                    <p className="text-[11px] uppercase tracking-[0.12em] text-caption">
                      Based on {methodRows.length}{" "}
                      {methodRows.length === 1 ? "method" : "methods"}:
                    </p>
                    <ul className="mt-2 flex flex-col gap-1.5">
                      {methodRows.map((row) => (
                        <li
                          key={row.key}
                          data-testid={`iv-method-${row.key}`}
                          className="flex items-center justify-between gap-3 rounded-lg border border-border bg-bg px-3 py-2"
                        >
                          <span className="flex items-center gap-2 min-w-0">
                            <row.icon
                              aria-hidden
                              className="h-3.5 w-3.5 shrink-0 text-caption"
                            />
                            <span className="text-[12px] text-body truncate">
                              {row.label}
                            </span>
                          </span>
                          <span className="font-mono tabular-nums text-[13px] font-semibold text-ink shrink-0">
                            {fmt(row.value)}
                          </span>
                        </li>
                      ))}
                    </ul>
                  </div>

                  {!limited && (
                    <ReconciliationNote
                      dcfValue={usable(dcfValue) ? dcfValue : null}
                      multiplesValue={usable(multiplesValue) ? multiplesValue : null}
                      currentPrice={currentPrice}
                    />
                  )}
                </div>
              )}

              {gaugeHasData && (
                <ConfidenceGauge
                  confidence={confidence}
                  pillars={confidencePillars}
                />
              )}
            </div>
          )}

          {/* ── Sector-aware drivers strip (self-hides under 2) ───── */}
          {!limited && (
            <ValuationDrivers
              quality={quality}
              sectorMedians={sectorMedians}
              fcfYield={fcfYield}
              className="mt-8"
            />
          )}
        </div>
      )}
    </section>
  )
}

/* ------------------------------------------------------------------ */
/*  Reconciliation note — DCF vs peer multiples, descriptive only      */
/* ------------------------------------------------------------------ */

interface ReconciliationNoteProps {
  dcfValue: number | null
  multiplesValue: number | null
  currentPrice: number | null
}

function ReconciliationNote({
  dcfValue,
  multiplesValue,
  currentPrice,
}: ReconciliationNoteProps) {
  if (dcfValue == null || currentPrice == null || !(currentPrice > 0)) {
    return null
  }

  let note: string
  if (multiplesValue == null) {
    note =
      "Only the DCF estimate is available for this ticker; the peer-multiples comparison is not applicable."
  } else {
    const dcfBelow = dcfValue < currentPrice
    const multBelow = multiplesValue < currentPrice
    if (dcfBelow && !multBelow) {
      note =
        "The DCF reads below the current price, while peer multiples read above it."
    } else if (!dcfBelow && multBelow) {
      note =
        "The DCF reads above the current price, while peer multiples read below it."
    } else if (dcfBelow && multBelow) {
      note =
        "Both the DCF and the peer-multiples estimate read below the current price."
    } else {
      note =
        "Both the DCF and the peer-multiples estimate read above the current price."
    }
  }

  return (
    <p
      data-testid="iv-reconciliation"
      className={cn("mt-3 text-[12px] italic leading-snug text-caption")}
    >
      {note}
    </p>
  )
}
