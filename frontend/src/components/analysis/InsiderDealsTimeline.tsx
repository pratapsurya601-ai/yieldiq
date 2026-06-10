"use client"

// InsiderDealsTimeline — unified vertical timeline of insider + bulk +
// block deals for a single ticker, last 90 days. This is the surface
// that closes the Tickertape "insider activity timeline" feature gap:
// instead of forcing the user to toggle between separate insider /
// bulk / block panels, every governance-significant trade lands on
// one chronological column with a date rail, a type chip, a direction
// arrow, the party, and the value.
//
// Data source: GET /api/v1/public/insider-deals/{ticker}?days=90
// (1h CDN cache, no auth, version_keyed=false).
//
// Empty-state contract: when the backend returns available=false
// (neither table has rows for this ticker, or ingestion has not landed
// yet) the panel shows a quiet "Coming soon — ingestion in progress"
// row. This matches the Phase J copy lint: acquired/reduced verbs only,
// no fake confidence chips.
//
// Auto-summary line synthesises a single SEBI-safe sentence from the
// 90-day net flow — e.g.
//   "Promoters acquired ~INR 12Cr over 3 transactions"
//   "Directors net-reduced positions in the last 90 days"
//   "Bulk + block deals net-acquired INR 45Cr by institutional buyers"
// Falls back silently when the data doesn't support a summary so we
// never invent narrative.

import { useEffect, useState } from "react"

type DealType = "insider" | "bulk" | "block"
type Direction = "acquired" | "reduced" | null

interface TimelineDeal {
  transaction_date: string | null
  type: DealType | string
  direction: Direction | string
  quantity: number | null
  value_cr: number | null
  party: string | null
}

interface TimelineResponse {
  ticker: string
  days: number
  count: number
  available: boolean
  deals: TimelineDeal[]
}

// ─────────────────────────────────────────────────────────────────
// Formatters
// ─────────────────────────────────────────────────────────────────

function fmtDate(s: string | null): string {
  if (!s) return "—"
  try {
    return new Date(s).toLocaleDateString("en-IN", {
      year: "2-digit", month: "short", day: "numeric",
    })
  } catch {
    return s
  }
}

function fmtValueCr(v: number | null | undefined): string {
  if (v == null || isNaN(v)) return "—"
  if (Math.abs(v) >= 1000) return `INR ${(v / 1000).toFixed(1)}KCr`
  if (Math.abs(v) >= 1) return `INR ${v.toFixed(1)}Cr`
  if (Math.abs(v) > 0) return `INR ${(v * 100).toFixed(1)}L`
  return "—"
}

function fmtQty(n: number | null | undefined): string {
  if (n == null || !isFinite(n) || n <= 0) return "—"
  if (n >= 1e7) return `${(n / 1e7).toFixed(2)}Cr sh`
  if (n >= 1e5) return `${(n / 1e5).toFixed(2)}L sh`
  return `${n.toLocaleString("en-IN")} sh`
}

function shortenParty(s: string | null, n = 40): string {
  if (!s) return "—"
  return s.length > n ? s.slice(0, n - 1) + "…" : s
}

// ─────────────────────────────────────────────────────────────────
// Type chip + direction arrow styling
// ─────────────────────────────────────────────────────────────────

function typeChipClasses(t: string): string {
  if (t === "insider") {
    return "bg-tone-info-bg text-tone-info-fg"
  }
  if (t === "bulk") {
    return "bg-tone-warn-bg text-tone-warn-fg"
  }
  if (t === "block") {
    return "bg-tone-good-bg text-tone-good-fg"
  }
  return "bg-slate-100 text-slate-600 dark:bg-slate-800/40 dark:text-slate-300"
}

function typeLabel(t: string): string {
  if (t === "insider") return "Insider"
  if (t === "bulk") return "Bulk"
  if (t === "block") return "Block"
  return t
}

function directionGlyph(d: string | null | undefined): { glyph: string; cls: string; label: string } {
  if (d === "acquired") {
    return {
      glyph: "↑",
      cls: "text-emerald-600 dark:text-emerald-400",
      label: "Acquired",
    }
  }
  if (d === "reduced") {
    return {
      glyph: "↓",
      cls: "text-red-600 dark:text-red-400",
      label: "Reduced",
    }
  }
  return { glyph: "•", cls: "text-caption", label: "—" }
}

// ─────────────────────────────────────────────────────────────────
// Auto-summary
// ─────────────────────────────────────────────────────────────────

interface NetFlow {
  insider_net_cr: number
  insider_count: number
  insider_acquired_count: number
  insider_reduced_count: number
  promoter_acquired_count: number
  promoter_reduced_count: number
  director_acquired_count: number
  director_reduced_count: number
  bb_net_cr: number
  bb_count: number
}

