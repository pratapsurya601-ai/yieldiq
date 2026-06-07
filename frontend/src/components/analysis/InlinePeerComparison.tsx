"use client"

/**
 * InlinePeerComparison — sortable peer table rendered on the analysis page.
 *
 * Competitor-walk gap #3 (2026-05-26): AlphaSpread / Tickertape / Screener
 * all surface a peer table inline on the analysis page. YieldIQ used to
 * route users to a separate /compare page via a "Compare ->" link, which
 * meant most visitors never saw the cross-sectional context. This panel
 * keeps the comparison in-place: top 5 cohort peers, sortable columns,
 * row-click to navigate to that ticker's analysis.
 *
 * Data: reuses the existing /api/v1/analysis/{ticker}/peers endpoint via
 * getPeers (same react-query key as SeeAlsoPeers, so the network call
 * is deduped). No backend change.
 *
 * SEBI: verdict labels go through verdictDisplayLabel which emits the
 * neutral set (Undervalued / Fairly Valued / Overvalued / Under Review /
 * Insufficient Data). No advisory vocabulary.
 */

import { useMemo, useState } from "react"
import { useRouter } from "next/navigation"
import { useQuery } from "@tanstack/react-query"
import { ChevronDown, ChevronUp } from "lucide-react"
import { getPeers, type PeerRow, type PeersResponse } from "@/lib/api"
import {
  cn,
  formatCurrency,
  formatPct,
  formatCompanyName,
  verdictDisplayLabel,
} from "@/lib/utils"
import { metricToneClass } from "@/lib/metricTone"
import TickerAvatar from "@/components/common/TickerAvatar"

interface Props {
  ticker: string
  currency: string
  /** Cap on rows rendered. Defaults to 6 (subject + 5 peers). */
  limit?: number
}

type SortKey =
  | "ticker"
  | "verdict"
  | "current_price"
  | "fair_value"
  | "mos_pct"
  | "pe_ratio"
  | "roe_pct"

type SortDir = "asc" | "desc"

interface SortState {
  key: SortKey
  dir: SortDir
}

interface DerivedRow extends PeerRow {
  derived_current_price: number | null
}

function displayTicker(t: string): string {
  return t.replace(".NS", "").replace(".BO", "")
}

/**
 * The /peers payload exposes fair_value + mos_pct but not current_price.
 * Recover price algebraically: price = FV / (1 + MoS/100). Same approach
 * SeeAlsoPeers uses — keeps both panels consistent without an API change.
 */
function deriveCurrentPrice(row: PeerRow): number | null {
  if (row.fair_value == null || row.mos_pct == null) return null
  if (!Number.isFinite(row.fair_value) || !Number.isFinite(row.mos_pct)) {
    return null
  }
  const denom = 1 + row.mos_pct / 100
  if (denom <= 0) return null
  return row.fair_value / denom
}

function mosToneClass(v: number | null): string {
  if (v == null || !Number.isFinite(v)) return "text-caption"
  if (v >= 10) return "text-success"
  if (v <= -10) return "text-danger"
  return "text-body"
}

function compareNullable(
  a: number | null | undefined,
  b: number | null | undefined,
  dir: SortDir,
): number {
  // Nulls always sink to the bottom regardless of direction, so the
  // header click never "loses" rows behind a stack of em-dashes.
  const aMissing = a == null || !Number.isFinite(a as number)
  const bMissing = b == null || !Number.isFinite(b as number)
  if (aMissing && bMissing) return 0
  if (aMissing) return 1
  if (bMissing) return -1
  const diff = (a as number) - (b as number)
  return dir === "asc" ? diff : -diff
}

function compareString(a: string, b: string, dir: SortDir): number {
  const diff = a.localeCompare(b)
  return dir === "asc" ? diff : -diff
}

function fmtRatio(v: number | null): string {
  if (v == null || !Number.isFinite(v)) return "—"
  return `${v.toFixed(1)}x`
}

function fmtPctValue(v: number | null): string {
  if (v == null || !Number.isFinite(v)) return "—"
  return `${v.toFixed(1)}%`
}

interface HeaderProps {
  label: string
  sortKey: SortKey
  align?: "left" | "right"
  sort: SortState
  onSort: (k: SortKey) => void
}

