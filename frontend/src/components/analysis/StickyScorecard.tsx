"use client"

/**
 * StickyScorecard — left-rail anchor for /analysis/[ticker].
 *
 * Tickertape-parity layout move (audit: .audit/tickertape-deep-walk-2026-05-27.md,
 * gap #1, "single biggest difference"). 336px wide rail that pins on the
 * left of the page from scroll position 80px and stays glued to the
 * viewport for the entire scroll. Gives users a persistent verdict + FV
 * + Worry + Score + Moat + Red-Flags anchor so they never lose the
 * "what is this stock?" read while scrolling through Scenarios →
 * Compounded Growth → Reverse DCF → Dividends → News → ...
 *
 * Composition only. NO new backend fields. Reads from the same
 * AnalysisResponse the page already fetches; the host component passes
 * the resolved values in as props so this file stays presentational.
 *
 * Responsive split:
 *   - lg: and up  → fixed 336px sidebar, sticky top-20, full vertical card
 *                   with 4 mini tiles + "Tell me the story" CTA.
 *   - below lg:   → horizontal sticky strip at top showing the 4 traffic-
 *                   light chips compactly so mobile gets the anchor too.
 *
 * SEBI lens:
 *   - Verdict labels mirror the existing vocabulary (Undervalued / Fairly
 *     Valued / Overvalued / Under Review / Insufficient Data) — sourced
 *     via lib/verdict-colors.verdictTierLabel which is already in use.
 *   - Traffic-light chips colour the score CONDITION (low risk = green,
 *     high risk = red), never the action.
 *   - No imperative language anywhere — no advice verbs, no targets.
 */

import Link from "next/link"
import { cn, formatCurrency, formatPct } from "@/lib/utils"
import {
  VERDICT_COLORS,
  verdictTierFromMos,
  verdictTierLabel,
  type VerdictTier,
} from "@/lib/verdict-colors"
import type { MoatGrade } from "@/types/api"

// Mirrors the inline tier union on AnalysisResponse.worry_index.tier
// (backend/services/analysis/worry_index.py). Kept local because the
// backend payload type literals it inline rather than exporting a named
// type, and we want the rail to compile independently.
export type WorryTier =
  | "sleep_well"
  | "normal"
  | "watch_closely"
  | "read_bears"
  | "significant_concerns"

/* ------------------------------------------------------------------ */
/*  Chip tone tokens                                                  */
/* ------------------------------------------------------------------ */

type ChipTone = "good" | "ok" | "warn" | "bad" | "neutral"

const CHIP_STYLES: Record<ChipTone, string> = {
  good: "bg-tone-good-bg text-tone-good-fg border-tone-good-bd",
  ok: "bg-lime-50 text-lime-700 border-lime-200",
  warn: "bg-tone-warn-bg text-tone-warn-fg border-tone-warn-bd",
  bad: "bg-rose-50 text-rose-700 border-rose-200",
  neutral: "bg-tone-neutral-bg text-slate-600 border-tone-neutral-bd",
}

const DOT_STYLES: Record<ChipTone, string> = {
  good: "bg-emerald-500",
  ok: "bg-lime-500",
  warn: "bg-amber-500",
  bad: "bg-rose-500",
  neutral: "bg-slate-400",
}

/* ------------------------------------------------------------------ */
/*  Metric → tone helpers (descriptive, never prescriptive)            */
/* ------------------------------------------------------------------ */

function worryTone(tier: WorryTier | null | undefined): ChipTone {
  switch (tier) {
    case "sleep_well":
      return "good"
    case "normal":
      return "ok"
    case "watch_closely":
      return "warn"
    case "read_bears":
    case "significant_concerns":
      return "bad"
    default:
      return "neutral"
  }
}

function worryTierLabel(tier: WorryTier | null | undefined): string {
  switch (tier) {
    case "sleep_well":
      return "Sleep well"
    case "normal":
      return "Normal"
    case "watch_closely":
      return "Watch closely"
    case "read_bears":
      return "Read bears"
    case "significant_concerns":
      return "High"
    default:
      return "—"
  }
}

