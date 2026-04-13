"use client"

import { useMemo, useState } from "react"
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
  { label: "1M", enabled: true },
  { label: "3M", enabled: false },
  { label: "6M", enabled: false },
  { label: "1Y", enabled: false },
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

export default function PriceChart({
  ticker,
  currentPrice,
  fairValue,
  currency = "INR",
}: PriceChartProps) {
  const [activePeriod, setActivePeriod] = useState("1M")

  const data = useMemo(
    () => generateMockData(currentPrice, 30),
    [currentPrice]
  )

  const prices = data.map((d) => d.price)
  const minPrice = Math.min(...prices, fairValue) * 0.98
  const maxPrice = Math.max(...prices, fairValue) * 1.02

  return (
    <div className="rounded-xl bg-white border border-gray-100 p-4 shadow-sm">
      <div className="h-[200px]">
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
        {TIME_PERIODS.map((period) => (
          <button
            key={period.label}
            disabled={!period.enabled}
            onClick={() => period.enabled && setActivePeriod(period.label)}
            className={cn(
              "rounded-lg px-3 py-1 text-xs font-medium transition-colors",
              activePeriod === period.label
                ? "bg-blue-50 text-blue-700"
                : "text-gray-500 hover:text-gray-700",
              !period.enabled && "cursor-not-allowed opacity-40"
            )}
          >
            {period.label}
          </button>
        ))}
      </div>
    </div>
  )
}
