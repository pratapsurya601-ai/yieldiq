"use client"

/**
 * CashflowStalenessBadge
 * ----------------------
 * Surfaces the freshness of TTM Free Cash Flow data based on the
 * backend's `fcf_ttm_basis` signal (carried inside `fcf_data_source`
 * as `ttm+nse_xbrl_cf_{basis}`).
 *
 * Why this exists
 * ---------------
 * SEBI only requires listed Indian companies to file a Cash Flow
 * Statement for the half-year (Sep) and full-year (Mar) windows.
 * In Q1 / Q3 windows, the most recent CFS is up to ~6 months old,
 * but the TTM revenue / PAT are fresh from quarterly XBRL filings.
 *
 * We deliberately DO NOT invent CFO from revenue ratios. Instead we
 * tell the user honestly when the cashflow side of the model is
 * lagging the income-statement side.
 *
 * Mapping (input → label / tone)
 *   "fy_q4"              → no badge (full FY, 12-month YTD)
 *   "h1_plus_prev_h2"    → neutral badge with explanatory tooltip
 *                          (data is stitched but current)
 *   "fy_q4_stale"        → AMBER badge "Cashflow data from FY-end (Mar)"
 *   "older_than_6mo"     → AMBER badge "Cashflow data >6 months old"
 *   anything else / null → no badge (back-compat / cached payloads)
 *
 * Aliases accepted for forward-compat with possible backend renames:
 *   "fresh", "latest_q_cfs"  → no badge
 *   "h1_stitched"            → treated like h1_plus_prev_h2
 */

import type { ReactElement } from "react"

export type CashflowBasis =
  | "fresh"
  | "latest_q_cfs"
  | "fy_q4"
  | "h1_stitched"
  | "h1_plus_prev_h2"
  | "fy_q4_stale"
  | "older_than_6mo"
  | string

interface CashflowStalenessBadgeProps {
  basis?: string | null
  /**
   * When provided, the badge will parse `fcf_data_source` strings of
   * the form "ttm+nse_xbrl_cf_{basis}" and "{basis}". If both `basis`
   * and `dataSource` are provided, `basis` wins.
   */
  dataSource?: string | null
  className?: string
}

const TOOLTIP_SEBI =
  "SEBI only requires Indian companies to file Cash Flow Statements " +
  "for H1 (Sep) and Q4 (Mar). In Q1 / Q3 windows, cashflow data lags " +
  "income-statement data by up to ~6 months."

interface BadgeSpec {
  label: string
  tone: "amber" | "neutral"
  tooltip: string
}

/** Extract the bare basis token from either form. */
export function parseCashflowBasis(
  basis?: string | null,
  dataSource?: string | null,
): string | null {
  if (basis && basis.length > 0) return basis
  if (!dataSource) return null
  // Form: "ttm+nse_xbrl_cf_{basis}" → pull the suffix.
  const marker = "nse_xbrl_cf_"
  const i = dataSource.indexOf(marker)
  if (i >= 0) return dataSource.slice(i + marker.length) || null
  return null
}

/** Resolve a basis token to the badge spec (or null for no badge). */
export function resolveBadgeSpec(basis: string | null): BadgeSpec | null {
  if (!basis) return null
  switch (basis) {
    case "fresh":
    case "latest_q_cfs":
    case "fy_q4":
      return null
    case "h1_stitched":
    case "h1_plus_prev_h2":
      return {
        label: "Cashflow stitched (H1 + prev Q4)",
        tone: "neutral",
        tooltip:
          "Cashflow stitched from latest H1 + Q4. Updated Sep/Mar per SEBI.",
      }
    case "fy_q4_stale":
      return {
        label: "Cashflow data from FY-end (Mar)",
        tone: "amber",
        tooltip: TOOLTIP_SEBI,
      }
    case "older_than_6mo":
      return {
        label: "Cashflow data >6 months old",
        tone: "amber",
        tooltip: TOOLTIP_SEBI,
      }
    default:
      return null
  }
}

export default function CashflowStalenessBadge({
  basis,
  dataSource,
  className,
}: CashflowStalenessBadgeProps): ReactElement | null {
  const token = parseCashflowBasis(basis, dataSource)
  const spec = resolveBadgeSpec(token)
  if (!spec) return null

  const tone =
    spec.tone === "amber"
      ? "bg-tone-warn-bg text-amber-800 border-tone-warn-bd"
      : "bg-gray-50 text-gray-700 border-gray-200"

  return (
    <span
      data-testid="cashflow-staleness-badge"
      data-basis={token ?? ""}
      data-tone={spec.tone}
      title={spec.tooltip}
      aria-label={`${spec.label}. ${spec.tooltip}`}
      className={
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 " +
        "text-[10px] font-medium leading-none align-middle " +
        tone +
        (className ? " " + className : "")
      }
    >
      {spec.label}
    </span>
  )
}
