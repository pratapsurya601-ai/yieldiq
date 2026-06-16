/**
 * PortfolioTab — the Portfolio section of the fund Asset Page.
 *
 * Server-renderable (no client hooks). Consumes the optional `portfolio`
 * block from the detail payload. While SEBI monthly disclosures are not
 * yet ingested the backend ships `{ updating: true, holdings_count: 0,
 * holdings: [] }`, which renders a clean "refreshing" empty state — NOT
 * a fake placeholder. Once real holdings land it shows:
 *   - asset / sector / market-cap allocation bars, and
 *   - the full holdings table (instrument, weight, sector, mcap, 3m Δ).
 *
 * Defensive: every field is optional-chained; a missing sub-block simply
 * hides its card.
 */
import type {
  FundAllocationSlice,
  FundPortfolioBlock,
} from "@/types/api"

import TabEmptyState from "./TabEmptyState"
import { DASH, pct, present, signTone } from "./fund-format"

function hasHoldings(p: FundPortfolioBlock | null | undefined): boolean {
  return !!p && Array.isArray(p.holdings) && p.holdings.length > 0
}

function AllocationBars({
  heading,
  slices,
}: {
  heading: string
  slices: FundAllocationSlice[] | null | undefined
}) {
  const rows = (slices ?? []).filter((s) => present(s.weight_pct))
  if (rows.length === 0) return null
  const max = Math.max(...rows.map((s) => s.weight_pct as number), 1)
  return (
    <section className="rounded-lg border border-border bg-raised p-4">
      <h3 className="mb-3 text-base font-semibold text-ink">{heading}</h3>
      <div className="space-y-2">
        {rows.map((s, i) => (
          <div key={`${s.label}-${i}`} className="flex items-center gap-3">
            <div className="w-28 shrink-0 truncate text-[12px] text-body">
              {s.label || DASH}
            </div>
            <div className="relative h-5 flex-1 overflow-hidden rounded-md bg-surface">
              <div
                className="h-full rounded-md bg-brand"
                style={{
                  width: `${Math.max(2, ((s.weight_pct as number) / max) * 100).toFixed(1)}%`,
                }}
              />
            </div>
            <div className="num w-14 shrink-0 text-right text-[12.5px] font-medium text-ink">
              {pct(s.weight_pct)}
            </div>
          </div>
        ))}
      </div>
    </section>
  )
}

export default function PortfolioTab({
  portfolio,
  asOfMonth,
}: {
  portfolio?: FundPortfolioBlock | null
  asOfMonth?: string | null
}) {
  // Updating, or no holdings yet → honest refreshing state.
  if (!portfolio || portfolio.updating || !hasHoldings(portfolio)) {
    return (
      <TabEmptyState
        title="Portfolio holdings are refreshing"
        message="Holdings update monthly from SEBI disclosures — refreshing."
      />
    )
  }

  const holdings = portfolio.holdings ?? []
  const asOf = portfolio.as_of_month ?? asOfMonth ?? null

  return (
    <div className="grid gap-6">
      {asOf ? (
        <p className="text-xs text-caption">
          Holdings as of {asOf}
          {present(portfolio.holdings_count)
            ? ` · ${portfolio.holdings_count} instruments`
            : ""}
          .
        </p>
      ) : null}

      {/* Allocation bars */}
      <div className="grid gap-6 lg:grid-cols-3">
        <AllocationBars heading="Asset allocation" slices={portfolio.asset_allocation} />
        <AllocationBars heading="Sector allocation" slices={portfolio.sector_allocation} />
        <AllocationBars heading="Market-cap allocation" slices={portfolio.mcap_allocation} />
      </div>

      {/* Holdings table */}
      <section className="rounded-lg border border-border bg-raised p-4">
        <h3 className="mb-3 text-base font-semibold text-ink">Top holdings</h3>
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-caption">
                <th className="py-2 pr-4 font-medium">Instrument</th>
                <th className="py-2 pr-4 font-medium">Sector</th>
                <th className="py-2 pr-4 font-medium">Mkt cap</th>
                <th className="py-2 pr-4 text-right font-medium">Weight</th>
                <th className="py-2 pr-4 text-right font-medium">3M Δ</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {holdings.map((h, i) => (
                <tr key={h.isin || `${h.instrument}-${i}`}>
                  <td className="py-2 pr-4 font-medium text-ink">
                    {h.instrument || DASH}
                  </td>
                  <td className="py-2 pr-4 text-body">{h.sector || DASH}</td>
                  <td className="py-2 pr-4 text-body">{h.mcap_bucket || DASH}</td>
                  <td className="num py-2 pr-4 text-right tabular-nums text-ink">
                    {pct(h.weight_pct)}
                  </td>
                  <td
                    className={`num py-2 pr-4 text-right tabular-nums ${signTone(h.change_3m_pct)}`}
                  >
                    {present(h.change_3m_pct)
                      ? `${h.change_3m_pct >= 0 ? "+" : ""}${pct(h.change_3m_pct)}`
                      : DASH}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-3 text-xs text-caption">
          Holdings are sourced from the scheme&apos;s monthly SEBI portfolio
          disclosure and may lag the live portfolio.
        </p>
      </section>
    </div>
  )
}
