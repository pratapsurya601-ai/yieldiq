/**
 * FundScreenerTable — the sortable research table at the heart of the
 * /funds screener, plus its <640px stacked-card fallback.
 *
 * Presentational only: all filter/sort/page STATE lives in the parent
 * <FundScreener>. This component renders the rows it is handed and emits
 * sort-toggle intents back up via `onSort`. Two layouts share one data
 * set:
 *
 *   • ≥640px — a real <table> with a sticky <thead>, sortable column
 *     headers (th[aria-sort]), right-aligned tabular numerics, and a
 *     subtle row hover. Restrained Morningstar cleanliness.
 *   • <640px — stacked fund cards (logo + name, category, a compact
 *     1Y/3Y/5Y row, score, risk) so the table never overflows the
 *     viewport horizontally.
 *
 * Returns are ANNUALIZED for the multi-year windows (global-research
 * convention) via lib/fund-annualize — the API ships CUMULATIVE fractions.
 * No advisory copy: columns/score/sort are factual, descriptive markers.
 */
"use client"

import Link from "next/link"

import type { FundListItem, FundListSort, FundSortOrder } from "@/types/api"
import AmcAvatar from "@/components/common/AmcAvatar"
import { RISKOMETER_TONE } from "@/lib/fund-riskometer"
import {
  formatTrailingReturn,
  RETURN_WINDOW_YEARS,
} from "@/lib/fund-annualize"
import {
  compactCategory,
  fmtTerPct,
  normalizeFundName,
  scoreTint,
} from "./FundCard"

// ── Column model ─────────────────────────────────────────────────────
// Each sortable numeric column maps to a FundListSort key. `name` and
// `score` sort too. The 10Y column is conditional (see needsTenYear).
type NumericWindow = "ret_1y" | "ret_3y" | "ret_5y" | "ret_10y"

interface ReturnCol {
  key: NumericWindow
  sort: FundListSort
  label: string
  years: number
}

const RETURN_COLS: ReturnCol[] = [
  { key: "ret_1y", sort: "ret_1y", label: "1Y", years: RETURN_WINDOW_YEARS.ret_1y },
  { key: "ret_3y", sort: "ret_3y", label: "3Y", years: RETURN_WINDOW_YEARS.ret_3y },
  { key: "ret_5y", sort: "ret_5y", label: "5Y", years: RETURN_WINDOW_YEARS.ret_5y },
  { key: "ret_10y", sort: "ret_10y", label: "10Y", years: RETURN_WINDOW_YEARS.ret_10y },
]

export interface FundScreenerTableProps {
  funds: FundListItem[]
  sort: FundListSort
  order: FundSortOrder
  /** Toggle/select a sort key. Same key flips order; new key starts desc
   *  (asc for name). */
  onSort: (key: FundListSort) => void
  /** Show the 10Y column only when at least one row carries ret_10y. */
  showTenYear: boolean
}

// aria-sort value for a header cell given the active sort state.
function ariaSortFor(
  col: FundListSort,
  active: FundListSort,
  order: FundSortOrder,
): "ascending" | "descending" | "none" {
  if (col !== active) return "none"
  return order === "asc" ? "ascending" : "descending"
}

// Direction caret. Inactive columns show a faint neutral chevron so the
// header still reads as sortable; the active one shows the live arrow.
function SortCaret({ state }: { state: "asc" | "desc" | "none" }) {
  if (state === "none") {
    return (
      <span aria-hidden="true" className="ml-1 inline-block text-caption/40">
        ▾
      </span>
    )
  }
  return (
    <span aria-hidden="true" className="ml-1 inline-block text-ink">
      {state === "asc" ? "▲" : "▾"}
    </span>
  )
}

function caretState(
  col: FundListSort,
  active: FundListSort,
  order: FundSortOrder,
): "asc" | "desc" | "none" {
  if (col !== active) return "none"
  return order
}

// A sortable header button. Keyboard-accessible (real <button>), updates
// aria-sort on the parent <th>.
function SortHeader({
  label,
  col,
  active,
  order,
  onSort,
  align = "right",
}: {
  label: string
  col: FundListSort
  active: FundListSort
  order: FundSortOrder
  onSort: (key: FundListSort) => void
  align?: "left" | "right"
}) {
  return (
    <button
      type="button"
      onClick={() => onSort(col)}
      className={`group inline-flex w-full items-center gap-0.5 text-[11px] font-semibold uppercase tracking-wide text-caption transition-colors hover:text-ink ${
        align === "right" ? "justify-end" : "justify-start"
      }`}
    >
      <span>{label}</span>
      <SortCaret state={caretState(col, active, order)} />
    </button>
  )
}

