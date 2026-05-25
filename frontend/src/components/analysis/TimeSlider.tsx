"use client"

/**
 * TimeSlider — Phase 2 "show me the receipts" surface.
 *
 * Horizontal slider above the hero that lets a user replay the
 * analysis as it stood 6m / 1y / 2y / 3y ago. Hits the new
 * `/api/v1/analysis/{ticker}/as-of` endpoint with a 300ms debounce
 * and bubbles the snapshot up via `onAsOfChange`. When the slider
 * sits at the "Today" tick the callback fires with `null`, which is
 * the signal to AnalysisBody to render the live payload as usual.
 *
 * Tier-gating: free users can only drag back to the 1y tick — past
 * that the track fades and an "Unlock full history" CTA renders in
 * place of the live snapshot. Paid plans (starter / pro / analyst)
 * get the full available range.
 *
 * Data caveat: `fair_value_history` only started populating in Feb
 * 2026, so 2y / 3y positions on most tickers will return
 * `data_available: false`. We render a calm "We started tracking
 * fair value for this ticker on X" line in that case — never a hard
 * empty state. The feature gets more powerful with every passing
 * day as history accumulates.
 *
 * SEBI: every user-facing string is screened against
 * backend/services/analysis/sebi_filter.py BANNED_WORDS.
 */

import Link from "next/link"
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react"
import { useQuery } from "@tanstack/react-query"
import { getAnalysisAsOf, type AsOfAnalysis } from "@/lib/api"
import { useAuthStore } from "@/store/authStore"
import { CountUp } from "@/components/anim"
import { formatCurrency, formatPct } from "@/lib/utils"

// ─── Tick positions (days back from today) ─────────────────────────
// Order matters: rendered left-to-right. "Today" is the rightmost.
const TICKS: Array<{ daysBack: number; label: string; short: string }> = [
  { daysBack: 365 * 3, label: "3 years ago", short: "3y" },
  { daysBack: 365 * 2, label: "2 years ago", short: "2y" },
  { daysBack: 365, label: "1 year ago", short: "1y" },
  { daysBack: 180, label: "6 months ago", short: "6m" },
  { daysBack: 0, label: "Today", short: "Today" },
]

// Free-tier cap: anything older than this is gated behind the
// upgrade CTA. Matches /fv-history's free-tier clamp.
const FREE_TIER_MAX_DAYS_BACK = 365

function isoDaysAgo(daysBack: number): string {
  const d = new Date()
  d.setDate(d.getDate() - daysBack)
  return d.toISOString().slice(0, 10)
}

function formatHumanDate(iso: string): string {
  try {
    const d = new Date(iso + "T00:00:00")
    return d.toLocaleDateString(undefined, {
      day: "numeric",
      month: "short",
      year: "numeric",
    })
  } catch {
    return iso
  }
}

interface Props {
  ticker: string
  /** Live fair value (for the "vs today" comparison row). */
  liveFairValue: number | null
  /** Live MoS % (for the "vs today" comparison row). */
  liveMosPct: number | null
  currency?: string | null
  /**
   * Called with the historical snapshot whenever the slider lands on
   * a non-today position. Called with `null` when the slider returns
   * to "Today" — the parent then renders its live payload.
   */
  onAsOfChange: (snapshot: AsOfAnalysis | null) => void
}

