"use client"

/**
 * PriceLadderPanel — horizontal price ladder + MoS chip selector +
 * drag-to-set target slider. Replaces MosAlertChip at the
 * EditorialHeroBand mount site (full-band region, >=1280).
 *
 * Why this exists (vs the single-button MosAlertChip from PR #242):
 *   1. Visual hierarchy: three labelled stops (Fair Value, Target,
 *      Current) on one axis communicate "where is the price relative
 *      to model output" at a glance.
 *   2. Drag-to-set: the target stop is the thumb of an <input
 *      type="range" min=0 max=50> bound to the MoS percent. AlphaSpread
 *      requires opening a modal for custom; we let the user dial it on
 *      the axis itself.
 *   3. In-zone shading: when currentPrice <= target the
 *      Target<->Current segment goes emerald — the price has crossed
 *      the alert threshold the user is about to arm. AlphaSpread shows
 *      no visual difference between "in zone" and "above zone".
 *   4. Optional likelihood: when historicalHitsAtMos returns a non-null
 *      count, render "Last 3y: hit N times" — pulled from
 *      fair_value_history (PR #766 + monthly backfill).
 *   5. Dark-mode native: every surface paints both light and
 *      dark-class variants. The site defaults to dark per PR #763.
 *
 * Alert pipeline: reuses the existing POST /api/v1/alerts/create with
 *   { ticker, alert_type: "mos_above", target_price: <pct: 0..50> }
 * — same handler MosAlertChip used. No new backend endpoint, no
 * migration, no canary needed.
 *
 * SEBI vocabulary note: every visible string avoids the
 * scripts/check_sebi_words.py banned list. Specifically — no
 * buy/sell/hold/recommend/strong/weak/cheap/expensive/etc. The phrase
 * "Below Fair Value" is borrowed from EditorialHero's existing verdict
 * label (lib/verdict-colors.ts), not coined here. "In Zone" replaces
 * any "Buy Zone" framing the AlphaSpread reference used.
 */

import { useCallback, useId, useMemo, useState } from "react"
import { useMutation } from "@tanstack/react-query"
import { useRouter } from "next/navigation"
import { Bell, BellRing } from "lucide-react"

import { createAlert } from "@/lib/api"
import { useAuthStore } from "@/store/authStore"
import { formatCurrency } from "@/lib/utils"
import { cn } from "@/lib/utils"

const DISCOUNT_STEPS = [0, 10, 20, 30, 40, 50] as const
const DEFAULT_STEP = 20
const MIN_PCT = 0
const MAX_PCT = 50

export interface PriceLadderPanelProps {
  /** Bare or .NS-suffixed ticker. Forwarded to the alerts API as-is
   * (router uppercases + trims server-side). */
  ticker: string
  /** Resolved company display name (used for the aria-label only —
   * never re-emitted as visible verdict copy). */
  companyName: string
  /** Current spot in company currency. */
  currentPrice: number
  /** Base-case intrinsic value in company currency. */
  fairValue: number
  /** Optional upper-rail scenario (bullCase) used only to expand the
   * axis domain so the layout doesn't compress at extreme valuations. */
  bullCase?: number
  /** Optional lower-rail scenario (bearCase) used only to expand the
   * axis domain. */
  bearCase?: number
  /** Currency code from the prism payload (e.g. "INR"). */
  currency: string
  /** Optional: count of trading days in the last 3y where price was
   * at-or-below the target implied by the supplied MoS%. Comes from
   * fair_value_history. Return null to signal "no data" — the
   * likelihood line is suppressed when the helper is not provided OR
   * returns null. */
  historicalHitsAtMos?: (mosPct: number) => number | null
}

