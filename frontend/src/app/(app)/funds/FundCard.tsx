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

import type { FundListItem } from "@/types/api"
import AmcAvatar from "@/components/common/AmcAvatar"
import { HoverCard } from "@/components/motion"
import { RISKOMETER_TONE } from "@/lib/fund-riskometer"

// ── Contract shape ──────────────────────────────────────────────────
// The base `FundListItem` type in types/api.ts has not yet grown the
// three LEFT-JOINed metric fields, but the backend FundListItem model
// already returns them (nullable). We widen locally so the cards can
// consume them today without touching the shared type file. When the
// shared type catches up these become redundant (assignable) — no
// breakage either way.
export interface FundCardItem extends FundListItem {
  /** Trailing 1-year return as a DECIMAL fraction (0.088 = 8.8%). Null
   *  when no returns cache row. Scaled ×100 for display (fmtReturnPct). */
  ret_1y?: number | null
  /** YieldIQ Fund Score (0-100). Null when not yet computed. */
  yieldiq_fund_score?: number | null
  /** Expense ratio in PERCENT (1.06 = 1.06%) — prefers Direct
   *  (COALESCE(ter_direct, ter_regular)). Rendered verbatim, NOT ×100. */
  ter?: number | null
}

// Lowercase connector words kept lowercase when Title-Casing a name
// (except as the first token). Keeps "Fund of Funds", "Banking and PSU"
// reading naturally instead of "Fund Of Funds".
const SMALL_WORDS = new Set(["of", "and", "the", "for", "to", "in", "a", "an"])