export default function TimeSlider({
  ticker,
  liveFairValue,
  liveMosPct,
  currency,
  onAsOfChange,
}: Props) {
  // Range index 0..(TICKS.length-1). Default = rightmost (Today).
  const [tickIndex, setTickIndex] = useState<number>(TICKS.length - 1)
  // Debounced index used for the actual fetch. Keeps drag-gestures
  // from firing N queries per second.
  const [debouncedIndex, setDebouncedIndex] = useState<number>(TICKS.length - 1)
  const debounceRef = useRef<number | null>(null)

  useEffect(() => {
    if (debounceRef.current !== null) {
      window.clearTimeout(debounceRef.current)
    }
    debounceRef.current = window.setTimeout(() => {
      setDebouncedIndex(tickIndex)
    }, 300)
    return () => {
      if (debounceRef.current !== null) {
        window.clearTimeout(debounceRef.current)
      }
    }
  }, [tickIndex])

  const tier = useAuthStore((s) => s.tier)
  const isPaid = tier === "starter" || tier === "pro" || tier === "analyst"

  const activeTick = TICKS[tickIndex] ?? TICKS[TICKS.length - 1]
  const debouncedTick = TICKS[debouncedIndex] ?? TICKS[TICKS.length - 1]
  const isToday = activeTick.daysBack === 0
  const debouncedIsToday = debouncedTick.daysBack === 0
  const gatedForFree = !isPaid && debouncedTick.daysBack > FREE_TIER_MAX_DAYS_BACK
  const isoForFetch = useMemo(
    () => isoDaysAgo(debouncedTick.daysBack),
    [debouncedTick.daysBack],
  )

  // Only fetch when we need a historical snapshot. Live (Today) and
  // gated-for-free positions skip the network entirely.
  const shouldFetch = !debouncedIsToday && !gatedForFree
  const { data: snapshot, isFetching } = useQuery({
    queryKey: ["analysis-as-of", ticker, isoForFetch],
    queryFn: () => getAnalysisAsOf(ticker, isoForFetch),
    enabled: !!ticker && shouldFetch,
    staleTime: 30 * 60 * 1000,
    retry: 1,
  })

  // Bubble up the active snapshot. Today → null so the parent renders
  // live. Gated free positions also bubble null because we never
  // mutate the page underneath the upgrade CTA.
  useEffect(() => {
    if (debouncedIsToday || gatedForFree) {
      onAsOfChange(null)
      return
    }
    if (snapshot) onAsOfChange(snapshot)
  }, [snapshot, debouncedIsToday, gatedForFree, onAsOfChange])

  const onSliderChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const next = Math.max(0, Math.min(TICKS.length - 1, Number(e.target.value)))
    setTickIndex(next)
  }, [])

  const onReset = useCallback(() => {
    setTickIndex(TICKS.length - 1)
    setDebouncedIndex(TICKS.length - 1)
    onAsOfChange(null)
  }, [onAsOfChange])

  // Comparison row (rendered only when we have a historical snapshot)
  const fvThen = snapshot?.fair_value ?? null
  const mosThen = snapshot?.mos_pct ?? null

  return (
    <section
      data-testid="time-slider"
      aria-label="Time machine — replay this analysis at a past date"
      className="bg-bg dark:bg-surface border border-border rounded-2xl p-4 md:p-5 mb-4"
    >
      <header className="mb-3">
        <p className="text-[10px] uppercase tracking-wider font-semibold text-caption mb-1">
          Time machine
        </p>
        <h2 className="text-sm md:text-base font-semibold text-ink leading-snug">
          What did YieldIQ think about{" "}
          <span className="font-mono">
            {ticker.replace(".NS", "").replace(".BO", "")}
          </span>{" "}
          on{" "}
          <span className="text-brand">
            {isToday ? "today" : formatHumanDate(isoDaysAgo(activeTick.daysBack))}
          </span>
          ?
        </h2>
      </header>

      {/* Slider track */}
      <div className="relative">
        {/* Tick labels above the rail */}
        <div className="flex justify-between text-[10px] md:text-xs text-caption mb-1.5 select-none">
          {TICKS.map((t, i) => {
            const isGated = !isPaid && t.daysBack > FREE_TIER_MAX_DAYS_BACK
            return (
              <button
                key={t.short}
                type="button"
                onClick={() => setTickIndex(i)}
                className={`px-1 py-0.5 rounded transition ${
                  i === tickIndex
                    ? "text-brand font-semibold"
                    : "hover:text-ink"
                } ${isGated ? "opacity-40" : ""}`}
                aria-label={`Jump to ${t.label}`}
              >
                {t.short}
              </button>
            )
          })}
        </div>

        <input
          type="range"
          min={0}
          max={TICKS.length - 1}
          step={1}
          value={tickIndex}
          onChange={onSliderChange}
          aria-label="Drag to replay the analysis at a past date"
          aria-valuemin={0}
          aria-valuemax={TICKS.length - 1}
          aria-valuenow={tickIndex}
          aria-valuetext={activeTick.label}
          className="w-full h-2 accent-brand cursor-pointer"
        />

        <div className="mt-2 flex items-center justify-between gap-3 flex-wrap">
          <div className="inline-flex items-center gap-2">
            <span className="inline-flex items-center px-2.5 py-1 rounded-full bg-brand text-white text-xs font-semibold tabular-nums">
              {isToday
                ? "Today"
                : formatHumanDate(isoDaysAgo(activeTick.daysBack))}
            </span>
            {isFetching && !isToday && !gatedForFree ? (
              <span className="text-[11px] text-caption" aria-live="polite">
                Loading snapshot…
              </span>
            ) : null}
          </div>
          {!isToday && (
            <button
              type="button"
              onClick={onReset}
              className="text-xs font-semibold text-brand hover:underline"
            >
              Reset to today →
            </button>
          )}
        </div>
      </div>

      {/* Body row — snapshot vs today comparison, OR upgrade CTA. */}
      <div className="mt-3 border-t border-border pt-3 min-h-[56px]">
        {isToday ? (
          <p className="text-xs text-caption">
            Drag the slider left to see what YieldIQ thought about this
            ticker in the past.
          </p>
        ) : gatedForFree ? (
          <div className="flex items-center justify-between gap-3 flex-wrap">
            <p className="text-xs text-caption max-w-md">
              Free plans can replay the last 12 months. Upgrade to step
              further back into history.
            </p>
            <Link
              href="/account?upgrade=true"
              className="inline-flex items-center rounded-full px-4 py-1.5 text-xs font-semibold bg-brand text-white hover:opacity-90 transition"
            >
              Unlock full history →
            </Link>
          </div>
        ) : !snapshot ? (
          <p className="text-xs text-caption">Loading snapshot…</p>
        ) : !snapshot.data_available ? (
          <p className="text-xs text-caption">
            {snapshot.limitations ??
              "No fair-value record for this date yet."}
          </p>
        ) : (
          <dl className="grid grid-cols-2 sm:grid-cols-3 gap-3 text-xs">
            <div>
              <dt className="text-caption uppercase tracking-wide text-[10px]">
                Fair value then
              </dt>
              <dd className="font-mono tabular-nums font-semibold text-ink">
                {fvThen !== null ? (
                  <CountUp
                    to={fvThen}
                    decimals={0}
                    format={(n) => formatCurrency(n, currency, ticker)}
                  />
                ) : (
                  "—"
                )}
                {liveFairValue !== null && fvThen !== null ? (
                  <span className="ml-1 text-[10px] text-caption font-normal">
                    vs today {formatCurrency(liveFairValue, currency, ticker)}
                  </span>
                ) : null}
              </dd>
            </div>
            <div>
              <dt className="text-caption uppercase tracking-wide text-[10px]">
                Discount to FV then
              </dt>
              <dd className="font-mono tabular-nums font-semibold text-ink">
                {mosThen !== null ? (
                  <CountUp
                    to={mosThen}
                    decimals={1}
                    format={(n) => formatPct(n)}
                  />
                ) : (
                  "—"
                )}
                {liveMosPct !== null && mosThen !== null ? (
                  <span className="ml-1 text-[10px] text-caption font-normal">
                    vs today {formatPct(liveMosPct)}
                  </span>
                ) : null}
              </dd>
            </div>
            <div>
              <dt className="text-caption uppercase tracking-wide text-[10px]">
                Price then
              </dt>
              <dd className="font-mono tabular-nums font-semibold text-ink">
                {snapshot.current_price !== null ? (
                  formatCurrency(snapshot.current_price, currency, ticker)
                ) : (
                  "—"
                )}
              </dd>
            </div>
          </dl>
        )}
      </div>
    </section>
  )
}