function computeNetFlow(deals: TimelineDeal[]): NetFlow {
  const flow: NetFlow = {
    insider_net_cr: 0,
    insider_count: 0,
    insider_acquired_count: 0,
    insider_reduced_count: 0,
    promoter_acquired_count: 0,
    promoter_reduced_count: 0,
    director_acquired_count: 0,
    director_reduced_count: 0,
    bb_net_cr: 0,
    bb_count: 0,
  }
  for (const d of deals) {
    const sign = d.direction === "acquired" ? 1 : d.direction === "reduced" ? -1 : 0
    const v = typeof d.value_cr === "number" ? d.value_cr : 0
    if (d.type === "insider") {
      flow.insider_count += 1
      flow.insider_net_cr += sign * v
      if (sign > 0) flow.insider_acquired_count += 1
      else if (sign < 0) flow.insider_reduced_count += 1
      const party = (d.party || "").toLowerCase()
      if (party.includes("promoter")) {
        if (sign > 0) flow.promoter_acquired_count += 1
        else if (sign < 0) flow.promoter_reduced_count += 1
      }
      if (party.includes("director")) {
        if (sign > 0) flow.director_acquired_count += 1
        else if (sign < 0) flow.director_reduced_count += 1
      }
    } else if (d.type === "bulk" || d.type === "block") {
      flow.bb_count += 1
      flow.bb_net_cr += sign * v
    }
  }
  return flow
}

function buildSummary(deals: TimelineDeal[]): string | null {
  if (!deals.length) return null
  const f = computeNetFlow(deals)
  const parts: string[] = []

  // Insider line — prefer promoter > director > generic insider.
  if (f.promoter_acquired_count > 0 && f.promoter_reduced_count === 0) {
    parts.push(
      `Promoters acquired ~${fmtValueCr(Math.abs(f.insider_net_cr))} over ${f.promoter_acquired_count} transaction${f.promoter_acquired_count > 1 ? "s" : ""}`,
    )
  } else if (f.promoter_reduced_count > 0 && f.promoter_acquired_count === 0) {
    parts.push(
      `Promoters net-reduced positions over ${f.promoter_reduced_count} transaction${f.promoter_reduced_count > 1 ? "s" : ""}`,
    )
  } else if (f.director_acquired_count > 0 || f.director_reduced_count > 0) {
    if (f.director_acquired_count > f.director_reduced_count) {
      parts.push(
        `Directors net-acquired in ${f.director_acquired_count} of ${f.director_acquired_count + f.director_reduced_count} disclosures`,
      )
    } else if (f.director_reduced_count > f.director_acquired_count) {
      parts.push(
        `Directors net-reduced in ${f.director_reduced_count} of ${f.director_acquired_count + f.director_reduced_count} disclosures`,
      )
    }
  } else if (f.insider_count > 0) {
    if (f.insider_acquired_count > f.insider_reduced_count) {
      parts.push(
        `Insiders net-acquired across ${f.insider_count} disclosure${f.insider_count > 1 ? "s" : ""}`,
      )
    } else if (f.insider_reduced_count > f.insider_acquired_count) {
      parts.push(
        `Insiders net-reduced across ${f.insider_count} disclosure${f.insider_count > 1 ? "s" : ""}`,
      )
    }
  }

  // Bulk/block line.
  if (f.bb_count > 0 && Math.abs(f.bb_net_cr) >= 1) {
    if (f.bb_net_cr > 0) {
      parts.push(
        `Bulk + block deals net-acquired ${fmtValueCr(f.bb_net_cr)}`,
      )
    } else {
      parts.push(
        `Bulk + block deals net-reduced ${fmtValueCr(Math.abs(f.bb_net_cr))}`,
      )
    }
  } else if (f.bb_count > 0) {
    parts.push(
      `${f.bb_count} bulk/block deal${f.bb_count > 1 ? "s" : ""} reported`,
    )
  }

  if (!parts.length) return null
  return parts.join(" · ") + " (last 90 days)"
}

// ─────────────────────────────────────────────────────────────────
// Component
// ─────────────────────────────────────────────────────────────────

interface Props {
  ticker: string
}

const DEFAULT_DAYS = 90
const ROW_LIMIT = 25