// Common AMC/financial acronyms that must stay upper-cased after the
// Title-Case pass (which would otherwise yield "Elss", "Psu", "Idcw",
// "Hdfc", "Sbi"). Includes the AMC house acronyms that lead many real
// scheme names so they don't read as "Hdfc Top 100 Fund".
const ACRONYMS = new Set([
  // option / structure tokens
  "elss",
  "psu",
  "idcw",
  "etf",
  "fof",
  "nfo",
  "esg",
  "reit",
  "amc",
  "sip",
  "tri",
  // geographies
  "us",
  "uk",
  // index family
  "nifty",
  // AMC house acronyms
  "hdfc",
  "sbi",
  "icici",
  "hsbc",
  "uti",
  "lic",
  "dsp",
  "idfc",
  "ppfas",
  "iifl",
  "jm",
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

// One trailing plan/option clause, anchored to end ($). Applied
// repeatedly (see stripPlanOption) so a stacked tail clears fully. Real
// AMFI names stack these noisily and inconsistently, e.g.
//   "… - Direct Plan Growth Plan - Growth Option"
//   "… - Direct Plan Growth Plan - Bonus Option"
//   "…-Growth Plan-Growth Option"   (no spaces around the hyphens)
// so an earlier two-pass regex left "- Direct Plan Growth Plan" stuck to
// the card. The peel matches, per iteration, ONE of:
//   • an option payout (growth/bonus/idcw/dividend/payout/reinvest/
//     income-distribution), optionally followed by "Option"/"Plan";
//   • a qualified plan word — "(direct|regular|growth) plan"; or
//   • a bare "direct"/"regular" qualifier (optionally + " plan").
// The bare word "plan" is NEVER stripped on its own, so a legitimate
// sub-plan token such as "Nifty 50 Plan" (preceded by an index/number,
// not a plan qualifier) is preserved.
const PLAN_OPTION_TAIL =
  /\s*[-–—]?\s*((growth|bonus|idcw|dividend|payout|reinvest\w*|income\s+distribution(\s+cum\s+capital\s+withdrawal)?)(\s+(option|plan))?|(direct|regular|growth)\s+plan|(direct|regular)(\s+plan)?)\s*$/i

function stripPlanOption(name: string): string {
  let prev: string | null = null
  let cur = name.trim()
  // Repeatedly peel the trailing clause until it stops shrinking. The
  // explicit "stopped shrinking" guard prevents an infinite loop on a
  // zero-width match.
  while (cur !== prev) {
    prev = cur
    const next = cur
      .replace(PLAN_OPTION_TAIL, "")
      .replace(/[\s\-–—]+$/, "")
      .trim()
    if (next === cur) break
    cur = next
  }
  return cur
}

/**
 * Normalize a raw AMFI scheme name for retail display.
 *
 * AMFI names arrive ALL-CAPS-ish with a stacked trailing plan/option
 * clause, e.g. "AXIS BLUECHIP FUND - DIRECT PLAN - GROWTH" or
 * "NIPPON INDIA LARGE CAP FUND - DIRECT PLAN GROWTH PLAN - GROWTH OPTION".
 * We:
 *   1. peel the recognised trailing plan/option clause(s)
 *      (see stripPlanOption), and
 *   2. Title-Case the remainder (keeping acronyms + connector words).
 *
 * The strip is conservative — it only removes a recognised trailing
 * plan/option clause, never arbitrary trailing words, and never the bare
 * word "Plan" on its own (so "… - Nifty 50 Plan" is preserved).
 */
export function normalizeFundName(raw: string): string {
  if (!raw) return ""
  let name = stripPlanOption(raw.trim())
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

// YieldIQ Fund Score chip tint — a coarse good→warn→bad token ramp so a
// high score reads at a glance as a neutral, descriptive marker. Tokens
// (not raw palette) so the chip follows dark mode + the design system.
export function scoreTint(score: number): string {
  if (score >= 75) return "bg-tone-good-bg text-tone-good-fg"
  if (score >= 60) return "bg-tone-good-bg text-tone-good-fg"
  if (score >= 45) return "bg-tone-warn-bg text-tone-warn-fg"
  return "bg-tone-bad-bg text-tone-bad-fg"
}

// IMPORTANT — ret_1y and ter no longer share units.
//
// `ret_1y` is still a DECIMAL FRACTION from fund_returns_cache
// (e.g. 0.088 = 8.8%, -0.0194 = -1.94%), so it must be ×100 to read as
// a percent. Without that scale every card showed "+0.1%" for an 8.8%
// return.
//
// `ter` is now stored in PERCENT (e.g. 1.06 = 1.06%) since the AMFI TER
// ingestion pipeline landed (PR #982/#985 populate ter_direct/ter_regular
// in whole-percent units). It must NOT be ×100 — doing so renders a
// 1.06% fund as "106.0%". A single shared ×100 helper used to format
// both fields, which is exactly how that bug shipped; the two formatters
// below keep the units explicit and separate.

/** Trailing return (DECIMAL fraction) → signed percent string. */
export function fmtReturnPct(fraction: number, withSign: boolean): string {
  const pct = fraction * 100
  const sign = withSign && pct > 0 ? "+" : ""
  return `${sign}${pct.toFixed(1)}%`
}

/**
 * Expense ratio (already in PERCENT) → percent string, NO ×100.
 *
 * Guards against a unit regression: AMFI TERs live in roughly [0, 3]%.
 * If a value > 10 slips through (e.g. a future pipeline reverts to a
 * basis-points or ×100 representation), it is almost certainly a unit
 * error, so we suppress it (return null) rather than render an absurd
 * "106.0%". The card then shows nothing for Expense instead of a wrong
 * number. ≤ 0 is treated as "no data" for the same reason.
 */
export function fmtTerPct(ter: number): string | null {
  if (!Number.isFinite(ter) || ter <= 0 || ter > 10) return null
  return `${ter.toFixed(2)}%`
}

export default function FundCard({ fund }: { fund: FundCardItem }) {
  const risk = fund.riskometer_level ? RISKOMETER_TONE[fund.riskometer_level] : null
  const name = normalizeFundName(fund.scheme_name)
  const category = compactCategory(fund.category)
  const score = typeof fund.yieldiq_fund_score === "number" ? fund.yieldiq_fund_score : null
  const ret1y = typeof fund.ret_1y === "number" ? fund.ret_1y : null
  // ter is already a percent; fmtTerPct returns null for missing/out-of-
  // range values, which also drives whether the Expense cell renders.
  const terLabel = typeof fund.ter === "number" ? fmtTerPct(fund.ter) : null

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
              className={`rounded-full ${risk.cls} px-2 py-0.5 text-[11px] font-medium`}
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
                {fmtReturnPct(ret1y, true)}
              </span>
            ) : (
              <span className="text-caption">—</span>
            )}
          </div>
          {/*
            Expense (TER) renders only when present AND in a sane range.
            AMFI TER ingestion (PR #982/#985) now populates ter_direct/
            ter_regular in PERCENT, so the value is shown verbatim with a
            single "%" (see fmtTerPct — no ×100). fmtTerPct returns null
            for missing or out-of-range values, so a unit regression or a
            scheme with no TER simply hides the cell rather than printing
            a wrong "106.0%".
          */}
          {terLabel !== null ? (
            <div className="flex flex-col items-end">
              <span className="text-[10px] uppercase tracking-wide text-caption">Expense</span>
              <span className="font-medium tabular-nums text-body">{terLabel}</span>
            </div>
          ) : null}
        </div>
      </Link>
    </HoverCard>
  )
}
