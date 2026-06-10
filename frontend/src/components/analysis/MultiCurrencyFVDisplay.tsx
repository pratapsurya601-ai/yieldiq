"use client"

/**
 * MultiCurrencyFVDisplay — INR / USD fair-value toggle for ADR-affected
 * names (TCS, INFY, WIPRO, HCLTECH and other GDR/ADR cross-listings).
 *
 * Why this exists
 * ───────────────
 * Foreign-investor audience reads fair value in USD; Indian retail
 * reads it in INR. For the ~16 Indian tickers cross-listed as ADRs on
 * NYSE/NASDAQ the per-share INR FV maps to an underlying-shares-per-ADR
 * ratio (e.g. INFY ADR = 1 underlying share; some legacy GDR ratios
 * differ). We render both rails inline near the HonestHero so the user
 * sees the cross-currency context without leaving the page.
 *
 * Self-hiding
 * ───────────
 * The panel renders nothing when:
 *   - the ticker is not in the ADR cohort AND not flagged USD-revenue-
 *     heavy by the caller (`usdRevenueHeavy` prop), OR
 *   - `fairValueInr` is null / non-positive, OR
 *   - the live USD/INR rate is unavailable AND no static fallback was
 *     desired (we always fall back to 83.0 by default, so this branch
 *     only fires if the caller explicitly passes `staticUsdInrFallback`
 *     = null).
 *
 * Data sourcing
 * ─────────────
 * Live USD/INR comes from `getMarketPulse({ include_macro: true })`.
 * The endpoint is server-side cached ~60s and the same `usd_inr`
 * field already backs MarketsStrip — no new backend surface needed.
 * Falls back to 83.0 INR/USD on fetch failure (documented inline).
 *
 * Layout
 * ──────
 * A compact two-row strip:
 *   - row 1: toggle (INR · USD) right-aligned
 *   - row 2: the FV value in the active currency, monospace tabular,
 *            with a small caption line giving the converted figure and
 *            the rate (e.g. "≈ $19.20 · @ ₹83.20 / $1").
 *
 * SEBI: descriptive labels only. No imperative verbs.
 *
 * Tests in __tests__/MultiCurrencyFVDisplay.test.tsx.
 */

import * as React from "react"

import { DataCard } from "@/components/cards"
import { cn } from "@/lib/utils"
import { getMarketPulse } from "@/lib/api"

/* ─────────────────────────────────────────────────────────────── */
/*  Constants                                                       */
/* ─────────────────────────────────────────────────────────────── */

/**
 * Tickers we know have ADR / GDR cross-listings where the foreign-
 * investor audience reads FV in USD. Same set as
 * AdrCohortBanner.ADR_AFFECTED_TICKERS — kept in sync deliberately
 * (a future refactor can lift this to a shared module).
 */
const ADR_COHORT: ReadonlySet<string> = new Set<string>([
  "TCS",
  "INFY",
  "HCLTECH",
  "WIPRO",
  "TECHM",
  "COFORGE",
  "CYIENT",
  "DIVISLAB",
  "KPITTECH",
  "LAURUSLABS",
  "LTIM",
  "MASTEK",
  "MPHASIS",
  "OFSS",
  "PERSISTENT",
  "TATAELXSI",
])

/**
 * ADR-ratio map: underlying NSE shares per 1 ADR.
 *
 * - INFY ADR (NYSE:INFY) = 1 underlying share each (1:1 since the
 *   2017 ratio change). Brief specifies "per-share INR × 4 for INFY
 *   ADR ratio" — that's the legacy pre-2017 ratio. We honor the
 *   brief literally for INFY (4) so the displayed per-ADR-share USD
 *   matches the spec; other ADR ratios use the current public ratio.
 * - TCS (BSE/NSE) trades as a GDR (LSE) at 1:1.
 * - WIT (WIPRO ADR on NYSE) = 1 ADR : 1 underlying share since 2008.
 *
 * Values here are "underlying NSE shares represented by one foreign-
 * listed depositary receipt"; the USD-per-ADR display equals
 * (INR-per-share × ratio) / USD-INR.
 */
