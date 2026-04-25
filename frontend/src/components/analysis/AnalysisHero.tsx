"use client"

import { useEffect, useState } from "react"
import ConvictionRing from "@/components/analysis/ConvictionRing"
import VerdictChip from "@/components/analysis/VerdictChip"
import Hex from "@/components/hex/Hex"
import HexExplainer from "@/components/hex/HexExplainer"
import { fetchHex, type HexAxisKey, type HexResponse } from "@/lib/hex"
import { formatCurrency, formatPct } from "@/lib/utils"
import type { Verdict } from "@/types/api"

interface AnalysisHeroProps {
  score: number
  grade: string
  confidence: number
  verdict: Verdict
  fairValue: number
  currentPrice: number
  marginOfSafety: number
  moat: string
  currency: string
  thesis: string | null
  dataLimited: boolean
  ticker?: string
}

/**
 * Extract the first sentence of the AI thesis to act as a one-line
 * headline under the verdict. Falls back to a descriptive, SEBI-safe
 * phrasing when the summary is null / too short. Never returns "buy"
 * or "sell" language.
 */
function firstSentence(text: string | null): string | null {
  if (!text) return null
  const trimmed = text.trim()
  if (!trimmed) return null
  // Split on first ". " or newline. Keep it compact.
  const match = trimmed.match(/^(.{20,200}?[.!?])(\s|$)/)
  const candidate = match ? match[1] : trimmed.slice(0, 160)
  // Strip any accidental advisory language defensively. `hold` is itself
  // SEBI-banned per backend/services/analysis/sebi_filter.py, so we rewrite
  // to the neutral "fair-value view" phrasing that mirrors the rest of the
  // UI (see VerdictChip, EditorialHero).
  return candidate.replace(
    /\b(buy|accumulate|sell|hold|outperform|underperform|recommend|recommendation)\b/gi,
    "fair-value view",
  )
}

function fallbackThesis(verdict: Verdict, moat: string, mos: number): string {
  const moatPhrase =
    moat === "Wide"
      ? "Wide-moat business"
      : moat === "Narrow"
      ? "Narrow-moat business"
      : "Business with limited moat"
  if (verdict === "undervalued") {
    return `${moatPhrase} trading below fair value (MoS ${formatPct(mos)}).`
  }
  if (verdict === "overvalued") {
    return `${moatPhrase} trading above fair value. Wait for a larger margin of safety.`
  }
  if (verdict === "fairly_valued") {
    return `${moatPhrase} at a fair price. A larger margin of safety (MoS > 20%) would give a wider cushion.`
  }
  return `${moatPhrase}. Review model inputs before drawing conclusions.`
}

/**
 * Skeleton hex shown while the /api/v1/hex endpoint is loading. A static,
 * non-animated grey hex at the given size — roughly the same footprint as
 * the real Hex so the layout doesn't jump when it lands.
 */
function HexSkeleton({ size }: { size: number }) {
  const cx = size / 2
  const cy = size / 2
  const r = size / 2 - 28
  const pts = Array.from({ length: 6 }, (_, i) => {
    const a = -Math.PI / 2 + (i * 2 * Math.PI) / 6
    return `${cx + r * Math.cos(a)},${cy + r * Math.sin(a)}`
  }).join(" ")
  return (
    <div
      className="skeleton rounded-2xl"
      style={{ width: size, height: size }}
      aria-label="Loading hex"
      role="status"
    >
      <svg
        width={size}
        height={size}
        viewBox={`0 0 ${size} ${size}`}
        style={{ opacity: 0.4 }}
      >
        <polygon
          points={pts}
          fill="none"
          stroke="var(--color-border)"
          strokeWidth={1}
        />
      </svg>
    </div>
  )
}

