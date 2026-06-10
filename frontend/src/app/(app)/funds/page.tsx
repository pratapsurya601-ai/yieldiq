/**
 * /funds — minimal mutual-fund landing.
 *
 * Phase 3-slim scope: card grid of the first 20 active funds
 * (alphabetical) linking into the detail page, plus a search box that
 * routes to the existing global search for now. Phase 6 replaces this
 * with a real screener (filters by category, returns window, risk
 * band, TER, AUM, manager tenure).
 *
 * No advisory copy — only AMC-published category labels and the SEBI
 * Riskometer chip. Past-performance disclaimer at the foot of the page.
 */
import Link from "next/link"

import { fetchFundListSSR } from "@/lib/api"
import type { FundListItem, FundRiskometerLevel } from "@/types/api"
import { HoverCard, RevealStagger } from "@/components/motion"
import FundsSearchInput from "./FundsSearchInput"

export const revalidate = 300

const RISKOMETER_COLORS: Record<FundRiskometerLevel, { bg: string; text: string; label: string }> = {
  Low: { bg: "bg-emerald-100", text: "text-emerald-800", label: "Low" },
  LowToModerate: { bg: "bg-lime-100", text: "text-lime-800", label: "Low to Moderate" },
  Moderate: { bg: "bg-yellow-100", text: "text-yellow-800", label: "Moderate" },
  ModeratelyHigh: { bg: "bg-amber-100", text: "text-amber-900", label: "Moderately High" },
  High: { bg: "bg-orange-100", text: "text-orange-900", label: "High" },
  VeryHigh: { bg: "bg-red-100", text: "text-red-800", label: "Very High" },
}

function FundCard({ fund }: { fund: FundListItem }) {
  const risk = fund.riskometer_level ? RISKOMETER_COLORS[fund.riskometer_level] : null
  // Motion (2026-06-11): wrap each card in <HoverCard> so the hover
  // lift + soft shadow primitive replaces the inline hover:shadow-sm.
  // The Link still owns the navigation behaviour; HoverCard is a
  // styling wrapper that does not introduce a button or trap clicks.
  return (
    <HoverCard className="rounded-lg">
      <Link
        href={`/funds/${encodeURIComponent(fund.scheme_code)}`}
        className="block rounded-lg border border-gray-200 bg-white p-4"
      >
        <div className="text-xs text-gray-500">{fund.amc}</div>
        <div className="mt-1 line-clamp-2 text-sm font-semibold text-gray-900">
          {fund.scheme_name}
        </div>
        <div className="mt-2 flex flex-wrap gap-1.5">
          {fund.category ? (
            <span className="rounded-full bg-blue-50 px-2 py-0.5 text-[11px] font-medium text-blue-700">
              {fund.category}
            </span>
          ) : null}
          {risk ? (
            <span
              className={`rounded-full ${risk.bg} ${risk.text} px-2 py-0.5 text-[11px] font-medium`}
            >
              {risk.label}
            </span>
          ) : null}
          {fund.plan ? (
            <span className="rounded-full bg-gray-100 px-2 py-0.5 text-[11px] font-medium text-gray-700">
              {fund.plan}
            </span>
          ) : null}
        </div>
      </Link>
    </HoverCard>
  )
}

export default async function FundsLanding() {
  const { funds, total } = await fetchFundListSSR(20)

  return (
    <main className="mx-auto max-w-6xl px-4 py-8 sm:px-6 lg:px-8">
      <header className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight text-gray-900 sm:text-3xl">
          Mutual Funds
        </h1>
        <p className="mt-1 text-sm text-gray-600">
          Read-only NAV history, benchmark-relative returns, and risk metrics for
          Indian mutual-fund schemes.
        </p>
      </header>

      {/* FundsSearchInput is a client component that wraps the same
          GET form but adds a focus-state glow ring. The semantics
          (form action="/search", input name="q") are unchanged so
          server-side search routing still works. */}
      <FundsSearchInput />

      {funds.length === 0 ? (
        <div className="rounded-lg border border-gray-200 bg-white p-6 text-sm text-gray-500">
          Fund data is being ingested. Check back shortly.
        </div>
      ) : (
        <>
          <div className="mb-3 text-xs text-gray-500">
            Showing {funds.length} of {total} schemes.
          </div>
          {/* Motion: tight 15ms stagger for the grid — funds lists can
              be long and a longer stagger compounds into a visible
              wait. RevealStagger short-circuits to the final state for
              reduced-motion users. */}
          <RevealStagger
            className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3"
            staggerMs={15}
          >
            {funds.map((f) => (
              <FundCard key={f.scheme_code} fund={f} />
            ))}
          </RevealStagger>
        </>
      )}

      <footer className="mt-8 rounded-lg border border-amber-200 bg-amber-50 p-4 text-xs leading-relaxed text-amber-900">
        Past performance is not indicative of future returns. Mutual fund investments
        are subject to market risks; read all scheme-related documents carefully.
      </footer>
    </main>
  )
}
