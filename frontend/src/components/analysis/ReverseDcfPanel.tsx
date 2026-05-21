"use client"

/**
 * ReverseDcfPanel — "what is the market pricing in?"
 *
 * Reads /api/v1/public/reverse-dcf/{ticker} (anonymous-accessible).
 * The endpoint returns the implied FCF growth + implied FCF margin
 * the current price embeds, plus a 3-point iso-FV curve and a plain-
 * English summary. When the backend returns null (loss-makers, data-
 * limited tickers, cache miss) the component renders nothing — this
 * is purely additive UI sitting below the scenario card.
 *
 * Day-87: wire the three new fields shipped by Day-76 backend:
 *   • applicable=false + category=bank_like → small "not applicable"
 *     card instead of hiding the panel.
 *   • growth_off_scale=true → headline becomes a >= / <= bound with
 *     an amber caveat note (summary text is already bound-qualified
 *     server-side; we surface it verbatim).
 *
 * No reuse from the existing /stocks/[ticker]/reverse-dcf page (which
 * hits the older authed endpoint with a different shape) — that path
 * is verdict-centric, this panel is implied-axis-centric.
 */

import { useQuery } from "@tanstack/react-query"

interface IsoFvPoint {
  growth: number
  margin: number
}

interface ReverseDcfInputs {
  current_price: number
  wacc: number
  terminal_g: number
  current_fcf: number
  current_margin: number
  current_revenue: number
  consensus_growth: number
  total_debt: number
  total_cash: number
  shares: number
  years: number
}

interface ReverseDcfPayload {
  ticker: string
  implied_growth_pct: number
  implied_margin_pct: number
  iso_fv_curve: IsoFvPoint[]
  current_market_implied_summary: string
  sanity_check_lines: string[]
  converged: boolean
  inputs: ReverseDcfInputs
  // Day-87: Day-76 backend additions ---------------------------------
  applicable?: boolean
  reason?: string
  category?: string
  growth_off_scale?: boolean
  growth_pegged_high?: boolean
  growth_pegged_low?: boolean
}

async function fetchReverseDcf(ticker: string): Promise<ReverseDcfPayload | null> {
  const base = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"
  try {
    const res = await fetch(`${base}/api/v1/public/reverse-dcf/${ticker}`, {
      next: { revalidate: 600 },
    })
    if (!res.ok) return null
    const data = await res.json()
    if (!data || typeof data !== "object") return null
    // Day-87: accept the bank-skip payload shape (no implied_growth_pct).
    if (data.applicable === false) {
      return data as ReverseDcfPayload
    }
    if (!("implied_growth_pct" in data)) {
      return null
    }
    return data as ReverseDcfPayload
  } catch {
    return null
  }
}

function formatPct(decimal: number, digits = 1): string {
  if (!Number.isFinite(decimal)) return "—"
  return `${(decimal * 100).toFixed(digits)}%`
}

interface Props {
  ticker: string
}

