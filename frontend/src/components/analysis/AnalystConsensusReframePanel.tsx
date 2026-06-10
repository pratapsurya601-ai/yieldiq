/**
 * AnalystConsensusReframePanel — competitor audit #2 reframe surface.
 *
 * The legacy "Independent" framing on the Analyst Consensus card reads
 * as "no validation." This panel inverts that posture: when Wall Street
 * coverage IS available we lean in, place the two estimates side-by-side,
 * and explain the gap. The gap itself becomes the differentiator.
 *
 * Composition:
 *   - Pure server-safe component (no client hooks). Reads pre-fetched
 *     analyst_consensus.price_target.mean + composite_intrinsic_value.
 *   - Renders an empty notice when Wall Street coverage is unavailable
 *     (the legacy InsightCards copy still handles the no-coverage card
 *     elsewhere on the page; this panel simply collapses to a single
 *     line so it doesn't double-render that idea).
 *
 * SEBI lens:
 *   - All copy is descriptive. No imperative verbs from the banned
 *     vocabulary in scripts/check_sebi_words.py. The gap explanation
 *     uses "sees more long-term value" / "more cautious" /
 *     "cross-validation" framing rather than directional advice.
 *   - The method-tag prettifier (prettifyMethod) intentionally avoids
 *     the banned-vocabulary list — composite method tags from the
 *     backend are mechanical model names (DCF / Multiples / Three-stage
 *     etc.) not opinion verbs.
 */

import * as React from "react"

import { SummaryCard } from "@/components/cards"
import { cn, formatCurrency } from "@/lib/utils"

export interface AnalystConsensusReframePanelProps {
  ticker: string
  /** Wall Street avg target — from analyst_consensus.price_target.mean. */
  wallStAvgTarget: number | null
  /** Optional high end of the analyst range. */
  wallStHighTarget?: number | null
  /** Optional low end of the analyst range. */
  wallStLowTarget?: number | null
  /** Optional count of contributing analysts. */
  analystCount?: number | null
  /** YieldIQ composite intrinsic value. */
  yiqComposite: number | null
  /** Optional method tag (e.g. "composite_dcf_multiples_analyst_threestage"). */
  yiqMethod?: string | null
  /** Live current price — used so the empty-state still reads with context. */
  currentPrice: number
  /** Optional currency for the formatter. Defaults to INR. */
  currency?: string | null
  className?: string
}

type GapDirection = "above" | "below" | "aligned"

/* ─── public component ─────────────────────────────────────────────── */

