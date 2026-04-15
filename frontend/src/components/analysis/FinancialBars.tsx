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

function generateMockData(currency: string): YearlyData[] {
  // Deterministic mock — no Math.random (causes SSR/client hydration
  // mismatch). Fixed FCF multipliers per index instead.
  const currentYear = new Date().getFullYear()
  const baseRevenue = currency === "INR" ? 5000_00_00_000 : 8_000_000_000
  const baseFcf = currency === "INR" ? 800_00_00_000 : 1_200_000_000
  const fcfMultipliers = [0.95, 1.05, 0.98, 1.08, 1.02]

  return Array.from({ length: 5 }, (_, i) => {
    const growthFactor = 1 + i * 0.12
    return {
      year: `FY${(currentYear - 4 + i).toString().slice(-2)}`,
      revenue: Math.round(baseRevenue * growthFactor),
      fcf: Math.round(baseFcf * growthFactor * fcfMultipliers[i]),
    }
  })
}

export default function FinancialBars({
  ticker,
  currency = "INR",
  revenue: revenueProp,
  fcf: fcfProp,
}: FinancialBarsProps) {
  const data: YearlyData[] = useMemo(() => {
    // If real data is provided, merge revenue and FCF by year
    if (revenueProp?.length || fcfProp?.length) {
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

      // Sort by year and return
      return Array.from(yearMap.values()).sort((a, b) =>
        a.year.localeCompare(b.year)
      )
    }

    // Fallback to mock data
    return generateMockData(currency)
  }, [currency, revenueProp, fcfProp])

  const yFormatter = currency === "INR" ? formatCrore : formatUSD

  const hasData = data.length > 0 && data.some((d) => d.revenue !== 0 || d.fcf !== 0)

  if (!hasData) {
    return (
      <div className="bg-gray-50 border border-gray-100 rounded-xl p-4 text-center">
        <p className="text-sm text-gray-400">Financial data unavailable</p>
      </div>
    )
  }

  return (
    <div className="grid grid-cols-2 gap-3">
      {/* Revenue chart */}
      <div className="rounded-xl bg-white border border-gray-100 p-3 shadow-sm">
        <p className="text-xs font-medium text-gray-500 mb-2">Revenue</p>
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
      <div className="rounded-xl bg-white border border-gray-100 p-3 shadow-sm">
        <p className="text-xs font-medium text-gray-500 mb-2">Free Cash Flow</p>
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
