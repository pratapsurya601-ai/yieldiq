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

interface FinancialBarsProps {
  ticker: string
  currency?: string
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
  const currentYear = new Date().getFullYear()
  const baseRevenue = currency === "INR" ? 5000_00_00_000 : 8_000_000_000
  const baseFcf = currency === "INR" ? 800_00_00_000 : 1_200_000_000

  return Array.from({ length: 5 }, (_, i) => {
    const growthFactor = 1 + i * 0.12
    return {
      year: `FY${(currentYear - 4 + i).toString().slice(-2)}`,
      revenue: Math.round(baseRevenue * growthFactor),
      fcf: Math.round(baseFcf * growthFactor * (0.9 + Math.random() * 0.2)),
    }
  })
}

export default function FinancialBars({
  ticker,
  currency = "INR",
}: FinancialBarsProps) {
  const data = useMemo(() => generateMockData(currency), [currency])

  const yFormatter = currency === "INR" ? formatCrore : formatUSD

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
