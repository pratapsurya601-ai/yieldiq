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
}

async function fetchReverseDcf(ticker: string): Promise<ReverseDcfPayload | null> {
  const base = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"
  try {
    const res = await fetch(`${base}/api/v1/public/reverse-dcf/${ticker}`, {
      next: { revalidate: 600 },
    })
    if (!res.ok) return null
    const data = await res.json()
    if (!data || typeof data !== "object" || !("implied_growth_pct" in data)) {
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
    // Skip rendering on null/error — task spec requires we hide cleanly.
    return null
  }

  const {
    implied_growth_pct: impliedG,
    implied_margin_pct: impliedM,
    iso_fv_curve: iso,
    current_market_implied_summary: summary,
    sanity_check_lines: sanity,
    inputs,
  } = data

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
              {formatPct(impliedG)}
            </span>
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
