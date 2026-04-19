"use client"

import { useMemo } from "react"
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
} from "recharts"
import { formatCurrency } from "@/lib/utils"

interface FinancialDataPoint {
  year: string
  value: number
}

interface FinancialBarsProps {
  ticker: string
  currency?: string
  revenue?: FinancialDataPoint[]
  fcf?: FinancialDataPoint[]
}

interface YearlyData {
  year: string
  revenue: number
  fcf: number
}

function formatCrore(value: number): string {
  if (Math.abs(value) >= 1e7) return `${(value / 1e7).toFixed(0)}Cr`
  if (Math.abs(value) >= 1e5) return `${(value / 1e5).toFixed(0)}L`
  return value.toLocaleString("en-IN")
}

function formatUSD(value: number): string {
  if (Math.abs(value) >= 1e9) return `$${(value / 1e9).toFixed(1)}B`
  if (Math.abs(value) >= 1e6) return `$${(value / 1e6).toFixed(0)}M`
  return `$${value.toLocaleString("en-US")}`
}

export default function FinancialBars({
  ticker,
  currency = "INR",
  revenue: revenueProp,
  fcf: fcfProp,
}: FinancialBarsProps) {
  const data: YearlyData[] = useMemo(() => {
    // Merge revenue + FCF by year. No synthetic fallback — if the
    // backend returned nothing, we show an empty state below, never
    // fictional numbers (regulatory + trust concern).
    if (!revenueProp?.length && !fcfProp?.length) return []

    const yearMap = new Map<string, YearlyData>()
    for (const r of revenueProp ?? []) {
      yearMap.set(r.year, { year: r.year, revenue: r.value, fcf: 0 })
    }
    for (const f of fcfProp ?? []) {
      const existing = yearMap.get(f.year)
      if (existing) {
        existing.fcf = f.value
      } else {
        yearMap.set(f.year, { year: f.year, revenue: 0, fcf: f.value })
      }
    }
    return Array.from(yearMap.values()).sort((a, b) =>
      a.year.localeCompare(b.year)
    )
  }, [revenueProp, fcfProp])

  const yFormatter = currency === "INR" ? formatCrore : formatUSD

  const hasData = data.length > 0 && data.some((d) => d.revenue !== 0 || d.fcf !== 0)

  if (!hasData) {
    return (
      <div className="bg-surface border border-border rounded-xl p-4 text-center">
        <p className="text-sm text-caption">Financial data unavailable</p>
      </div>
    )
  }

  return (
    <div className="grid grid-cols-2 gap-3">
      {/* Revenue chart */}
      <div className="rounded-xl bg-surface border border-border p-3 shadow-sm">
        <p className="text-xs font-medium text-caption mb-2">Revenue</p>
        <div className="h-[180px]">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
              <XAxis
                dataKey="year"
                tick={{ fontSize: 9, fill: "#9ca3af" }}
                axisLine={false}
                tickLine={false}
              />
              <YAxis
                tick={{ fontSize: 9, fill: "#9ca3af" }}
                axisLine={false}
                tickLine={false}
                tickFormatter={yFormatter}
                width={48}
              />
              <Tooltip
                content={({ active, payload, label }) => {
                  if (!active || !payload?.length) return null
                  const value = payload[0].value as number
                  return (
                    <div className="rounded-lg bg-gray-900 px-3 py-2 text-xs text-white shadow-lg">
                      <p className="text-gray-400">{label}</p>
                      <p className="font-semibold">{formatCurrency(value, currency)}</p>
                    </div>
                  )
                }}
              />
              <Bar dataKey="revenue" fill="#185FA5" radius={[3, 3, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* FCF chart */}
      <div className="rounded-xl bg-surface border border-border p-3 shadow-sm">
        <p className="text-xs font-medium text-caption mb-2">Free Cash Flow</p>
        <div className="h-[180px]">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
              <XAxis
                dataKey="year"
                tick={{ fontSize: 9, fill: "#9ca3af" }}
                axisLine={false}
                tickLine={false}
              />
              <YAxis
                tick={{ fontSize: 9, fill: "#9ca3af" }}
                axisLine={false}
                tickLine={false}
                tickFormatter={yFormatter}
                width={48}
              />
              <Tooltip
                content={({ active, payload, label }) => {
                  if (!active || !payload?.length) return null
                  const value = payload[0].value as number
                  return (
                    <div className="rounded-lg bg-gray-900 px-3 py-2 text-xs text-white shadow-lg">
                      <p className="text-gray-400">{label}</p>
                      <p className="font-semibold">{formatCurrency(value, currency)}</p>
                    </div>
                  )
                }}
              />
              <Bar dataKey="fcf" fill="#06B6D4" radius={[3, 3, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  )
}