function SortHeader({ label, sortKey, align = "right", sort, onSort }: HeaderProps) {
  const active = sort.key === sortKey
  const Icon = sort.dir === "asc" ? ChevronUp : ChevronDown
  return (
    <th
      scope="col"
      aria-sort={active ? (sort.dir === "asc" ? "ascending" : "descending") : "none"}
      className={cn(
        "py-2 text-[10px] font-medium uppercase tracking-wide select-none",
        align === "left" ? "text-left pl-3 pr-2" : "text-right px-2",
        active ? "text-ink" : "text-caption",
      )}
    >
      <button
        type="button"
        onClick={() => onSort(sortKey)}
        className={cn(
          "inline-flex items-center gap-1 hover:text-ink transition-colors",
          align === "right" && "justify-end w-full",
        )}
      >
        <span>{label}</span>
        {active ? <Icon className="w-3 h-3" aria-hidden="true" /> : null}
      </button>
    </th>
  )
}

function EmptyState({ message }: { message: string }) {
  return (
    <section className="bg-bg rounded-2xl border border-border p-4">
      <h2 className="text-sm font-semibold text-ink mb-1">Peers in this cohort</h2>
      <p className="text-xs text-caption">{message}</p>
    </section>
  )
}

function LoadingSkeleton() {
  return (
    <section className="bg-bg rounded-2xl border border-border p-4">
      <div className="h-4 w-40 bg-surface rounded animate-pulse mb-3" />
      <div className="space-y-2">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="h-8 bg-surface rounded animate-pulse" />
        ))}
      </div>
    </section>
  )
}

