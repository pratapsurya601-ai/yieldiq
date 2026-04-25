"use client"

import { useMemo, useState } from "react"
import type { StockSummary } from "@/lib/api"

/**
 * DCF Sensitivity Heatmap (Task C1)
 * --------------------------------------------------------------------------
 * Interactive WACC × Terminal-Growth grid that previews how the fair value
 * changes if you nudge the two main DCF assumptions. The heatmap is a pure
 * SVG/CSS implementation — no chart libs, no backend round-trips.
 *
 * Math note (mock recompute): we approximate the published fair value as a
 * Gordon-Growth surface anchored on the cached (wacc, base_case) point.
 *
 *     FV(w, g) = base_case * (wacc - g_anchor) / (w - g)
 *
 * with g_anchor inferred from the published wacc and a conservative 4%
 * terminal growth (matches the backend's default tg). This is a linear-ish
 * extrapolation — the cell colors and ordering are correct even if the
 * absolute rupee value drifts a few percent from the canonical engine.
 * Once /api/v1/public/dcf-sensitivity/{ticker} ships, swap the closure
 * below for a fetch and keep the rendering the same.
 */

const WACC_STEP = 0.005      // 0.5%
const WACC_MIN = 0.08
const WACC_MAX = 0.16
const TG_STEP = 0.005        // 0.5%
const TG_MIN = 0.01
const TG_MAX = 0.06

const WACC_VALUES: number[] = []
for (let w = WACC_MIN; w <= WACC_MAX + 1e-9; w += WACC_STEP) WACC_VALUES.push(Number(w.toFixed(4)))
const TG_VALUES: number[] = []
for (let g = TG_MIN; g <= TG_MAX + 1e-9; g += TG_STEP) TG_VALUES.push(Number(g.toFixed(4)))

function fmtRupee(n: number): string {
  if (!isFinite(n) || n <= 0) return "—"
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 0,
  }).format(n)
}

function mosColor(mosPct: number): string {
  // Diverging palette: red → neutral → green, clamped at ±50%.
  const clamped = Math.max(-50, Math.min(50, mosPct))
  if (clamped >= 0) {
    // 0 → 50 maps to a soft → strong green using --color-success palette
    const t = clamped / 50
    const r = Math.round(240 - 140 * t)
    const g = Math.round(253 - 30 * t)
    const b = Math.round(244 - 100 * t)
    return `rgb(${r}, ${g}, ${b})`
  }
  const t = -clamped / 50
  const r = Math.round(254 - 14 * t)
  const g = Math.round(242 - 110 * t)
  const b = Math.round(242 - 120 * t)
  return `rgb(${r}, ${g}, ${b})`
}

function textColorFor(mosPct: number): string {
  return Math.abs(mosPct) > 30 ? "#FFFFFF" : "var(--color-ink, #0F172A)"
}

interface Props {
  ticker: string
  summary: StockSummary
}

interface ScenarioCell {
  wacc: number
  tg: number
  fv: number
  mos: number
}

