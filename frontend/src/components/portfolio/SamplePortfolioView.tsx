"use client"
// Day-97 (2026-05-22): onboarding sample-portfolio view.
//
// Rendered on /portfolio ONLY when the backend attaches a
// `sample_portfolio` payload (first-session signup with zero real
// holdings) AND the user has not previously dismissed it (localStorage
// flag `yieldiq_sample_portfolio_dismissed`). The intent is to give
// brand-new signups the Portfolio Prism "wow moment" instantly, so the
// instant-value bar isn't an empty state + a CSV upload prompt.
//
// Every row carries an explicit "Sample" badge so the user can never
// mistake the fixture for their own positions. Primary CTA points at
// the broker import flow; secondary CTA simply continues with the
// sample. Dismissal is one-way (localStorage flag) — next visit shows
// the standard empty state.
import Link from "next/link"
import { formatCurrency } from "@/lib/utils"
import type { SamplePortfolio } from "@/lib/api"

export const SAMPLE_DISMISSED_KEY = "yieldiq_sample_portfolio_dismissed"

function fmtRsCompact(n: number): string {
  const abs = Math.abs(n)
  const sign = n < 0 ? "-" : ""
  if (abs >= 10_000_000) return `${sign}₹${(abs / 10_000_000).toFixed(2)}Cr`
  if (abs >= 100_000) return `${sign}₹${(abs / 100_000).toFixed(2)}L`
  if (abs >= 1_000) return `${sign}₹${(abs / 1_000).toFixed(1)}K`
  return `${sign}₹${abs.toFixed(0)}`
}

interface Props {
  sample: SamplePortfolio
  onDismiss: () => void
}

export default function SamplePortfolioView({ sample, onDismiss }: Props) {
  return (
    <section
      aria-label="Sample portfolio"
      data-testid="sample-portfolio-view"
      className="space-y-4"
    >
      {/* Header banner — explicit framing so the fixture is never
          mistaken for the user's real positions. */}
      <div className="bg-gradient-to-br from-violet-600 to-blue-600 rounded-2xl p-4 text-white">
        <div className="flex items-center gap-2 mb-2">
          <span
            data-testid="sample-banner-badge"
            className="inline-flex items-center gap-1 rounded-full bg-white/15 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider ring-1 ring-white/30"
          >
            Sample
          </span>
          <p className="text-xs font-bold uppercase tracking-wider opacity-90">
            Try YieldIQ on a sample portfolio
          </p>
        </div>
        <p className="text-sm leading-snug opacity-95 mb-3">
          {sample.note}
        </p>
        <div className="flex flex-wrap gap-2 pt-2">
          <Link
            href="/portfolio/import"
            data-testid="sample-cta-import"
            className="inline-flex items-center justify-center min-h-[40px] bg-white text-tone-info-fg text-sm font-bold px-4 py-2 rounded-lg hover:bg-tone-info-bg active:scale-[0.98] transition"
          >
            Import your real holdings &rarr;
          </Link>
          <button
            type="button"
            onClick={onDismiss}
            data-testid="sample-cta-dismiss"
            className="inline-flex items-center justify-center min-h-[40px] bg-white/10 text-white text-sm font-semibold px-4 py-2 rounded-lg hover:bg-white/20 active:scale-[0.98] transition ring-1 ring-white/30"
          >
            Continue exploring sample
          </button>
        </div>
        <p className="text-[11px] opacity-75 mt-3">
          Total notional: <span className="font-bold">{fmtRsCompact(sample.summary.total_invested)}</span>
          {" · "}
          {sample.summary.count} holdings across 6 sectors
        </p>
      </div>

      {/* Holdings list — same visual rhythm as the real holdings
          rows, but each row is explicitly badged "Sample" so the
          fixture is never mistaken for live positions. */}
      <div data-testid="sample-holdings-list" className="space-y-3">
        {sample.holdings.map((h) => (
          <div
            key={h.ticker}
            className="bg-bg dark:bg-surface rounded-xl border border-dashed border-violet-200 p-4"
          >
            <div className="flex items-start justify-between mb-2">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <p className="font-bold text-ink">{h.display_ticker}</p>
                  <span
                    data-testid={`sample-badge-${h.display_ticker}`}
                    className="inline-flex items-center gap-1 rounded-full bg-violet-50 text-violet-700 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider ring-1 ring-violet-200"
                    title="This is a sample holding, not a real position"
                  >
                    <span aria-hidden="true">{"👀"}</span>
                    Sample
                  </span>
                </div>
                <p className="text-xs text-caption truncate">
                  {h.sector} <span className="text-gray-300">|</span> {h.company_name}
                </p>
              </div>
              <div className="text-right">
                <p className="text-sm font-mono font-semibold text-ink">
                  {formatCurrency(h.entry_price, "INR")}
                </p>
                <p className="text-[10px] text-caption uppercase tracking-wider">
                  Cost basis
                </p>
              </div>
            </div>
            <div className="flex items-center justify-between text-xs">
              <div className="text-caption">
                {h.quantity} <span className="text-gray-300 mx-1">x</span>
                {formatCurrency(h.entry_price, "INR")}
                <span className="text-gray-300 mx-1">=</span>
                <span className="text-ink">{fmtRsCompact(h.invested_value)}</span>
              </div>
              <Link
                href={`/analysis/${h.ticker}`}
                className="text-violet-700 font-semibold hover:underline"
              >
                Open analysis &rarr;
              </Link>
            </div>
          </div>
        ))}
      </div>

      {/* Footnote — repeats the framing so users scrolling the list
          can never lose track of the fixture nature. */}
      <p className="text-[11px] text-caption text-center pt-1">
        Sample fixture only. Cost-basis values shown are illustrative
        historical prints, not current market prices.
      </p>
    </section>
  )
}
