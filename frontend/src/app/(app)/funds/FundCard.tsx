/**
 * FundCard — a single rich card in the /funds browse grid.
 *
 * The old card showed only AMC + raw AMFI scheme name + a couple of
 * chips, so a user had to click into every fund to learn anything. The
 * list endpoint now LEFT-JOINs three metrics per scheme (`ret_1y`,
 * `yieldiq_fund_score`, `ter` — all nullable; see the SHARED CONTRACT
 * in models/fund.py:FundListItem), so the card can lead with real
 * numbers: the YieldIQ Fund Score as a chip, 1-year return (green/red),
 * the expense ratio, and the SEBI Riskometer band.
 *
 * Two presentation helpers also live here and are reused by page.tsx:
 *   - normalizeFundName(): strips the noisy " - Direct Plan - Growth/
 *     IDCW" plan/option suffix and Title-Cases the ALL-CAPS AMFI name.
 *   - compactCategory(): collapses the verbose AMFI category label
 *     ("Equity Scheme - Large Cap Fund") to its short tail
 *     ("Large Cap Fund").
 *
 * No advisory copy — only AMC-published facts and the SEBI Riskometer.
 */
import Link from "next/link"

import type { FundListItem, FundRiskometerLevel } from "@/types/api"
import AmcAvatar from "@/components/common/AmcAvatar"
import { HoverCard } from "@/components/motion"

// ── Contract shape ──────────────────────────────────────────────────
// The base `FundListItem` type in types/api.ts has not yet grown the
// three LEFT-JOINed metric fields, but the backend FundListItem model
// already returns them (nullable). We widen locally so the cards can
// consume them today without touching the shared type file. When the
// shared type catches up these become redundant (assignable) — no
// breakage either way.
export interface FundCardItem extends FundListItem {
  /** Trailing 1-year return, percent. Null when no returns cache row. */
  ret_1y?: number | null
  /** YieldIQ Fund Score (0-100). Null when not yet computed. */
  yieldiq_fund_score?: number | null
  /** Expense ratio, percent — prefers Direct (ter_direct). */
  ter?: number | null
}

const RISKOMETER_COLORS: Record<
  FundRiskometerLevel,
  { bg: string; text: string; label: string }
> = {
  Low: { bg: "bg-emerald-100", text: "text-emerald-800", label: "Low" },
  LowToModerate: { bg: "bg-lime-100", text: "text-lime-800", label: "Low to Moderate" },
  Moderate: { bg: "bg-yellow-100", text: "text-yellow-800", label: "Moderate" },
  ModeratelyHigh: { bg: "bg-amber-100", text: "text-amber-900", label: "Moderately High" },
  High: { bg: "bg-orange-100", text: "text-orange-900", label: "High" },
  VeryHigh: { bg: "bg-red-100", text: "text-red-800", label: "Very High" },
}

// Lowercase connector words kept lowercase when Title-Casing a name
// (except as the first token). Keeps "Fund of Funds", "Banking and PSU"
// reading naturally instead of "Fund Of Funds".
const SMALL_WORDS = new Set(["of", "and", "the", "for", "to", "in", "a", "an"])

// Common AMC/financial acronyms that must stay upper-cased after the
// Title-Case pass (which would otherwise yield "Elss", "Psu", "Idcw").
const ACRONYMS = new Set([
  "elss",
  "psu",
  "idcw",
  "etf",
  "fof",
  "nfo",
  "us",
  "uk",
  "esg",
  "reit",
  "amc",
  "sip",
])

function titleCaseWord(word: string, isFirst: boolean): string {
  const lower = word.toLowerCase()
  if (ACRONYMS.has(lower)) return word.toUpperCase()
  if (!isFirst && SMALL_WORDS.has(lower)) return lower
  // Preserve already-mixed-case tokens (e.g. "iShares") and tokens with
  // digits ("50", "500"); only normalize ALL-CAPS / all-lower words.
  if (/[a-z]/.test(word) && /[A-Z]/.test(word)) return word
  return lower.charAt(0).toUpperCase() + lower.slice(1)
}

/**
 * Normalize a raw AMFI scheme name for retail display.
 *
 * AMFI names arrive ALL-CAPS-ish with a trailing plan/option clause,
 * e.g. "AXIS BLUECHIP FUND - DIRECT PLAN - GROWTH". We:
 *   1. strip the plan/option suffix (" - Direct/Regular Plan - Growth/
 *      IDCW", or a bare " - Growth/IDCW"), and
 *   2. Title-Case the remainder (keeping acronyms + connector words).
 *
 * The strip is conservative — it only removes a recognised trailing
 * plan/option clause, never arbitrary trailing words.
 */
