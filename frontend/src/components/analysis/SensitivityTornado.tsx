"use client"

/* ------------------------------------------------------------------ *
 * SensitivityTornado — horizontal-bar "tornado" chart of per-input FV
 * sensitivity. Re-uses recharts (already in the bundle) for a stacked
 * horizontal BarChart pinned at base FV.
 *
 * Each row shows:
 *   ── downside leg (left of base) — FV when input moves the BAD way
 *   ── upside leg (right of base) — FV when input moves the GOOD way
 *
 * Sorted by total swing (most-impactful at top). Teaches users which
 * assumption is worth the most scrutiny for THIS specific stock —
 * NIM for banks, terminal margin for SaaS, capex for cement.
 * ------------------------------------------------------------------ */

import { useMemo } from "react"
import { useQuery } from "@tanstack/react-query"
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ReferenceLine,
  Cell,
} from "recharts"
import { getSensitivity, type SensitivityRow } from "@/lib/api"
import { formatCurrency } from "@/lib/utils"

interface Props {
  ticker: string
  currency: string
}

interface ChartRow {
  input: string
  /** Negative offset from base — drawn left of the centre line */
  downOffset: number
  /** Positive offset from base — drawn right of the centre line */
  upOffset: number
  raw: SensitivityRow
}

function formatDelta(row: SensitivityRow): string {
  if (row.unit === "bps") {
    const lo = row.delta_low > 0 ? `+${row.delta_low}` : `${row.delta_low}`
    const hi = row.delta_high > 0 ? `+${row.delta_high}` : `${row.delta_high}`
    return `${lo} / ${hi} bps`
  }
  const lo = row.delta_low > 0 ? `+${row.delta_low}` : `${row.delta_low}`
  const hi = row.delta_high > 0 ? `+${row.delta_high}` : `${row.delta_high}`
  return `${lo}% / ${hi}%`
}

export default function SensitivityTornado({ ticker, currency }: Props) {
  const query = useQuery({
    queryKey: ["sensitivity", ticker],
    queryFn: () => getSensitivity(ticker),
    // Server caches 24h; client cache for the page lifetime is enough.
    staleTime: 60 * 60 * 1000,
    retry: 1,
  })

  const data = query.data
  const baseFv = data?.base_fair_value ?? 0

  const chartRows: ChartRow[] = useMemo(() => {
    if (!data || !data.sensitivities?.length || baseFv <= 0) return []
    // Already sorted server-side by swing_pct DESC. Recharts plots
    // the FIRST row at the BOTTOM of the y-axis, so reverse for the
    // most-impactful-at-top convention users expect from a tornado.
    return [...data.sensitivities].reverse().map((s) => {
      // fv_low / fv_high may be in either order depending on whether
      // moving the input "up" is good or bad. We always plot the
      // smaller leg as "down" (red) and the larger as "up" (green)
      // around the base FV — the legend explains the unit.
      const lo = Math.min(s.fv_low, s.fv_high)
      const hi = Math.max(s.fv_low, s.fv_high)
      return {
        input: s.input,
        // Negative number so recharts draws to the left of x=0
        // when we set domain symmetric around base — but we shift by
        // base, so use raw offsets from base instead.
        downOffset: lo - baseFv,
        upOffset: hi - baseFv,
        raw: s,
      }
    })
  }, [data, baseFv])

  const top3 = useMemo(() => {
    if (!data?.sensitivities) return []
    return data.sensitivities.slice(0, 3)
  }, [data])

  if (query.isLoading) {
    return (
      <div className="bg-bg rounded-2xl border border-border p-5">
        <div className="h-4 w-48 bg-surface rounded animate-pulse mb-3" />
        <div className="h-48 bg-surface rounded animate-pulse" />
      </div>
    )
  }

  if (query.isError || !data || data.error || !chartRows.length) {
    return null
  }

  // Compute symmetric x-domain so the centre line sits at the base FV.
  const maxAbs = chartRows.reduce(
    (m, r) => Math.max(m, Math.abs(r.downOffset), Math.abs(r.upOffset)),
    0,
  )
  const pad = maxAbs * 0.1 || 1
  const domain: [number, number] = [-(maxAbs + pad), maxAbs + pad]

  return (
    <div className="bg-bg rounded-2xl border border-border p-5">
      <div className="mb-4">
        <h2 className="text-sm font-semibold text-ink">
          What matters most for this stock
        </h2>
        <p className="text-xs text-caption mt-0.5">
          How fair value swings when each assumption is perturbed.
          Centre line is the base fair value of {formatCurrency(baseFv, currency)}.
          Sorted by total swing — top row is the most-impactful input.
        </p>
      </div>

      <div className="h-[260px] w-full">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart
            data={chartRows}
            layout="vertical"
            stackOffset="sign"
            margin={{ top: 4, right: 12, bottom: 4, left: 8 }}
            barCategoryGap={6}
          >
            <XAxis
              type="number"
              domain={domain}
              tickFormatter={(v: number) =>
                formatCurrency(baseFv + v, currency)
              }
              tick={{ fontSize: 10, fill: "currentColor" }}
              className="text-caption"
            />
            <YAxis
              type="category"
              dataKey="input"
              tick={{ fontSize: 11, fill: "currentColor" }}
              width={140}
              className="text-ink"
            />
            <ReferenceLine x={0} stroke="currentColor" strokeOpacity={0.5} />
            <Tooltip
              cursor={{ fill: "rgba(0,0,0,0.04)" }}
              contentStyle={{
                fontSize: 11,
                borderRadius: 8,
                border: "1px solid var(--color-border)",
                background: "var(--color-bg)",
              }}
              formatter={(value) => {
                // value is offset from base; show absolute FV
                const offset = typeof value === "number" ? value : Number(value) || 0
                return [formatCurrency(baseFv + offset, currency), "Fair value"]
              }}
              labelFormatter={(label, payload) => {
                const row = payload?.[0]?.payload as ChartRow | undefined
                if (!row) return label
                return `${label} (${formatDelta(row.raw)}, swing ${row.raw.swing_pct}%)`
              }}
            />
            <Bar dataKey="downOffset" stackId="t" radius={[2, 0, 0, 2]}>
              {chartRows.map((_, i) => (
                <Cell key={`d-${i}`} fill="#dc2626" fillOpacity={0.85} />
              ))}
            </Bar>
            <Bar dataKey="upOffset" stackId="t" radius={[0, 2, 2, 0]}>
              {chartRows.map((_, i) => (
                <Cell key={`u-${i}`} fill="#16a34a" fillOpacity={0.85} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      {top3.length > 0 ? (
        <div className="mt-4 border-t border-border pt-3 text-xs text-ink">
          <p className="font-semibold mb-1.5">
            Most-sensitive inputs for {ticker}:
          </p>
          <ol className="space-y-1 list-decimal list-inside text-caption">
            {top3.map((s) => {
              const swingAbs = Math.abs(s.fv_high - s.fv_low) / 2
              return (
                <li key={s.input}>
                  <span className="text-ink font-medium">{s.input}</span>
                  {" "}
                  ({formatDelta(s)} → {formatCurrency(swingAbs, currency)} swing)
                </li>
              )
            })}
          </ol>
          <p className="mt-2 text-[11px] text-caption italic">
            Why this matters: small changes to your assumption about{" "}
            <span className="text-ink not-italic font-medium">
              {top3[0].input}
            </span>{" "}
            have outsized impact on fair value. Worth getting right.
          </p>
        </div>
      ) : null}
    </div>
  )
}
