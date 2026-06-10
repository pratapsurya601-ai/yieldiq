"use client"
// Day-108c (2026-05-23) — sortable cohort table for the sector
// landing page. Pure client component so the server payload stays
// streamable; sort state lives in this component only.
//
// Motion (2026-06-11): the first 20 rows get a per-row stagger on
// first viewport entry. RevealStagger can't be used directly because
// it inserts a wrapper <div> that breaks <tbody><tr> semantics, so
// we replicate its CSS-only stagger inline on each <tr>. Sort state
// changes are NOT re-animated — the stagger only fires once at mount.

import Link from "next/link"
import { useMemo, useState } from "react"
import { useInViewOnce } from "@/components/anim/useInViewOnce"
import { useReducedMotion } from "@/lib/motion/useReducedMotion"
import { DURATION, cssEase } from "@/lib/motion/timing"

// Tight stagger for long lists — 20ms keeps the cascade brisk so the
// last (20th) row arrives ~400ms after the first.
const ROW_STAGGER_MS = 20
const ROW_STAGGER_LIMIT = 20

type Row = {
  ticker: string
  name: string
  score: number | null
  verdict: string | null
  fv: number | null
  price: number | null
  mos_pct: number | null
  pe_ratio: number | null
  roe: number | null
  fv_to_price: number | null
}

type SortKey = "score" | "mos_pct" | "verdict" | "ticker"

const VERDICT_RANK: Record<string, number> = {
  undervalued: 3,
  fairly_valued: 2,
  overvalued: 1,
}

function fmt(n: number | null, digits = 2): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—"
  return n.toFixed(digits)
}

function verdictBadge(v: string | null): { label: string; cls: string } {
  if (v === "undervalued") return { label: "Undervalued", cls: "bg-green-50 text-green-700 border-green-200" }
  if (v === "overvalued") return { label: "Overvalued", cls: "bg-red-50 text-red-700 border-red-200" }
  if (v === "fairly_valued") return { label: "Fairly valued", cls: "bg-blue-50 text-blue-700 border-blue-200" }
  return { label: v ?? "—", cls: "bg-gray-50 text-gray-600 border-gray-200" }
}

