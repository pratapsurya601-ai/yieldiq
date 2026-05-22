"use client"
import { useEffect, useState } from "react"
import { useAuthStore } from "@/store/authStore"
import { useRouter } from "next/navigation"
import api from "@/lib/api"

// Distinct error class so the Sentry dashboard filter
// `error.type:SentryClientProbeError` cleanly separates the Day-101
// readiness probe from real production errors.
class SentryClientProbeError extends Error {
  constructor(msg: string) {
    super(msg)
    this.name = "SentryClientProbeError"
  }
}

const ADMIN_EMAILS = ["pratapsurya601@gmail.com", "suryasbss601@gmail.com"]

interface AdminStats {
  total_users: number
  users_today: number
  analyses_today: number
  paid_users: number
  revenue_monthly: number
  top_stocks_today: string[]
  errors_today: number
  db_size_mb: number
  cache_hit_rate: number
}

function StatCard({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <div className="bg-bg dark:bg-surface rounded-2xl border border-gray-100 p-5">
      <p className="text-xs text-caption uppercase tracking-wide">{label}</p>
      <p className="text-2xl font-bold text-ink mt-1">{value}</p>
      {sub && <p className="text-xs text-caption mt-0.5">{sub}</p>}
    </div>
  )
}

export default function AdminPage() {
  const { email } = useAuthStore()
  const router = useRouter()
  const [stats, setStats] = useState<AdminStats | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")

  // Wait for Zustand persist hydration before redirecting non-admins.
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
    api.get("/api/v1/admin/stats")
      .then((r) => setStats(r.data))
      .catch((e) => setError(e?.response?.data?.detail || "Failed to load stats"))
      .finally(() => setLoading(false))
  }, [hydrated, email, router])

  if (!hydrated) return null
  if (!email || !ADMIN_EMAILS.includes(email)) {
    return null
  }

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

  if (!stats) return null

  return (
    <div className="max-w-4xl mx-auto px-4 py-8 space-y-6 pb-20">
      <div>
        <h1 className="text-xl font-bold text-ink">Admin Dashboard</h1>
        <p className="text-sm text-caption">Real-time platform metrics</p>
      </div>

      {/* Stat Cards Grid */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
        <StatCard label="Total Users" value={stats.total_users} />
        <StatCard label="Users Today" value={stats.users_today} />
        <StatCard label="Analyses Today" value={stats.analyses_today} />
        <StatCard label="Paid Users" value={stats.paid_users} />
        <StatCard
          label="Monthly Revenue"
          value={`\u20b9${stats.revenue_monthly.toLocaleString()}`}
        />
        <StatCard label="Errors Today" value={stats.errors_today} />
        <StatCard label="DB Size" value={`${stats.db_size_mb} MB`} />
        <StatCard
          label="Cache Hit Rate"
          value={`${(stats.cache_hit_rate * 100).toFixed(0)}%`}
        />
      </div>

      {/* Top Stocks */}
      {stats.top_stocks_today.length > 0 && (
        <div className="bg-bg dark:bg-surface rounded-2xl border border-gray-100 p-5">
          <h2 className="text-sm font-semibold text-ink mb-3">Top Analysed Stocks Today</h2>
          <div className="flex flex-wrap gap-2">
            {stats.top_stocks_today.map((ticker) => (
              <span
                key={ticker}
                className="px-3 py-1 bg-blue-50 text-blue-700 rounded-full text-xs font-medium"
              >
                {ticker.replace(".NS", "").replace(".BO", "")}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Operator tools */}
      <div className="bg-bg dark:bg-surface rounded-2xl border border-gray-100 p-5">
        <h2 className="text-sm font-semibold text-ink mb-3">Operator tools</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <a
            href="/admin/realty"
            className="rounded-xl border border-gray-100 p-4 hover:border-blue-200 hover:bg-blue-50/40 transition"
          >
            <p className="text-sm font-semibold text-ink">Realty land-bank inputs</p>
            <p className="text-xs text-caption mt-0.5">
              Approach C engine curation (annual operator pass)
            </p>
          </a>
          <a
            href="/admin/insurance"
            className="rounded-xl border border-gray-100 p-4 hover:border-blue-200 hover:bg-blue-50/40 transition"
          >
            <p className="text-sm font-semibold text-ink">Insurance EV inputs</p>
            <p className="text-xs text-caption mt-0.5">
              Appraisal value (life insurers)
            </p>
          </a>
          <a
            href="/admin/outliers"
            className="rounded-xl border border-gray-100 p-4 hover:border-blue-200 hover:bg-blue-50/40 transition"
          >
            <p className="text-sm font-semibold text-ink">Benchmark reconciliation</p>
            <p className="text-xs text-caption mt-0.5">
              Outlier tickers vs consensus (daily)
            </p>
          </a>
          <a
            href="/admin/story-dcf"
            className="rounded-xl border border-gray-100 p-4 hover:border-blue-200 hover:bg-blue-50/40 transition"
          >
            <p className="text-sm font-semibold text-ink">Story-DCF overrides</p>
            <p className="text-xs text-caption mt-0.5">
              View + simulate (operator submits PR to change)
            </p>
          </a>
        </div>
      </div>

      {/* Sentry readiness probes (Day-101). Two buttons that throw
          deliberate, distinct error types so the Sentry dashboard can
          confirm both backend and client capture end-to-end before
          the first paying user hits the flow. */}
      <div className="bg-bg dark:bg-surface rounded-2xl border border-amber-100 p-5">
        <h2 className="text-sm font-semibold text-ink mb-1">Sentry readiness probes</h2>
        <p className="text-xs text-caption mb-3">
          Admin-only. Each button throws a labeled synthetic exception.
          See <code>docs/runbooks/sentry-verify-2026-05-22.md</code>.
        </p>
        <div className="flex flex-wrap gap-3">
          <button
            type="button"
            onClick={() => {
              api.get("/api/v1/admin/sentry-probe").catch(() => {
                // expected 500 — the endpoint raises by design
              })
            }}
            className="px-4 py-2 rounded-lg border border-amber-200 bg-amber-50 text-amber-900 text-xs font-medium hover:bg-amber-100"
          >
            Trigger backend error
          </button>
          <button
            type="button"
            onClick={() => {
              // Throw on a microtask so React's error boundary catches it
              // and Sentry's Next.js integration ships an event.
              setTimeout(() => {
                throw new SentryClientProbeError(
                  "Day-101 client-side Sentry probe — admin /admin button",
                )
              }, 0)
            }}
            className="px-4 py-2 rounded-lg border border-amber-200 bg-amber-50 text-amber-900 text-xs font-medium hover:bg-amber-100"
          >
            Trigger client error
          </button>
        </div>
      </div>
    </div>
  )
}
