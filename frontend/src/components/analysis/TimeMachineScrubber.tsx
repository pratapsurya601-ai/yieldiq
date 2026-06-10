"use client"

/**
 * TimeMachineScrubber — T6.3 (2026-06-10).
 *
 * Interactive horizontal slider that lets the user "rewind" the
 * analysis page to any date in the persisted fair_value_history
 * series for this ticker. Sits ABOVE the ValuationTrajectoryChart
 * on the History tab.
 *
 * How it differs from the existing TimeSlider (Phase 2, 2026-05-25):
 *
 *   - TimeSlider uses 5 SNAP TICKS (6m / 1y / 2y / 3y / today) and
 *     fetches a fresh `analysis/{ticker}/as-of` snapshot for each
 *     debounced position. That gives a structured "what did YIQ
 *     think 1y ago" reading + tier gating.
 *
 *   - TimeMachineScrubber consumes the ALREADY-LOADED fv_history
 *     series (one row per day) and lets the user scrub continuously
 *     across the full window. Zero extra network round-trips —
 *     everything is a frontend lookup against the cached series. The
 *     trade-off is that historical fields without a column in
 *     fair_value_history (score, insights, peer commentary) fall
 *     back to "today" — we never invent data we don't have.
 *
 * Both components co-exist intentionally: the snap-tick slider is
 * the structured "rewind anchor" UX; the scrubber is the continuous
 * exploration UX paired with the trajectory chart.
 *
 * Data shape — the parent passes the same `FVHistoryPoint[]` series
 * the ValuationTrajectoryChart sibling uses (sorted oldest-first,
 * newest-last). `onDateChange(null)` is the explicit "today"
 * signal — a sibling TimeMachineProvider listens and broadcasts to
 * opt-in panels via `useTimeMachine()`.
 *
 * SEBI compliance — every user-facing string is screened against
 * `backend/services/analysis/sebi_filter.py BANNED_WORDS`. No advice
 * language; we show the model's historical FV and a factual
 * margin-of-safety percentage.
 */

import { useCallback, useMemo } from "react"
import { useQuery } from "@tanstack/react-query"

import { getFVHistory, type FVHistoryPoint, type FVHistoryResponse } from "@/lib/api"
import { useTimeMachine } from "@/lib/time-machine-context"
import { cn, formatCurrency } from "@/lib/utils"

export interface TimeMachineScrubberProps {
  ticker: string
  /**
   * fv_history series, oldest-first / newest-last. When omitted, the
   * component fetches the series itself via the same React-Query key
   * (`["fv-history", ticker, 5]`) the ValuationTrajectoryChart sibling
   * uses — both observers share one round-trip.
   */
  fvHistory?: FVHistoryPoint[]
  /** ISO YYYY-MM-DD selected via the parent's TimeMachineProvider. */
  selectedDate: string | null
  /**
   * Fired when the user moves the slider or clicks "Reset to today".
   * `null` means the scrubber is back at the rightmost tick — the
   * parent clears any scrubbed state in that case.
   */
  onDateChange: (date: string | null) => void
  currency?: string | null
  className?: string
}

function formatHumanDate(iso: string): string {
  // Defensive parse — `new Date("YYYY-MM-DD")` is UTC midnight which can
  // off-by-one in negative-offset zones; appending T00:00:00 keeps the
  // displayed date stable in the user's locale.
  try {
    const d = new Date(iso + "T00:00:00")
    return d.toLocaleDateString("en-IN", {
      day: "numeric",
      month: "short",
      year: "numeric",
    })
  } catch {
    return iso
  }
}

function pctDelta(then: number | null, now: number | null): number | null {
  if (then === null || now === null) return null
  if (!Number.isFinite(then) || !Number.isFinite(now)) return null
  if (now === 0) return null
  return ((then - now) / Math.abs(now)) * 100
}

/* ------------------------------------------------------------------ */
/* Delta row — "FV then vs today" + "MoS then vs today"                */
/* ------------------------------------------------------------------ */
interface DateDeltaProps {
  selected: FVHistoryPoint | null
  today: FVHistoryPoint | null
  currency?: string | null
}

