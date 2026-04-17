"use client"

import Link from "next/link"
import { useState, useMemo } from "react"
import {
  ResponsiveContainer, ComposedChart, LineChart, Line, BarChart, Bar,
  XAxis, YAxis, Tooltip, CartesianGrid, ReferenceLine,
} from "recharts"

interface SeriesPoint {
  date: string
  close: number
  sma_20: number | null
  sma_50: number | null
  sma_200: number | null
  rsi_14: number | null
  macd: number | null
  macd_signal: number | null
  macd_histogram: number | null
  boll_upper: number | null
  boll_lower: number | null
}

interface TechData {
  ticker: string
  series: SeriesPoint[]
  latest: {
    close: number
    sma_20: number | null
    sma_50: number | null
    sma_200: number | null
    rsi_14: number | null
    macd: number | null
    macd_signal: number | null
    rsi_zone: string | null
    sma_position: string | null
    macd_state: string | null
  }
  days_in_sample: number
}

type Indicator = "sma" | "bollinger"

function regimeBadge(label: string | null): { text: string; cls: string } {
  if (!label) return { text: "—", cls: "bg-gray-100 text-gray-600" }
  const map: Record<string, { text: string; cls: string }> = {
    overbought_zone: { text: "Overbought zone (RSI ≥ 70)", cls: "bg-red-50 text-red-700" },
    oversold_zone: { text: "Oversold zone (RSI ≤ 30)", cls: "bg-green-50 text-green-700" },
    neutral_zone: { text: "Neutral zone (RSI 30-70)", cls: "bg-blue-50 text-blue-700" },
    above_200dma: { text: "Above 200-day MA", cls: "bg-green-50 text-green-700" },
    below_200dma: { text: "Below 200-day MA", cls: "bg-amber-50 text-amber-700" },
    macd_above_signal: { text: "MACD above signal line", cls: "bg-green-50 text-green-700" },
    macd_below_signal: { text: "MACD below signal line", cls: "bg-amber-50 text-amber-700" },
  }
  return map[label] || { text: label, cls: "bg-gray-100 text-gray-600" }
}

function fmtDate(s: string): string {
  try {
    return new Date(s).toLocaleDateString("en-IN", { month: "short", year: "2-digit" })
  } catch {
    return s
  }
}

