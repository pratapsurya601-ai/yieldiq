"use client"
// FlowsPanel — /markets hub (2026-06-09).
//
// Net FII + DII flow tiles for the most-recent NSE trading day.
// Sourced from /api/v1/market/pulse?include_macro=true → same payload
// MarketsStrip uses, so this is a free read off the React-Query cache.
//
// Empty-state policy: render NOTHING when the backend doesn't have a
// fresh flow row (pulse.fii_net_cr is null or the row is stale). The
// "coming soon" treatment is reserved for surfaces where we KNOW the
// data isn't wired yet — here it IS wired, so the only honest
// fallback is to hide the panel.
//
// SEBI watch: tiles surface the raw net-rupee number with neutral
// "net inflow" / "net outflow" descriptors. No verbs, no superlatives.

import { useQuery } from "@tanstack/react-query"
import { getMarketPulse } from "@/lib/api"
import { useAuthStore } from "@/store/authStore"

function formatCr(n: number | null | undefined): string {
  if (n === null || n === undefined || !Number.isFinite(n)) return "—"
  const sign = n > 0 ? "+" : ""
  // Indian convention: show full rupee-crore figure with sign.
  return `${sign}₹${Math.round(n).toLocaleString("en-IN")} Cr`
}

function flowClass(n: number | null | undefined): string {
  if (n === null || n === undefined || !Number.isFinite(n)) return "text-caption"
  return n >= 0
    ? "text-green-700 dark:text-green-400"
    : "text-rose-700 dark:text-rose-400"
}

function FlowTile({
  label,
  helper,
  net,
}: {
  label: string
  helper: string
  net: number | null | undefined
}) {
  const direction =
    net === null || net === undefined || !Number.isFinite(net)
      ? "Pending"
      : net >= 0
        ? "Net inflow"
        : "Net outflow"
  return (
    <div
      className="bg-bg dark:bg-surface border border-border rounded-xl p-4"
      data-testid="flow-tile"
    >
      <p className="text-[10px] font-bold uppercase tracking-wider text-caption mb-1">
        {label}
      </p>
      <p
        className={`text-lg font-mono font-semibold tabular-nums ${flowClass(net)}`}
        data-testid="flow-net"
      >
        {formatCr(net)}
      </p>
      <p className="text-[11px] text-caption mt-1">
        {direction} &middot; {helper}
      </p>
    </div>
  )
}

export default function FlowsPanel() {
  // FII/DII flow numbers only exist in the authed /market/pulse payload —
  // the 200-anon /public/indices endpoint carries none. So there is no
  // anon fallback here by design: logged-out users have no token, the
  // query stays disabled (no doomed 401), pulse is undefined, and the
  // hasAnyFlow guard below hides the whole panel. Authed path unchanged.
  const token = useAuthStore((s) => s.token)

  const { data: pulse } = useQuery({
    queryKey: ["markets-strip"],
    queryFn: () => getMarketPulse(true),
    enabled: !!token,
    staleTime: 60 * 1000,
    refetchOnWindowFocus: false,
    retry: 1,
  })

  const fii = pulse?.fii_net_cr
  const dii = pulse?.dii_net_cr
  const fiiDate = pulse?.fii_date
  const stale = pulse?.fii_stale

  // Hide the entire panel when BOTH flows are missing — never surface
  // an empty "Flows" header. When at least one number exists, render
  // both tiles so the layout doesn't shift around as a single tile.
  const hasAnyFlow =
    (fii !== null && fii !== undefined) ||
    (dii !== null && dii !== undefined)
  if (!hasAnyFlow) return null

  return (
    <section>
      <div className="flex items-baseline justify-between gap-3 mb-3">
        <h2 className="text-sm font-bold uppercase tracking-wider text-ink">
          Institutional flows
        </h2>
        {fiiDate && (
          <span className="text-[11px] text-caption font-mono" data-testid="flows-as-of">
            {stale ? "Last reported · " : ""}{fiiDate}
          </span>
        )}
      </div>
      <div className="grid sm:grid-cols-2 gap-3">
        <FlowTile
          label="FII"
          helper="Foreign institutional cash-market net"
          net={fii}
        />
        <FlowTile
          label="DII"
          helper="Domestic institutional cash-market net"
          net={dii}
        />
      </div>
    </section>
  )
}
