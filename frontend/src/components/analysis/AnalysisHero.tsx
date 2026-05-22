"use client"

import { useEffect, useRef, useState } from "react"
import ConvictionRing from "@/components/analysis/ConvictionRing"
import VerdictChip from "@/components/analysis/VerdictChip"
import CoverageTierBadge from "@/components/analysis/CoverageTierBadge"
import StoryDcfBadge from "@/components/analysis/StoryDcfBadge"
import Hex from "@/components/hex/Hex"
import HexExplainer from "@/components/hex/HexExplainer"
import { fetchHex, type HexAxisKey, type HexResponse } from "@/lib/hex"
import {
  fetchIndustryPercentile,
  percentileCaption,
  type IndustryPercentileResponse,
} from "@/lib/industryPercentile"
import { formatCurrency, formatPct, shouldGateVerdict } from "@/lib/utils"
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
  // Day-91 (2026-05-22): scenario band gate inputs. When the bull/bear
  // band exceeds 25% of current price the verdict pill collapses to
  // low_confidence even when raw confidence reads >= 60. Optional for
  // legacy cached payloads.
  bullCase?: number | null
  bearCase?: number | null
  // feat/transparency (2026-05-02) — optional per-number provenance
  // surfaced as small "source · as-of" captions under each hero metric.
  // All optional and additive; legacy callers continue to render the
  // hero unchanged.
  fairValueComputedAt?: string | null
  valuationEngineUsed?: string | null
  currentPriceAsOf?: string | null
  currentPriceSource?: string | null
}

/**
 * Render a tiny "source · as-of (relative)" caption used beneath each
 * hero metric so users can see provenance without leaving the page.
 * Hover surfaces the full ISO via the `title` attribute. Returns null
 * when there's nothing to show — keeps the hero compact for legacy
 * cached payloads that lack the new fields.
 */