function DateDelta({ selected, today, currency }: DateDeltaProps) {
  if (!selected || !today) {
    return (
      <p
        data-testid="time-machine-empty-delta"
        className="text-xs text-caption"
      >
        Drag the slider to pick a date — we&rsquo;ll show what the model said about
        this ticker on that day.
      </p>
    )
  }

  const fvDelta = pctDelta(selected.fair_value, today.fair_value)
  const priceDelta = pctDelta(selected.price, today.price)

  return (
    <dl
      data-testid="time-machine-delta"
      className="grid grid-cols-2 sm:grid-cols-3 gap-3 text-xs"
    >
      <div>
        <dt className="text-caption uppercase tracking-wide text-[10px]">
          Fair value then
        </dt>
        <dd className="font-mono tabular-nums font-semibold text-ink">
          {formatCurrency(selected.fair_value, currency)}
          {fvDelta !== null && (
            <span
              className={cn(
                "ml-1 text-[10px] font-normal",
                fvDelta >= 0 ? "text-emerald-600" : "text-rose-600",
              )}
              data-testid="time-machine-fv-delta"
            >
              {fvDelta >= 0 ? "+" : ""}
              {fvDelta.toFixed(1)}% vs today
            </span>
          )}
        </dd>
      </div>

      <div>
        <dt className="text-caption uppercase tracking-wide text-[10px]">
          Price then
        </dt>
        <dd className="font-mono tabular-nums font-semibold text-ink">
          {formatCurrency(selected.price, currency)}
          {priceDelta !== null && (
            <span
              className={cn(
                "ml-1 text-[10px] font-normal",
                priceDelta >= 0 ? "text-emerald-600" : "text-rose-600",
              )}
            >
              {priceDelta >= 0 ? "+" : ""}
              {priceDelta.toFixed(1)}% vs today
            </span>
          )}
        </dd>
      </div>

      <div>
        <dt className="text-caption uppercase tracking-wide text-[10px]">
          Gap to FV then
        </dt>
        <dd
          className={cn(
            "font-mono tabular-nums font-semibold",
            selected.mos_pct >= 0 ? "text-emerald-700" : "text-rose-700",
          )}
        >
          {selected.mos_pct >= 0 ? "+" : ""}
          {selected.mos_pct.toFixed(1)}%
        </dd>
      </div>
    </dl>
  )
}