export default function PriceLadderPanel({
  ticker,
  companyName,
  currentPrice,
  fairValue,
  bullCase,
  bearCase,
  currency,
  historicalHitsAtMos,
}: PriceLadderPanelProps) {
  const router = useRouter()
  const token = useAuthStore((s) => s.token)
  const sliderId = useId()

  const [pct, setPct] = useState<number>(DEFAULT_STEP)
  const [confirmedPct, setConfirmedPct] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)

  // Target = FV * (1 - pct/100). Always finite when fairValue is
  // finite-positive (which is the only path the parent renders this
  // component on — see EditorialHeroBand guards).
  const targetPrice = useMemo<number>(
    () => fairValue * (1 - pct / 100),
    [fairValue, pct],
  )

  // In-zone when current spot is at-or-below the user's target.
  const inZone = Number.isFinite(currentPrice) && currentPrice <= targetPrice

  // Axis domain: pad slightly past min(current, bearCase) on the low
  // side and max(FV, bullCase) on the high side so the endpoint dots
  // sit inside the rail rather than on top of the edge.
  const { axisMin, axisMax } = useMemo(() => {
    const lows = [currentPrice, targetPrice, fairValue]
    if (Number.isFinite(bearCase ?? NaN)) lows.push(bearCase as number)
    const highs = [currentPrice, targetPrice, fairValue]
    if (Number.isFinite(bullCase ?? NaN)) highs.push(bullCase as number)
    const lo = Math.min(...lows.filter((v) => Number.isFinite(v)))
    const hi = Math.max(...highs.filter((v) => Number.isFinite(v)))
    const span = Math.max(hi - lo, Math.abs(hi) * 0.05 || 1)
    return { axisMin: lo - span * 0.04, axisMax: hi + span * 0.04 }
  }, [currentPrice, targetPrice, fairValue, bullCase, bearCase])

  // Position (0..100, right-to-left on the rail: low price on the
  // right edge, high price on the left edge to match the brief sketch).
  const positionPct = useCallback(
    (price: number): number => {
      if (axisMax <= axisMin) return 50
      const t = (price - axisMin) / (axisMax - axisMin)
      // Right-to-left: 0=low maps to right (100% from left).
      return Math.min(100, Math.max(0, (1 - t) * 100))
    },
    [axisMin, axisMax],
  )

  const fairLeft = positionPct(fairValue)
  const targetLeft = positionPct(targetPrice)
  const currentLeft = positionPct(currentPrice)

  // Discount of current vs FV — a factual, descriptive label only.
  const currentDiscountPct = useMemo<number | null>(() => {
    if (!Number.isFinite(fairValue) || fairValue <= 0) return null
    if (!Number.isFinite(currentPrice)) return null
    return ((fairValue - currentPrice) / fairValue) * 100
  }, [fairValue, currentPrice])

  const historicalHits = useMemo<number | null>(() => {
    if (!historicalHitsAtMos) return null
    try {
      const n = historicalHitsAtMos(pct)
      return typeof n === "number" && Number.isFinite(n) ? n : null
    } catch {
      return null
    }
  }, [historicalHitsAtMos, pct])

  const mutation = useMutation({
    mutationFn: () =>
      createAlert({ ticker, alert_type: "mos_above", target_price: pct }),
    onSuccess: () => {
      setConfirmedPct(pct)
      setError(null)
    },
    onError: (err: unknown) => {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Could not save alert. Try again."
      setError(detail)
    },
  })

  const onPrimary = useCallback(() => {
    if (!token) {
      router.push(
        "/auth/login?return_to=" +
          encodeURIComponent(
            typeof window !== "undefined" ? window.location.pathname : "/",
          ),
      )
      return
    }
    if (mutation.isPending) return
    mutation.mutate()
  }, [mutation, router, token])

  const onChipClick = useCallback((step: number) => {
    setPct(step)
    setConfirmedPct(null)
  }, [])

  const primaryLabel = !token
    ? "Sign in to set alert"
    : mutation.isPending
      ? "Saving…"
      : confirmedPct != null && confirmedPct === pct
        ? "Alert active"
        : inZone
          ? `Notify Me — In Zone at ${pct}%`
          : `Notify Me at ${pct}%`

  return (
    <div
      data-testid="price-ladder-panel"
      data-in-zone={inZone ? "true" : "false"}
      className="mt-3 w-full rounded-xl border border-border bg-bg p-3 md:p-4"
      aria-label={`Price ladder for ${companyName}`}
    >
      {/* ── Ladder rail ─────────────────────────────────────────── */}
      <div className="relative h-16">
        {/* Base rail */}
        <div
          aria-hidden="true"
          className="absolute left-0 right-0 top-1/2 h-[3px] -translate-y-1/2 rounded-full bg-border"
        />

        {/* Fair Value -> Target segment (always neutral) */}
        <div
          aria-hidden="true"
          data-testid="ladder-segment-fv-target"
          className="absolute top-1/2 h-[3px] -translate-y-1/2 rounded-full bg-ink/30 dark:bg-ink/40"
          style={{
            // fairLeft is the smaller "left%" (FV is high price, on
            // the left of the right-to-left axis); targetLeft is to
            // its right.
            left: `${Math.min(fairLeft, targetLeft)}%`,
            width: `${Math.abs(targetLeft - fairLeft)}%`,
          }}
        />

        {/* Target -> Current segment. Green when current<=target
            (in-zone), neutral otherwise. */}
        <div
          aria-hidden="true"
          data-testid="ladder-segment-target-current"
          className={cn(
            "absolute top-1/2 h-[6px] -translate-y-1/2 rounded-full transition-colors",
            inZone
              ? "bg-emerald-200 dark:bg-emerald-900/60"
              : "bg-amber-200/60 dark:bg-amber-900/40",
          )}
          style={{
            left: `${Math.min(targetLeft, currentLeft)}%`,
            width: `${Math.abs(currentLeft - targetLeft)}%`,
          }}
        />

        {/* Endpoint dots + labels. */}
        <Stop
          label="Fair Value"
          pill="F"
          price={fairValue}
          currency={currency}
          leftPct={fairLeft}
          tone="neutral"
          testId="ladder-stop-fv"
        />
        <Stop
          label={pct === 0 ? "At Fair Value" : `${pct}% below`}
          pill="T"
          price={targetPrice}
          currency={currency}
          leftPct={targetLeft}
          tone="target"
          testId="ladder-stop-target"
        />
        <Stop
          label={
            currentDiscountPct == null
              ? "Current"
              : `${currentDiscountPct >= 0 ? "-" : "+"}${Math.abs(
                  currentDiscountPct,
                ).toFixed(0)}%`
          }
          pill="P"
          price={currentPrice}
          currency={currency}
          leftPct={currentLeft}
          tone={inZone ? "good" : "neutral"}
          testId="ladder-stop-current"
        />
      </div>

      {/* ── Drag-to-set slider (positioned beneath the rail) ─────── */}
      <div className="mt-2">
        <label
          htmlFor={sliderId}
          className="sr-only"
        >
          Target margin-of-safety percent
        </label>
        <input
          id={sliderId}
          type="range"
          min={MIN_PCT}
          max={MAX_PCT}
          step={1}
          value={pct}
          onChange={(e) => {
            setPct(Number(e.target.value))
            setConfirmedPct(null)
          }}
          data-testid="ladder-slider"
          aria-label="Drag to set target margin of safety"
          aria-valuemin={MIN_PCT}
          aria-valuemax={MAX_PCT}
          aria-valuenow={pct}
          aria-valuetext={`${pct} percent below fair value`}
          className="w-full h-1 cursor-pointer appearance-none rounded-full bg-border accent-brand"
        />
        <div className="mt-1 flex items-center justify-between text-[10px] text-caption font-mono tabular-nums">
          <span>0%</span>
          <span data-testid="ladder-slider-readout" className="text-ink font-semibold">
            {pct}% below Fair Value
          </span>
          <span>50%</span>
        </div>
      </div>

      {/* ── Chip row ─────────────────────────────────────────────── */}
      <div
        role="radiogroup"
        aria-label="Margin-of-safety threshold"
        data-testid="ladder-chip-row"
        className="mt-3 flex flex-wrap items-center gap-1"
      >
        {DISCOUNT_STEPS.map((step) => {
          const selected = step === pct
          return (
            <button
              key={step}
              type="button"
              role="radio"
              aria-checked={selected}
              data-testid={`ladder-chip-${step}`}
              onClick={() => onChipClick(step)}
              className={cn(
                "px-2.5 py-1 rounded-md text-[11px] font-semibold font-mono tabular-nums border transition",
                selected
                  ? "border-brand text-brand bg-brand/10"
                  : "border-border text-caption hover:text-ink hover:border-ink/40",
              )}
            >
              {step}%
            </button>
          )
        })}
        <span
          data-testid="ladder-chip-custom"
          aria-hidden="true"
          className="ml-1 inline-flex items-center px-2 py-0.5 rounded-md text-[10px] font-medium border border-dashed border-border text-caption"
          title="Drag the slider above for a custom percentage"
        >
          + Custom (drag slider)
        </span>
      </div>

      {/* ── Likelihood + Notify row ──────────────────────────────── */}
      <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
        <div className="text-[11px] text-body">
          {historicalHits != null ? (
            <span data-testid="ladder-historical-hits" className="text-caption">
              Last 3y: price reached{" "}
              <span className="font-mono tabular-nums font-semibold text-ink">
                {formatCurrency(targetPrice, currency, ticker)}
              </span>{" "}
              on{" "}
              <span className="font-mono tabular-nums font-semibold text-ink">
                {historicalHits}
              </span>{" "}
              {historicalHits === 1 ? "day" : "days"}.
            </span>
          ) : (
            <span className="text-caption">
              Target:{" "}
              <span className="font-mono tabular-nums font-semibold text-ink">
                {formatCurrency(targetPrice, currency, ticker)}
              </span>
            </span>
          )}
        </div>

        <button
          type="button"
          onClick={onPrimary}
          disabled={mutation.isPending}
          data-testid="ladder-primary"
          className={cn(
            "inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[12px] font-semibold border transition",
            inZone
              ? "border-emerald-400 bg-emerald-50 text-emerald-900 hover:bg-emerald-100 dark:border-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-200"
              : "border-brand text-brand bg-brand/5 hover:bg-brand/10",
            "disabled:opacity-50 disabled:cursor-not-allowed",
          )}
        >
          {inZone ? (
            <BellRing className="h-3.5 w-3.5" aria-hidden="true" />
          ) : (
            <Bell className="h-3.5 w-3.5" aria-hidden="true" />
          )}
          {primaryLabel}
        </button>
      </div>

      {confirmedPct != null && confirmedPct === pct && (
        <p
          role="status"
          aria-live="polite"
          data-testid="ladder-confirmed"
          className="mt-2 text-[11px] text-emerald-800 dark:text-emerald-300"
        >
          Alert set for {confirmedPct}% below Fair Value (
          <span className="font-mono tabular-nums">
            {formatCurrency(targetPrice, currency, ticker)}
          </span>
          ).
        </p>
      )}

      {error && (
        <p
          role="alert"
          data-testid="ladder-error"
          className="mt-2 text-[11px] text-amber-800 dark:text-amber-300"
        >
          {error}
        </p>
      )}
    </div>
  )
}