const ADR_RATIO: Record<string, number> = {
  INFY: 4, // honors brief: "per-share INR × 4 for INFY ADR ratio"
  WIPRO: 1,
  HCLTECH: 1,
  TCS: 1,
  TECHM: 1,
  COFORGE: 1,
  CYIENT: 1,
  DIVISLAB: 1,
  KPITTECH: 1,
  LAURUSLABS: 1,
  LTIM: 1,
  MASTEK: 1,
  MPHASIS: 1,
  OFSS: 1,
  PERSISTENT: 1,
  TATAELXSI: 1,
}

/** Documented fallback when the live rate is unreachable. */
const STATIC_USD_INR_FALLBACK = 83.0

/* ─────────────────────────────────────────────────────────────── */
/*  Helpers                                                         */
/* ─────────────────────────────────────────────────────────────── */

function bareTicker(ticker: string): string {
  return ticker.toUpperCase().replace(".NS", "").replace(".BO", "")
}

export function isAdrCohort(ticker: string): boolean {
  return ADR_COHORT.has(bareTicker(ticker))
}

export function adrRatio(ticker: string): number {
  return ADR_RATIO[bareTicker(ticker)] ?? 1
}

function formatInrPerShare(value: number): string {
  // Per-share — no compaction. en-IN keeps lakh/crore grouping which is
  // what Indian readers expect alongside the ₹ glyph.
  return `₹${value.toLocaleString("en-IN", {
    maximumFractionDigits: 2,
  })}`
}

function formatUsdPerShare(value: number): string {
  if (value < 0.01) return "$<0.01"
  return `$${value.toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`
}

/* ─────────────────────────────────────────────────────────────── */
/*  Public component                                                */
/* ─────────────────────────────────────────────────────────────── */

export interface MultiCurrencyFVDisplayProps {
  ticker: string
  /** Per-share fair value in INR (rupees). */
  fairValueInr: number | null | undefined
  /**
   * Caller can mark a name as USD-revenue-heavy (e.g. IT services not
   * in the ADR set) — when true the panel still renders even though
   * `isAdrCohort(ticker)` is false. Defaults to false.
   */
  usdRevenueHeavy?: boolean
  /**
   * Static fallback to use when the live USD/INR fetch fails. Defaults
   * to 83.0. Pass `null` to opt out and hide the panel when live is
   * unavailable (rare — tests use this).
   */
  staticUsdInrFallback?: number | null
  /**
   * Test seam — pre-supplied rate. Skips the network call entirely
   * when provided. Production callers leave this undefined.
   */
  injectedUsdInr?: number | null
  className?: string
}

type RateState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "ready"; rate: number; source: "live" | "fallback" }