export default function DCFSensitivityHeatmap({ ticker, summary }: Props) {
  const baseFV = summary.base_case || summary.fair_value
  const baseWACC = summary.wacc && summary.wacc > 0 ? summary.wacc : 0.12
  const baseTG = 0.04 // backend default terminal growth
  const cmp = summary.current_price

  const compute = useMemo(() => {
    // Pre-derive a Gordon-style "implied perpetuity cash flow" so that the
    // surface passes exactly through (baseWACC, baseTG) → baseFV.
    const impliedNumerator = baseFV * (baseWACC - baseTG)
    return (wacc: number, tg: number): number => {
      const spread = wacc - tg
      if (spread <= 0.001) return NaN // numerically unstable / negative
      return impliedNumerator / spread
    }
  }, [baseFV, baseWACC, baseTG])

  const grid: ScenarioCell[][] = useMemo(() => {
    return TG_VALUES.map(tg =>
      WACC_VALUES.map(wacc => {
        const fv = compute(wacc, tg)
        const mos = cmp > 0 && isFinite(fv) ? ((fv - cmp) / fv) * 100 : NaN
        return { wacc, tg, fv, mos }
      }),
    )
  }, [compute, cmp])

  const [selected, setSelected] = useState<ScenarioCell | null>(null)

  return (
    <section
      className="rounded-2xl border bg-bg dark:bg-surface p-5 sm:p-6"
      style={{ borderColor: "var(--color-border, #E2E8F0)" }}
    >
      <header className="mb-4">
        <h2 className="text-lg font-bold" style={{ color: "var(--color-ink, #0F172A)" }}>
          DCF Sensitivity — {ticker.toUpperCase()}
        </h2>
        <p className="text-xs text-caption mt-1">
          How the fair value (and margin of safety vs. current price{" "}
          <span className="font-mono">{fmtRupee(cmp)}</span>) shifts as you change
          WACC (cost of capital) and terminal growth. Click any cell to lock it
          as a “what-if” scenario.
        </p>
      </header>

      <div className="overflow-x-auto">
        <table className="w-full border-separate" style={{ borderSpacing: 0 }}>
          <thead>
            <tr>
              <th
                className="sticky left-0 z-10 bg-bg dark:bg-surface text-[10px] font-semibold text-caption uppercase tracking-wider px-2 py-2 text-left"
                style={{ borderBottom: "1px solid var(--color-border, #E2E8F0)" }}
              >
                TG ↓ \ WACC →
              </th>
              {WACC_VALUES.map(w => (
                <th
                  key={w}
                  className="text-[10px] font-mono text-caption px-1 py-2 text-center"
                  style={{ borderBottom: "1px solid var(--color-border, #E2E8F0)" }}
                >
                  {(w * 100).toFixed(1)}%
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {grid.map((row, i) => (
              <tr key={TG_VALUES[i]}>
                <td
                  className="sticky left-0 z-10 bg-bg dark:bg-surface text-[10px] font-mono text-caption px-2 py-1 text-left"
                  style={{ borderRight: "1px solid var(--color-border, #E2E8F0)" }}
                >
                  {(TG_VALUES[i] * 100).toFixed(1)}%
                </td>
                {row.map(cell => {
                  const isAnchor =
                    Math.abs(cell.wacc - baseWACC) < WACC_STEP / 2 &&
                    Math.abs(cell.tg - baseTG) < TG_STEP / 2
                  const isSelected =
                    selected &&
                    Math.abs(cell.wacc - selected.wacc) < 1e-6 &&
                    Math.abs(cell.tg - selected.tg) < 1e-6
                  return (
                    <td key={cell.wacc} className="p-0.5">
                      <button
                        type="button"
                        onClick={() => setSelected(cell)}
                        className="w-full h-12 rounded-md text-[11px] font-mono leading-tight transition focus:outline-none focus:ring-2"
                        style={{
                          background: isFinite(cell.fv) ? mosColor(cell.mos) : "#F1F5F9",
                          color: isFinite(cell.fv) ? textColorFor(cell.mos) : "#94A3B8",
                          outline: isAnchor
                            ? "2px solid var(--color-brand, #2563EB)"
                            : isSelected
                              ? "2px dashed var(--color-ink, #0F172A)"
                              : "none",
                          outlineOffset: isAnchor || isSelected ? "-2px" : undefined,
                        }}
                        title={`WACC ${(cell.wacc * 100).toFixed(1)}% / TG ${(cell.tg * 100).toFixed(1)}% → FV ${fmtRupee(cell.fv)} (MoS ${isFinite(cell.mos) ? cell.mos.toFixed(1) + "%" : "—"})`}
                        aria-label={`WACC ${(cell.wacc * 100).toFixed(1)} percent, terminal growth ${(cell.tg * 100).toFixed(1)} percent`}
                      >
                        <span className="block font-semibold">{fmtRupee(cell.fv)}</span>
                        <span className="block opacity-80">
                          {isFinite(cell.mos) ? `${cell.mos >= 0 ? "+" : ""}${cell.mos.toFixed(0)}%` : "—"}
                        </span>
                      </button>
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="mt-4 grid sm:grid-cols-2 gap-3">
        <div
          className="rounded-xl border p-3"
          style={{ borderColor: "var(--color-border, #E2E8F0)" }}
        >
          <p className="text-[10px] uppercase tracking-wider text-caption">
            Anchor (published)
          </p>
          <p className="text-sm font-mono mt-1" style={{ color: "var(--color-ink, #0F172A)" }}>
            WACC {(baseWACC * 100).toFixed(1)}% · TG {(baseTG * 100).toFixed(1)}% → FV {fmtRupee(baseFV)}
          </p>
          <p className="text-xs text-caption mt-1">
            MoS{" "}
            <span className={summary.mos >= 0 ? "text-green-600 dark:text-green-400" : "text-red-600 dark:text-red-400"}>
              {summary.mos >= 0 ? "+" : ""}{summary.mos.toFixed(1)}%
            </span>
          </p>
        </div>
        <div
          className="rounded-xl border p-3"
          style={{ borderColor: "var(--color-border, #E2E8F0)" }}
        >
          <p className="text-[10px] uppercase tracking-wider text-caption">
            Selected scenario
          </p>
          {selected ? (
            <>
              <p className="text-sm font-mono mt-1" style={{ color: "var(--color-ink, #0F172A)" }}>
                WACC {(selected.wacc * 100).toFixed(1)}% · TG {(selected.tg * 100).toFixed(1)}% → FV {fmtRupee(selected.fv)}
              </p>
              <p className="text-xs text-caption mt-1">
                MoS{" "}
                <span className={selected.mos >= 0 ? "text-green-600 dark:text-green-400" : "text-red-600 dark:text-red-400"}>
                  {isFinite(selected.mos) ? `${selected.mos >= 0 ? "+" : ""}${selected.mos.toFixed(1)}%` : "—"}
                </span>
              </p>
            </>
          ) : (
            <p className="text-xs text-caption mt-2">Click a cell to lock a “what-if”.</p>
          )}
        </div>
      </div>

      <p className="mt-3 text-[10px] text-caption">
        Mock recompute via Gordon-Growth extrapolation around the published
        anchor — exact figures will sync once the dedicated DCF-sensitivity
        endpoint ships.
      </p>
    </section>
  )
}
