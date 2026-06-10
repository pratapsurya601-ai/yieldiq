"use client"

/**
 * CrossConfirmationChip — competitor-audit gap #1 (2026-06-10).
 *
 * AlphaSpread's signature trust signal is a single sentence near the
 * hero that reads "Both methods agree within X%" — they wire DCF and
 * a peer-multiples estimate into one chip that telegraphs conviction
 * at a glance. YieldIQ already computes both numbers (and, as of
 * Tier-3 / PR #836, a 7-method cross-engine consensus), so the only
 * gap was a chip that surfaces the agreement headline above the fold.
 *
 * Rendering tiers
 * ───────────────
 *   1. **Consensus tier** — when the response carries a
 *      `cross_engine_consensus` payload with >= 4 estimators we render
 *      "N of M methods agree within 15% of Rs.X" against the composite
 *      intrinsic value. This is the richer signal so it wins
 *      precedence whenever the data is present.
 *
 *   2. **DCF-vs-Multiples tier** — fallback when consensus is absent
 *      (legacy cached payloads, ticker sub-categories without enough
 *      estimators). Same agreement framing across the two numbers we
 *      have always shipped: DCF fair value and multiples-based fair
 *      value. Threshold 15% mirrors the consensus tier.
 *
 *   3. **No render** — both inputs unusable. The chip self-hides so
 *      the caller can mount it unconditionally below <HonestHero />.
 *
 * SEBI vocabulary
 * ───────────────
 * Every visible string is observational and describes the COMPUTATION
 * (the two engines, the spread between them) rather than rendering a
 * verdict on the stock. "Agree" / "diverge" describe the relationship
 * between OUR OWN MODEL OUTPUTS, not the security. Vocabulary lint
 * owned by scripts/check_sebi_words.py — the companion
 * CrossConfirmationChip.test.tsx pins a runtime SEBI sweep across
 * every render branch as the backstop.
 *
 * NB the existing <DcfMultiplesChip /> (Sprint A2) renders a wider
 * pill row inside <HonestHero />. This component is the headline
 * single-sentence chip; the two complement each other and are
 * intentionally mounted on different surfaces (this above HonestHero
 * as the trust-signal banner, DcfMultiplesChip below the FV figure
 * as the methodology side-by-side).
 */

import * as React from "react"

import { cn, formatCurrency } from "@/lib/utils"

/**
 * Minimal local interface for the cross-engine consensus payload.
 * The full ConsensusSignal type lands with PR #836; this shape is
 * the subset the chip reads. Fields are all optional / nullable so
 * the chip degrades gracefully against partial backends.
 */
export interface ConsensusSignalLike {
  total_estimators?: number | null
  direction_agreement_count?: number | null
  consensus_level?: "high" | "moderate" | "low" | null
  /** Per-estimator fair-value points, used for the within-15% sweep. */
  estimator_values?: ReadonlyArray<number | null | undefined> | null
}

export interface CrossConfirmationChipProps {
  /** DCF fair value (typically signals.fairValue / valuation.fair_value). */
  dcfFv: number | null | undefined
  /** Peer-relative multiples fair value (payload.multiples_based_fv). */
  multiplesFv: number | null | undefined
  /** Composite intrinsic value — anchor for the within-15% sweep. */
  compositeIv?: number | null | undefined
  /** Cross-engine consensus payload from PR #836; optional. */
  consensus?: ConsensusSignalLike | null | undefined
  /** Used by formatCurrency for the INR ticker-prefix routing. */
  ticker?: string | null
  /** Backend currency tag, e.g. "INR". */
  currency?: string | null
  className?: string
}

const AGREE_THRESHOLD_PCT = 15

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value)
}

function pctSpread(a: number, b: number): number {
  const ref = Math.max(Math.abs(a), Math.abs(b))
  if (ref <= 0) return 0
  return (Math.abs(a - b) / ref) * 100
}

/**
 * Count estimators whose value sits within AGREE_THRESHOLD_PCT of the
 * anchor. Null / non-finite estimator entries are skipped (they
 * contribute neither to the agree count nor the total).
 */
export function countWithin15Pct(
  consensus: ConsensusSignalLike | null | undefined,
  anchor: number,
): number {
  if (!consensus || !isFiniteNumber(anchor) || anchor === 0) return 0
  const values = consensus.estimator_values ?? []
  let agree = 0
  for (const raw of values) {
    if (!isFiniteNumber(raw)) continue
    if (pctSpread(raw, anchor) <= AGREE_THRESHOLD_PCT) agree += 1
  }
  return agree
}

function ConsensusBadge({
  level,
}: {
  level?: ConsensusSignalLike["consensus_level"]
}) {
  if (!level) return null
  const tone =
    level === "high"
      ? "border-emerald-300 bg-emerald-50 text-emerald-900 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-200"
      : level === "moderate"
        ? "border-amber-300 bg-amber-50 text-amber-900 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-200"
        : "border-slate-300 bg-slate-50 text-slate-700 dark:border-slate-700 dark:bg-slate-900/50 dark:text-slate-200"
  return (
    <span
      data-testid="cross-conf-consensus-badge"
      className={cn(
        "ml-2 inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider",
        tone,
      )}
    >
      {level} agreement
    </span>
  )
}

