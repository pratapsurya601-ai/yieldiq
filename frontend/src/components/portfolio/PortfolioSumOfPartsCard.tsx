"use client"
/**
 * Portfolio Sum-of-Parts FV card (P0 #2, 2026-05-25).
 *
 * Aggregates DCF fair value across every holding the user owns and
 * compares it to total market value. Pulls from
 * `GET /api/v1/portfolio/sum-of-parts`, which is READ-ONLY against
 * the analysis_cache — holdings with no cached FV are reported in
 * `holdings_without_fv_count` and surfaced here via a LIMITED DATA
 * chip so users know coverage is partial.
 *
 * Empty state: when zero holdings have a cached FV we render a
 * pointer to "/search" so the user can analyse something and
 * unlock the card on next page load.
 *
 * SEBI-safe copy: "based on our DCF model" framing — never "true
 * worth", "should be priced at", etc.
 */
import { useQuery } from "@tanstack/react-query"
import { getPortfolioSumOfParts } from "@/lib/api"

function fmtRsCompact(n: number): string {
  const abs = Math.abs(n)
  const sign = n < 0 ? "-" : ""
  if (abs >= 10_000_000) return `${sign}₹${(abs / 10_000_000).toFixed(2)}Cr`
  if (abs >= 100_000) return `${sign}₹${(abs / 100_000).toFixed(2)}L`
  if (abs >= 1_000) return `${sign}₹${(abs / 1_000).toFixed(1)}K`
  return `${sign}₹${abs.toFixed(0)}`
}

function verdictColor(label: string | null): { text: string; chip: string } {
  if (label === "Overvalued") return { text: "text-red-600", chip: "bg-red-50 text-red-700 ring-red-200" }
  if (label === "Undervalued") return { text: "text-green-600", chip: "bg-green-50 text-green-700 ring-green-200" }
  return { text: "text-ink", chip: "bg-gray-50 text-gray-700 ring-gray-200" }
}

export default function PortfolioSumOfPartsCard() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["portfolio-sum-of-parts"],
    queryFn: getPortfolioSumOfParts,
    retry: 1,
    staleTime: 60_000,
  })

  if (isLoading) {
    return (
      <div
        aria-busy="true"
        aria-label="Loading portfolio sum-of-parts"
        className="skeleton rounded-2xl h-[130px]"
      />
    )
  }
  if (isError || !data) return null

  // No holdings at all → no card.
  if (data.total_holdings === 0) return null

  // Holdings exist but none have a cached FV → empty-state prompt.
  if (data.intrinsic_value === null || data.verdict_label === null) {
    return (
      <section
        aria-label="Portfolio sum-of-parts (no coverage)"
        data-testid="sop-empty"
        className="bg-bg dark:bg-surface rounded-2xl border border-border p-5"
      >
        <div className="flex items-center justify-between mb-1">
          <p className="text-xs font-bold uppercase tracking-wider text-caption">
            Sum-of-parts fair value
          </p>
          <span className="inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold ring-1 bg-amber-50 text-amber-700 ring-amber-200">
            LIMITED DATA
          </span>
        </div>
        <p className="text-sm text-ink mt-2">
          No DCF coverage on your holdings yet — analyse one to see this card.
        </p>
        <a
          href="/search"
          className="inline-block mt-3 text-xs font-semibold text-blue-600 hover:underline"
        >
          Analyse a stock &rarr;
        </a>
      </section>
    )
  }

  const gap = data.gap_pct ?? 0
  const colors = verdictColor(data.verdict_label)
  const mv = data.market_value
  const iv = data.intrinsic_value
  // FIX portfolio-hotfix-#3: replaced confusing 100%-wide stacked
  // bar (which falsely implied MV + IV summed to one whole) with
  // two parallel bars, each scaled against max(MV, IV). Reads as
  // an unambiguous comparison instead of a composition.
  const maxVal = Math.max(mv, iv, 1)
  const mvBarPct = (mv / maxVal) * 100
  const ivBarPct = (iv / maxVal) * 100
  const partial = data.holdings_without_fv_count > 0

  return (
    <section
      aria-label="Portfolio sum-of-parts fair value"
      data-testid="sop-card"
      className="bg-bg dark:bg-surface rounded-2xl border border-border p-5 space-y-3"
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs font-bold uppercase tracking-wider text-caption">
            Sum-of-parts fair value
          </p>
          <p className={`text-lg font-bold mt-1 ${colors.text}`}>
            Your portfolio is{" "}
            <span data-testid="sop-headline-gap">
              {Math.abs(gap).toFixed(1)}%
            </span>{" "}
            <span data-testid="sop-headline-verdict">{data.verdict_label}</span>
          </p>
        </div>
        {partial && (
          <span
            className={`shrink-0 inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold ring-1 ${colors.chip}`}
            title={`${data.holdings_without_fv_count} of ${data.total_holdings} holdings have no cached fair value`}
          >
            LIMITED DATA
          </span>
        )}
      </div>

      {/* Two parallel comparison bars (P0 hotfix #3) — each scaled
          to its actual value against max(MV, IV). The taller side
          fills the row; the other reads as obviously shorter. */}
      <div
        className="space-y-2"
        role="img"
        aria-label={`Market value ${fmtRsCompact(mv)}, intrinsic value ${fmtRsCompact(iv)}`}
      >
        <div>
          <div className="flex items-center justify-between text-xs mb-1">
            <span className="text-caption">Market Value</span>
            <span className="font-mono font-semibold text-ink">
              {fmtRsCompact(mv)}
            </span>
          </div>
          <div className="h-2 w-full rounded-full bg-surface overflow-hidden">
            <div
              className="h-full bg-orange-400 rounded-full"
              style={{ width: `${mvBarPct}%` }}
              data-testid="sop-bar-market"
            />
          </div>
        </div>
        <div>
          <div className="flex items-center justify-between text-xs mb-1">
            <span className="text-caption">Intrinsic Value</span>
            <span className="font-mono font-semibold text-ink">
              {fmtRsCompact(iv)}
            </span>
          </div>
          <div className="h-2 w-full rounded-full bg-surface overflow-hidden">
            <div
              className="h-full bg-emerald-500 rounded-full"
              style={{ width: `${ivBarPct}%` }}
              data-testid="sop-bar-intrinsic"
            />
          </div>
        </div>
      </div>

      <p className="text-[11px] text-caption">
        Computed from DCF fair value of {data.holdings_with_fv_count} of{" "}
        {data.total_holdings} holdings. Not investment advice.
      </p>
    </section>
  )
}