export default function InsiderDealsTimeline({ ticker }: Props) {
  const [data, setData] = useState<TimelineResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showAll, setShowAll] = useState(false)

  useEffect(() => {
    let cancelled = false
    const base = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"
    const symbol = (ticker || "").replace(".NS", "").replace(".BO", "")
    if (!symbol) {
      setLoading(false)
      return
    }
    setLoading(true)
    setError(null)
    fetch(`${base}/api/v1/public/insider-deals/${symbol}?days=${DEFAULT_DAYS}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((j: TimelineResponse | null) => {
        if (cancelled) return
        setData(j)
        setLoading(false)
      })
      .catch(() => {
        if (cancelled) return
        setError("Could not load insider + deals timeline")
        setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [ticker])

  if (loading) {
    return (
      <section
        className="bg-bg dark:bg-surface rounded-2xl border border-border p-4"
        aria-label={`Insider and deals timeline for ${ticker}`}
      >
        <h3 className="text-sm font-semibold text-ink mb-2">Insider + Deals Timeline</h3>
        <div className="text-xs text-caption">Loading…</div>
      </section>
    )
  }

  const deals = data?.deals ?? []
  const isEmpty = !data || !data.available || deals.length === 0

  if (isEmpty) {
    return (
      <section
        className="bg-bg dark:bg-surface rounded-2xl border border-border p-4"
        aria-label={`Insider and deals timeline for ${ticker}`}
      >
        <div className="flex items-start justify-between gap-3 mb-2">
          <div>
            <h3 className="text-sm font-semibold text-ink">Insider + Deals Timeline</h3>
            <p className="text-xs text-caption mt-0.5">
              Promoter / director disclosures and exchange bulk + block deals, last 90 days.
            </p>
          </div>
        </div>
        <div className="text-xs text-caption italic">
          Coming soon — ingestion in progress. Once SEBI PIT and NSE/BSE deal reports are archived for this ticker, transactions will surface here.
          {error ? ` (${error})` : ""}
        </div>
      </section>
    )
  }

  const summary = buildSummary(deals)
  const visible = showAll ? deals : deals.slice(0, ROW_LIMIT)
  const remaining = deals.length - visible.length

  return (
    <section
      className="bg-bg dark:bg-surface rounded-2xl border border-border p-4"
      aria-label={`Insider and deals timeline for ${ticker}`}
    >
      <div className="flex items-start justify-between gap-3 mb-3">
        <div>
          <h3 className="text-sm font-semibold text-ink">Insider + Deals Timeline</h3>
          <p className="text-xs text-caption mt-0.5">
            Promoter / director disclosures and exchange bulk + block deals, last 90 days.
          </p>
        </div>
        <div className="text-right">
          <div className="text-xs text-caption">Transactions</div>
          <div className="text-lg font-semibold text-ink tabular-nums">
            {data!.count}
          </div>
        </div>
      </div>

      {summary && (
        <div className="text-xs font-medium text-ink mb-3 leading-relaxed">
          {summary}
        </div>
      )}

      <ol
        className="relative border-l border-border ml-2 space-y-3"
        aria-label="Timeline of transactions"
      >
        {visible.map((d, i) => {
          const dir = directionGlyph(d.direction)
          const tlabel = typeLabel(d.type)
          return (
            <li
              key={`${d.transaction_date ?? "n"}-${i}-${d.type}`}
              className="ml-4"
            >
              <span
                className="absolute -left-1.5 mt-1.5 h-3 w-3 rounded-full border border-border bg-surface"
                aria-hidden="true"
              />
              <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
                <span className="font-mono text-caption whitespace-nowrap">
                  {fmtDate(d.transaction_date)}
                </span>
                <span
                  className={
                    "inline-flex items-center px-1.5 py-0.5 rounded text-[10px] " +
                    "font-semibold uppercase tracking-wide " +
                    typeChipClasses(d.type)
                  }
                >
                  {tlabel}
                </span>
                <span
                  className={`text-sm font-semibold ${dir.cls}`}
                  aria-label={dir.label}
                  title={dir.label}
                >
                  {dir.glyph}
                </span>
                <span className="text-ink flex-1 min-w-0 truncate">
                  {shortenParty(d.party)}
                </span>
                <span className="text-ink tabular-nums whitespace-nowrap">
                  {fmtValueCr(d.value_cr)}
                </span>
                <span className="text-caption tabular-nums whitespace-nowrap text-[10px]">
                  {fmtQty(d.quantity)}
                </span>
              </div>
            </li>
          )
        })}
      </ol>

      {remaining > 0 && (
        <button
          type="button"
          onClick={() => setShowAll(true)}
          className="mt-3 text-xs text-tone-info-fg hover:underline focus:outline-none focus:underline"
        >
          Show {remaining} more
        </button>
      )}

      <div className="flex items-center justify-between text-[10px] text-caption mt-3">
        <span>Window: last {data!.days} days</span>
        <span>Source: SEBI PIT + NSE/BSE bulk &amp; block reports</span>
      </div>
    </section>
  )
}