/* ------------------------------------------------------------------ */
/* Main component                                                      */
/* ------------------------------------------------------------------ */
export default function TimeMachineScrubber({
  ticker,
  fvHistory,
  selectedDate,
  onDateChange,
  currency,
  className,
}: TimeMachineScrubberProps) {
  // When the caller does not pre-load the series, fetch it ourselves
  // via the same React-Query key the ValuationTrajectoryChart uses —
  // both observers de-duplicate to a single round-trip.
  const { data: queryData } = useQuery<FVHistoryResponse>({
    queryKey: ["fv-history", ticker, 5],
    queryFn: () => getFVHistory(ticker, 5),
    enabled: !!ticker && fvHistory === undefined,
    staleTime: 15 * 60 * 1000,
    retry: 1,
  })

  const series: FVHistoryPoint[] = fvHistory ?? queryData?.data ?? []

  // Memo the date axis once — the slider value indexes into this.
  const dates = useMemo(() => series.map((p) => p.date), [series])
  const maxIndex = Math.max(0, dates.length - 1)

  const todayPoint = series.length > 0 ? series[series.length - 1] : null

  const sliderValue =
    selectedDate === null ? maxIndex : Math.max(0, dates.indexOf(selectedDate))

  const selectedPoint =
    selectedDate === null
      ? null
      : series.find((p) => p.date === selectedDate) ?? null

  const onSliderChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const idx = Math.max(0, Math.min(maxIndex, parseInt(e.target.value, 10)))
      const date = dates[idx]
      // Snapping to the rightmost tick is the "back to today" affordance —
      // bubble null so any sibling that lights up off `selectedDate` clears
      // its scrubbed state.
      if (idx === maxIndex) {
        onDateChange(null)
      } else if (date) {
        onDateChange(date)
      }
    },
    [dates, maxIndex, onDateChange],
  )

  const onReset = useCallback(() => {
    onDateChange(null)
  }, [onDateChange])

  // Empty state — series hasn't loaded yet (cold ticker, fetch in
  // flight, or pre-coverage window). Render nothing rather than a
  // broken single-point slider.
  if (series.length < 2) {
    return null
  }

  const displayLabel =
    selectedDate === null
      ? "Today"
      : formatHumanDate(selectedDate)

  const cleanTicker = ticker.replace(".NS", "").replace(".BO", "")
  const dateRangeStart = formatHumanDate(dates[0])
  const dateRangeEnd = formatHumanDate(dates[maxIndex])

  return (
    <section
      data-testid="time-machine-scrubber"
      aria-label="Time machine — rewind the analysis to any past date in history"
      className={cn(
        "bg-surface rounded-2xl border border-border p-4 md:p-5",
        className,
      )}
    >
      <header className="flex items-start justify-between gap-3 mb-3">
        <div>
          <p className="text-[10px] uppercase tracking-wider font-semibold text-caption mb-1">
            Time machine
          </p>
          <h3 className="text-sm md:text-base font-semibold text-ink leading-snug">
            Rewind <span className="font-mono">{cleanTicker}</span> to any date
            between {dateRangeStart} and {dateRangeEnd}.
          </h3>
          <p className="text-[11px] text-caption mt-0.5">
            Scrubs the fair-value and margin-of-safety reading on this page to
            match the model&rsquo;s output on the selected day.
          </p>
        </div>
        {selectedDate !== null && (
          <button
            type="button"
            onClick={onReset}
            data-testid="time-machine-reset"
            className="shrink-0 text-xs font-semibold text-brand hover:underline"
          >
            Reset to today →
          </button>
        )}
      </header>

      {/* Slider with snap-to-day ticks */}
      <div className="relative">
        <input
          type="range"
          min={0}
          max={maxIndex}
          step={1}
          value={sliderValue}
          onChange={onSliderChange}
          data-testid="time-machine-slider"
          aria-label="Drag to rewind the analysis to a past date"
          aria-valuemin={0}
          aria-valuemax={maxIndex}
          aria-valuenow={sliderValue}
          aria-valuetext={displayLabel}
          className="w-full h-2 accent-brand cursor-pointer"
        />

        {/* Axis labels — oldest on the left, today on the right */}
        <div className="mt-1 flex justify-between text-[10px] text-caption select-none">
          <span>{dateRangeStart}</span>
          <span>Today</span>
        </div>

        <div className="mt-2 inline-flex items-center gap-2">
          <span
            data-testid="time-machine-current-label"
            className="inline-flex items-center px-2.5 py-1 rounded-full bg-brand text-white text-xs font-semibold tabular-nums"
          >
            {displayLabel}
          </span>
          <span className="text-[11px] text-caption">
            {selectedDate === null
              ? "Live values shown."
              : "Page is rewound — other panels show today’s data when no history exists for the chosen date."}
          </span>
        </div>
      </div>

      {/* Delta row */}
      <div className="mt-3 border-t border-border pt-3 min-h-[56px]">
        <DateDelta
          selected={selectedPoint}
          today={todayPoint}
          currency={currency}
        />
      </div>
    </section>
  )
}

/* ------------------------------------------------------------------ */
/* Connected variant — reads + writes the TimeMachineContext for       */
/* callers that have a TimeMachineProvider mounted up the tree (the    */
/* analysis-page History tab). Avoids each mount site re-implementing  */
/* the same `useState` ↔ context bridge.                               */
/* ------------------------------------------------------------------ */

export interface ConnectedTimeMachineScrubberProps {
  ticker: string
  currency?: string | null
  className?: string
}

export function ConnectedTimeMachineScrubber({
  ticker,
  currency,
  className,
}: ConnectedTimeMachineScrubberProps) {
  const { selectedDate, setSelectedDate } = useTimeMachine()
  return (
    <TimeMachineScrubber
      ticker={ticker}
      selectedDate={selectedDate}
      onDateChange={setSelectedDate}
      currency={currency}
      className={className}
    />
  )
}