function ProvenanceCaption({
  source,
  asOf,
  label,
}: {
  source?: string | null
  asOf?: string | null
  label?: string
}) {
  if (!source && !asOf) return null
  const d = asOf ? new Date(asOf) : null
  const ago = d && Number.isFinite(d.getTime())
    ? (() => {
        const diffMin = Math.max(0, Math.round((Date.now() - d.getTime()) / 60000))
        if (diffMin < 1) return "just now"
        if (diffMin < 60) return `${diffMin}m ago`
        const h = Math.round(diffMin / 60)
        if (h < 24) return `${h}h ago`
        const days = Math.round(h / 24)
        return `${days}d ago`
      })()
    : null
  const parts: string[] = []
  if (label) parts.push(label)
  if (source) parts.push(source.replace(/_/g, " "))
  if (ago) parts.push(ago)
  return (
    <p
      className="text-[10px] text-caption mt-0.5 truncate"
      title={asOf ?? undefined}
    >
      {parts.join(" · ")}
    </p>
  )
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
  // Day-61 (2026-05-21): explicit low_confidence framing rather than
  // the generic "review model inputs" — gives the user one honest
  // sentence about why the pill is neutral. Phrasing uses the
  // canonical advisory-safe vocabulary per
  // backend/services/analysis/sebi_filter.py.
  if (verdict === "low_confidence") {
    return `${moatPhrase}. Model confidence is below the gate threshold (60%) or the bull/bear scenario band is wide — read the FV / MoS numbers as a leaning, not a fair-value view to act on.`
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

/**
 * Inline "?" tooltip explaining why a stock can carry a C/D composite
 * grade while the verdict still reads "Below Fair Value". Without this,
 * new users see "Wide moat + Below fair value" next to a "C" and read
 * it as an internal contradiction. The tooltip names the cause — model-
 * confidence and validator findings vs. the verdict band — and points at
 * the score breakdown for the per-pillar story.
 *
 * Self-contained tooltip (no Radix dep) — mirrors the open/close pattern
 * used by MetricTooltip without requiring a registered metric key.
 */
function GradeContradictionTip() {
  const [open, setOpen] = useState(false)
  const wrapperRef = useRef<HTMLSpanElement | null>(null)
  const [alignRight, setAlignRight] = useState(false)
  const triggerRef = useRef<HTMLButtonElement | null>(null)

  useEffect(() => {
    if (!open) return
    const trigger = triggerRef.current
    if (!trigger) return
    const rect = trigger.getBoundingClientRect()
    const POPOVER_WIDTH = 300
    const viewportW = typeof window !== "undefined" ? window.innerWidth : 1024
    setAlignRight(rect.left + POPOVER_WIDTH > viewportW)
  }, [open])

  useEffect(() => {
    if (!open) return
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false)
    }
    function onDocClick(e: MouseEvent) {
      const node = wrapperRef.current
      if (!node) return
      if (!node.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener("keydown", onKey)
    document.addEventListener("mousedown", onDocClick)
    return () => {
      document.removeEventListener("keydown", onKey)
      document.removeEventListener("mousedown", onDocClick)
    }
  }, [open])

  return (
    <span
      ref={wrapperRef}
      className="relative inline-flex items-center ml-1 align-middle"
    >
      <button
        ref={triggerRef}
        type="button"
        aria-label="Why is the grade lower than the verdict suggests?"
        aria-expanded={open}
        onClick={(e) => {
          e.stopPropagation()
          setOpen((v) => !v)
        }}
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={(e) => {
          const next = e.relatedTarget as Node | null
          if (next && wrapperRef.current?.contains(next)) return
          setOpen(false)
        }}
        onFocus={() => setOpen(true)}
        onBlur={(e) => {
          const next = e.relatedTarget as Node | null
          if (next && wrapperRef.current?.contains(next)) return
          setOpen(false)
        }}
        className="inline-flex items-center justify-center w-3.5 h-3.5 rounded-full text-[9px] font-bold leading-none p-2 sm:p-0 box-content sm:box-border border border-current text-caption hover:text-brand focus-visible:text-brand focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1 transition-colors"
      >
        ?
      </button>
      {open && (
        <div
          role="tooltip"
          className={`absolute top-full mt-2 z-50 w-72 max-w-[calc(100vw-2rem)] rounded-lg border border-border bg-surface shadow-lg p-3 text-left text-ink ${alignRight ? "right-0" : "left-0"}`}
          onClick={(e) => e.stopPropagation()}
        >
          <p className="text-[11px] font-semibold uppercase tracking-wide text-caption mb-1">
            Why the grade vs. verdict differ
          </p>
          <p className="text-[12px] leading-snug text-body">
            Score reflects model confidence and validator findings, not the
            fair-value gap. A &lsquo;C&rsquo; grade with a high MoS means: the
            model believes this stock is below fair value, but data-quality
            flags or pillar weaknesses prevented a higher composite score.
            Open the score breakdown for the per-pillar details.
          </p>
        </div>
      )}
    </span>
  )
}

/**
 * True when the composite grade reads as low-quality (C/D/F) yet the
 * model's verdict still says the stock is below fair value. This is the
 * exact combination that read as an internal contradiction during the
 * 2026-05 UX audit.
 */
function shouldShowGradeContradictionTip(
  grade: string | undefined | null,
  verdict: Verdict,
): boolean {
  if (!grade) return false
  const first = grade.trim().charAt(0).toUpperCase()
  if (first !== "C" && first !== "D" && first !== "F") return false
  return verdict === "undervalued"
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
  fairValueComputedAt,
  valuationEngineUsed,
  currentPriceAsOf,
  currentPriceSource,
  bullCase,
  bearCase,
}: AnalysisHeroProps) {
  // Day-91 (2026-05-22): verdict-pill confidence gate — tightened per
  // audit #4. See lib/utils.ts::shouldGateVerdict for the canonical
  // rule. Changes vs Day-61:
  //   - _LOW_CONFIDENCE_THRESHOLD = 60 (was 50) — RELIANCE/INDIGO at
  //     41-45% confidence were slipping through
  //   - new _WIDE_BAND_RATIO_THRESHOLD = 0.25 — scenario band wider
  //     than 25% of current price also routes to low_confidence
  //   - single source of truth so EditorialHero / PublicAnalysis /
  //     tab title can't disagree (audit found 4 independent paths)
  //
  // Cascade: dataLimited (outer) > low_confidence > verdict. The
  // dataLimited path keeps its own "data_limited" verdict so TCS-class
  // tickers (Data Limited banner present) render the Data Limited
  // pill, not a fair-value pill.
  const lowConfidence =
    !dataLimited &&
    shouldGateVerdict({
      dataLimited: false,
      confidence,
      currentPrice,
      bullCase,
      bearCase,
    })
  const effectiveVerdict: Verdict = dataLimited
    ? "data_limited"
    : lowConfidence
      ? "low_confidence"
      : verdict
  const thesisLine =
    firstSentence(thesis) ?? fallbackThesis(effectiveVerdict, moat, marginOfSafety)

  // --- Hex integration ---
  const [hex, setHex] = useState<HexResponse | null>(null)
  const [hexStatus, setHexStatus] = useState<"loading" | "ok" | "error">(
    "loading",
  )
  const [explainerAxis, setExplainerAxis] = useState<HexAxisKey | null>(null)

  // Day-99: industry-relative percentiles. Optional secondary fetch —
  // null on error / missing so the hero degrades to the legacy render.
  const [percentile, setPercentile] = useState<IndustryPercentileResponse | null>(
    null,
  )

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
    // Percentile fetch is independent and best-effort.
    fetchIndustryPercentile(ticker)
      .then((p) => {
        if (cancelled) return
        setPercentile(p)
      })
      .catch(() => {
        if (cancelled) return
        setPercentile(null)
      })
    return () => {
      cancelled = true
    }
  }, [ticker])

  const percentileMap = percentile?.percentiles ?? undefined
  const scoreCaption = percentileCaption(
    (percentileMap?.score ?? null) as number | null,
    percentile?.industry ?? null,
  )

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
                percentiles={percentileMap}
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
              {shouldShowGradeContradictionTip(grade, effectiveVerdict) && (
                <GradeContradictionTip />
              )}
            </p>
            {/* Day-99: industry-relative caption under the score.
                SEBI-safe vocabulary by construction (see
                backend/services/analysis/sebi_filter.py). */}
            {scoreCaption && (
              <p
                className="text-xs text-caption mt-0.5"
                data-testid="industry-percentile-caption"
              >
                {scoreCaption}
              </p>
            )}
          </div>
        </div>

        {/* Right — verdict, metrics, thesis */}
        <div className="flex-1 min-w-0 space-y-3">
          {/* Verdict + coverage tier sit on the same row so users see
              the model output and our honest framing of how confident
              we are in that output side by side. The CoverageTierBadge
              lazy-fetches its own rubric on first expand — it has no
              impact on the hero's first paint. */}
          <div className="flex flex-wrap items-center gap-2">
            <VerdictChip verdict={effectiveVerdict} size="lg" />
            {ticker && <CoverageTierBadge ticker={ticker} size="md" />}
            {valuationEngineUsed === "sector_relative_recent_ipo" && (
              <span
                className="inline-flex items-center rounded-full border border-border bg-surface px-2 py-0.5 text-[11px] font-medium text-caption"
                title="Recent IPO — sector-relative valuation, no DCF available."
              >
                Recent IPO — sector-relative valuation, no DCF available.
              </span>
            )}
            {/* Story-DCF badge — fires when the DCF-collapse safety net's
                third rung (after Tier 2 cohort + Platform P/S) rescued
                the FV using Damodaran narrative + numbers. See
                components/analysis/StoryDcfBadge for the engine-string
                contract. */}
            <StoryDcfBadge valuationEngineUsed={valuationEngineUsed} />
          </div>

          {/* Metric block — 2x2 on md+, 2 rows of 2 on mobile */}
          <dl className="grid grid-cols-2 gap-x-6 gap-y-3">
            <div>
              <dt className="text-xs text-caption">Fair Value</dt>
              <dd className="font-mono tabular-nums text-lg font-semibold text-ink">
                {fairValue > 0 ? formatCurrency(fairValue, currency) : "Not reported"}
              </dd>
              <ProvenanceCaption
                source={valuationEngineUsed}
                asOf={fairValueComputedAt}
                label="Engine"
              />
            </div>
            <div>
              <dt className="text-xs text-caption">Current</dt>
              <dd className="font-mono tabular-nums text-lg font-semibold text-ink">
                {currentPrice > 0 ? formatCurrency(currentPrice, currency) : "Awaiting data"}
              </dd>
              <ProvenanceCaption
                source={currentPriceSource}
                asOf={currentPriceAsOf}
                label="Delayed"
              />
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