function scoreTone(score: number | null | undefined): ChipTone {
  if (score == null || !Number.isFinite(score) || score <= 0) return "neutral"
  if (score >= 75) return "good"
  if (score >= 60) return "ok"
  if (score >= 40) return "warn"
  return "bad"
}

function moatTone(moat: MoatGrade | string | null | undefined): ChipTone {
  const m = (moat ?? "").toString().toLowerCase()
  if (m === "wide") return "good"
  if (m === "narrow") return "ok"
  if (m === "none") return "warn"
  return "neutral"
}

function moatLabel(moat: MoatGrade | string | null | undefined): string {
  if (!moat) return "—"
  const m = moat.toString()
  // Preserve "N/A (Financial)" for banks; otherwise title-case.
  return m
}

function redFlagsTone(count: number | null | undefined): ChipTone {
  if (count == null || !Number.isFinite(count)) return "neutral"
  if (count === 0) return "good"
  if (count <= 2) return "warn"
  return "bad"
}

function redFlagsLabel(count: number | null | undefined): string {
  if (count == null || !Number.isFinite(count)) return "—"
  if (count === 0) return "Clean"
  return `${count} flagged`
}

/* ------------------------------------------------------------------ */
/*  Small subcomponents                                                */
/* ------------------------------------------------------------------ */

function Chip({
  tone,
  children,
  className,
}: {
  tone: ChipTone
  children: React.ReactNode
  className?: string
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-medium leading-none",
        CHIP_STYLES[tone],
        className,
      )}
    >
      <span aria-hidden className={cn("h-1.5 w-1.5 rounded-full", DOT_STYLES[tone])} />
      {children}
    </span>
  )
}

interface TileProps {
  label: string
  value: string
  chipLabel: string
  tone: ChipTone
}

function Tile({ label, value, chipLabel, tone }: TileProps) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-xl border border-border bg-bg dark:bg-surface px-3 py-2.5">
      <div className="min-w-0">
        <p className="text-[10px] uppercase tracking-wide text-caption leading-tight">
          {label}
        </p>
        <p className="font-mono tabular-nums text-sm text-ink leading-tight mt-0.5 truncate">
          {value}
        </p>
      </div>
      <Chip tone={tone}>{chipLabel}</Chip>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  Public props                                                      */
/* ------------------------------------------------------------------ */

export interface StickyScorecardProps {
  ticker: string
  displayTicker: string
  companyName: string
  currency: string

  /** Headline price + signed change %. Change may be null on cold data. */
  currentPrice: number | null
  priceChangePct?: number | null

  /** Headline fair value (after FV-clamp resolution). */
  fairValue: number | null
  /** Composite model confidence 0-100. */
  confidence: number | null
  /** Signed MoS percentage — same number rendered in the hero. */
  marginOfSafety: number | null
  /** Raw verdict enum (used for tier resolution). */
  verdict: string | null
  /** True when the page is in the dataLimited / under-review branch. */
  dataLimited?: boolean

  /** Worry Index composite — null on legacy cached payloads. */
  worryScore?: number | null
  worryTier?: WorryTier | null

  /** YieldIQ composite 0-100 + letter grade. */
  yieldiqScore: number | null
  grade: string | null

  /** Moat label as emitted by the backend QualityOutput. */
  moat: MoatGrade | string | null
  /** Number of red flags (matches insights.red_flags_structured.length). */
  redFlagCount: number | null

  /** Optional handler for the "Tell me the story" CTA. */
  onTellStory?: () => void
}

/* ------------------------------------------------------------------ */
/*  Mobile horizontal strip — < lg                                     */
/* ------------------------------------------------------------------ */

interface StripProps {
  worryTone: ChipTone
  worryLabel: string
  scoreTone: ChipTone
  scoreLabel: string
  moatTone: ChipTone
  moatLabel: string
  redTone: ChipTone
  redLabel: string
}

