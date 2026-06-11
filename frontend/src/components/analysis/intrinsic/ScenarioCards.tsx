"use client"

/**
 * ScenarioCards — Bear / Base / Bull interactive cards for
 * "1. INTRINSIC VALUE" (feat/intrinsic-value-thesis-redesign).
 *
 * Each card carries the per-share scenario value (scenarios.X.iv), the
 * signed % versus the current market price, and an assumption detail
 * row (FCF growth / WACC / terminal growth) that expands on hover OR
 * keyboard focus (focus-within) with a smooth height transition. The
 * Base card is visually emphasized — it is the figure the headline IV
 * narrative anchors on.
 *
 * Interaction: <HoverCard> from the motion library provides the lift +
 * scale 1.02; the expand uses the CSS grid-rows 0fr→1fr trick so no
 * height measurement is needed. Everything snap-cuts under reduced
 * motion. Cards are focusable (tabIndex=0) so the detail row is
 * reachable without a pointer.
 *
 * Copy discipline: assumption lines are descriptive ("assumes…"),
 * values only — no directional language beyond the cleared
 * Discount / Premium-class vocabulary.
 */

import * as React from "react"

import { HoverCard } from "@/components/motion"
import { useReducedMotion } from "@/lib/motion/useReducedMotion"
import { cn, formatCurrency } from "@/lib/utils"
import type { ScenarioCase, ScenariosOutput } from "@/types/api"

export interface ScenarioCardsProps {
  ticker: string
  currency: string
  scenarios: ScenariosOutput | null | undefined
  currentPrice: number | null | undefined
  className?: string
}

type CaseKey = "bear" | "base" | "bull"

const CASE_LABEL: Record<CaseKey, string> = {
  bear: "Bear case",
  base: "Base case",
  bull: "Bull case",
}

const num = (v: number | null | undefined): v is number =>
  v != null && Number.isFinite(v)

function vsPricePct(iv: number, price: number | null | undefined): number | null {
  if (!num(price) || price <= 0) return null
  return ((iv - price) / price) * 100
}

export default function ScenarioCards({
  ticker,
  currency,
  scenarios,
  currentPrice,
  className,
}: ScenarioCardsProps) {
  const reduced = useReducedMotion()
  if (!scenarios) return null

  const cases: Array<{ key: CaseKey; data: ScenarioCase }> = [
    { key: "bear", data: scenarios.bear },
    { key: "base", data: scenarios.base },
    { key: "bull", data: scenarios.bull },
  ].filter((c): c is { key: CaseKey; data: ScenarioCase } =>
    Boolean(c.data && num(c.data.iv) && c.data.iv > 0),
  )
  if (cases.length === 0) return null

  const fmt = (v: number) => formatCurrency(v, currency, ticker)

  return (
    <div data-testid="iv-scenarios" className={className}>
      <p className="text-[11px] uppercase tracking-[0.12em] text-caption">
        Scenario values
      </p>
      <div
        className={cn(
          "mt-2 flex gap-3 overflow-x-auto snap-x snap-mandatory pb-1",
          "md:grid md:grid-cols-3 md:overflow-visible md:pb-0",
        )}
      >
        {cases.map(({ key, data }) => {
          const isBase = key === "base"
          const vs = vsPricePct(data.iv, currentPrice)
          const detail = [
            num(data.growth) ? `FCF growth ${data.growth.toFixed(1)}%` : null,
            num(data.wacc) ? `WACC ${data.wacc.toFixed(1)}%` : null,
            num(data.term_g) ? `terminal ${data.term_g.toFixed(1)}%` : null,
          ].filter(Boolean)

          return (
            <HoverCard
              key={key}
              className={cn(
                "group min-w-[200px] snap-start rounded-xl border p-4 outline-none md:min-w-0",
                "focus-visible:ring-2 focus-visible:ring-brand/50",
                isBase
                  ? "border-brand/50 bg-brand-50/40 dark:bg-brand-50/10"
                  : "border-border bg-surface/60",
              )}
            >
              <div
                data-testid={`iv-scenario-${key}`}
                tabIndex={0}
                aria-label={`${CASE_LABEL[key]}: ${fmt(data.iv)} per share`}
                className="outline-none"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[10px] uppercase tracking-[0.14em] text-caption">
                    {CASE_LABEL[key]}
                  </span>
                  {isBase && (
                    <span className="rounded-full border border-brand/40 bg-brand-50/60 px-2 py-px text-[9px] font-semibold uppercase tracking-wider text-brand dark:bg-brand-50/20">
                      Model base
                    </span>
                  )}
                </div>

                <p className="mt-2 font-mono tabular-nums text-xl md:text-2xl font-semibold text-ink">
                  {fmt(data.iv)}
                </p>

                {vs != null && (
                  <p
                    className={cn(
                      "mt-0.5 font-mono tabular-nums text-[12px] font-medium",
                      vs >= 0
                        ? "text-emerald-600 dark:text-emerald-400"
                        : "text-rose-600 dark:text-rose-400",
                    )}
                  >
                    {vs >= 0 ? "+" : ""}
                    {vs.toFixed(1)}% vs price
                  </p>
                )}

                {/* Assumption detail — grid-rows 0fr→1fr height expand on
                    hover / keyboard focus. */}
                {detail.length > 0 && (
                  <div
                    data-testid={`iv-scenario-detail-${key}`}
                    className={cn(
                      "grid grid-rows-[0fr] group-hover:grid-rows-[1fr] group-focus-within:grid-rows-[1fr]",
                      !reduced && "transition-[grid-template-rows] duration-300 ease-out",
                    )}
                  >
                    <div className="overflow-hidden">
                      <p className="pt-2 text-[11px] leading-snug text-caption">
                        Assumes {detail.join(" · ")}.
                      </p>
                    </div>
                  </div>
                )}
              </div>
            </HoverCard>
          )
        })}
      </div>
      <p className="mt-2 text-[11px] text-caption">
        The full 5-year projection of these paths renders further down the
        page.
      </p>
    </div>
  )
}