function ConsensusChip({
  consensus,
  composite,
  ticker,
  currency,
}: {
  consensus: ConsensusSignalLike
  composite: number | null | undefined
  ticker: string | null | undefined
  currency: string | null | undefined
}) {
  const total = consensus.total_estimators ?? 0
  const direction = consensus.direction_agreement_count ?? 0
  const within = isFiniteNumber(composite)
    ? countWithin15Pct(consensus, composite)
    : 0
  // Headline anchors on the within-15% count when a composite anchor
  // is available, otherwise it falls back to the direction-agreement
  // count the backend already reported.
  const headlineCount = isFiniteNumber(composite) ? within : direction
  const highConviction = total > 0 && headlineCount >= total * 0.7
  const anchorDisplay = isFiniteNumber(composite)
    ? formatCurrency(composite, currency ?? undefined, ticker ?? undefined)
    : null

  return (
    <div
      data-testid="cross-conf-chip"
      data-variant="consensus"
      data-conviction={highConviction ? "high" : "moderate"}
      aria-label="Cross-engine consensus summary"
      className={cn(
        "rounded-xl border px-4 py-3 text-[13px] leading-snug",
        highConviction
          ? "border-emerald-300 bg-emerald-50 text-emerald-950 dark:border-emerald-900 dark:bg-emerald-950/30 dark:text-emerald-100"
          : "border-amber-300 bg-amber-50 text-amber-950 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-100",
      )}
    >
      <p className="text-[10px] uppercase tracking-[0.15em] opacity-70">
        Cross-engine agreement
      </p>
      <p
        data-testid="cross-conf-headline"
        className="mt-1 text-[14px] font-medium"
      >
        {anchorDisplay ? (
          <>
            <span className="font-semibold tabular-nums">
              {headlineCount}
            </span>{" "}
            of <span className="font-semibold tabular-nums">{total}</span>{" "}
            methods agree within {AGREE_THRESHOLD_PCT}% of{" "}
            <span className="font-semibold tabular-nums">
              {anchorDisplay}
            </span>
          </>
        ) : (
          <>
            <span className="font-semibold tabular-nums">
              {headlineCount}
            </span>{" "}
            of <span className="font-semibold tabular-nums">{total}</span>{" "}
            methods point in the same direction
          </>
        )}
        <ConsensusBadge level={consensus.consensus_level ?? null} />
      </p>
    </div>
  )
}

function DcfMultiplesAgreementChip({
  dcf,
  multiples,
  ticker,
  currency,
}: {
  dcf: number
  multiples: number
  ticker: string | null | undefined
  currency: string | null | undefined
}) {
  const diff = pctSpread(dcf, multiples)
  const agree = diff < AGREE_THRESHOLD_PCT
  const dcfDisplay = formatCurrency(
    dcf,
    currency ?? undefined,
    ticker ?? undefined,
  )
  const multiplesDisplay = formatCurrency(
    multiples,
    currency ?? undefined,
    ticker ?? undefined,
  )
  const diffDisplay = `${diff.toFixed(0)}%`

  return (
    <div
      data-testid="cross-conf-chip"
      data-variant="dcf-multiples"
      data-agreement={agree ? "agree" : "diverge"}
      aria-label="DCF and multiples agreement summary"
      className={cn(
        "rounded-xl border px-4 py-3 text-[13px] leading-snug",
        agree
          ? "border-emerald-300 bg-emerald-50 text-emerald-950 dark:border-emerald-900 dark:bg-emerald-950/30 dark:text-emerald-100"
          : "border-slate-300 bg-slate-50 text-slate-900 dark:border-slate-700 dark:bg-slate-900/40 dark:text-slate-100",
      )}
    >
      <p className="text-[10px] uppercase tracking-[0.15em] opacity-70">
        Method cross-check
      </p>
      <p
        data-testid="cross-conf-headline"
        className="mt-1 text-[14px] font-medium"
      >
        <span className="tabular-nums">DCF {dcfDisplay}</span>
        <span className="opacity-60"> &middot; </span>
        <span className="tabular-nums">Multiples {multiplesDisplay}</span>
      </p>
      <p
        data-testid="cross-conf-summary"
        className="mt-1 text-[12px] opacity-80"
      >
        {agree
          ? `Both methods agree within ${diffDisplay}.`
          : `Methods diverge by ${diffDisplay}.`}
      </p>
    </div>
  )
}

export default function CrossConfirmationChip({
  dcfFv,
  multiplesFv,
  compositeIv,
  consensus,
  ticker,
  currency,
  className,
}: CrossConfirmationChipProps) {
  // Tier 1 — richer consensus view when PR #836's payload is present.
  const consensusUsable =
    consensus != null &&
    isFiniteNumber(consensus.total_estimators) &&
    (consensus.total_estimators ?? 0) >= 4

  if (consensusUsable && consensus) {
    return (
      <div className={className} data-testid="cross-conf-chip-wrapper">
        <ConsensusChip
          consensus={consensus}
          composite={compositeIv ?? null}
          ticker={ticker ?? null}
          currency={currency ?? null}
        />
      </div>
    )
  }

  // Tier 2 — DCF + Multiples fallback. Both must be finite and positive.
  if (
    isFiniteNumber(dcfFv) &&
    isFiniteNumber(multiplesFv) &&
    dcfFv > 0 &&
    multiplesFv > 0
  ) {
    return (
      <div className={className} data-testid="cross-conf-chip-wrapper">
        <DcfMultiplesAgreementChip
          dcf={dcfFv}
          multiples={multiplesFv}
          ticker={ticker ?? null}
          currency={currency ?? null}
        />
      </div>
    )
  }

  // Tier 3 — nothing usable, self-hide.
  return null
}

export { ConsensusChip, DcfMultiplesAgreementChip, AGREE_THRESHOLD_PCT }