function MobileStrip(p: StripProps) {
  return (
    <div
      className="lg:hidden sticky top-12 z-20 -mx-4 px-4 py-2 bg-bg/95 backdrop-blur border-b border-border"
      aria-label="Stock scorecard summary"
    >
      <div className="flex items-center gap-2 overflow-x-auto no-scrollbar">
        <Chip tone={p.worryTone}>Worry · {p.worryLabel}</Chip>
        <Chip tone={p.scoreTone}>Score · {p.scoreLabel}</Chip>
        <Chip tone={p.moatTone}>Moat · {p.moatLabel}</Chip>
        <Chip tone={p.redTone}>Flags · {p.redLabel}</Chip>
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  Main component                                                    */
/* ------------------------------------------------------------------ */

export default function StickyScorecard({
  ticker,
  displayTicker,
  companyName,
  currency,
  currentPrice,
  priceChangePct,
  fairValue,
  confidence,
  marginOfSafety,
  verdict,
  dataLimited = false,
  worryScore,
  worryTier,
  yieldiqScore,
  grade,
  moat,
  redFlagCount,
  onTellStory,
}: StickyScorecardProps) {
  const tier: VerdictTier = dataLimited
    ? "data_limited"
    : verdictTierFromMos(marginOfSafety, verdict)
  const palette = VERDICT_COLORS[tier]
  const verdictLabel = verdictTierLabel(tier)

  // Pill colour — solid on hero gradient backgrounds reads loud; here we
  // stay in the chip surface convention (border + tinted bg + dark text)
  // so the rail keeps with the rest of the page card aesthetic. The
  // verdict bar at the top of the card carries the saturated colour.
  const pillTone: ChipTone =
    tier === "undervalued"
      ? "good"
      : tier === "fairly_valued"
        ? "neutral"
        : tier === "overvalued"
          ? "bad"
          : "neutral"

  const priceDisplay =
    currentPrice != null && currentPrice > 0
      ? formatCurrency(currentPrice, currency, ticker)
      : "—"

  const fvDisplay =
    fairValue != null && fairValue > 0 && !dataLimited
      ? formatCurrency(fairValue, currency, ticker)
      : "—"

  const confDisplay =
    confidence != null && Number.isFinite(confidence) && !dataLimited
      ? `conf ${Math.round(confidence)}%`
      : null

  const mosDisplay =
    marginOfSafety != null && Number.isFinite(marginOfSafety) && !dataLimited
      ? formatPct(marginOfSafety)
      : "—"

  const mosTone: ChipTone =
    marginOfSafety == null || !Number.isFinite(marginOfSafety) || dataLimited
      ? "neutral"
      : marginOfSafety >= 20
        ? "good"
        : marginOfSafety >= -10
          ? "neutral"
          : "bad"

  const priceChangeDisplay =
    priceChangePct != null && Number.isFinite(priceChangePct)
      ? `${priceChangePct >= 0 ? "+" : ""}${priceChangePct.toFixed(2)}%`
      : null
  const priceChangeColor =
    priceChangePct == null || !Number.isFinite(priceChangePct)
      ? "text-caption"
      : priceChangePct >= 0
        ? "text-emerald-600"
        : "text-rose-600"

  /* ---- Tile data ---- */
  const wTone = worryTone(worryTier)
  const wValue =
    worryScore != null && Number.isFinite(worryScore)
      ? `${Math.round(worryScore)}/100`
      : "—"
  const wLabel = worryTierLabel(worryTier)

  const sTone = scoreTone(yieldiqScore)
  const sValue =
    yieldiqScore != null && Number.isFinite(yieldiqScore) && yieldiqScore > 0
      ? `${Math.round(yieldiqScore)}/100`
      : "—"
  const sLabel = grade && grade.trim() ? grade : "—"

  const mTone = moatTone(moat)
  const mValue = moatLabel(moat)
  const mLabel =
    mTone === "good"
      ? "Wide"
      : mTone === "ok"
        ? "Narrow"
        : mTone === "warn"
          ? "None"
          : "—"

  const rTone = redFlagsTone(redFlagCount)
  const rValue = redFlagsLabel(redFlagCount)
  const rLabel = redFlagCount === 0 ? "Clean" : redFlagCount ? `${redFlagCount}` : "—"

  return (
    <>
      {/* ── Mobile horizontal strip ── */}
      <MobileStrip
        worryTone={wTone}
        worryLabel={wLabel}
        scoreTone={sTone}
        scoreLabel={sLabel}
        moatTone={mTone}
        moatLabel={mLabel}
        redTone={rTone}
        redLabel={rLabel}
      />

      {/* ── Desktop sticky rail ── */}
      <aside
        className="hidden lg:block lg:sticky lg:top-20 lg:self-start lg:w-[336px] lg:shrink-0"
        aria-label={`${displayTicker} scorecard`}
      >
        <div className="rounded-2xl border border-border bg-bg dark:bg-surface overflow-hidden shadow-sm">
          {/* Verdict colour bar — same cascade as the page-top sticky bar */}
          <div aria-hidden className={cn("h-1 w-full", palette.bar)} />

          {/* Header */}
          <div className="px-4 pt-4 pb-3 border-b border-border">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="font-display text-base font-semibold text-ink leading-tight">
                  {displayTicker}
                </p>
                <p className="text-[11px] text-caption truncate mt-0.5">
                  {companyName}
                </p>
              </div>
              <Chip tone={pillTone} className="shrink-0">
                {verdictLabel}
              </Chip>
            </div>

            {/* Price + change */}
            <div className="flex items-baseline gap-2 mt-3">
              <span className="font-mono tabular-nums text-lg text-ink">
                {priceDisplay}
              </span>
              {priceChangeDisplay && (
                <span className={cn("font-mono tabular-nums text-xs", priceChangeColor)}>
                  {priceChangeDisplay}
                </span>
              )}
            </div>
          </div>

          {/* FV + MoS block */}
          <div className="px-4 py-3 border-b border-border">
            <div className="flex items-baseline justify-between gap-3">
              <div className="min-w-0">
                <p className="text-[10px] uppercase tracking-wide text-caption leading-tight">
                  Fair value
                </p>
                <p className="font-mono tabular-nums text-base text-ink mt-0.5 truncate">
                  {fvDisplay}
                  {confDisplay && (
                    <span className="text-[11px] text-caption font-sans ml-1.5">
                      · {confDisplay}
                    </span>
                  )}
                </p>
              </div>
              <div className="text-right shrink-0">
                <p className="text-[10px] uppercase tracking-wide text-caption leading-tight">
                  Discount to FV
                </p>
                <p
                  className={cn(
                    "font-mono tabular-nums text-base mt-0.5",
                    mosTone === "good"
                      ? "text-tone-good-fg"
                      : mosTone === "bad"
                        ? "text-rose-700"
                        : "text-ink",
                  )}
                >
                  {mosDisplay}
                </p>
              </div>
            </div>
          </div>

          {/* Mini scorecard tiles */}
          <div className="px-4 py-3 space-y-2">
            <Tile label="Worry Index" value={wValue} chipLabel={wLabel} tone={wTone} />
            <Tile label="YieldIQ Score" value={sValue} chipLabel={sLabel} tone={sTone} />
            <Tile label="Moat" value={mValue} chipLabel={mLabel} tone={mTone} />
            <Tile label="Red Flags" value={rValue} chipLabel={rLabel} tone={rTone} />
          </div>

          {/* Story CTA */}
          <div className="px-4 pb-4 pt-2 border-t border-border">
            {onTellStory ? (
              <button
                type="button"
                onClick={onTellStory}
                className="w-full inline-flex items-center justify-center gap-2 rounded-lg bg-brand text-white text-xs font-semibold px-3 py-2 min-h-[36px] hover:opacity-90 active:scale-[0.98] transition"
              >
                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M5 3l14 9-14 9V3z" />
                </svg>
                Tell me the story
              </button>
            ) : (
              <Link
                href={`/report/${ticker}`}
                className="w-full inline-flex items-center justify-center gap-2 rounded-lg bg-brand text-white text-xs font-semibold px-3 py-2 min-h-[36px] hover:opacity-90 active:scale-[0.98] transition"
              >
                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M5 3l14 9-14 9V3z" />
                </svg>
                Tell me the story
              </Link>
            )}
          </div>
        </div>
      </aside>
    </>
  )
}