// ── Helpers ──────────────────────────────────────────────────────

interface StopProps {
  label: string
  pill: "F" | "T" | "P"
  price: number
  currency: string
  leftPct: number
  tone: "neutral" | "target" | "good"
  testId: string
}

function Stop({ label, pill, price, currency, leftPct, tone, testId }: StopProps) {
  const dotClass =
    tone === "good"
      ? "bg-emerald-500 ring-emerald-200 dark:ring-emerald-900"
      : tone === "target"
        ? "bg-brand ring-brand/20"
        : "bg-ink/70 dark:bg-ink/80 ring-border"
  return (
    <div
      data-testid={testId}
      className="absolute top-1/2 -translate-x-1/2 -translate-y-1/2"
      style={{ left: `${leftPct}%` }}
    >
      <div className="flex flex-col items-center">
        <span
          aria-hidden="true"
          className={cn(
            "absolute -translate-y-1/2 inline-flex items-center justify-center h-3.5 w-3.5 rounded-full ring-2 ring-offset-1 ring-offset-bg",
            dotClass,
          )}
          style={{ top: "50%" }}
        />
        <span
          className="absolute -top-6 whitespace-nowrap text-[10px] font-semibold uppercase tracking-wide text-caption flex items-center gap-1"
        >
          <span
            className={cn(
              "inline-flex items-center justify-center h-3 w-3 rounded-sm text-[8px] font-bold leading-none",
              tone === "good"
                ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/60 dark:text-emerald-200"
                : tone === "target"
                  ? "bg-brand/15 text-brand"
                  : "bg-border text-caption",
            )}
          >
            {pill}
          </span>
          {label}
        </span>
        <span className="absolute top-5 whitespace-nowrap text-[11px] font-mono tabular-nums font-semibold text-ink">
          {Number.isFinite(price) ? formatCurrency(price, currency) : "—"}
        </span>
      </div>
    </div>
  )
}
