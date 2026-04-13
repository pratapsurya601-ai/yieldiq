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
  const now = new Date()
  const points: PricePoint[] = []

  for (let i = days - 1; i >= 0; i--) {
    const date = new Date(now)
    date.setDate(date.getDate() - i)

    const variance = (Math.random() - 0.5) * 0.1 * currentPrice
    const price = Math.round((currentPrice + variance) * 100) / 100

    points.push({
      date: date.toLocaleDateString("en-US", { month: "short", day: "numeric" }),
      price,
    })
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
      return chartResponse.prices.map((p: { date: string; price: number }) => ({
        date: new Date(p.date).toLocaleDateString("en-US", {
          month: "short",
          day: "numeric",
        }),
        price: p.price,
      }))
    }
    // Fallback to mock data
    return generateMockData(currentPrice, PERIOD_DAYS[period] ?? 30)
  }, [chartResponse, currentPrice, period])

  const prices = data.map((d) => d.price)
  const minPrice = Math.min(...prices, fairValue) * 0.98
  const maxPrice = Math.max(...prices, fairValue) * 1.02

  return (
    <div className="rounded-xl bg-white border border-gray-100 p-4 shadow-sm">
      <div className="h-[200px] relative">
        {isLoading && (
          <div className="absolute inset-0 flex items-center justify-center bg-white/70 z-10">
            <div className="h-5 w-5 animate-spin rounded-full border-2 border-blue-600 border-t-transparent" />
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
                ? "bg-blue-50 text-blue-700"
                : "text-gray-500 hover:text-gray-700"
            )}
          >
            {tp.label}
          </button>
        ))}
      </div>
    </div>
  )
}
