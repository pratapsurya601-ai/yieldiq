"use client"

/**
 * ValuationDrivers — "What drives this reading" strip of
 * "1. INTRINSIC VALUE" (feat/intrinsic-value-thesis-redesign).
 *
 * Three sector-aware data-driven cards. Banks read growth / returns /
 * margin-or-efficiency from the bank-native quality fields; non-banks
 * read revenue CAGR / ROE-or-ROCE / FCF-yield. Each card carries one
 * DESCRIPTIVE context sentence — verbs are reads / sits / runs, never
 * imperative, never advisory.
 *
 * Null discipline (house rule): a driver with a null value self-hides;
 * when fewer than 2 drivers survive, the whole strip self-hides. Never
 * an em-dash card, never a fabricated zero.
 *
 * Driver selection is the exported pure `resolveDrivers` so the
 * fallback chains are unit-testable without a DOM.
 */

import * as React from "react"
import {
  Banknote,
  Gauge,
  Percent,
  TrendingUp,
  type LucideIcon,
} from "lucide-react"

import { RevealStagger } from "@/components/motion"
import { cn } from "@/lib/utils"
import type { AnalysisResponse, QualityOutput } from "@/types/api"

export interface DriverSpec {
  key: string
  /** Card title, e.g. "Returns". */
  label: string
  /** Big formatted value, e.g. "8.8%". */
  value: string
  /** One-line descriptive context sentence. */
  context: string
  icon: LucideIcon
}

export interface ResolveDriversInput {
  quality?: QualityOutput | null
  sectorMedians?: AnalysisResponse["sector_medians"]
  /** insights.fcf_yield (percent) for the non-bank cash card. */
  fcfYield?: number | null
}

const num = (v: number | null | undefined): v is number =>
  v != null && Number.isFinite(v)

const pct1 = (v: number) => `${v.toFixed(1)}%`
const signedPct1 = (v: number) => `${v >= 0 ? "+" : ""}${v.toFixed(1)}%`

