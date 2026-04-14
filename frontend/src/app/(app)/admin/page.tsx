"use client"
import { useEffect, useState } from "react"
import { useAuthStore } from "@/store/authStore"
import { useRouter } from "next/navigation"
import api from "@/lib/api"

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
    <div className="bg-white rounded-2xl border border-gray-100 p-5">
      <p className="text-xs text-gray-400 uppercase tracking-wide">{label}</p>
      <p className="text-2xl font-bold text-gray-900 mt-1">{value}</p>
      {sub && <p className="text-xs text-gray-500 mt-0.5">{sub}</p>}
    </div>
  )
}

export default function AdminPage() {
  const { email } = useAuthStore()
  const router = useRouter()
  const [stats, setStats] = useState<AdminStats | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")

  useEffect(() => {
    if (!email || !ADMIN_EMAILS.includes(email)) {
      router.push("/home")
      return
    }
    api.get("/api/v1/admin/stats")
      .then((r) => setStats(r.data))
      .catch((e) => setError(e?.response?.data?.detail || "Failed to load stats"))
      .finally(() => setLoading(false))
  }, [email, router])

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
        <h1 className="text-xl font-bold text-gray-900">Admin Dashboard</h1>
        <p className="text-sm text-gray-500">Real-time platform metrics</p>
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
        <div className="bg-white rounded-2xl border border-gray-100 p-5">
          <h2 className="text-sm font-semibold text-gray-900 mb-3">Top Analysed Stocks Today</h2>
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
    </div>
  )
}