export function normalizeFundName(raw: string): string {
  if (!raw) return ""
  let name = raw.trim()
  // Strip a trailing " - <Direct|Regular> Plan" clause and/or a trailing
  // " - <Growth|IDCW|Dividend|...>" option clause, in either order /
  // combination. Run twice so "… - Direct Plan - Growth" fully clears.
  const PLAN_OPTION =
    /\s*[-–—]\s*(direct|regular)?\s*plan\s*(?:[-–—]\s*(growth|idcw|dividend|payout|reinvest\w*|income\s+distribution\s+cum\s+capital\s+withdrawal)\b.*)?$/i
  const OPTION_ONLY =
    /\s*[-–—]\s*(growth|idcw|dividend|payout|reinvest\w*|income\s+distribution\s+cum\s+capital\s+withdrawal)\b.*$/i
  for (let i = 0; i < 2; i++) {
    const before = name
    name = name.replace(PLAN_OPTION, "").trim()
    name = name.replace(OPTION_ONLY, "").trim()
    if (name === before) break
  }
  if (!name) name = raw.trim() // never blank out the whole name
  return name
    .split(/\s+/)
    .map((w, i) => titleCaseWord(w, i === 0))
    .join(" ")
}

/**
 * Collapse a verbose AMFI category label to its short tail.
 *
 *   "Equity Scheme - Large Cap Fund"  -> "Large Cap Fund"
 *   "Other Scheme - Index Funds"      -> "Index Funds"
 *   "Debt Scheme - Income Fund"       -> "Income Fund"
 *
 * Falls back to the (trimmed) input when there's no " - " separator.
 */
export function compactCategory(raw: string | null | undefined): string {
  if (!raw) return ""
  const trimmed = raw.trim()
  const parts = trimmed.split(/\s*[-–—]\s*/)
  const tail = parts.length > 1 ? parts[parts.length - 1] : trimmed
  return tail
    .split(/\s+/)
    .map((w, i) => titleCaseWord(w, i === 0))
    .join(" ")
}

// YieldIQ Fund Score chip tint — a coarse emerald→amber→rose ramp so a
// strong score reads at a glance without implying a recommendation.
function scoreTint(score: number): string {
  if (score >= 75) return "bg-emerald-100 text-emerald-800"
  if (score >= 60) return "bg-lime-100 text-lime-800"
  if (score >= 45) return "bg-amber-100 text-amber-900"
  return "bg-rose-100 text-rose-800"
}

function fmtPct(v: number, withSign: boolean): string {
  const sign = withSign && v > 0 ? "+" : ""
  return `${sign}${v.toFixed(1)}%`
}

export default function FundCard({ fund }: { fund: FundCardItem }) {
  const risk = fund.riskometer_level ? RISKOMETER_COLORS[fund.riskometer_level] : null
  const name = normalizeFundName(fund.scheme_name)
  const category = compactCategory(fund.category)
  const score = typeof fund.yieldiq_fund_score === "number" ? fund.yieldiq_fund_score : null
  const ret1y = typeof fund.ret_1y === "number" ? fund.ret_1y : null
  const ter = typeof fund.ter === "number" ? fund.ter : null

  return (
    <HoverCard className="h-full rounded-lg">
      <Link
        href={`/funds/${encodeURIComponent(fund.scheme_code)}`}
        className="flex h-full flex-col rounded-lg border border-border bg-raised p-4"
      >
        {/* AMC row + score chip */}
        <div className="flex items-start justify-between gap-2">
          <div className="flex min-w-0 items-center gap-2">
            <AmcAvatar amc={fund.amc} size="sm" />
            <span className="truncate text-xs text-caption">{fund.amc}</span>
          </div>
          {score !== null ? (
            <span
              className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] font-semibold ${scoreTint(score)}`}
              title="YieldIQ Fund Score (0-100)"
            >
              {score}
            </span>
          ) : null}
        </div>

        {/* Normalized fund name */}
        <div className="mt-2 line-clamp-2 text-sm font-semibold leading-snug text-ink">
          {name}
        </div>

        {/* Category + Riskometer chips */}
        <div className="mt-2 flex flex-wrap gap-1.5">
          {category ? (
            <span className="rounded-full bg-tone-info-bg px-2 py-0.5 text-[11px] font-medium text-tone-info-fg">
              {category}
            </span>
          ) : null}
          {risk ? (
            <span
              className={`rounded-full ${risk.bg} ${risk.text} px-2 py-0.5 text-[11px] font-medium`}
            >
              {risk.label}
            </span>
          ) : null}
        </div>

        {/* Metric strip — pinned to the card foot so cards line up */}
        <div className="mt-auto flex items-end justify-between gap-2 pt-3 text-xs">
          <div className="flex flex-col">
            <span className="text-[10px] uppercase tracking-wide text-caption">1Y Return</span>
            {ret1y !== null ? (
              <span
                className={`font-semibold tabular-nums ${
                  ret1y >= 0 ? "text-emerald-600" : "text-rose-600"
                }`}
              >
                {fmtPct(ret1y, true)}
              </span>
            ) : (
              <span className="text-caption">—</span>
            )}
          </div>
          <div className="flex flex-col items-end">
            <span className="text-[10px] uppercase tracking-wide text-caption">Expense</span>
            <span className="font-medium tabular-nums text-body">
              {ter !== null ? fmtPct(ter, false) : "—"}
            </span>
          </div>
        </div>
      </Link>
    </HoverCard>
  )
}
