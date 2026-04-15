"use client"

import type { MarketPulseResponse } from "@/types/api"
import { cn } from "@/lib/utils"

interface Props {
  pulse: MarketPulseResponse
  ai_summary?: string | null
}

/* ------------------------------------------------------------------ */
/* Formatters                                                          */
/* ------------------------------------------------------------------ */
function fmtCr(v: number): string {
  const abs = Math.abs(v)
  if (abs >= 100_000) return `₹${(abs / 100_000).toFixed(1)}L Cr`
  if (abs >= 1_000) return `₹${(abs / 1_000).toFixed(1)}K Cr`
  return `₹${abs.toFixed(0)} Cr`
}

function vixZone(v: number): { label: string; color: string } {
  if (v < 15) return { label: "😌 Calm", color: "text-green-600" }
  if (v < 20) return { label: "⚠ Caution", color: "text-yellow-600" }
  return { label: "😰 Fear", color: "text-red-600" }
}

// 1 troy ounce = 31.1035 grams. Convert spot USD/oz to INR/<unit>.
const TROY_OZ_G = 31.1035
function metalInrPer(grams: number, usdPerOz: number, usdInr: number): number {
  return (usdPerOz / TROY_OZ_G) * grams * usdInr
}
function fmtInrLakh(v: number): string {
  // Indian-style comma grouping, no decimals.
  return `\u20b9${Math.round(v).toLocaleString("en-IN")}`
}

/* ------------------------------------------------------------------ */
/* Small card primitive                                                */
/* ------------------------------------------------------------------ */
function Card({
  title,
  children,
  borderClass,
}: {
  title: string
  children: React.ReactNode
  borderClass?: string
}) {
  return (
    <div
      className={cn(
        "flex-shrink-0 bg-white rounded-xl border border-gray-100 px-4 py-3 min-w-[120px] text-center",
        borderClass && `border-l-[3px] ${borderClass}`,
      )}
    >
      <p className="text-[10px] font-bold text-gray-400 uppercase tracking-wider">
        {title}
      </p>
      {children}
    </div>
  )
}

function Dash() {
  return <p className="text-lg font-bold text-gray-300">—</p>
}

