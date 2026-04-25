"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import Prism from "@/components/prism/Prism"
import { fetchPrism } from "@/lib/prism"
import type { PrismData } from "@/components/prism/types"

const SUGGESTIONS = [
  { ticker: "RELIANCE.NS", label: "RELIANCE" },
  { ticker: "TCS.NS", label: "TCS" },
  { ticker: "INFY.NS", label: "INFY" },
  { ticker: "HDFCBANK.NS", label: "HDFCBANK" },
  { ticker: "ITC.NS", label: "ITC" },
]

/**
 * Hardcoded TCS demo used in the `idle` state so the Prism is never
 * empty. Gives a first-time visitor a concrete example of what each
 * axis looks like before they type anything. Values are editorial
 * picks — close enough to real TCS readings (FY25) to feel honest,
 * labelled explicitly as an example so we can't be accused of
 * misrepresenting live data.
 */
const TCS_DEMO: PrismData = {
  ticker: "TCS.NS",
  company_name: "Tata Consultancy Services",
  verdict_band: "undervalued",
  verdict_label: "Below Fair Value \u00b7 32.7% MoS",
  overall: 7.55,
  refraction_index: 0.7,
  pulse_velocity_hz: 0.4,
  disclaimer: "Illustrative example. Not investment advice.",
  pillars: [
    { key: "pulse",   score: 6.5, label: "Neutral",  why: "Steady momentum, low volatility.",              data_limited: false, weight: 0.10 },
    { key: "quality", score: 9.2, label: "Strong",   why: "Industry-leading ROE and margin stability.",    data_limited: false, weight: 0.22 },
    { key: "moat",    score: 7.5, label: "Wide",     why: "Entrenched enterprise relationships, scale.",   data_limited: false, weight: 0.18 },
    { key: "safety",  score: 8.1, label: "Strong",   why: "Net-cash balance sheet, durable coverage.",      data_limited: false, weight: 0.15 },
    { key: "growth",  score: 6.8, label: "Moderate", why: "Mid-single-digit revenue growth holding up.",   data_limited: false, weight: 0.15 },
    { key: "value",   score: 7.2, label: "Favorable", why: "Fair value \u20b93,465 vs price \u20b92,611.", data_limited: false, weight: 0.20 },
  ],
}

function normalize(t: string): string {
  const up = t.trim().toUpperCase()
  if (!up) return up
  if (/\.(NS|BO)$/.test(up)) return up
  return `${up}.NS`
}

interface StepFirstStockProps {
  onNext: (prism: PrismData | null) => void
}

type Status = "idle" | "loading" | "ready" | "error"