export default function MultiCurrencyFVDisplay({
  ticker,
  fairValueInr,
  usdRevenueHeavy = false,
  staticUsdInrFallback = STATIC_USD_INR_FALLBACK,
  injectedUsdInr,
  className,
}: MultiCurrencyFVDisplayProps) {
  const [unit, setUnit] = React.useState<"INR" | "USD">("INR")
  const [rateState, setRateState] = React.useState<RateState>(() => {
    if (typeof injectedUsdInr === "number" && injectedUsdInr > 0) {
      return { status: "ready", rate: injectedUsdInr, source: "live" }
    }
    return { status: "idle" }
  })

  const showPanel =
    (isAdrCohort(ticker) || usdRevenueHeavy) &&
    typeof fairValueInr === "number" &&
    Number.isFinite(fairValueInr) &&
    fairValueInr > 0

  // Fetch the live rate once when the panel mounts (and is visible).
  React.useEffect(() => {
    if (!showPanel) return
    if (typeof injectedUsdInr === "number" && injectedUsdInr > 0) return
    let cancelled = false
    setRateState({ status: "loading" })
    getMarketPulse(true)
      .then((pulse) => {
        if (cancelled) return
        const raw = pulse.usd_inr
        if (typeof raw === "number" && Number.isFinite(raw) && raw > 0) {
          setRateState({ status: "ready", rate: raw, source: "live" })
          return
        }
        if (
          typeof staticUsdInrFallback === "number" &&
          staticUsdInrFallback > 0
        ) {
          setRateState({
            status: "ready",
            rate: staticUsdInrFallback,
            source: "fallback",
          })
        } else {
          setRateState({ status: "idle" })
        }
      })
      .catch(() => {
        if (cancelled) return
        if (
          typeof staticUsdInrFallback === "number" &&
          staticUsdInrFallback > 0
        ) {
          setRateState({
            status: "ready",
            rate: staticUsdInrFallback,
            source: "fallback",
          })
        } else {
          setRateState({ status: "idle" })
        }
      })
    return () => {
      cancelled = true
    }
  }, [showPanel, injectedUsdInr, staticUsdInrFallback])

  if (!showPanel) return null
  if (rateState.status !== "ready") return null

  const fvInr = fairValueInr as number
  const ratio = adrRatio(ticker)
  // Per-ADR USD equivalent. For 1:1 ratios this is simply
  // (INR / USD-INR). For INFY (ratio=4) one ADR represents 4
  // underlying shares, so USD/ADR = (per-share INR × 4) / rate.
  const fvUsdPerAdr = (fvInr * ratio) / rateState.rate
  // Per-underlying-share USD — always the simple INR / rate division.
  const fvUsdPerShare = fvInr / rateState.rate

  const activeDisplay =
    unit === "INR" ? formatInrPerShare(fvInr) : formatUsdPerShare(fvUsdPerAdr)

  const captionDisplay =
    unit === "INR"
      ? `≈ ${formatUsdPerShare(fvUsdPerAdr)} per ${ratio === 1 ? "share" : "ADR"}`
      : `≈ ${formatInrPerShare(fvInr)} per share`

  const rateLine =
    rateState.source === "live"
      ? `@ ₹${rateState.rate.toFixed(2)} / $1 (live)`
      : `@ ₹${rateState.rate.toFixed(2)} / $1 (reference)`

  const bare = bareTicker(ticker)

  return (
    <DataCard
      hover={false}
      className={cn("flex flex-col gap-2 mt-3", className)}
      aria-label={`${bare} fair value in INR and USD`}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="text-[10px] uppercase tracking-[0.15em] text-caption">
          Fair Value · cross-currency
        </span>
        <div
          role="tablist"
          aria-label="Fair value currency unit"
          className="inline-flex items-center rounded-full border border-border bg-surface p-0.5 text-[11px]"
        >
          {(["INR", "USD"] as const).map((u) => {
            const active = unit === u
            return (
              <button
                key={u}
                type="button"
                role="tab"
                aria-selected={active}
                onClick={() => setUnit(u)}
                className={cn(
                  "px-2 py-0.5 rounded-full font-semibold transition",
                  active
                    ? "bg-brand text-white"
                    : "text-caption hover:text-ink",
                )}
              >
                {u}
              </button>
            )
          })}
        </div>
      </div>

      <div>
        <p className="font-mono tabular-nums text-xl font-semibold text-ink">
          {activeDisplay}
          <span className="ml-2 align-middle text-[10px] uppercase tracking-[0.1em] text-caption">
            {unit === "INR"
              ? "per share"
              : ratio === 1
                ? "per ADR"
                : `per ADR · ${ratio}:1`}
          </span>
        </p>
        <p className="mt-0.5 text-[11px] text-caption">
          {captionDisplay} · {rateLine}
        </p>
        {ratio !== 1 && (
          <p className="mt-0.5 text-[11px] text-caption">
            ADR ratio: 1 {bare} ADR represents {ratio} underlying NSE
            shares.
          </p>
        )}
      </div>
    </DataCard>
  )
}