/* ------------------------------------------------------------------ */
/* Main                                                                */
/* ------------------------------------------------------------------ */
export default function MacroDashboard({ pulse, ai_summary }: Props) {
  // Prefer the explicit prop (from the separate /macro-summary query
  // which has its own 24-hour cache), fall back to whatever came in
  // on the pulse response.
  const summary = ai_summary ?? pulse.ai_summary ?? null
  const fii = pulse.fii_net_cr
  const dii = pulse.dii_net_cr
  const vix = pulse.fear_greed_index

  // If we have literally no macro fields, render nothing — the
  // existing indices strip below us already shows Nifty/Sensex/Bank.
  const hasAnyMacro = [
    fii, dii, pulse.usd_inr, pulse.gold_usd,
    pulse.silver_usd, pulse.risk_free_pct, vix,
  ].some(v => v !== null && v !== undefined)
  if (!hasAnyMacro) return null

  const fiiColor =
    fii === null || fii === undefined ? ""
    : fii > 0 ? "border-l-green-500"
    : fii < 0 ? "border-l-red-500"
    : ""
  const diiColor =
    dii === null || dii === undefined ? ""
    : dii > 0 ? "border-l-green-500"
    : dii < 0 ? "border-l-red-500"
    : ""
  const vixInfo = vix !== null && vix !== undefined ? vixZone(vix) : null

  return (
    <div className="space-y-3">
      {/* Row 1 — Flows & Sentiment */}
      <div className="flex gap-2 overflow-x-auto pb-1">
        <Card title="FII Today" borderClass={fiiColor}>
          {fii === null || fii === undefined ? (
            <Dash />
          ) : (
            <>
              <p
                className={cn(
                  "text-lg font-bold tabular-nums",
                  fii > 0 ? "text-green-700" : fii < 0 ? "text-red-700" : "text-gray-700",
                )}
              >
                {fii > 0 ? "+" : fii < 0 ? "-" : ""}
                {fmtCr(fii)}
              </p>
              <p
                className={cn(
                  "text-[10px] font-bold",
                  fii > 0 ? "text-green-500" : fii < 0 ? "text-red-500" : "text-gray-400",
                )}
              >
                {fii > 0 ? "▲ BUYING" : fii < 0 ? "▼ SELLING" : "— FLAT"}
              </p>
            </>
          )}
          {pulse.fii_date && (
            <p className="text-[9px] text-gray-400 mt-0.5">{pulse.fii_date}</p>
          )}
        </Card>

        <Card title="DII Today" borderClass={diiColor}>
          {dii === null || dii === undefined ? (
            <Dash />
          ) : (
            <>
              <p
                className={cn(
                  "text-lg font-bold tabular-nums",
                  dii > 0 ? "text-green-700" : dii < 0 ? "text-red-700" : "text-gray-700",
                )}
              >
                {dii > 0 ? "+" : dii < 0 ? "-" : ""}
                {fmtCr(dii)}
              </p>
              <p
                className={cn(
                  "text-[10px] font-bold",
                  dii > 0 ? "text-green-500" : dii < 0 ? "text-red-500" : "text-gray-400",
                )}
              >
                {dii > 0 ? "▲ BUYING" : dii < 0 ? "▼ SELLING" : "— FLAT"}
              </p>
            </>
          )}
        </Card>

        <Card title="India VIX" borderClass="border-l-amber-500">
          {vix === null || vix === undefined ? (
            <Dash />
          ) : (
            <>
              <p className="text-lg font-bold text-gray-900 tabular-nums">
                {vix.toFixed(1)}
              </p>
              <p className={cn("text-[10px] font-bold", vixInfo?.color)}>
                {vixInfo?.label}
              </p>
            </>
          )}
        </Card>
      </div>

      {/* Row 2 — Rates & Commodities */}
      <div className="flex gap-2 overflow-x-auto pb-1">
        <Card title="USD / INR">
          {pulse.usd_inr === null || pulse.usd_inr === undefined ? (
            <Dash />
          ) : (
            <>
              <p className="text-lg font-bold text-gray-900 tabular-nums">
                ₹{pulse.usd_inr.toFixed(2)}
              </p>
              <p className="text-[10px] text-gray-400">1 USD</p>
            </>
          )}
        </Card>

        <Card title="Gold">
          {pulse.gold_usd && pulse.usd_inr ? (
            <>
              <p className="text-lg font-bold text-gray-900 tabular-nums">
                {fmtInrLakh(metalInrPer(10, pulse.gold_usd, pulse.usd_inr))}
              </p>
              <p className="text-[10px] text-gray-400">per 10g</p>
            </>
          ) : (
            <Dash />
          )}
        </Card>

        <Card title="Silver">
          {pulse.silver_usd && pulse.usd_inr ? (
            <>
              <p className="text-lg font-bold text-gray-900 tabular-nums">
                {fmtInrLakh(metalInrPer(1000, pulse.silver_usd, pulse.usd_inr))}
              </p>
              <p className="text-[10px] text-gray-400">per kg</p>
            </>
          ) : (
            <Dash />
          )}
        </Card>

        <Card title="10Y G-Sec">
          {pulse.risk_free_pct === null || pulse.risk_free_pct === undefined ? (
            <Dash />
          ) : (
            <>
              <p className="text-lg font-bold text-gray-900 tabular-nums">
                {pulse.risk_free_pct.toFixed(2)}%
              </p>
              <p className="text-[10px] text-gray-400">Risk-free</p>
            </>
          )}
        </Card>
      </div>

      {/* AI summary — only when populated */}
      {summary && (
        <div className="bg-gray-50 rounded-xl p-3">
          <p className="text-xs text-gray-600 leading-relaxed">{summary}</p>
        </div>
      )}
    </div>
  )
}
