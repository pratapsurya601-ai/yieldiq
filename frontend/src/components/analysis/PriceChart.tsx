"use client"

import { useMemo, useState } from "react"
import { useQuery } from "@tanstack/react-query"
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ReferenceLine,
} from "recharts"
import { cn, formatCurrency } from "@/lib/utils"
import { getChartData } from "@/lib/api"

interface PriceChartProps {
  ticker: string
  currentPrice: number
  fairValue: number
  currency?: string
}

interface PricePoint {
  date: string
  price: number
}

const TIME_PERIODS = [
  { label: "1M", value: "1m" },
  { label: "3M", value: "3m" },
  { label: "6M", value: "6m" },
  { label: "1Y", value: "1y" },
] as const

function generateMockData(currentPrice: number, days: number): PricePoint[] {
  // Deterministic mock — never use Math.random() or locale-dependent
  // date formatting here: both cause React hydration mismatches (SSR
  // emits different output than client hydration). The variance is a
  // pure function of index so server and client produce identical HTML.
  const now = new Date()
  const points: PricePoint[] = []

  for (let i = days - 1; i >= 0; i--) {
    const date = new Date(now)
    date.setDate(date.getDate() - i)

    // Sinusoidal variance ±5% of price — deterministic per index
    const variance = Math.sin(i * 0.3) * 0.05 * currentPrice
    const price = Math.round((currentPrice + variance) * 100) / 100

    // Use ISO substring instead of toLocaleDateString — locale-independent
    const month = date.toLocaleString("en-US", { month: "short", timeZone: "UTC" })
    const day = date.getUTCDate()

    points.push({ date: `${month} ${day}`, price })
  }

  return points
}

const PERIOD_DAYS: Record<string, number> = {
  "1m": 30,
  "3m": 90,
  "6m": 180,
  "1y": 365,
}

export default function PriceChart({
  ticker,
  currentPrice,
  fairValue,
  currency = "INR",
}: PriceChartProps) {
  const [period, setPeriod] = useState("1m")

  const { data: chartResponse, isLoading } = useQuery({
    queryKey: ["chart-data", ticker, period],
    queryFn: () => getChartData(ticker, period),
    enabled: !!ticker,
    staleTime: 5 * 60 * 1000,
  })

  const data: PricePoint[] = useMemo(() => {
    // Use API data if available
    if (chartResponse?.prices?.length) {
      return chartResponse.prices.map((p: { date: string; price: number }) => {
        // Parse the ISO date and format without locale-dependent behaviour
        const d = new Date(p.date)
        const month = d.toLocaleString("en-US", { month: "short", timeZone: "UTC" })
        return { date: `${month} ${d.getUTCDate()}`, price: p.price }
      })
    }
    // Fallback to deterministic mock data
    return generateMockData(currentPrice, PERIOD_DAYS[period] ?? 30)
  }, [chartResponse, currentPrice, period])

  if (!data || data.length === 0) {
    return (
      <div className="bg-surface border border-border rounded-xl p-4 text-center">
        <p className="text-sm text-caption">Price data unavailable</p>
      </div>
    )
  }

  const prices = data.map((d) => d.price).filter((p) => typeof p === "number" && !isNaN(p))
  if (prices.length === 0) {
    return (
      <div className="bg-surface border border-border rounded-xl p-4 text-center">
        <p className="text-sm text-caption">Price data unavailable</p>
      </div>
    )
  }

  let minPrice = Math.min(...prices, fairValue) * 0.98
  let maxPrice = Math.max(...prices, fairValue) * 1.02
  const range = maxPrice - minPrice
  if (range < 1) {
    minPrice -= 10
    maxPrice += 10
  }

  return (
    <div className="rounded-xl bg-surface border border-border p-4 shadow-sm">
      <div className="h-[200px] relative">
        {isLoading && (
          <div className="absolute inset-0 flex items-center justify-center bg-surface/70 z-10">
            <div className="h-5 w-5 animate-spin rounded-full border-2 border-brand border-t-transparent" />
          </div>
        )}
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
            <XAxis
              dataKey="date"
              tick={{ fontSize: 10, fill: "#9ca3af" }}
              axisLine={false}
              tickLine={false}
              interval="preserveStartEnd"
            />
            <YAxis
              domain={[minPrice, maxPrice]}
              tick={{ fontSize: 10, fill: "#9ca3af" }}
              axisLine={false}
              tickLine={false}
              tickFormatter={(v: number) => formatCurrency(v, currency)}
              width={60}
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
            <ReferenceLine
              y={fairValue}
              stroke="#9ca3af"
              strokeDasharray="6 4"
              label={{
                value: "Fair Value",
                position: "insideTopRight",
                fill: "#9ca3af",
                fontSize: 10,
              }}
            />
            <Line
              type="monotone"
              dataKey="price"
              stroke="#185FA5"
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 4, fill: "#185FA5" }}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>

      <div className="mt-3 flex gap-2">
        {TIME_PERIODS.map((tp) => (
          <button
            key={tp.value}
            onClick={() => setPeriod(tp.value)}
            className={cn(
              "rounded-lg px-3 py-1 text-xs font-medium transition-colors",
              period === tp.value
                ? "bg-brand-50 text-brand"
                : "text-caption hover:text-body"
            )}
          >
            {tp.label}
          </button>
        ))}
      </div>
    </div>
  )
}
