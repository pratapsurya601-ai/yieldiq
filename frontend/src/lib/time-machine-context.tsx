"use client"

/**
 * Time-Machine context (T6.3, 2026-06-10).
 *
 * Lets the TimeMachineScrubber on the History tab broadcast a
 * "selected date" (ISO YYYY-MM-DD) to any sibling panel on the
 * analysis page that wants to render its data AS-OF that date
 * rather than today.
 *
 * Why a context (not a top-level prop) — most analysis panels
 * (HonestCard, verdict pill, MoS chips, etc.) live deep inside
 * AnalysisBody's tab subtrees. Threading a `scrubbedDate` prop to
 * each one would balloon AnalysisBody's already-large surface.
 * A context lets opt-in consumers subscribe without changing the
 * non-consumer tree.
 *
 * Semantics:
 *   - `selectedDate === null` ⇒ "today" — consumers render live
 *     payload values unchanged.
 *   - `selectedDate === "YYYY-MM-DD"` ⇒ consumers look up the
 *     matching row in `fair_value_history` (passed alongside) and
 *     render the historical FV / MoS / verdict. Fields without a
 *     historical column (insights, scores, peer commentary)
 *     gracefully fall back to today's value — we never invent
 *     historical data we don't have.
 *
 * Default value (no provider mounted) leaves `selectedDate === null`
 * and a no-op setter, so every consumer is safe to call
 * `useTimeMachine()` even on pages that never mount the scrubber.
 */

import { createContext, useContext, useMemo, useState, type ReactNode } from "react"
import { useQuery } from "@tanstack/react-query"

import { getFVHistory, type FVHistoryPoint, type FVHistoryResponse } from "@/lib/api"

export interface TimeMachineState {
  /** ISO YYYY-MM-DD, or null when scrubber sits at "today". */
  selectedDate: string | null
  /** Updater — consumers should rarely call this; the scrubber owns writes. */
  setSelectedDate: (date: string | null) => void
  /**
   * Historical row matching `selectedDate`, or null when:
   *   - the scrubber is at "today"
   *   - no row exists for the date (sparse history coverage)
   *   - no provider is mounted (default fallback)
   */
  selectedPoint: FVHistoryPoint | null
}

const DEFAULT_STATE: TimeMachineState = {
  selectedDate: null,
  setSelectedDate: () => {
    /* no-op — provider not mounted */
  },
  selectedPoint: null,
}

export const TimeMachineContext = createContext<TimeMachineState>(DEFAULT_STATE)

export interface TimeMachineProviderProps {
  /**
   * Ticker to load the fv_history series for. The provider does its
   * own fetch (shared cache key with ValuationTrajectoryChart and the
   * scrubber, so zero extra round-trips).
   */
  ticker: string
  /**
   * Test-only — when supplied, skips the network and uses these
   * points to seed `selectedPoint`.
   */
  historyOverride?: FVHistoryPoint[]
  children: ReactNode
}

export function TimeMachineProvider({
  ticker,
  historyOverride,
  children,
}: TimeMachineProviderProps) {
  const [selectedDate, setSelectedDate] = useState<string | null>(null)

  const { data } = useQuery<FVHistoryResponse>({
    queryKey: ["fv-history", ticker, 5],
    queryFn: () => getFVHistory(ticker, 5),
    enabled: !!ticker && !historyOverride,
    staleTime: 15 * 60 * 1000,
    retry: 1,
  })

  const history: FVHistoryPoint[] = historyOverride ?? data?.data ?? []

  const value = useMemo<TimeMachineState>(() => {
    const selectedPoint =
      selectedDate === null
        ? null
        : history.find((p) => p.date === selectedDate) ?? null
    return { selectedDate, setSelectedDate, selectedPoint }
  }, [selectedDate, history])

  return (
    <TimeMachineContext.Provider value={value}>
      {children}
    </TimeMachineContext.Provider>
  )
}

/**
 * Subscribe to the current time-machine state. Safe to call from any
 * component on the analysis page — returns the default (null) state
 * when no provider is mounted, so non-History-tab callers behave as
 * if the user is on "today".
 */
export function useTimeMachine(): TimeMachineState {
  return useContext(TimeMachineContext)
}