export default function StepFirstStock({ onNext }: StepFirstStockProps) {
  const [query, setQuery] = useState("")
  const [status, setStatus] = useState<Status>("idle")
  const [prism, setPrism] = useState<PrismData | null>(null)
  const [displayScore, setDisplayScore] = useState(0)
  const [errored, setErrored] = useState(false)
  const countRafRef = useRef<number | null>(null)
  const minDelayTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const startAnalysis = useCallback(async (tickerRaw: string) => {
    const ticker = normalize(tickerRaw)
    if (!ticker) return
    setStatus("loading")
    setPrism(null)
    setErrored(false)
    setDisplayScore(0)

    // Guarantee at least ~900ms of skeleton so the reveal lands dramatically
    // even on a warm cache.
    const startedAt = performance.now()
    try {
      const data = await fetchPrism(ticker)
      const elapsed = performance.now() - startedAt
      const wait = Math.max(0, 900 - elapsed)
      minDelayTimerRef.current = setTimeout(() => {
        setPrism(data)
        setStatus("ready")
      }, wait)
    } catch {
      const elapsed = performance.now() - startedAt
      const wait = Math.max(0, 700 - elapsed)
      minDelayTimerRef.current = setTimeout(() => {
        setErrored(true)
        setStatus("error")
      }, wait)
    }
  }, [])

  // Count up the composite score from 0 → final value over 800ms once
  // the Prism renders. Uses RAF so it feels in-sync with the spring.
  useEffect(() => {
    if (status !== "ready" || !prism) return
    const target = prism.overall
    const durationMs = 800
    const t0 = performance.now()
    const tick = (now: number) => {
      const p = Math.min(1, (now - t0) / durationMs)
      // easeOutCubic
      const eased = 1 - Math.pow(1 - p, 3)
      setDisplayScore(target * eased)
      if (p < 1) {
        countRafRef.current = requestAnimationFrame(tick)
      } else {
        setDisplayScore(target)
      }
    }
    countRafRef.current = requestAnimationFrame(tick)
    return () => {
      if (countRafRef.current != null) cancelAnimationFrame(countRafRef.current)
    }
  }, [status, prism])

  useEffect(
    () => () => {
      if (minDelayTimerRef.current != null) clearTimeout(minDelayTimerRef.current)
      if (countRafRef.current != null) cancelAnimationFrame(countRafRef.current)
    },
    [],
  )

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (query.trim()) void startAnalysis(query)
  }

  return (
    <div className="flex flex-col min-h-[calc(100vh-56px)] px-5 pb-8">
      <header className="pt-6 pb-4">
        <h1 className="font-editorial text-3xl sm:text-4xl text-ink leading-tight">
          Name a stock you know
        </h1>
        <p className="mt-2 text-base text-body">
          We&apos;ll show you how YieldIQ sees it — in one glance.
        </p>
      </header>

      {status === "idle" && (
        <>
          <form onSubmit={handleSubmit} className="mt-2">
            <label htmlFor="ob-search" className="sr-only">
              Search ticker or company
            </label>
            <div className="relative">
              <input
                id="ob-search"
                type="text"
                inputMode="text"
                autoComplete="off"
                autoCapitalize="characters"
                spellCheck={false}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Try RELIANCE, TCS, INFY…"
                className="w-full min-h-[52px] rounded-full border border-border bg-surface px-5 pr-14 text-base text-ink placeholder:text-caption focus:outline-none focus:ring-2 focus:ring-brand/60 focus:border-brand"
              />
              <button
                type="submit"
                disabled={!query.trim()}
                aria-label="Show me the Prism"
                className="absolute right-1.5 top-1/2 -translate-y-1/2 w-11 h-11 rounded-full bg-ink text-bg flex items-center justify-center disabled:bg-border disabled:text-caption transition-colors"
              >
                <svg viewBox="0 0 16 16" className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M3 8h10M9 4l4 4-4 4" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </button>
            </div>
          </form>
          <p className="text-xs text-caption mt-3">Or pick one of these</p>
          <div className="flex flex-wrap gap-2 mt-3">
            {SUGGESTIONS.map((s) => (
              <button
                key={s.ticker}
                type="button"
                onClick={() => {
                  setQuery(s.label)
                  void startAnalysis(s.ticker)
                }}
                className="min-h-[44px] px-4 rounded-full border border-border bg-surface text-sm font-medium text-ink hover:border-ink/40 active:scale-[0.98] transition-all"
              >
                {s.label}
              </button>
            ))}
          </div>

          {/* Pre-populated TCS demo so the Prism never looks empty. Rendered
              at ~55% opacity so it clearly reads as an example rather than
              a live result. Once the user types a ticker, the idle block
              is replaced by the `loading`/`ready` branches. */}
          <div className="mt-8 flex flex-col items-center" aria-hidden="true">
            <div className="opacity-60 w-full max-w-[240px]">
              <Prism data={TCS_DEMO} firstView={false} size={240} />
            </div>
            <p className="mt-3 text-xs text-caption text-center max-w-[18rem]">
              Example: <span className="font-semibold text-body">TCS</span> &middot; Fair Value &#8377;3,465 vs &#8377;2,611 &middot; MoS +32.7%
            </p>
            <p className="mt-1 text-xs text-caption text-center max-w-[18rem]">
              Type your own ticker above to see its shape.
            </p>
          </div>
        </>
      )}

      {status === "loading" && (
        <div className="flex-1 flex flex-col items-center justify-center animate-pulse">
          <div className="w-[280px] h-[280px] rounded-full bg-surface border border-border flex items-center justify-center">
            <div className="w-40 h-40 rounded-full bg-bg border border-border" />
          </div>
          <p className="text-sm text-caption mt-6">Reading the signal…</p>
        </div>
      )}

      {status === "ready" && prism && (
        <div
          className="flex-1 flex flex-col items-center justify-center"
          style={{
            animation: "onboardingReveal 700ms cubic-bezier(0.34, 1.56, 0.64, 1) both",
          }}
        >
          <div className="w-full max-w-[280px]">
            <Prism data={prism} firstView={true} size={280} />
          </div>
          <div className="mt-6 text-center">
            <div className="flex items-baseline justify-center gap-1">
              <span className="font-editorial text-6xl text-ink tabular-nums">
                {displayScore.toFixed(1)}
              </span>
              <span className="text-lg text-caption">/ 10</span>
            </div>
            <p className="mt-2 text-base font-semibold text-ink">
              {prism.verdict_label}
            </p>
            <p className="mt-1 text-sm text-body max-w-xs">
              {prism.company_name} — a composite of 6 pillars.
            </p>
            <p className="mt-3 text-xs text-caption">
              Model estimate. Not investment advice.
            </p>
          </div>
        </div>
      )}

      {status === "error" && (
        <div className="flex-1 flex flex-col items-center justify-center text-center px-4">
          <div className="w-14 h-14 rounded-full bg-surface border border-border flex items-center justify-center text-2xl">
            ◌
          </div>
          <p className="mt-4 text-base text-ink font-semibold">
            We couldn&apos;t read that one just now
          </p>
          <p className="mt-1 text-sm text-body max-w-xs">
            No matter — we&apos;ll still show you how the Prism works next.
          </p>
        </div>
      )}

      {(status === "ready" || status === "error") && (
        <div className="pt-6 sticky bottom-0 bg-bg">
          <button
            type="button"
            onClick={() => onNext(errored ? null : prism)}
            className="w-full min-h-[52px] rounded-full bg-ink text-bg font-semibold text-base hover:opacity-90 active:scale-[0.99] transition-all"
          >
            Next
          </button>
        </div>
      )}

      <style jsx>{`
        @keyframes onboardingReveal {
          from {
            opacity: 0;
            transform: scale(0.92) translateY(8px);
          }
          to {
            opacity: 1;
            transform: scale(1) translateY(0);
          }
        }
      `}</style>
    </div>
  )
}
