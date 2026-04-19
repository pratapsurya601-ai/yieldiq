"use client"
// TODO: swap to design tokens
import { useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { ChevronDown } from "lucide-react"
import MacroDashboard from "@/components/home/MacroDashboard"
import { getMarketPulse, getMacroSummary } from "@/lib/api"
import { formatPct } from "@/lib/utils"

// Collapsed by default. Title row is a one-liner — NIFTY and USD/INR.
// Expanded: the full MacroDashboard + indices row.
export default function MarketAccordion() {
  const [open, setOpen] = useState(false)

  const { data: pulse } = useQuery({
    queryKey: ["market-pulse"],
    queryFn: () => getMarketPulse(true),
    staleTime: 4 * 60 * 1000,
  })
  const { data: macroSummary } = useQuery({
    queryKey: ["macro-summary"],
    queryFn: () => getMacroSummary(),
    staleTime: 24 * 60 * 60 * 1000,
    retry: 1,
  })

  const nifty = pulse?.indices?.find((i) =>
    i.name.toLowerCase().includes("nifty 50") || i.name.toLowerCase() === "nifty",
  ) || pulse?.indices?.[0]
  const usdInr = pulse?.usd_inr ?? null

  const summary = (() => {
    const parts: string[] = []
    if (nifty) {
      // formatPct already prepends "+" or "-" sign — don't double it.
      parts.push(`${nifty.name} ${formatPct(nifty.change_pct)}`)
    }
    if (usdInr !== null) {
      parts.push(`USD/INR ₹${usdInr.toFixed(2)}`)
    }
    return parts.length ? parts.join(", ") : "Tap to view indices and macro data"
  })()

  return (
    <section className="px-4">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between gap-3 bg-surface border border-border rounded-xl px-4 py-3 text-left hover:border-brand transition"
        aria-expanded={open}
      >
        <div className="min-w-0 flex-1">
          <p className="text-[10px] font-bold text-caption uppercase tracking-widest">
            Market
          </p>
          <p className="text-sm font-semibold text-ink truncate">{summary}</p>
        </div>
        <ChevronDown
          className={`w-5 h-5 text-caption flex-shrink-0 transition-transform ${open ? "rotate-180" : ""}`}
        />
      </button>
      {open && (
        <div className="mt-4 space-y-4">
          {pulse && (
            <MacroDashboard pulse={pulse} ai_summary={macroSummary?.summary ?? null} />
          )}
          {pulse && pulse.indices && pulse.indices.length > 0 && (
            <div className="flex gap-2 overflow-x-auto pb-2 snap-x snap-mandatory -mx-4 px-4 scroll-px-4">
              {pulse.indices.map((idx) => (
                <div
                  key={idx.name}
                  className={`flex-shrink-0 snap-start bg-surface rounded-xl border border-border px-4 py-3 text-center min-w-[140px] border-l-[3px] ${idx.change_pct >= 0 ? "border-l-green-500" : "border-l-red-500"}`}
                >
                  <p className="text-[10px] font-bold text-caption uppercase tracking-wider">
                    {idx.name}
                  </p>
                  <p className="text-lg font-bold text-ink font-mono">
                    {idx.price.toLocaleString()}
                  </p>
                  <p
                    className={`text-xs font-bold font-mono ${idx.change_pct >= 0 ? "text-green-600" : "text-red-600"}`}
                  >
                    {idx.change_pct >= 0 ? "▲" : "▼"} {formatPct(idx.change_pct)}
                  </p>
                </div>
              ))}
              {pulse.fear_greed_label && (
                <div className="flex-shrink-0 snap-start bg-surface rounded-xl border border-border border-l-[3px] border-l-amber-500 px-4 py-3 text-center min-w-[140px]">
                  <p className="text-[10px] font-bold text-caption uppercase tracking-wider">
                    Sentiment
                  </p>
                  <p className="text-lg font-bold text-ink font-mono">
                    {pulse.fear_greed_index}
                  </p>
                  <p className="text-xs font-bold text-amber-600">
                    {pulse.fear_greed_label}
                  </p>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </section>
  )
}
