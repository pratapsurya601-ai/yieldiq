/**
 * useLivePrice(ticker, fallback, intervalMs=60_000)
 *
 * Poll /api/v1/public/quote/{ticker} for the latest live_quotes row
 * and return the price as a number. Used by <LiveMosDisplay/> on the
 * analysis page hero so margin-of-safety updates as the market price
 * moves — without re-running the full analysis pipeline.
 *
 * Returns the cached `fallback` whenever:
 *   - the fetch has not yet resolved,
 *   - the endpoint returned price=null (no live quote yet),
 *   - the request errored or was aborted on unmount.
 *
 * The polling timer pauses when document.hidden becomes true so
 * background tabs don't burn the user's data plan; it resumes on
 * `visibilitychange` flipping back. Same pattern the live news feed
 * uses on the home page — no new abstraction.
 */

import { useEffect, useRef, useState } from "react"

export interface UseLivePriceResult {
  /** The price to render — live when available, fallback otherwise. */
  price: number
  /** True once a successful fetch has returned a non-null price. */
  isLive: boolean
  /** Server timestamp of the live quote (ISO 8601), or null. */
  asOf: string | null
  /** True only during the first fetch; flips false after either
   *  the first response OR the first error. */
  isInitialLoad: boolean
}

const DEFAULT_INTERVAL_MS = 60_000

function _resolveApiBase(): string {
  // Mirrors the pattern in frontend/src/lib/api.ts — env var with
  // local-dev fallback. Inlined here so this hook stays self-contained
  // and doesn't pull the full axios client into the analysis-hero
  // bundle just for one fetch.
  return process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"
}

function _resolveQuoteUrl(ticker: string): string {
  const base = _resolveApiBase()
  const t = encodeURIComponent(ticker.trim().toUpperCase())
  return `${base}/api/v1/public/quote/${t}`
}

export function useLivePrice(
  ticker: string,
  fallback: number,
  intervalMs: number = DEFAULT_INTERVAL_MS,
): UseLivePriceResult {
  const [livePrice, setLivePrice] = useState<number | null>(null)
  const [asOf, setAsOf] = useState<string | null>(null)
  const [isInitialLoad, setIsInitialLoad] = useState<boolean>(true)

  // Cancel-on-unmount guard kept outside React state so it persists
  // across the polling timer callbacks without re-render churn.
  const cancelledRef = useRef<boolean>(false)

  useEffect(() => {
    cancelledRef.current = false
    if (!ticker) {
      setIsInitialLoad(false)
      return () => {
        cancelledRef.current = true
      }
    }

    const url = _resolveQuoteUrl(ticker)
    const _settleInitial = () => {
      if (!cancelledRef.current) setIsInitialLoad(false)
    }

    const fetchPrice = async () => {
      if (typeof document !== "undefined" && document.hidden) return
      try {
        const res = await fetch(url, {
          method: "GET",
          credentials: "omit",
          cache: "no-store",
        })
        if (cancelledRef.current) return
        if (!res.ok) {
          _settleInitial()
          return
        }
        const data = await res.json().catch(() => null)
        if (cancelledRef.current || data == null) {
          _settleInitial()
          return
        }
        const raw = (data as { price?: unknown }).price
        const px =
          typeof raw === "number" && Number.isFinite(raw) && raw > 0
            ? raw
            : null
        setLivePrice(px)
        const ts = (data as { as_of?: unknown }).as_of
        setAsOf(typeof ts === "string" ? ts : null)
      } catch {
        // network error / cancelled — keep fallback, just settle the
        // initial-load flag so the chip can stop showing a skeleton.
      } finally {
        _settleInitial()
      }
    }

    void fetchPrice()
    const id = window.setInterval(() => {
      void fetchPrice()
    }, Math.max(15_000, intervalMs))

    const onVis = () => {
      if (!document.hidden) void fetchPrice()
    }
    document.addEventListener("visibilitychange", onVis)

    return () => {
      cancelledRef.current = true
      window.clearInterval(id)
      document.removeEventListener("visibilitychange", onVis)
    }
  }, [ticker, intervalMs])

  const price =
    livePrice != null && Number.isFinite(livePrice) && livePrice > 0
      ? livePrice
      : fallback
  return {
    price,
    isLive: livePrice != null,
    asOf,
    isInitialLoad,
  }
}

export default useLivePrice
