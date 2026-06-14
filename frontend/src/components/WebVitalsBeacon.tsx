"use client"

/**
 * WebVitalsBeacon — real-user Core Web Vitals (RUM), zero-dependency.
 *
 * Lab traces (Chrome DevTools) only measure one machine. This captures
 * field metrics from real visitors via the native PerformanceObserver
 * and beacons them once per page view (on first page-hide) to
 * POST /api/v1/telemetry/web-vital, where the backend stores them for
 * the /admin/web-vitals p75 dashboard.
 *
 * No `web-vitals` npm dep on purpose (bundle + lockfile cost). The one
 * place that's genuinely tricky to DIY is CLS — implemented here with
 * the CrUX "session window" algorithm (max of 1s-gap / 5s-cap windows).
 * INP is an approximation (max event-processing latency) rather than the
 * library's exact high-percentile-of-interactions, which is fine for a
 * p75 trend dashboard; it's labelled as such in the PR.
 *
 * Renders nothing. Mounted once in app/layout.tsx next to <Analytics />.
 */
import { useEffect } from "react"

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL || "https://api.yieldiq.in"

type MetricName = "LCP" | "CLS" | "INP" | "TTFB" | "FCP"

// The rating band is derived server-side from `value` (the backend owns
// the Core-Web-Vitals p75 thresholds — single source of truth), so the
// client just reports raw metric values.

// Collapse high-cardinality dynamic routes to a template so the dashboard
// groups by route (not per-ticker) — keeps cardinality + privacy sane.
function templatePath(p: string): string {
  return p
    .replace(/^\/(analysis|stock|fair-value|report)\/[^/]+.*/, "/$1/[ticker]")
    .replace(/^\/funds\/[^/]+.*/, "/funds/[scheme]")
    .replace(/^\/screener\/[^/]+.*/, "/screener/[preset]")
    .slice(0, 120)
}

export default function WebVitalsBeacon() {
  useEffect(() => {
    if (
      typeof window === "undefined" ||
      typeof PerformanceObserver === "undefined"
    ) {
      return
    }

    const metrics: Partial<Record<MetricName, number>> = {}
    let sent = false

    // TTFB — navigation responseStart is relative to navigation start.
    try {
      const nav = performance.getEntriesByType(
        "navigation",
      )[0] as PerformanceNavigationTiming | undefined
      if (nav && nav.responseStart > 0) metrics.TTFB = nav.responseStart
    } catch {
      /* no-op */
    }

    const observers: PerformanceObserver[] = []
    const obs = (
      type: string,
      cb: (entries: PerformanceEntry[]) => void,
      extra: Record<string, unknown> = {},
    ) => {
      try {
        const po = new PerformanceObserver((list) => cb(list.getEntries()))
        po.observe({ type, buffered: true, ...extra } as PerformanceObserverInit)
        observers.push(po)
      } catch {
        /* entry type unsupported in this browser — skip */
      }
    }

    // FCP
    obs("paint", (entries) => {
      for (const e of entries) {
        if (e.name === "first-contentful-paint") metrics.FCP = e.startTime
      }
    })

    // LCP — keep the latest candidate (finalised on hide).
    obs("largest-contentful-paint", (entries) => {
      const last = entries[entries.length - 1] as
        | (PerformanceEntry & { renderTime?: number; loadTime?: number })
        | undefined
      if (last) {
        metrics.LCP = last.renderTime || last.loadTime || last.startTime
      }
    })

    // CLS — CrUX session-window algorithm (1s gap / 5s cap; max window).
    let clsValue = 0
    let sessionValue = 0
    let sessionFirst = 0
    let sessionLast = 0
    obs("layout-shift", (entries) => {
      for (const e of entries as (PerformanceEntry & {
        value: number
        hadRecentInput: boolean
      })[]) {
        if (e.hadRecentInput) continue
        const ts = e.startTime
        if (
          sessionValue &&
          ts - sessionLast < 1000 &&
          ts - sessionFirst < 5000
        ) {
          sessionValue += e.value
          sessionLast = ts
        } else {
          sessionValue = e.value
          sessionFirst = ts
          sessionLast = ts
        }
        if (sessionValue > clsValue) clsValue = sessionValue
      }
      metrics.CLS = clsValue
    })

    // INP (approx) — max event-processing latency over the page view.
    let inp = 0
    obs(
      "event",
      (entries) => {
        for (const e of entries as (PerformanceEntry & {
          duration: number
        })[]) {
          if (e.duration > inp) inp = e.duration
        }
        if (inp > 0) metrics.INP = inp
      },
      { durationThreshold: 40 },
    )

    const flush = () => {
      if (sent) return
      const items = (Object.keys(metrics) as MetricName[])
        .filter((k) => typeof metrics[k] === "number")
        .map((k) => ({
          name: k,
          value: Math.round((metrics[k] as number) * 1000) / 1000,
        }))
      if (!items.length) return
      sent = true
      const conn = (
        navigator as Navigator & { connection?: { effectiveType?: string } }
      ).connection?.effectiveType
      const navEntry = performance.getEntriesByType("navigation")[0] as
        | PerformanceNavigationTiming
        | undefined
      const payload = {
        metrics: items,
        path: templatePath(window.location.pathname),
        nav_type: navEntry?.type,
        conn,
      }
      try {
        const blob = new Blob([JSON.stringify(payload)], {
          type: "application/json",
        })
        const url = `${API_BASE}/api/v1/telemetry/web-vital`
        if (navigator.sendBeacon) {
          navigator.sendBeacon(url, blob)
        } else {
          fetch(url, { method: "POST", body: blob, keepalive: true }).catch(
            () => {},
          )
        }
      } catch {
        /* never let telemetry break the page */
      }
    }

    const onVisibility = () => {
      if (document.visibilityState === "hidden") flush()
    }
    document.addEventListener("visibilitychange", onVisibility)
    window.addEventListener("pagehide", flush)

    return () => {
      document.removeEventListener("visibilitychange", onVisibility)
      window.removeEventListener("pagehide", flush)
      observers.forEach((o) => {
        try {
          o.disconnect()
        } catch {
          /* no-op */
        }
      })
    }
  }, [])

  return null
}