export default function InlinePeerComparison({
  ticker,
  currency,
  limit = 6,
}: Props) {
  const router = useRouter()
  const [sort, setSort] = useState<SortState>({ key: "mos_pct", dir: "desc" })

  const { data, isLoading, isError } = useQuery<PeersResponse>({
    queryKey: ["peers", ticker],
    queryFn: () => getPeers(ticker),
    enabled: !!ticker,
    staleTime: 30 * 60 * 1000,
    retry: 1,
  })

  const upperTicker = ticker.toUpperCase()

  const derivedRows = useMemo<DerivedRow[]>(() => {
    if (!data?.peers) return []
    // Always include the subject row first so the highlight is anchored,
    // even if the backend forgot to mark it `is_main` on a cached payload.
    const subjectRow = data.peers.find(
      (p) => p.is_main || p.ticker.toUpperCase() === upperTicker,
    )
    const restRows = data.peers.filter(
      (p) => !p.is_main && p.ticker.toUpperCase() !== upperTicker,
    )
    const trimmed = [
      ...(subjectRow ? [subjectRow] : []),
      ...restRows.slice(0, Math.max(0, limit - (subjectRow ? 1 : 0))),
    ]
    return trimmed.map((r) => ({
      ...r,
      derived_current_price: deriveCurrentPrice(r),
    }))
  }, [data, upperTicker, limit])

  // Tickertape trick #4 (.audit/tickertape-deep-walk-2026-05-27.md): color
  // the P/E and ROE values per row against the *cohort* median surfaced in
  // this very table. Tickertape pairs each ratio with a "Sector PE" so the
  // implicit delta reads at a glance; we don't ship that secondary number
  // (yet) but we CAN do the comparison server-side-equivalent here by
  // taking the median across the visible peer rows.
  //
  // For ROE the helper is absolute (>=20 -> good, etc.), so no cohort
  // median is needed; for P/E the helper deliberately returns 'neutral'
  // without a sectorMedian to avoid a directional read on raw absolute
  // multiples (SEBI lens — see metricTone.ts).
  const cohortPeMedian = useMemo<number | null>(() => {
    const xs = derivedRows
      .map(r => r.pe_ratio)
      .filter((v): v is number => typeof v === "number" && Number.isFinite(v) && v > 0)
      .sort((a, b) => a - b)
    if (xs.length === 0) return null
    const mid = Math.floor(xs.length / 2)
    return xs.length % 2 ? xs[mid] : (xs[mid - 1] + xs[mid]) / 2
  }, [derivedRows])

  const sortedRows = useMemo<DerivedRow[]>(() => {
    if (derivedRows.length === 0) return derivedRows
    const rows = [...derivedRows]
    rows.sort((a, b) => {
      switch (sort.key) {
        case "ticker":
          return compareString(a.ticker, b.ticker, sort.dir)
        case "verdict":
          return compareString(
            verdictDisplayLabel(a.verdict ?? ""),
            verdictDisplayLabel(b.verdict ?? ""),
            sort.dir,
          )
        case "current_price":
          return compareNullable(
            a.derived_current_price,
            b.derived_current_price,
            sort.dir,
          )
        case "fair_value":
          return compareNullable(a.fair_value, b.fair_value, sort.dir)
        case "mos_pct":
          return compareNullable(a.mos_pct, b.mos_pct, sort.dir)
        case "pe_ratio":
          return compareNullable(a.pe_ratio, b.pe_ratio, sort.dir)
        case "roe_pct":
          return compareNullable(a.roe_pct, b.roe_pct, sort.dir)
        default:
          return 0
      }
    })
    return rows
  }, [derivedRows, sort])

  const handleSort = (key: SortKey) => {
    setSort((prev) => {
      if (prev.key !== key) {
        // Numeric columns default to descending (highest first), text
        // columns default to ascending — matches the affordance of the
        // sector cohort table.
        const numericDefault: SortDir =
          key === "ticker" || key === "verdict" ? "asc" : "desc"
        return { key, dir: numericDefault }
      }
      return { key, dir: prev.dir === "asc" ? "desc" : "asc" }
    })
  }

  const handleRowActivate = (row: DerivedRow) => {
    if (row.ticker.toUpperCase() === upperTicker) return
    router.push(`/analysis/${row.ticker}`)
  }

  if (isLoading) return <LoadingSkeleton />

  if (isError || !data) {
    return <EmptyState message="Cohort peers unavailable for this stock." />
  }

  const hasPeers = data.has_peers ?? (data.peers?.length ?? 0) > 0
  if (!hasPeers || derivedRows.length <= 1) {
    return (
      <EmptyState
        message={
          data.message ?? "Cohort peers unavailable for this stock."
        }
      />
    )
  }

  return (
    <section
      className="bg-bg rounded-2xl border border-border p-4"
      aria-labelledby="inline-peer-comparison-heading"
    >
      <div className="flex items-baseline justify-between gap-2 flex-wrap mb-3">
        <h2
          id="inline-peer-comparison-heading"
          className="text-sm font-semibold text-ink"
        >
          Peers in this cohort
        </h2>
        {data.sector_label ? (
          <p className="text-[11px] text-caption">{data.sector_label}</p>
        ) : null}
      </div>

      {/* Mobile: stacked cards. Tablet+: sortable table. Avoids a
          horizontal-scroll table on phones (a11y + thumb-reach win). */}
      <div className="sm:hidden space-y-2">
        {sortedRows.map((row) => {
          const isSubject = row.ticker.toUpperCase() === upperTicker
          return (
            <button
              key={row.ticker}
              type="button"
              onClick={() => handleRowActivate(row)}
              disabled={isSubject}
              className={cn(
                "w-full text-left rounded-xl border p-3 transition-colors",
                isSubject
                  ? "border-brand bg-brand-50/40 cursor-default"
                  : "border-border bg-bg hover:border-brand hover:bg-surface",
              )}
            >
              <div className="flex items-baseline justify-between gap-2 mb-1">
                <span className="flex items-center gap-1.5 min-w-0">
                  <TickerAvatar ticker={row.ticker} size="sm" />
                  <span className="font-display text-sm font-semibold text-ink">
                    {displayTicker(row.ticker)}
                    {isSubject ? (
                      <span className="ml-2 text-[10px] uppercase tracking-wide text-brand">
                        This stock
                      </span>
                    ) : null}
                  </span>
                </span>
                <span className={cn("text-xs font-mono tabular-nums", mosToneClass(row.mos_pct))}>
                  {row.mos_pct != null && Number.isFinite(row.mos_pct)
                    ? formatPct(row.mos_pct)
                    : "—"}
                </span>
              </div>
              <p className="text-[11px] text-caption truncate mb-2">
                {formatCompanyName(row.company_name)}
              </p>
              <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-[11px]">
                <div className="flex justify-between">
                  <dt className="text-caption">Price</dt>
                  <dd className="font-mono tabular-nums text-body">
                    {row.derived_current_price != null
                      ? formatCurrency(row.derived_current_price, currency, row.ticker)
                      : "—"}
                  </dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-caption">Fair Value</dt>
                  <dd className="font-mono tabular-nums text-body">
                    {row.fair_value != null
                      ? formatCurrency(row.fair_value, currency, row.ticker)
                      : "—"}
                  </dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-caption">P/E</dt>
                  <dd
                    className={cn(
                      "font-mono tabular-nums",
                      metricToneClass({
                        metric: "pe",
                        value: row.pe_ratio,
                        sectorMedian: cohortPeMedian,
                      }),
                    )}
                  >
                    {fmtRatio(row.pe_ratio)}
                  </dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-caption">ROE</dt>
                  <dd
                    className={cn(
                      "font-mono tabular-nums",
                      metricToneClass({ metric: "roe", value: row.roe_pct }),
                    )}
                  >
                    {fmtPctValue(row.roe_pct)}
                  </dd>
                </div>
              </dl>
              <p className="mt-2 text-[10px] text-caption">
                {verdictDisplayLabel(row.verdict ?? "") || "Under Review"}
              </p>
            </button>
          )
        })}
      </div>

      <div className="hidden sm:block overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-border">
              <SortHeader label="Ticker" sortKey="ticker" align="left" sort={sort} onSort={handleSort} />
              <SortHeader label="Verdict" sortKey="verdict" align="left" sort={sort} onSort={handleSort} />
              <SortHeader label="Price" sortKey="current_price" sort={sort} onSort={handleSort} />
              <SortHeader label="Fair Value" sortKey="fair_value" sort={sort} onSort={handleSort} />
              <SortHeader label="Discount to FV" sortKey="mos_pct" sort={sort} onSort={handleSort} />
              <SortHeader label="P/E" sortKey="pe_ratio" sort={sort} onSort={handleSort} />
              <SortHeader label="ROE" sortKey="roe_pct" sort={sort} onSort={handleSort} />
            </tr>
          </thead>
          <tbody>
            {sortedRows.map((row) => {
              const isSubject = row.ticker.toUpperCase() === upperTicker
              return (
                <tr
                  key={row.ticker}
                  onMouseEnter={() => {
                    if (!isSubject) router.prefetch(`/analysis/${row.ticker}`)
                  }}
                  onClick={() => handleRowActivate(row)}
                  className={cn(
                    "border-b border-border last:border-0 transition-colors",
                    isSubject
                      ? "bg-brand-50/60 border-l-4 border-l-brand"
                      : "cursor-pointer hover:bg-surface",
                  )}
                >
                  <td className="py-2 pl-3 pr-2">
                    <div className="flex items-center gap-2">
                      <TickerAvatar ticker={row.ticker} size="sm" />
                      <div className="flex flex-col min-w-0">
                        <span className="font-display text-xs font-semibold text-ink">
                          {displayTicker(row.ticker)}
                          {isSubject ? (
                            <span className="ml-2 text-[9px] uppercase tracking-wide text-brand">
                              This stock
                            </span>
                          ) : null}
                        </span>
                        <span className="text-[10px] text-caption truncate max-w-[180px]">
                          {formatCompanyName(row.company_name)}
                        </span>
                      </div>
                    </div>
                  </td>
                  <td className="py-2 px-2 text-[11px] text-body">
                    {verdictDisplayLabel(row.verdict ?? "") || "Under Review"}
                  </td>
                  <td className="py-2 px-2 text-right font-mono tabular-nums text-body">
                    {row.derived_current_price != null
                      ? formatCurrency(row.derived_current_price, currency, row.ticker)
                      : "—"}
                  </td>
                  <td className="py-2 px-2 text-right font-mono tabular-nums text-body">
                    {row.fair_value != null
                      ? formatCurrency(row.fair_value, currency, row.ticker)
                      : "—"}
                  </td>
                  <td
                    className={cn(
                      "py-2 px-2 text-right font-mono tabular-nums font-medium",
                      mosToneClass(row.mos_pct),
                    )}
                  >
                    {row.mos_pct != null && Number.isFinite(row.mos_pct)
                      ? formatPct(row.mos_pct)
                      : "—"}
                  </td>
                  <td
                    className={cn(
                      "py-2 px-2 text-right font-mono tabular-nums",
                      metricToneClass({
                        metric: "pe",
                        value: row.pe_ratio,
                        sectorMedian: cohortPeMedian,
                      }),
                    )}
                  >
                    {fmtRatio(row.pe_ratio)}
                  </td>
                  <td
                    className={cn(
                      "py-2 px-2 text-right font-mono tabular-nums",
                      metricToneClass({ metric: "roe", value: row.roe_pct }),
                    )}
                  >
                    {fmtPctValue(row.roe_pct)}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      <p className="mt-3 text-[10px] text-caption">
        Click a peer row to open its analysis. Current price is derived from
        fair value and discount-to-FV on the cohort snapshot.
      </p>
    </section>
  )
}
