"use client"

// Day-101c (2026-05-22) — PWA install funnel dashboard.
//
// Reads GET /api/v1/admin/pwa-funnel (admin-gated; see
// backend.routers.telemetry.admin_router). Persistent telemetry lands
// in pwa_telemetry_events via migration 050, written best-effort by
// the same router that already logged events since Day-100a.
//
// Three big numbers at the top, a 7-day line chart of prompted vs
// installed, and a table of the four event counts.

import { useEffect, useState } from "react"
import { useAuthStore } from "@/store/authStore"
import { useRouter } from "next/navigation"
import api from "@/lib/api"
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  Legend,
} from "recharts"

const ADMIN_EMAILS = ["pratapsurya601@gmail.com", "suryasbss601@gmail.com"]

interface DailyRow {
  date: string
  prompted: number
  installed: number
  dismissed: number
  ios_hint_shown: number
}

interface FunnelResponse {
  window_days: number
  totals: {
    prompted: number
    installed: number
    dismissed: number
    ios_hint_shown: number
  }
  conversion_rate: number
  dismissal_rate: number
  daily_breakdown: DailyRow[]
}

function BigStat({
  label,
  value,
  sub,
}: {
  label: string
  value: string | number
  sub?: string
}) {
  return (
    <div className="bg-bg dark:bg-surface rounded-2xl border border-gray-100 p-6">
      <p className="text-xs text-caption uppercase tracking-wide">{label}</p>
      <p className="text-3xl font-bold text-ink mt-2">{value}</p>
      {sub && <p className="text-xs text-caption mt-1">{sub}</p>}
    </div>
  )
}

export default function PwaFunnelPage() {
  const { email } = useAuthStore()
  const router = useRouter()
  const [data, setData] = useState<FunnelResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")

  const [hydrated, setHydrated] = useState(false)
  useEffect(() => {
    if (useAuthStore.persist.hasHydrated()) {
      setHydrated(true)
      return
    }
    const unsub = useAuthStore.persist.onFinishHydration(() => setHydrated(true))
    return unsub
  }, [])

  useEffect(() => {
    if (!hydrated) return
    if (!email || !ADMIN_EMAILS.includes(email)) {
      router.push("/home")
      return
    }
    api
      .get<FunnelResponse>("/api/v1/admin/pwa-funnel")
      .then((r) => setData(r.data))
      .catch((e) =>
        setError(e?.response?.data?.detail || "Failed to load funnel data"),
      )
      .finally(() => setLoading(false))
  }, [hydrated, email, router])

  if (!hydrated) return null
  if (!email || !ADMIN_EMAILS.includes(email)) return null

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="h-6 w-6 animate-spin rounded-full border-2 border-blue-600 border-t-transparent" />
      </div>
    )
  }

  if (error) {
    return (
      <div className="max-w-md mx-auto px-4 py-16 text-center">
        <p className="text-lg font-medium text-red-600">{error}</p>
      </div>
    )
  }

  if (!data) return null

  const conversionPct = (data.conversion_rate * 100).toFixed(1)
  const dismissalPct = (data.dismissal_rate * 100).toFixed(1)

  return (
    <div className="max-w-5xl mx-auto px-4 py-8 space-y-6 pb-20">
      <div>
        <h1 className="text-xl font-bold text-ink">
          PWA Install Funnel ({data.window_days}d)
        </h1>
        <p className="text-sm text-caption">
          Conversion of install prompts → completed installs. Aggregated
          from <code className="text-xs">pwa_telemetry_events</code>.
        </p>
      </div>

      {/* Three big numbers */}
      <div
        data-testid="pwa-funnel-stats"
        className="grid grid-cols-1 md:grid-cols-3 gap-3"
      >
        <BigStat
          label="Prompted (7d)"
          value={data.totals.prompted}
          sub="Native install prompt fired"
        />
        <BigStat
          label="Installed (7d)"
          value={data.totals.installed}
          sub="appinstalled event received"
        />
        <BigStat
          label="Conversion"
          value={`${conversionPct}%`}
          sub={`Dismissal ${dismissalPct}%`}
        />
      </div>

      {/* Daily line chart */}
      <div className="bg-bg dark:bg-surface rounded-2xl border border-gray-100 p-4">
        <h2 className="text-sm font-semibold text-ink mb-3">
          Daily prompted vs installed
        </h2>
        <div data-testid="pwa-funnel-chart" className="w-full h-[320px]">
          {data.daily_breakdown.length === 0 ? (
            <div className="flex h-full items-center justify-center text-sm text-caption">
              No events in the last {data.window_days} days yet.
            </div>
          ) : (
            <ResponsiveContainer width="100%" height="100%">
              <LineChart
                data={data.daily_breakdown}
                margin={{ top: 8, right: 16, left: 0, bottom: 8 }}
              >
                <CartesianGrid
                  strokeDasharray="3 3"
                  stroke="var(--color-border)"
                />
                <XAxis
                  dataKey="date"
                  tick={{ fill: "var(--color-caption)", fontSize: 12 }}
                  stroke="var(--color-border)"
                />
                <YAxis
                  allowDecimals={false}
                  tick={{ fill: "var(--color-caption)", fontSize: 12 }}
                  stroke="var(--color-border)"
                />
                <Tooltip
                  contentStyle={{
                    background: "var(--color-surface)",
                    border: "1px solid var(--color-border)",
                    borderRadius: 8,
                    color: "var(--color-ink)",
                    fontSize: 12,
                  }}
                />
                <Legend
                  wrapperStyle={{ fontSize: 12, color: "var(--color-body)" }}
                />
                <Line
                  type="monotone"
                  dataKey="prompted"
                  name="Prompted"
                  stroke="var(--color-brand)"
                  strokeWidth={2.5}
                  dot={{ r: 3, fill: "var(--color-brand)" }}
                />
                <Line
                  type="monotone"
                  dataKey="installed"
                  name="Installed"
                  stroke="var(--color-caption)"
                  strokeWidth={2}
                  dot={{ r: 3, fill: "var(--color-caption)" }}
                />
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>

      {/* Event counts table */}
      <div className="bg-bg dark:bg-surface rounded-2xl border border-gray-100 p-4">
        <h2 className="text-sm font-semibold text-ink mb-3">
          Event counts ({data.window_days}d)
        </h2>
        <table className="min-w-full text-sm">
          <thead className="text-caption">
            <tr className="border-b border-border">
              <th className="py-2 pr-3 text-left font-semibold">Event</th>
              <th className="py-2 pr-3 text-right font-semibold">Count</th>
            </tr>
          </thead>
          <tbody>
            <tr className="border-b border-gray-100">
              <td className="py-2 pr-3 text-ink">prompted</td>
              <td className="py-2 pr-3 text-right">{data.totals.prompted}</td>
            </tr>
            <tr className="border-b border-gray-100">
              <td className="py-2 pr-3 text-ink">installed</td>
              <td className="py-2 pr-3 text-right">{data.totals.installed}</td>
            </tr>
            <tr className="border-b border-gray-100">
              <td className="py-2 pr-3 text-ink">dismissed</td>
              <td className="py-2 pr-3 text-right">{data.totals.dismissed}</td>
            </tr>
            <tr>
              <td className="py-2 pr-3 text-ink">ios_hint_shown</td>
              <td className="py-2 pr-3 text-right">
                {data.totals.ios_hint_shown}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  )
}
