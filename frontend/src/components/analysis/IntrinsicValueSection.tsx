"use client"

/**
 * IntrinsicValueSection — "1. INTRINSIC VALUE", the first numbered
 * section of the analysis page (feat/alphaspread-style-opening).
 *
 * AlphaSpread-style composition:
 *   - Big centered numbered heading. REUSES the shared
 *     <NumberedSectionHeader> (per the agent-partition hard rule it is
 *     NOT modified) — the centering + brand-blue numeral are applied by
 *     a wrapper with arbitrary-variant utilities only.
 *   - Two-column body (≥ xl): LEFT = SEBI-templated narrative sentence
 *     with the key numbers in bold ink, then "Based on N methods:" chip
 *     rows (DCF / Peer Multiples / sector-specific estimator), then an
 *     italic one-line reconciliation note. RIGHT = <IntrinsicValueCard>
 *     (huge IV figure + Discount/Premium badge + IV-vs-price bars).
 *   - Below xl the columns stack with the card FIRST (mobile spec).
 *
 * Narrative templates are the EXACT SEBI-cleared strings from the
 * design spec (descriptive verbs only: reads / trades / sits — never
 * imperative). pct = |IV − price| / price × 100; the near-parity branch
 * fires below 5%. "base case" mirrors scenarios.base wording.
 *
 * Canonical-FV contract: `intrinsicValue` is the headline FV
 * (signals.headlineFairValue). The DCF-specific figure arrives via the
 * `dcfValue` prop strictly for the DCF method row — the caller owns the
 * lint annotation for that read.
 *
 * data_limited: template [D] renders, methods rows + reconciliation are
 * suppressed, and the card hides its badge/bars (no fabricated zeros).
 *
 * degraded (WIPRO-clamp class): the caller passes `degradedContent`
 * (DegradedScenarioCard et al.) which replaces the two-column body —
 * the numbered heading stays so the section numbering never gaps.
 */

import * as React from "react"
import { Calculator, Landmark, Scale, type LucideIcon } from "lucide-react"

import IntrinsicValueCard, {
  intrinsicValueGapPct,
} from "@/components/analysis/IntrinsicValueCard"
import NumberedSectionHeader from "@/components/analysis/NumberedSectionHeader"
import { cn, formatCurrency } from "@/lib/utils"

/** |gap| below this % reads as parity (template C). */
const PARITY_BAND_PCT = 5

export interface IntrinsicValueSectionProps {
  /** Canonical ticker (suffix ok) — INR override for formatCurrency. */
  ticker: string
  /** Bare display ticker for prose + the card caption. */
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
        <div className="grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(260px,320px)] xl:gap-8 xl:items-start">
          {/* Card first when stacked (mobile spec); right column at xl. */}
          <div className="order-1 xl:order-2">
            <IntrinsicValueCard
              ticker={ticker}
              displayTicker={displayTicker}
              currency={currency}
              intrinsicValue={limited ? null : intrinsicValue}
              currentPrice={currentPrice}
              dataLimited={limited}
            />
          </div>

          <div className="order-2 xl:order-1 min-w-0">
            <Narrative
              companyName={companyName}
              displayTicker={displayTicker}
              intrinsicValue={limited ? null : intrinsicValue}
              currentPrice={currentPrice}
              fmt={fmt}
            />

            {methodRows.length > 0 && (
              <div className="mt-4" data-testid="iv-methods">
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
            )}

            {!limited && (
              <ReconciliationNote
                dcfValue={usable(dcfValue) ? dcfValue : null}
                multiplesValue={usable(multiplesValue) ? multiplesValue : null}
                currentPrice={currentPrice}
              />
            )}
          </div>
        </div>
      )}
    </section>
  )
}

/* ------------------------------------------------------------------ */
/*  Narrative sentence — exact SEBI-cleared templates                  */
/* ------------------------------------------------------------------ */

interface NarrativeProps {
  companyName: string
  displayTicker: string
  intrinsicValue: number | null
  currentPrice: number | null
  fmt: (v: number) => string
}

function Em({ children }: { children: React.ReactNode }) {
  return <span className="font-semibold text-ink">{children}</span>
}

function Narrative({
  companyName,
  displayTicker,
  intrinsicValue,
  currentPrice,
  fmt,
}: NarrativeProps) {
  const baseClass = "text-[13px] md:text-sm leading-relaxed text-body"

  // Template [D] — data-limited / unpublished IV.
  if (
    intrinsicValue == null ||
    currentPrice == null ||
    !(currentPrice > 0) ||
    !(intrinsicValue > 0)
  ) {
    return (
      <p data-testid="iv-narrative" data-template="data-limited" className={baseClass}>
        An intrinsic value for <Em>{companyName}</Em> ({displayTicker}) is not
        published yet — the model does not have enough reliable data to
        produce a base-case figure. Check back after the next data refresh.
      </p>
    )
  }

  const gap = intrinsicValueGapPct(intrinsicValue, currentPrice) ?? 0
  const pct = Math.abs(gap).toFixed(1)
  const lead = (
    <>
      The intrinsic value of <Em>{companyName}</Em> ({displayTicker}) under
      the base case is <Em>{fmt(intrinsicValue)}</Em>.
    </>
  )

  // Template [C] — near parity (|gap| < 5%).
  if (Math.abs(gap) < PARITY_BAND_PCT) {
    return (
      <p data-testid="iv-narrative" data-template="parity" className={baseClass}>
        {lead} The current market price of <Em>{fmt(currentPrice)}</Em> sits
        within <Em>{pct}%</Em> of that figure — close to parity under this
        model.
      </p>
    )
  }

  // Templates [A] / [B] — trades below / above the model's IV.
  const direction = currentPrice < intrinsicValue ? "below" : "above"
  return (
    <p
      data-testid="iv-narrative"
      data-template={direction === "below" ? "trades-below" : "trades-above"}
      className={baseClass}
    >
      {lead} Compared with the current market price of{" "}
      <Em>{fmt(currentPrice)}</Em>, the stock trades <Em>{pct}%</Em>{" "}
      {direction} the model&rsquo;s intrinsic value.
    </p>
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
