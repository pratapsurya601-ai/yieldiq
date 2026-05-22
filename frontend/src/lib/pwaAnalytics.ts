// Day-100a (2026-05-22): PWA install funnel telemetry.
//
// Fire-and-forget POSTs to /api/v1/telemetry/pwa-event. No await, no
// retry, no PII — UA is included but the backend truncates it to 80
// chars before logging. The event is best-effort: if the network is
// offline or the backend is rolling, we silently drop. The install
// banner itself must never block on this helper.

export type PwaEvent =
  | "prompted"
  | "installed"
  | "dismissed"
  | "ios_hint_shown"

export function trackPwaEvent(event: PwaEvent): void {
  if (typeof window === "undefined") return
  try {
    const ua = typeof navigator !== "undefined" ? navigator.userAgent : ""
    const body = JSON.stringify({ event, ua })
    const url = "/api/v1/telemetry/pwa-event"
    // sendBeacon is the right primitive for fire-and-forget telemetry
    // (survives page unload, doesn't block). Fall back to fetch with
    // keepalive when unavailable (older Safari).
    if (navigator.sendBeacon) {
      const blob = new Blob([body], { type: "application/json" })
      navigator.sendBeacon(url, blob)
      return
    }
    void fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
      keepalive: true,
    }).catch(() => {
      /* swallow — telemetry must never break UX */
    })
  } catch {
    /* swallow */
  }
}