export default function SectorTable({ rows }: { rows: Row[] }) {
  const [sortKey, setSortKey] = useState<SortKey>("score")
  const [asc, setAsc] = useState<boolean>(false)
  const reduced = useReducedMotion()
  // Trigger the stagger on the wrapper's first viewport entry.
  const { ref: animRef, inView } = useInViewOnce<HTMLDivElement>(0.1)
  const animVisible = reduced || inView
  const rowEase = cssEase("outExpo")

  const sorted = useMemo(() => {
    const out = [...rows]
    out.sort((a, b) => {
      let av: number, bv: number
      if (sortKey === "ticker") {
        return asc
          ? a.ticker.localeCompare(b.ticker)
          : b.ticker.localeCompare(a.ticker)
      }
      if (sortKey === "verdict") {
        av = VERDICT_RANK[a.verdict ?? ""] ?? 0
        bv = VERDICT_RANK[b.verdict ?? ""] ?? 0
      } else {
        av = (a[sortKey] as number | null) ?? -Infinity
        bv = (b[sortKey] as number | null) ?? -Infinity
      }
      return asc ? av - bv : bv - av
    })
    return out
  }, [rows, sortKey, asc])

  function toggle(k: SortKey) {
    if (sortKey === k) setAsc(prev => !prev)
    else {
      setSortKey(k)
      setAsc(k === "ticker")
    }
  }

  function arrow(k: SortKey): string {
    if (sortKey !== k) return ""
    return asc ? " ↑" : " ↓"
  }

  if (rows.length === 0) {
    return (
      <p className="text-sm text-caption italic mt-4">
        No cached analyses for this cohort yet. Sector aggregates appear
        as the nightly compute fills in.
      </p>
    )
  }

  return (
    <div
      ref={animRef}
      className="overflow-x-auto -mx-4 md:mx-0"
      data-anim="sector-table"
    >
      <table className="w-full text-sm border-collapse">
        <thead>
          <tr className="border-b border-gray-200 text-left text-caption">
            <th className="py-2 px-3">
              <button
                type="button"
                onClick={() => toggle("ticker")}
                className="font-semibold hover:text-ink"
              >Ticker{arrow("ticker")}</button>
            </th>
            <th className="py-2 px-3 hidden md:table-cell">Name</th>
            <th className="py-2 px-3 text-right">
              <button
                type="button"
                onClick={() => toggle("score")}
                className="font-semibold hover:text-ink"
              >Score{arrow("score")}</button>
            </th>
            <th className="py-2 px-3 text-right">
              <button
                type="button"
                onClick={() => toggle("mos_pct")}
                className="font-semibold hover:text-ink"
                /* J-copy-2 (audit item 18): make the sort order's
                   intent explicit. Cold-read audit flagged the risk
                   that a MoS-descending sort could be read as a
                   ranking of preference. Native title attribute keeps
                   the UI surface unchanged on desktop hover and is
                   exposed to screen readers. */
                title="Sort order is purely numerical. MoS = (fair value − price) / price."
              >MoS %{arrow("mos_pct")}</button>
            </th>
            <th className="py-2 px-3 text-right hidden sm:table-cell">FV</th>
            <th className="py-2 px-3 text-right hidden sm:table-cell">Price</th>
            <th className="py-2 px-3 text-left">
              <button
                type="button"
                onClick={() => toggle("verdict")}
                className="font-semibold hover:text-ink"
              >Verdict{arrow("verdict")}</button>
            </th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((r, idx) => {
            const v = verdictBadge(r.verdict)
            const bare = r.ticker.replace(/\.(NS|BO)$/i, "")
            // Per-row stagger entrance — only animate the first
            // ROW_STAGGER_LIMIT rows so a 200-ticker cohort doesn't
            // wait 4s for the cascade to finish. Beyond the limit the
            // <tr> renders in its final state with no transition.
            // Reduced-motion: render final state, no transition.
            const animate = idx < ROW_STAGGER_LIMIT
            const rowStyle: React.CSSProperties = animate
              ? {
                  opacity: animVisible ? 1 : 0,
                  transform: animVisible
                    ? "translate3d(0,0,0)"
                    : "translate3d(0,6px,0)",
                  transition: reduced
                    ? "none"
                    : `opacity ${DURATION.normal}ms ease-out ${idx * ROW_STAGGER_MS}ms, transform ${DURATION.normal}ms ${rowEase} ${idx * ROW_STAGGER_MS}ms`,
                  willChange: animVisible ? "auto" : "opacity, transform",
                }
              : {}
            return (
              <tr
                key={r.ticker}
                className="border-b border-gray-100 hover:bg-gray-50"
                style={rowStyle}
                data-stagger-index={animate ? idx : undefined}
              >
                <td className="py-2 px-3 font-mono">
                  <Link
                    href={`/analysis/${encodeURIComponent(r.ticker)}`}
                    className="text-blue-700 hover:underline"
                  >{bare}</Link>
                </td>
                <td className="py-2 px-3 hidden md:table-cell">{r.name}</td>
                <td className="py-2 px-3 text-right tabular-nums">{fmt(r.score, 0)}</td>
                <td className="py-2 px-3 text-right tabular-nums">{fmt(r.mos_pct, 1)}</td>
                <td className="py-2 px-3 text-right tabular-nums hidden sm:table-cell">{fmt(r.fv, 2)}</td>
                <td className="py-2 px-3 text-right tabular-nums hidden sm:table-cell">{fmt(r.price, 2)}</td>
                <td className="py-2 px-3">
                  <span className={`inline-block px-2 py-0.5 rounded border text-xs ${v.cls}`}>
                    {v.label}
                  </span>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