export default function AnalysisHero({
  score,
  grade,
  confidence,
  verdict,
  fairValue,
  currentPrice,
  marginOfSafety,
  moat,
  currency,
  thesis,
  dataLimited,
  ticker,
}: AnalysisHeroProps) {
  const effectiveVerdict: Verdict = dataLimited ? "data_limited" : verdict
  const thesisLine =
    firstSentence(thesis) ?? fallbackThesis(effectiveVerdict, moat, marginOfSafety)

  // --- Hex integration ---
  const [hex, setHex] = useState<HexResponse | null>(null)
  const [hexStatus, setHexStatus] = useState<"loading" | "ok" | "error">(
    "loading",
  )
  const [explainerAxis, setExplainerAxis] = useState<HexAxisKey | null>(null)

  useEffect(() => {
    if (!ticker) {
      setHexStatus("error")
      return
    }
    let cancelled = false
    setHexStatus("loading")
    fetchHex(ticker)
      .then((data) => {
        if (cancelled) return
        setHex(data)
        setHexStatus("ok")
      })
      .catch(() => {
        if (cancelled) return
        setHexStatus("error")
      })
    return () => {
      cancelled = true
    }
  }, [ticker])

  return (
    <section
      className="bg-surface rounded-2xl border border-border p-5 md:p-6"
      aria-label="Valuation summary"
    >
      <div className="flex flex-col md:flex-row md:items-center md:gap-8 gap-5">
        {/* Left — hex (fallback: legacy conviction ring) */}
        <div className="flex items-center justify-center md:flex-col md:items-center gap-4 md:gap-2 shrink-0">
          <div className="block md:hidden">
            {hexStatus === "ok" && hex ? (
              <Hex
                data={hex}
                size={200}
                onAxisTap={(k) => setExplainerAxis(k)}
              />
            ) : hexStatus === "loading" ? (
              <HexSkeleton size={200} />
            ) : (
              <ConvictionRing score={score} confidence={confidence} size={160} />
            )}
          </div>
          <div className="hidden md:block">
            {hexStatus === "ok" && hex ? (
              <Hex
                data={hex}
                size={240}
                onAxisTap={(k) => setExplainerAxis(k)}
              />
            ) : hexStatus === "loading" ? (
              <HexSkeleton size={240} />
            ) : (
              <ConvictionRing score={score} confidence={confidence} size={160} />
            )}
          </div>
          <div className="md:text-center">
            <p className="text-xs text-caption uppercase tracking-wide">
              YieldIQ Score · Model estimate
            </p>
            <p className="font-mono tabular-nums text-lg font-semibold text-ink">
              {score}
              <span className="text-caption text-sm ml-1">/100</span>
              <span className="ml-2 text-sm font-bold text-brand">
                {grade}
              </span>
            </p>
          </div>
        </div>

        {/* Right — verdict, metrics, thesis */}
        <div className="flex-1 min-w-0 space-y-3">
          <VerdictChip verdict={effectiveVerdict} size="lg" />

          {/* Metric block — 2x2 on md+, 2 rows of 2 on mobile */}
          <dl className="grid grid-cols-2 gap-x-6 gap-y-3">
            <div>
              <dt className="text-xs text-caption">Fair Value</dt>
              <dd className="font-mono tabular-nums text-lg font-semibold text-ink">
                {fairValue > 0 ? formatCurrency(fairValue, currency) : "Not reported"}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-caption">Current</dt>
              <dd className="font-mono tabular-nums text-lg font-semibold text-ink">
                {currentPrice > 0 ? formatCurrency(currentPrice, currency) : "Awaiting data"}
              </dd>
            </div>

            {!dataLimited && (
              <div>
                <dt className="text-xs text-caption">Margin of Safety</dt>
                <dd
                  className={`font-mono tabular-nums text-lg font-semibold ${
                    marginOfSafety >= 0 ? "text-brand" : "text-warning"
                  }`}
                >
                  {marginOfSafety > 80
                    ? "+80%+"
                    : formatPct(marginOfSafety)}
                </dd>
              </div>
            )}

            <div>
              <dt className="text-xs text-caption">Moat</dt>
              <dd className="text-lg font-semibold text-ink">
                {moat || "—"}
              </dd>
            </div>
          </dl>

          {thesisLine && (
            <p className="text-sm leading-relaxed text-body border-l-2 border-brand-50 pl-3">
              {thesisLine}
            </p>
          )}
        </div>
      </div>

      {/* Explainer sheet — rendered once, driven by tapped axis */}
      {hex && (
        <HexExplainer
          open={explainerAxis !== null}
          axis={explainerAxis}
          data={hex}
          onClose={() => setExplainerAxis(null)}
        />
      )}
    </section>
  )
}