/** Sector-aware driver resolution with per-slot fallback chains. */
export function resolveDrivers(input: ResolveDriversInput): DriverSpec[] {
  const q = input.quality
  if (!q) return []
  const medians = input.sectorMedians
  const drivers: DriverSpec[] = []

  const pushReturns = () => {
    if (num(q.roe)) {
      const vs =
        medians && num(medians.roe)
          ? ` against a sector median of ${pct1(medians.roe)}`
          : ""
      drivers.push({
        key: "returns",
        label: "Returns",
        value: pct1(q.roe),
        context: `Return on equity reads ${pct1(q.roe)}${vs}.`,
        icon: Percent,
      })
      return true
    }
    return false
  }

  if (q.is_bank) {
    // Growth — advances, then deposits, then bank revenue YoY.
    if (num(q.advances_yoy)) {
      drivers.push({
        key: "growth",
        label: "Growth",
        value: signedPct1(q.advances_yoy),
        context: `Advances read ${signedPct1(q.advances_yoy)} year over year.`,
        icon: TrendingUp,
      })
    } else if (num(q.deposits_yoy)) {
      drivers.push({
        key: "growth",
        label: "Growth",
        value: signedPct1(q.deposits_yoy),
        context: `Deposits read ${signedPct1(q.deposits_yoy)} year over year.`,
        icon: TrendingUp,
      })
    } else if (num(q.revenue_yoy_bank)) {
      drivers.push({
        key: "growth",
        label: "Growth",
        value: signedPct1(q.revenue_yoy_bank),
        context: `Revenue reads ${signedPct1(q.revenue_yoy_bank)} year over year.`,
        icon: TrendingUp,
      })
    }

    // Returns — ROE, then ROA.
    if (!pushReturns() && num(q.roa)) {
      drivers.push({
        key: "returns",
        label: "Returns",
        value: pct1(q.roa),
        context: `Return on assets reads ${pct1(q.roa)} on the latest filings.`,
        icon: Percent,
      })
    }

    // Margin / efficiency — NIM, then CASA, then cost-to-income.
    if (num(q.nim)) {
      drivers.push({
        key: "margin",
        label: "Margin",
        value: pct1(q.nim),
        context: `Net interest margin sits at ${pct1(q.nim)} on the latest filings.`,
        icon: Gauge,
      })
    } else if (num(q.casa)) {
      drivers.push({
        key: "margin",
        label: "Deposit mix",
        value: pct1(q.casa),
        context: `The CASA share of deposits sits at ${pct1(q.casa)}.`,
        icon: Gauge,
      })
    } else if (num(q.cost_to_income)) {
      drivers.push({
        key: "margin",
        label: "Efficiency",
        value: pct1(q.cost_to_income),
        context: `Cost-to-income runs at ${pct1(q.cost_to_income)}.`,
        icon: Gauge,
      })
    }
    return drivers
  }

  // ── Non-banks ──────────────────────────────────────────────────────
  // Growth — revenue CAGR (decimal on the wire), then historical FCF growth.
  if (num(q.revenue_cagr_3y)) {
    const v = q.revenue_cagr_3y * 100
    drivers.push({
      key: "growth",
      label: "Growth",
      value: pct1(v),
      context: `Revenue compounded at ${pct1(v)} a year over the trailing three years.`,
      icon: TrendingUp,
    })
  }

  // Returns — ROE (vs sector when present), then ROCE.
  const usedRoe = pushReturns()
  if (!usedRoe && num(q.roce)) {
    drivers.push({
      key: "returns",
      label: "Returns",
      value: pct1(q.roce),
      context: `Return on capital employed reads ${pct1(q.roce)}.`,
      icon: Percent,
    })
  }

  // Cash — FCF yield, then ROCE (when not already the returns card).
  if (num(input.fcfYield)) {
    drivers.push({
      key: "cash",
      label: "Cash generation",
      value: pct1(input.fcfYield),
      context: `Free-cash-flow yield reads ${pct1(input.fcfYield)} at the current price.`,
      icon: Banknote,
    })
  } else if (usedRoe && num(q.roce)) {
    drivers.push({
      key: "cash",
      label: "Capital efficiency",
      value: pct1(q.roce),
      context: `Return on capital employed reads ${pct1(q.roce)}.`,
      icon: Banknote,
    })
  }

  return drivers
}

export interface ValuationDriversProps extends ResolveDriversInput {
  className?: string
}

export default function ValuationDrivers({
  quality,
  sectorMedians,
  fcfYield,
  className,
}: ValuationDriversProps) {
  const drivers = resolveDrivers({ quality, sectorMedians, fcfYield })
  // Fewer than 2 usable drivers → the strip earns no space at all.
  if (drivers.length < 2) return null

  return (
    <div data-testid="iv-drivers" className={className}>
      <p className="text-[11px] uppercase tracking-[0.12em] text-caption">
        What drives this reading
      </p>
      <RevealStagger
        staggerMs={80}
        className={cn(
          "mt-2 flex gap-3 overflow-x-auto snap-x snap-mandatory pb-1",
          "md:grid md:gap-3 md:overflow-visible md:pb-0",
          drivers.length === 2 ? "md:grid-cols-2" : "md:grid-cols-3",
        )}
      >
        {drivers.map((d) => (
          <div
            key={d.key}
            data-testid={`iv-driver-${d.key}`}
            className="min-w-[220px] snap-start rounded-xl border border-border bg-surface/60 p-4 md:min-w-0"
          >
            <div className="flex items-center gap-2">
              <d.icon aria-hidden className="h-4 w-4 shrink-0 text-brand" />
              <span className="text-[10px] uppercase tracking-[0.14em] text-caption">
                {d.label}
              </span>
            </div>
            <p className="mt-2 font-mono tabular-nums text-2xl font-semibold text-ink">
              {d.value}
            </p>
            <p className="mt-1 text-[12px] leading-snug text-body">
              {d.context}
            </p>
          </div>
        ))}
      </RevealStagger>
    </div>
  )
}