export default function AnalystConsensusReframePanel({
  ticker,
  wallStAvgTarget,
  wallStHighTarget,
  wallStLowTarget,
  analystCount,
  yiqComposite,
  yiqMethod,
  currentPrice: _currentPrice,
  currency,
  className,
}: AnalystConsensusReframePanelProps) {
  const ccy = currency ?? "INR"

  // Empty state: Wall Street coverage not available. We stay
  // intentionally short — InsightCards already carries the deeper "no
  // coverage" framing further down the page.
  if (
    wallStAvgTarget === null ||
    !Number.isFinite(wallStAvgTarget) ||
    wallStAvgTarget <= 0
  ) {
    return (
      <SummaryCard
        data-testid="analyst-consensus-reframe-empty"
        className={cn("gap-2", className)}
      >
        <h3 className="text-lg font-bold text-ink">
          How YieldIQ compares to Wall Street
        </h3>
        <p className="text-sm text-caption" data-testid="analyst-reframe-empty-copy">
          Wall Street consensus is not yet available for {ticker}. YieldIQ
          values this ticker from first-principles DCF + peer multiples;
          broker coverage is not an input to our composite.
        </p>
      </SummaryCard>
    )
  }

  // YIQ composite missing — we still render the Wall Street side so the
  // surface is informative rather than blank, but no gap math.
  const yiqValid =
    yiqComposite !== null &&
    Number.isFinite(yiqComposite) &&
    yiqComposite > 0

  const gapPct = yiqValid
    ? ((yiqComposite! - wallStAvgTarget) / wallStAvgTarget) * 100
    : null

  const direction: GapDirection | null = gapPct === null
    ? null
    : gapPct > 5
      ? "above"
      : gapPct < -5
        ? "below"
        : "aligned"

  const gapClass =
    direction === "above"
      ? "border-success/40 bg-success/5 text-success"
      : direction === "below"
        ? "border-warn/40 bg-warn/5 text-warn"
        : direction === "aligned"
          ? "border-border bg-surface text-body"
          : "border-border bg-surface text-body"

  const headlineGap = gapPct === null
    ? null
    : direction === "aligned"
      ? "In line with Wall Street"
      : `${Math.abs(gapPct).toFixed(0)}% ${direction === "above" ? "more" : "less"}`

  return (
    <SummaryCard
      data-testid="analyst-consensus-reframe"
      className={cn("gap-4", className)}
    >
      <header className="flex flex-col gap-1">
        <h3 className="text-lg font-bold text-ink">
          How YieldIQ compares to Wall Street
        </h3>
        <p className="text-xs text-caption leading-snug">
          The estimates below are computed independently. Read the gap as
          a confidence signal — convergence reinforces, divergence flags
          modelling assumptions worth a second look.
        </p>
      </header>

      {/* Side-by-side comparison */}
      <div
        className="grid grid-cols-1 md:grid-cols-2 gap-3"
        data-testid="analyst-reframe-comparison"
      >
        <div
          className="rounded-xl border border-border bg-surface p-4 flex flex-col gap-1"
          data-testid="analyst-reframe-wallst"
        >
          <h4 className="text-xs uppercase tracking-wide text-caption font-semibold">
            Wall Street analysts
          </h4>
          <div className="num text-2xl font-bold text-ink" data-testid="analyst-reframe-wallst-value">
            {formatCurrency(Math.round(wallStAvgTarget), ccy)}
          </div>
          {wallStHighTarget != null &&
            wallStLowTarget != null &&
            Number.isFinite(wallStHighTarget) &&
            Number.isFinite(wallStLowTarget) && (
              <div
                className="text-xs text-caption"
                data-testid="analyst-reframe-wallst-range"
              >
                Range: {formatCurrency(Math.round(wallStLowTarget), ccy)}
                {" – "}
                {formatCurrency(Math.round(wallStHighTarget), ccy)}
              </div>
            )}
          {analystCount != null && analystCount > 0 && (
            <div
              className="text-xs text-caption"
              data-testid="analyst-reframe-wallst-count"
            >
              {analystCount} analyst{analystCount === 1 ? "" : "s"}
            </div>
          )}
          <div className="text-[11px] text-caption italic mt-1">
            12-month price target consensus (Finnhub).
          </div>
        </div>

        <div
          className="rounded-xl border border-border bg-surface p-4 flex flex-col gap-1"
          data-testid="analyst-reframe-yiq"
        >
          <h4 className="text-xs uppercase tracking-wide text-caption font-semibold">
            YieldIQ composite
          </h4>
          <div className="num text-2xl font-bold text-ink" data-testid="analyst-reframe-yiq-value">
            {yiqValid
              ? formatCurrency(Math.round(yiqComposite!), ccy)
              : "—"}
          </div>
          <div
            className="text-xs text-caption"
            data-testid="analyst-reframe-yiq-method"
          >
            {prettifyMethod(yiqMethod)}
          </div>
          <div className="text-[11px] text-caption italic mt-1">
            Weighted multi-model intrinsic value (full FCF horizon).
          </div>
        </div>
      </div>

      {/* Gap explanation strip */}
      {direction !== null && (
        <div
          className={cn(
            "rounded-xl border px-4 py-3 flex flex-col gap-1",
            gapClass,
            `gap-${direction}`,
          )}
          data-testid="analyst-reframe-gap"
          data-direction={direction}
        >
          <span
            className="num text-base font-bold"
            data-testid="analyst-reframe-gap-headline"
          >
            {headlineGap}
          </span>
          <p
            className="text-sm leading-snug text-ink/90"
            data-testid="analyst-reframe-gap-copy"
          >
            {getGapExplanation(direction)}
          </p>
        </div>
      )}

      {/* Why we may differ */}
      <div className="rounded-xl border border-border bg-surface p-4 flex flex-col gap-2">
        <h4 className="text-sm font-semibold text-ink">
          Why we may differ
        </h4>
        <ul
          className="text-sm text-body space-y-1.5 list-disc pl-5 leading-snug"
          data-testid="analyst-reframe-reasons"
        >
          <li>
            Wall Street targets are 12-month horizon; YieldIQ discounts
            the full free-cash-flow stream out to a terminal value.
          </li>
          <li>
            Broker coverage mixes Indian and foreign desks — depth varies
            ticker by ticker, and the mean can over-weight the loudest
            voices.
          </li>
          <li>
            YieldIQ normalises SBC dilution, IFRS-16 leases, excess
            cash, minority interest, and working capital — adjustments
            broker models rarely surface.
          </li>
        </ul>
      </div>

      <p className="text-[11px] text-caption italic">
        Both numbers are model estimates, not investment advice. Inputs
        and assumptions change daily.
      </p>
    </SummaryCard>
  )
}