// One return cell — annualized + colour-coded, or an em dash.
function ReturnCell({
  value,
  years,
}: {
  value: number | null | undefined
  years: number
}) {
  const text = formatTrailingReturn(value, years)
  if (text === "—") {
    return <span className="text-caption">—</span>
  }
  const positive = text.startsWith("+")
  const negative = text.startsWith("−")
  return (
    <span
      className={
        positive ? "text-success" : negative ? "text-danger" : "text-body"
      }
    >
      {text}
    </span>
  )
}

function RiskChip({ fund }: { fund: FundListItem }) {
  const risk = fund.riskometer_level ? RISKOMETER_TONE[fund.riskometer_level] : null
  if (!risk) return <span className="text-caption">—</span>
  return (
    <span
      className={`inline-block rounded-full ${risk.cls} px-2 py-0.5 text-[11px] font-medium`}
    >
      {risk.label}
    </span>
  )
}

// ── Desktop table ────────────────────────────────────────────────────
function DesktopTable({ funds, sort, order, onSort, showTenYear }: FundScreenerTableProps) {
  const cols = showTenYear ? RETURN_COLS : RETURN_COLS.filter((c) => c.key !== "ret_10y")
  return (
    <div className="hidden overflow-x-auto rounded-lg border border-border sm:block">
      <table className="w-full border-collapse text-sm">
        <caption className="sr-only">
          Mutual fund schemes with annualized trailing returns, YieldIQ
          Score, expense ratio and SEBI Riskometer band. Multi-year returns
          are annualized (per annum).
        </caption>
        <thead className="sticky top-0 z-10 bg-surface">
          <tr className="border-b border-border">
            <th
              scope="col"
              aria-sort={ariaSortFor("name", sort, order)}
              className="px-3 py-2.5 text-left"
            >
              <SortHeader
                label="Fund"
                col="name"
                active={sort}
                order={order}
                onSort={onSort}
                align="left"
              />
            </th>
            <th
              scope="col"
              className="px-3 py-2.5 text-left text-[11px] font-semibold uppercase tracking-wide text-caption"
            >
              Category
            </th>
            {cols.map((c) => (
              <th
                key={c.key}
                scope="col"
                aria-sort={ariaSortFor(c.sort, sort, order)}
                className="px-3 py-2.5 text-right"
                title="Annualized (per annum)"
              >
                <SortHeader
                  label={c.label}
                  col={c.sort}
                  active={sort}
                  order={order}
                  onSort={onSort}
                />
              </th>
            ))}
            <th
              scope="col"
              aria-sort={ariaSortFor("score", sort, order)}
              className="px-3 py-2.5 text-right"
            >
              <SortHeader
                label="YieldIQ Score"
                col="score"
                active={sort}
                order={order}
                onSort={onSort}
              />
            </th>
            <th
              scope="col"
              aria-sort={ariaSortFor("ter", sort, order)}
              className="px-3 py-2.5 text-right"
            >
              <SortHeader
                label="Expense"
                col="ter"
                active={sort}
                order={order}
                onSort={onSort}
              />
            </th>
            <th
              scope="col"
              className="px-3 py-2.5 text-left text-[11px] font-semibold uppercase tracking-wide text-caption"
            >
              Risk
            </th>
          </tr>
        </thead>
        <tbody>
          {funds.map((fund) => {
            const name = normalizeFundName(fund.scheme_name)
            const category = compactCategory(fund.category)
            const score =
              typeof fund.yieldiq_fund_score === "number" ? fund.yieldiq_fund_score : null
            const terLabel =
              typeof fund.ter_direct === "number" ? fmtTerPct(fund.ter_direct) : null
            return (
              <tr
                key={fund.scheme_code}
                className="border-b border-border/60 transition-colors last:border-0 hover:bg-raised"
              >
                <th scope="row" className="px-3 py-2.5 text-left font-normal">
                  <Link
                    href={`/funds/${encodeURIComponent(fund.scheme_code)}`}
                    className="flex items-center gap-2.5 rounded outline-none focus-visible:ring-2 focus-visible:ring-tone-info-fg"
                  >
                    <AmcAvatar amc={fund.amc} size="sm" />
                    <span className="min-w-0">
                      <span className="block truncate font-medium text-ink hover:underline">
                        {name}
                      </span>
                      <span className="block truncate text-xs text-caption">{fund.amc}</span>
                    </span>
                  </Link>
                </th>
                <td className="px-3 py-2.5 text-left">
                  {category ? (
                    <span className="inline-block rounded-full bg-tone-info-bg px-2 py-0.5 text-[11px] font-medium text-tone-info-fg">
                      {category}
                    </span>
                  ) : (
                    <span className="text-caption">—</span>
                  )}
                </td>
                {cols.map((c) => (
                  <td key={c.key} className="num px-3 py-2.5 text-right font-medium">
                    <ReturnCell value={fund[c.key]} years={c.years} />
                  </td>
                ))}
                <td className="num px-3 py-2.5 text-right">
                  {score !== null ? (
                    <span
                      className={`inline-block rounded-full px-2 py-0.5 text-[11px] font-semibold ${scoreTint(score)}`}
                      title="YieldIQ Fund Score (0-100)"
                    >
                      {score}
                    </span>
                  ) : (
                    <span className="text-caption">—</span>
                  )}
                </td>
                <td className="num px-3 py-2.5 text-right font-medium text-body">
                  {terLabel ?? <span className="text-caption">—</span>}
                </td>
                <td className="px-3 py-2.5 text-left">
                  <RiskChip fund={fund} />
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

// ── Mobile stacked cards ─────────────────────────────────────────────
function MobileCards({ funds, showTenYear }: { funds: FundListItem[]; showTenYear: boolean }) {
  const cols = showTenYear ? RETURN_COLS : RETURN_COLS.filter((c) => c.key !== "ret_10y")
  return (
    <ul className="space-y-2 sm:hidden" aria-label="Fund results">
      {funds.map((fund) => {
        const name = normalizeFundName(fund.scheme_name)
        const category = compactCategory(fund.category)
        const score =
          typeof fund.yieldiq_fund_score === "number" ? fund.yieldiq_fund_score : null
        return (
          <li key={fund.scheme_code}>
            <Link
              href={`/funds/${encodeURIComponent(fund.scheme_code)}`}
              className="flex flex-col gap-2 rounded-lg border border-border bg-raised p-3 outline-none focus-visible:ring-2 focus-visible:ring-tone-info-fg"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="flex min-w-0 items-center gap-2">
                  <AmcAvatar amc={fund.amc} size="sm" />
                  <div className="min-w-0">
                    <div className="line-clamp-2 text-sm font-semibold leading-snug text-ink">
                      {name}
                    </div>
                    <div className="truncate text-xs text-caption">{fund.amc}</div>
                  </div>
                </div>
                {score !== null ? (
                  <span
                    className={`num shrink-0 rounded-full px-2 py-0.5 text-[11px] font-semibold ${scoreTint(score)}`}
                    title="YieldIQ Fund Score (0-100)"
                  >
                    {score}
                  </span>
                ) : null}
              </div>
              <div className="flex flex-wrap items-center gap-1.5">
                {category ? (
                  <span className="rounded-full bg-tone-info-bg px-2 py-0.5 text-[11px] font-medium text-tone-info-fg">
                    {category}
                  </span>
                ) : null}
                <RiskChip fund={fund} />
              </div>
              <div className="grid grid-cols-3 gap-2 border-t border-border/60 pt-2">
                {cols.map((c) => (
                  <div key={c.key} className="flex flex-col">
                    <span className="text-[10px] uppercase tracking-wide text-caption">
                      {c.label} p.a.
                    </span>
                    <span className="num text-sm font-semibold">
                      <ReturnCell value={fund[c.key]} years={c.years} />
                    </span>
                  </div>
                ))}
              </div>
            </Link>
          </li>
        )
      })}
    </ul>
  )
}

export default function FundScreenerTable(props: FundScreenerTableProps) {
  return (
    <>
      <DesktopTable {...props} />
      <MobileCards funds={props.funds} showTenYear={props.showTenYear} />
    </>
  )
}
