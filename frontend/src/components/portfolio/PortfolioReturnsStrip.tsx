"use client"
/**
 * Portfolio return-decomposition strip (P0 #5 Feature C, 2026-05-25).
 *
 * Five cards that decompose total portfolio return into its drivers.
 * This is the SCAFFOLD pass — only Unrealized Returns is wired to
 * the existing /holdings-live summary today. The other four cards
 * render LIMITED DATA chips and are gated behind backend services
 * that don't yet exist:
 *
 *   - Realized Returns        → needs closed-positions ledger
 *   - Dividends Received      → needs corp_actions × holdings join
 *   - Currency Impact         → needs FX exposure (INR-only today)
 *   - Forward Dividends       → needs dividend forecast service
 *
 * Shipping the strip as a skeleton today (instead of building all
 * four backends in one mega-PR) follows the "don't build long jobs
 * in a router" discipline in CLAUDE.md and the project's
 * "no broker sync, no SE Asia" cut-list. The cards become
 * progressively populated as each backend lands. The contract /
 * placement is locked in now so subsequent PRs are diffs not adds.
 */
import { useQuery } from "@tanstack/react-query"
import { getHoldingsLive } from "@/lib/api"

function fmtRsCompact(n: number): string {
  const abs = Math.abs(n)
  const sign = n < 0 ? "-" : ""
  if (abs >= 10_000_000) return `${sign}₹${(abs / 10_000_000).toFixed(2)}Cr`
  if (abs >= 100_000) return `${sign}₹${(abs / 100_000).toFixed(2)}L`
  if (abs >= 1_000) return `${sign}₹${(abs / 1_000).toFixed(1)}K`
  return `${sign}₹${abs.toFixed(0)}`
}

interface CardProps {
  label: string
  tooltip: string
  primary: string
  secondary?: string | null
  primaryClass?: string
  limited?: boolean
  testid?: string
}

function ReturnCard({
  label,
  tooltip,
  primary,
  secondary,
  primaryClass = "text-ink",
  limited,
  testid,
}: CardProps) {
  return (
    <div
      data-testid={testid}
      className="flex-1 min-w-[140px] bg-bg dark:bg-surface rounded-xl border border-border p-3"
    >
      <div className="flex items-center gap-1 mb-1">
        <p className="text-[10px] font-bold uppercase tracking-wider text-caption">
          {label}
        </p>
        <span
          className="text-caption text-[10px] cursor-help"
          title={tooltip}
          aria-label={tooltip}
        >
          (i)
        </span>
      </div>
      <p className={`text-base font-bold font-mono ${primaryClass}`}>{primary}</p>
      {limited ? (
        <span className="mt-1 inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold ring-1 bg-amber-50 text-amber-700 ring-amber-200">
          LIMITED DATA
        </span>
      ) : secondary ? (
        <p className="text-[11px] text-caption mt-1">{secondary}</p>
      ) : null}
    </div>
  )
}

export default function PortfolioReturnsStrip() {
  const { data, isLoading } = useQuery({
    queryKey: ["holdings-live"],
    queryFn: getHoldingsLive,
    retry: 1,
  })

  if (isLoading) {
    return (
      <div
        aria-busy="true"
        aria-label="Loading returns strip"
        className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-2"
      >
        {[0, 1, 2, 3, 4].map(i => (
          <div key={i} className="skeleton h-[88px] rounded-xl" />
        ))}
      </div>
    )
  }

  const summary = data?.summary
  if (!summary || summary.count === 0) return null

  const unrealizedAbs = summary.total_pnl_abs ?? 0
  const unrealizedPct = summary.total_pnl_pct ?? 0
  const unrealizedClass =
    unrealizedAbs > 0 ? "text-green-600" : unrealizedAbs < 0 ? "text-red-600" : "text-ink"

  return (
    <section
      aria-label="Portfolio return decomposition"
      data-testid="returns-strip"
      className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-2"
    >
      <ReturnCard
        testid="returns-unrealized"
        label="Unrealized"
        tooltip="Mark-to-market gain or loss on currently held positions."
        primary={`${unrealizedAbs >= 0 ? "+" : ""}${fmtRsCompact(unrealizedAbs)}`}
        secondary={`${unrealizedPct >= 0 ? "+" : ""}${unrealizedPct.toFixed(2)}%`}
        primaryClass={unrealizedClass}
      />
      <ReturnCard
        testid="returns-realized"
        label="Realized"
        tooltip="Cumulative gain or loss from closed positions this FY."
        primary="—"
        limited
      />
      <ReturnCard
        testid="returns-dividends"
        label="Dividends Received"
        tooltip="Cash dividends paid into your portfolio (financial year to date)."
        primary="—"
        limited
      />
      <ReturnCard
        testid="returns-fx"
        label="Currency Impact"
        tooltip="Gain or loss from FX moves on non-INR holdings."
        primary="—"
        limited
      />
      <ReturnCard
        testid="returns-forward-div"
        label="Forward Dividends (12m)"
        tooltip="Projected dividend income over the next 12 months based on declared payouts."
        primary="—"
        limited
      />
    </section>
  )
}