export default function TechnicalsClient({ data, ticker }: { data: TechData; ticker: string }) {
  const display = ticker.toUpperCase().replace(".NS", "").replace(".BO", "")
  const [overlay, setOverlay] = useState<Indicator>("sma")

  const latest = data.latest
  const rsiBadge = regimeBadge(latest.rsi_zone)
  const smaBadge = regimeBadge(latest.sma_position)
  const macdBadge = regimeBadge(latest.macd_state)

  // Pre-format chart-ready data
  const chartData = useMemo(() => data.series.map(p => ({ ...p, dateLabel: fmtDate(p.date) })), [data.series])

  return (
    <div className="max-w-5xl mx-auto px-4 py-8">
      {/* Breadcrumb */}
      <nav className="text-xs text-gray-400 mb-6 flex items-center gap-1.5">
        <Link href="/" className="hover:text-gray-600">Home</Link>
        <span>/</span>
        <Link href={`/stocks/${display}/fair-value`} className="hover:text-gray-600">{display}</Link>
        <span>/</span>
        <span className="text-gray-600 font-medium">Technicals</span>
      </nav>

      <div className="mb-8">
        <p className="text-blue-600 text-xs font-bold tracking-[0.2em] uppercase mb-2">Technical Indicators</p>
        <h1 className="text-2xl sm:text-3xl font-black text-gray-900 mb-2">
          {display} Technical Reference
        </h1>
        <p className="text-gray-500 text-sm">
          SMA, RSI, MACD, Bollinger Bands. Factual reference data — not buy/sell signals.
        </p>
      </div>

      {/* Latest snapshot */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
        <div className="bg-white border border-gray-200 rounded-xl p-4">
          <p className="text-[10px] text-gray-400 uppercase tracking-wider mb-1">Close</p>
          <p className="text-xl font-bold text-gray-900 font-mono">₹{latest.close.toLocaleString("en-IN")}</p>
        </div>
        <div className="bg-white border border-gray-200 rounded-xl p-4">
          <p className="text-[10px] text-gray-400 uppercase tracking-wider mb-1">RSI(14)</p>
          <p className="text-xl font-bold text-gray-900">{latest.rsi_14 ?? "—"}</p>
          <p className={`text-[10px] mt-1 px-2 py-0.5 rounded-full font-semibold inline-block ${rsiBadge.cls}`}>{rsiBadge.text}</p>
        </div>
        <div className="bg-white border border-gray-200 rounded-xl p-4">
          <p className="text-[10px] text-gray-400 uppercase tracking-wider mb-1">200 DMA</p>
          <p className="text-xl font-bold text-gray-900 font-mono">₹{latest.sma_200?.toLocaleString("en-IN") ?? "—"}</p>
          <p className={`text-[10px] mt-1 px-2 py-0.5 rounded-full font-semibold inline-block ${smaBadge.cls}`}>{smaBadge.text}</p>
        </div>
        <div className="bg-white border border-gray-200 rounded-xl p-4">
          <p className="text-[10px] text-gray-400 uppercase tracking-wider mb-1">MACD</p>
          <p className="text-xl font-bold text-gray-900">{latest.macd?.toFixed(2) ?? "—"}</p>
          <p className={`text-[10px] mt-1 px-2 py-0.5 rounded-full font-semibold inline-block ${macdBadge.cls}`}>{macdBadge.text}</p>
        </div>
      </div>

      {/* Price chart with overlay toggle */}
      <div className="bg-white border border-gray-200 rounded-2xl p-4 sm:p-6 mb-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-sm font-bold text-gray-900">Price + Overlay</h2>
          <div className="flex bg-gray-100 rounded-lg p-1 text-xs">
            <button
              onClick={() => setOverlay("sma")}
              className={`px-3 py-1 rounded-md font-semibold transition ${overlay === "sma" ? "bg-white text-gray-900 shadow-sm" : "text-gray-500"}`}
            >
              SMA 20/50/200
            </button>
            <button
              onClick={() => setOverlay("bollinger")}
              className={`px-3 py-1 rounded-md font-semibold transition ${overlay === "bollinger" ? "bg-white text-gray-900 shadow-sm" : "text-gray-500"}`}
            >
              Bollinger Bands
            </button>
          </div>
        </div>
        <ResponsiveContainer width="100%" height={320}>
          <ComposedChart data={chartData}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
            <XAxis dataKey="dateLabel" tick={{ fontSize: 10 }} interval="preserveStartEnd" />
            <YAxis tick={{ fontSize: 10 }} domain={["auto", "auto"]} />
            <Tooltip
              labelStyle={{ fontSize: 11 }}
              contentStyle={{ fontSize: 11, borderRadius: 8 }}
              formatter={(value: unknown) => typeof value === "number" ? value.toFixed(2) : "—"}
            />
            <Line type="monotone" dataKey="close" stroke="#1D4ED8" strokeWidth={2} dot={false} name="Close" />
            {overlay === "sma" && (
              <>
                <Line type="monotone" dataKey="sma_20" stroke="#10B981" strokeWidth={1} dot={false} name="SMA 20" />
                <Line type="monotone" dataKey="sma_50" stroke="#F59E0B" strokeWidth={1} dot={false} name="SMA 50" />
                <Line type="monotone" dataKey="sma_200" stroke="#EF4444" strokeWidth={1} dot={false} name="SMA 200" />
              </>
            )}
            {overlay === "bollinger" && (
              <>
                <Line type="monotone" dataKey="boll_upper" stroke="#94A3B8" strokeWidth={1} strokeDasharray="3 3" dot={false} name="Upper Band" />
                <Line type="monotone" dataKey="boll_lower" stroke="#94A3B8" strokeWidth={1} strokeDasharray="3 3" dot={false} name="Lower Band" />
              </>
            )}
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      {/* RSI chart */}
      <div className="bg-white border border-gray-200 rounded-2xl p-4 sm:p-6 mb-6">
        <h2 className="text-sm font-bold text-gray-900 mb-3">RSI(14)</h2>
        <ResponsiveContainer width="100%" height={180}>
          <LineChart data={chartData}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
            <XAxis dataKey="dateLabel" tick={{ fontSize: 10 }} interval="preserveStartEnd" />
            <YAxis tick={{ fontSize: 10 }} domain={[0, 100]} />
            <Tooltip labelStyle={{ fontSize: 11 }} contentStyle={{ fontSize: 11, borderRadius: 8 }} formatter={(value: unknown) => typeof value === "number" ? value.toFixed(1) : "—"} />
            <ReferenceLine y={70} stroke="#EF4444" strokeDasharray="3 3" label={{ value: "70", fontSize: 10, fill: "#EF4444" }} />
            <ReferenceLine y={30} stroke="#10B981" strokeDasharray="3 3" label={{ value: "30", fontSize: 10, fill: "#10B981" }} />
            <Line type="monotone" dataKey="rsi_14" stroke="#7C3AED" strokeWidth={2} dot={false} name="RSI" />
          </LineChart>
        </ResponsiveContainer>
        <p className="text-[10px] text-gray-400 mt-2">RSI ≥ 70 = overbought zone; RSI ≤ 30 = oversold zone. These are descriptive labels, not trade recommendations.</p>
      </div>

      {/* MACD chart */}
      <div className="bg-white border border-gray-200 rounded-2xl p-4 sm:p-6 mb-6">
        <h2 className="text-sm font-bold text-gray-900 mb-3">MACD (12, 26, 9)</h2>
        <ResponsiveContainer width="100%" height={180}>
          <ComposedChart data={chartData}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
            <XAxis dataKey="dateLabel" tick={{ fontSize: 10 }} interval="preserveStartEnd" />
            <YAxis tick={{ fontSize: 10 }} />
            <Tooltip labelStyle={{ fontSize: 11 }} contentStyle={{ fontSize: 11, borderRadius: 8 }} formatter={(value: unknown) => typeof value === "number" ? value.toFixed(2) : "—"} />
            <ReferenceLine y={0} stroke="#9CA3AF" strokeDasharray="3 3" />
            <Bar dataKey="macd_histogram" fill="#3B82F6" opacity={0.5} name="Histogram" />
            <Line type="monotone" dataKey="macd" stroke="#1D4ED8" strokeWidth={2} dot={false} name="MACD" />
            <Line type="monotone" dataKey="macd_signal" stroke="#F59E0B" strokeWidth={2} dot={false} name="Signal" />
          </ComposedChart>
        </ResponsiveContainer>
        <p className="text-[10px] text-gray-400 mt-2">MACD line crossing above/below signal line is a directional indicator, not a buy/sell instruction.</p>
      </div>

      {/* Disclaimer */}
      <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 mb-6">
        <p className="text-xs font-bold text-amber-800 uppercase tracking-wider mb-1">Important</p>
        <p className="text-sm text-amber-900 leading-relaxed">
          Technical indicators show <b>what prices have done</b>, not what they will do. RSI, MACD, and moving averages
          are reference tools, not buy/sell signals. Combine with fundamentals (DCF, quality scores) for context.
        </p>
      </div>

      {/* CTA */}
      <div className="bg-gradient-to-r from-blue-600 to-cyan-500 rounded-2xl p-6 text-center text-white mb-8">
        <h2 className="text-lg font-bold mb-1">See fundamentals for {display}</h2>
        <p className="text-blue-100 text-sm mb-4">Combine technicals with DCF fair value.</p>
        <Link href={`/stocks/${display}/fair-value`} className="inline-block bg-white text-blue-700 font-bold px-6 py-2.5 rounded-xl hover:bg-blue-50 transition text-sm">
          See Fair Value &rarr;
        </Link>
      </div>

      <p className="text-[10px] text-gray-400 text-center">
        Indicators computed from {data.days_in_sample} days of price history.
        YieldIQ is not registered with SEBI as an investment adviser.
      </p>
    </div>
  )
}
