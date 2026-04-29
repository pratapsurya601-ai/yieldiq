"use client"

// BacktestResults — KPI header, equity curve, monthly returns heatmap,
// holdings table. Renders the BacktestResult shape returned by the
// /api/v1/strategies/run endpoint.

import { useState } from "react"
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"
import { cn } from "@/lib/utils"
import type { BacktestResult } from "@/lib/strategyTypes"

interface Props {
  result: BacktestResult
  onSave?: () => void
  onShare?: () => void
  shareUrl?: string | null
  isReadOnly?: boolean
}

const KPI_CARD = "rounded-xl border border-border bg-white p-3"

function fmtPct(v: number | undefined | null, sign = false): string {
  if (v === undefined || v === null || Number.isNaN(v)) return "—"
  const s = sign && v > 0 ? "+" : ""
  return `${s}${v.toFixed(2)}%`
}

export default function BacktestResults({
  result,
  onSave,
  onShare,
  shareUrl,
  isReadOnly,
}: Props) {
  const [logScale, setLogScale] = useState(false)

  if (result.error && !result.curve) {
    return (
      <div className="rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">
        {result.error}
      </div>
    )
  }

  const m = result.metrics || {}
  const curve = result.curve || []
  const holdings = result.holdings || []
  const monthly = result.monthly_returns || []

  return (
    <div className="space-y-4">
      {/* ── KPI strip ──────────────────────────────────────────── */}
      <div className="grid grid-cols-2 sm:grid-cols-5 gap-2">
        <Kpi
          label="Total return"
          value={fmtPct(m.total_return_pct, true)}
          accent={m.total_return_pct && m.total_return_pct > 0 ? "pos" : "neg"}
        />
        <Kpi label="CAGR" value={fmtPct(m.cagr_pct, true)} />
        <Kpi label="Max drawdown" value={fmtPct(m.max_drawdown_pct)} accent="neg" />
        <Kpi label="Sharpe (proxy)" value={(m.sharpe_proxy ?? 0).toFixed(2)} />
        <Kpi
          label="vs Benchmark"
          value={fmtPct(m.outperformance_pct, true)}
          accent={m.outperformance_pct && m.outperformance_pct > 0 ? "pos" : "neg"}
        />
      </div>

      {/* ── Equity curve ───────────────────────────────────────── */}
      <section className="rounded-2xl border border-border bg-white p-4">
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-sm font-semibold text-ink">
            Equity curve {result.years ? `(${result.years}y)` : ""}
          </h3>
          <label className="flex items-center gap-1 text-xs text-caption">
            <input
              type="checkbox"
              checked={logScale}
              onChange={(e) => setLogScale(e.target.checked)}
            />
            Log scale
          </label>
        </div>
        <div className="h-64 w-full">
          <ResponsiveContainer>
            <LineChart data={curve} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
              <CartesianGrid stroke="#eef0f3" strokeDasharray="3 3" />
              <XAxis dataKey="date" tick={{ fontSize: 11 }} minTickGap={32} />
              <YAxis
                scale={logScale ? "log" : "auto"}
                domain={logScale ? ["auto", "auto"] : [0, "auto"]}
                tick={{ fontSize: 11 }}
                width={50}
              />
              <Tooltip />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Line
                type="monotone"
                dataKey="portfolio"
                name="Strategy"
                stroke="#2563eb"
                strokeWidth={2}
                dot={false}
              />
              <Line
                type="monotone"
                dataKey="benchmark"
                name={result.benchmark || "Benchmark"}
                stroke="#94a3b8"
                strokeWidth={1.5}
                strokeDasharray="4 4"
                dot={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </section>

      {/* ── Monthly returns heatmap ─────────────────────────────── */}
      {monthly.length > 0 && <MonthlyHeatmap rows={monthly} />}

      {/* ── Holdings ────────────────────────────────────────────── */}
      {holdings.length > 0 && (
        <section className="rounded-2xl border border-border bg-white p-4">
          <h3 className="text-sm font-semibold text-ink mb-3">
            Holdings at last rebalance ({holdings.length})
          </h3>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="text-caption">
                <tr className="text-left">
                  <th className="py-1 pr-3">Ticker</th>
                  <th className="py-1 pr-3">Company</th>
                  <th className="py-1 pr-3">Sector</th>
                  <th className="py-1 pr-3 text-right">Score</th>
                  <th className="py-1 pr-3 text-right">MoS %</th>
                  <th className="py-1 text-right">Weight</th>
                </tr>
              </thead>
              <tbody className="text-ink">
                {holdings.slice(0, 50).map((h) => (
                  <tr key={h.ticker} className="border-t border-gray-100">
                    <td className="py-1 pr-3 font-mono">{h.ticker.replace(".NS", "")}</td>
                    <td className="py-1 pr-3">{h.company_name || "—"}</td>
                    <td className="py-1 pr-3 text-caption">{h.sector || "—"}</td>
                    <td className="py-1 pr-3 text-right">
                      {h.score !== undefined && h.score !== null ? Math.round(h.score) : "—"}
                    </td>
                    <td className="py-1 pr-3 text-right">
                      {h.mos !== undefined && h.mos !== null ? h.mos.toFixed(1) : "—"}
                    </td>
                    <td className="py-1 text-right">{h.weight_pct.toFixed(1)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* ── Save & share ────────────────────────────────────────── */}
      {!isReadOnly && (onSave || onShare) && (
        <div className="flex items-center gap-2">
          {onSave && (
            <button
              type="button"
              onClick={onSave}
              className="rounded-lg border border-blue-500 px-3 py-1.5 text-xs font-medium text-blue-700 hover:bg-blue-50"
            >
              Save strategy
            </button>
          )}
          {onShare && (
            <button
              type="button"
              onClick={onShare}
              className="rounded-lg border border-border px-3 py-1.5 text-xs font-medium text-ink hover:bg-gray-50"
            >
              Share strategy
            </button>
          )}
          {shareUrl && (
            <a
              href={shareUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs text-blue-600 hover:underline"
            >
              {shareUrl}
            </a>
          )}
        </div>
      )}

      {/* ── Disclaimer ──────────────────────────────────────────── */}
      <p className="text-[11px] text-caption">
        Backtests use the CURRENT stocks matching your rules — survivorship bias present.
        Past performance does not guarantee future results.
        {result.tickers_dropped ? ` ${result.tickers_dropped} ticker(s) dropped due to missing price history.` : ""}
      </p>
    </div>
  )
}

function Kpi({
  label,
  value,
  accent,
}: {
  label: string
  value: string
  accent?: "pos" | "neg"
}) {
  return (
    <div className={KPI_CARD}>
      <div className="text-[11px] uppercase tracking-wide text-caption">{label}</div>
      <div
        className={cn(
          "mt-1 text-lg font-semibold",
          accent === "pos" && "text-green-600",
          accent === "neg" && "text-red-600",
          !accent && "text-ink",
        )}
      >
        {value}
      </div>
    </div>
  )
}

// ── Monthly returns heatmap ─────────────────────────────────────────
function MonthlyHeatmap({ rows }: { rows: { year: number; month: number; return_pct: number }[] }) {
  const years = Array.from(new Set(rows.map((r) => r.year))).sort()
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

  const lookup = new Map<string, number>()
  rows.forEach((r) => lookup.set(`${r.year}-${r.month}`, r.return_pct))

  function color(v: number | undefined): string {
    if (v === undefined) return "#f3f4f6"
    const clamped = Math.max(-12, Math.min(12, v))
    if (clamped >= 0) {
      const a = Math.min(1, clamped / 12)
      return `rgba(34, 197, 94, ${0.15 + 0.7 * a})`
    } else {
      const a = Math.min(1, -clamped / 12)
      return `rgba(239, 68, 68, ${0.15 + 0.7 * a})`
    }
  }

  return (
    <section className="rounded-2xl border border-border bg-white p-4">
      <h3 className="text-sm font-semibold text-ink mb-3">Monthly returns</h3>
      <div className="overflow-x-auto">
        <table className="w-full text-[11px]">
          <thead>
            <tr className="text-caption">
              <th className="py-1 pr-2 text-left">Year</th>
              {months.map((m) => (
                <th key={m} className="px-1 py-1 text-center">
                  {m}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {years.map((y) => (
              <tr key={y}>
                <td className="py-1 pr-2 text-caption">{y}</td>
                {months.map((_, mi) => {
                  const v = lookup.get(`${y}-${mi + 1}`)
                  return (
                    <td
                      key={mi}
                      className="px-1 py-1 text-center"
                      style={{ background: color(v) }}
                      title={v !== undefined ? `${y}-${mi + 1}: ${v.toFixed(2)}%` : "—"}
                    >
                      {v !== undefined ? v.toFixed(1) : ""}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}