export default function ReverseDcfPanel({ ticker }: Props) {
  const { data, isLoading } = useQuery({
    queryKey: ["public-reverse-dcf", ticker],
    queryFn: () => fetchReverseDcf(ticker),
    enabled: !!ticker,
    staleTime: 10 * 60 * 1000,
    retry: 1,
  })

  if (isLoading || !data) {
    // Still hide on null/error — only the bank-skip payload renders.
    return null
  }

  // Day-87: bank-skip card. Banks / NBFCs / insurers do not admit an
  // FCF-based reverse-DCF — Day-76 returns a structured non-applicable
  // payload and we surface a small explanatory card so the absence is
  // legible rather than mysteriously missing.
  if (data.applicable === false) {
    return (
      <section
        aria-label="Reverse DCF — not applicable"
        className="bg-bg dark:bg-surface rounded-2xl border border-border p-4"
      >
        <header className="mb-1">
          <h2 className="text-sm font-semibold text-ink tracking-tight uppercase">
            Reverse-DCF
          </h2>
        </header>
        <p className="text-caption text-xs leading-relaxed">
          <span className="font-bold text-ink">Not applicable for banks.</span>{" "}
          Banks, NBFCs and insurers use ROE / RoA / NIM instead of FCF-based
          valuation. See the Quality panel for those metrics.
        </p>
      </section>
    )
  }

  const {
    implied_growth_pct: impliedG,
    implied_margin_pct: impliedM,
    iso_fv_curve: iso,
    current_market_implied_summary: summary,
    sanity_check_lines: sanity,
    inputs,
    growth_off_scale: offScale,
    growth_pegged_high: peggedHigh,
    growth_pegged_low: peggedLow,
  } = data

  // Day-87: off-scale headline. When the bisector pegs at the search
  // boundary we surface the number as a bound (>= / <=) plus a short
  // caveat. The backend `summary` field is already bound-qualified so
  // we render it verbatim and tag it with the amber note below.
  const offScalePrefix = peggedHigh ? "≥" : peggedLow ? "≤" : null
  const offScaleCaveat = peggedHigh
    ? "off-scale — likely trough-margin distortion"
    : peggedLow
      ? "off-scale — likely balance-sheet event distortion"
      : null

  return (
    <section
      aria-label="Reverse DCF"
      className="bg-bg rounded-2xl border border-border p-5"
    >
      <header className="mb-3">
        <h2 className="text-sm font-semibold text-ink tracking-tight uppercase">
          Reverse-DCF — what&rsquo;s the market pricing in?
        </h2>
        <p className="text-xs text-caption mt-1">
          Holding today&rsquo;s price as the target, the assumptions a 10-year
          two-stage DCF must adopt to match it.
        </p>
      </header>

      <p className="text-sm text-body leading-relaxed">{summary}</p>

      {offScale && offScaleCaveat && (
        <p className="mt-2 text-xs leading-relaxed rounded-md border border-amber-300/40 bg-amber-50 dark:bg-amber-950/20 text-amber-900 dark:text-amber-200 px-3 py-2">
          <span className="font-bold">Note:</span> {offScaleCaveat}. The
          implied-growth figure above is a bound, not a point estimate.
        </p>
      )}

      <ul className="mt-4 space-y-2 text-sm">
        <li className="flex items-baseline gap-2">
          <span aria-hidden className="text-caption">&bull;</span>
          <span>
            Implied FCF growth at current{" "}
            <span className="font-mono tabular-nums">
              {formatPct(inputs.current_margin)}
            </span>{" "}
            margins:{" "}
            <span className="font-semibold font-mono tabular-nums text-ink">
              {offScalePrefix ? `${offScalePrefix} ` : ""}
              {formatPct(impliedG)}
            </span>
            {offScale && (
              <span className="ml-1 text-caption text-xs">(off-scale)</span>
            )}
          </span>
        </li>
        <li className="flex items-baseline gap-2">
          <span aria-hidden className="text-caption">&bull;</span>
          <span>
            Implied FCF margin at consensus{" "}
            <span className="font-mono tabular-nums">
              {formatPct(inputs.consensus_growth)}
            </span>{" "}
            growth:{" "}
            <span className="font-semibold font-mono tabular-nums text-ink">
              {formatPct(impliedM)}
            </span>
          </span>
        </li>
        {iso && iso.length > 0 && (
          <li className="flex items-baseline gap-2">
            <span aria-hidden className="text-caption">&bull;</span>
            <span>
              Iso-FV curve:{" "}
              <span className="font-mono tabular-nums">
                {iso.map((p, i) => (
                  <span key={i}>
                    {i > 0 ? "  /  " : ""}
                    {formatPct(p.growth)} g &amp; {formatPct(p.margin)} m
                  </span>
                ))}
              </span>
            </span>
          </li>
        )}
      </ul>

      {sanity && sanity.length > 0 && (
        <footer className="mt-4 pt-3 border-t border-border">
          <p className="text-[11px] uppercase tracking-wider text-caption mb-1">
            Sanity check vs trailing 5y actuals
          </p>
          <ul className="space-y-1">
            {sanity.map((line, i) => (
              <li key={i} className="text-xs text-caption leading-relaxed">
                {line}
              </li>
            ))}
          </ul>
        </footer>
      )}
    </section>
  )
}