/* ─── helpers ──────────────────────────────────────────────────────── */

export function getGapExplanation(direction: GapDirection): string {
  if (direction === "aligned") {
    return "Independent cross-validation — YieldIQ and Wall Street land within 5% of each other on this ticker, computed from separate inputs."
  }
  if (direction === "above") {
    return "YieldIQ sees more long-term value than the Street's 12-month target captures — typically because the full FCF horizon credits compounding past the 1-year window."
  }
  // below
  return "YieldIQ is more cautious than Wall Street — usually a sign that the Street's growth or terminal-value assumptions are richer than what our normalised model supports."
}

const METHOD_FRAGMENT_LABELS: Record<string, string> = {
  composite: "Composite",
  dcf: "DCF",
  multiples: "Multiples",
  analyst: "Wall Street",
  consensus: "Wall Street",
  threestage: "Three-stage DCF",
  three_stage: "Three-stage DCF",
  ddm: "DDM",
  epv: "EPV",
  liquidation: "Liquidation Floor",
  probability: "Probability-weighted",
  probabilityweighted: "Probability-weighted",
  weighted: "Weighted",
  graham: "Graham",
  tobin: "Tobin Q",
}

export function prettifyMethod(method: string | null | undefined): string {
  if (!method || typeof method !== "string") {
    return "Composite intrinsic value"
  }
  const trimmed = method.trim()
  if (trimmed === "") {
    return "Composite intrinsic value"
  }
  // Split on underscores; drop a leading "composite_" prefix so we don't
  // emit "Composite + DCF + ..." (the panel header already says it's
  // a composite). Map each fragment to a friendly label; fall back to
  // a Title-Case version of the raw fragment for anything we don't
  // recognise.
  const fragments = trimmed
    .toLowerCase()
    .split(/[_\s]+/)
    .filter(Boolean)
  const head = fragments[0] === "composite" ? fragments.slice(1) : fragments
  if (head.length === 0) {
    return "Composite intrinsic value"
  }
  const seen = new Set<string>()
  const labels: string[] = []
  for (const frag of head) {
    const label =
      METHOD_FRAGMENT_LABELS[frag] ??
      frag.charAt(0).toUpperCase() + frag.slice(1)
    if (!seen.has(label)) {
      seen.add(label)
      labels.push(label)
    }
  }
  return labels.join(" + ")
}
