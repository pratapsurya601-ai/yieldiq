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

// NSE returns dates like "13-Apr-2026". Convert to a short
// user-friendly label relative to today. Returns null if
// we can't parse — caller renders nothing.
function fmtRelativeDate(raw: string | null | undefined): string | null {
  if (!raw) return null
  // "13-Apr-2026" → Date
  const m = /^(\d{1,2})-([A-Za-z]{3})-(\d{4})$/.exec(raw.trim())
  if (!m) return raw // Unknown format — render as-is
  const [, dStr, monStr, yStr] = m
  const months: Record<string, number> = {
    Jan: 0, Feb: 1, Mar: 2, Apr: 3, May: 4, Jun: 5,
    Jul: 6, Aug: 7, Sep: 8, Oct: 9, Nov: 10, Dec: 11,
  }
  const monKey = monStr.charAt(0).toUpperCase() + monStr.slice(1, 3).toLowerCase()
  const mon = months[monKey]
  if (mon === undefined) return raw
  const then = new Date(parseInt(yStr, 10), mon, parseInt(dStr, 10))
  const now = new Date()
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const diffDays = Math.round((today.getTime() - then.getTime()) / 86400000)
  if (diffDays === 0) return "Today"
  if (diffDays === 1) return "Yesterday"
  if (diffDays > 1 && diffDays <= 7) return `${diffDays}d ago`
  return raw
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
        "flex-shrink-0 bg-surface rounded-xl border border-border px-4 py-3 min-w-[120px] text-center",
        borderClass && `border-l-[3px] ${borderClass}`,
      )}
    >
      <p className="text-[10px] font-bold text-caption uppercase tracking-wider">
        {title}
      </p>
      {children}
    </div>
  )
}

function Dash() {
  return <p className="text-lg font-bold text-caption">—</p>
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
  const dateLabel = fmtRelativeDate(pulse.fii_date)
  const isStale = pulse.fii_stale === true

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
                  fii > 0 ? "text-green-700" : fii < 0 ? "text-red-700" : "text-body",
                )}
              >
                {fii > 0 ? "+" : fii < 0 ? "-" : ""}
                {fmtCr(fii)}
              </p>
              <p
                className={cn(
                  "text-[10px] font-bold",
                  fii > 0 ? "text-green-500" : fii < 0 ? "text-red-500" : "text-caption",
                )}
              >
                {fii > 0 ? "▲ BUYING" : fii < 0 ? "▼ SELLING" : "— FLAT"}
              </p>
            </>
          )}
          {dateLabel && (
            <p
              className={cn(
                "text-[9px] mt-0.5",
                isStale ? "text-warning font-medium" : "text-caption",
              )}
            >
              {isStale ? `${dateLabel} · last known` : dateLabel}
            </p>
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
                  dii > 0 ? "text-green-700" : dii < 0 ? "text-red-700" : "text-body",
                )}
              >
                {dii > 0 ? "+" : dii < 0 ? "-" : ""}
                {fmtCr(dii)}
              </p>
              <p
                className={cn(
                  "text-[10px] font-bold",
                  dii > 0 ? "text-green-500" : dii < 0 ? "text-red-500" : "text-caption",
                )}
              >
                {dii > 0 ? "▲ BUYING" : dii < 0 ? "▼ SELLING" : "— FLAT"}
              </p>
            </>
          )}
          {dateLabel && (
            <p
              className={cn(
                "text-[9px] mt-0.5",
                isStale ? "text-warning font-medium" : "text-caption",
              )}
            >
              {isStale ? `${dateLabel} · last known` : dateLabel}
            </p>
          )}
        </Card>

        <Card title="India VIX" borderClass="border-l-amber-500">
          {vix === null || vix === undefined ? (
            <Dash />
          ) : (
            <>
              <p className="text-lg font-bold text-ink tabular-nums">
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
              <p className="text-lg font-bold text-ink tabular-nums">
                ₹{pulse.usd_inr.toFixed(2)}
              </p>
              <p className="text-[10px] text-caption">1 USD</p>
            </>
          )}
        </Card>

        <Card title="Gold">
          {pulse.gold_usd && pulse.usd_inr ? (
            <>
              <p className="text-lg font-bold text-ink tabular-nums">
                {fmtInrLakh(metalInrPer(10, pulse.gold_usd, pulse.usd_inr))}
              </p>
              <p className="text-[10px] text-caption">per 10g</p>
            </>
          ) : (
            <Dash />
          )}
        </Card>

        <Card title="Silver">
          {pulse.silver_usd && pulse.usd_inr ? (
            <>
              <p className="text-lg font-bold text-ink tabular-nums">
                {fmtInrLakh(metalInrPer(1000, pulse.silver_usd, pulse.usd_inr))}
              </p>
              <p className="text-[10px] text-caption">per kg</p>
            </>
          ) : (
            <Dash />
          )}
        </Card>
      </div>

      {/* AI summary — only when populated */}
      {summary && (
        <div className="bg-surface rounded-xl p-3">
          <p className="text-xs text-body leading-relaxed">{summary}</p>
        </div>
      )}
    </div>
  )
}
