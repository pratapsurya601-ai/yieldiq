// frontend/src/lib/useSessionTrace.ts
// Phase J — session-observation harness.
//
// React hook that records UI events for the currently-authenticated
// session and POSTs them in batches to /api/v1/internal/session-trace.
//
// Design constraints (see Phase J spec):
//   * Anonymous users: hook is a no-op. Nothing is buffered, nothing
//     is sent. The backend also enforces auth as defense in depth.
//   * Per-session cap: 100 events. After that we stop buffering.
//   * Flush interval: every 30s OR when the buffer hits the cap.
//   * Captured events: page_view, search_query, button_click only.
//     Each carries a small JSON blob with the ticker / query / button
//     id — NO PII, NO form contents.
//   * Fire-and-forget. The hook never throws into render; network
//     failures silently drop the batch.
//
// Consumers:
//   * The app shell wraps the auth'd route group with
//     <SessionTraceProvider /> (TBD in a follow-up PR — this PR ships
//     only the hook + backend). For now the hook can be called
//     directly from any client component inside the auth'd shell.
//
// API:
//   const { trackPageView, trackSearch, trackClick } = useSessionTrace()
//   useEffect(() => { trackPageView(`/analysis/${ticker}`) }, [ticker])
//
"use client"

import { useCallback, useEffect, useMemo, useRef } from "react"

import { useAuthStore } from "@/store/authStore"

export type SessionTraceEventType =
  | "page_view"
  | "search_query"
  | "button_click"

export interface SessionTraceEvent {
  event_type: SessionTraceEventType
  event_data?: Record<string, unknown>
}

const MAX_EVENTS_PER_SESSION = 100
const FLUSH_INTERVAL_MS = 30_000
const ENDPOINT = "/api/v1/internal/session-trace"

function makeSessionId(): string {
  // Crypto-random is preferred; degrade gracefully if unavailable
  // (older sandboxed environments). The id is opaque — only used to
  // group events server-side.
  try {
    if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
      return crypto.randomUUID()
    }
  } catch {
    /* fall through */
  }
  return `st_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`
}

interface SessionTraceApi {
  trackPageView: (path: string) => void
  trackSearch: (query: string) => void
  trackClick: (buttonId: string, extra?: Record<string, unknown>) => void
}

export function useSessionTrace(): SessionTraceApi {
  // Read the auth store imperatively so unauth'd visitors never even
  // subscribe to it (the hook is then a no-op).
  const userId = useAuthStore((s) => s.userId)
  const token = useAuthStore((s) => s.token)
  const isAuthed = Boolean(userId && token)

  // Buffer + counter + session id live in refs so they survive
  // re-renders without retriggering effects.
  const bufferRef = useRef<SessionTraceEvent[]>([])
  const sentCountRef = useRef<number>(0)
  const sessionIdRef = useRef<string>("")

  // Initialise sessionId once per mount. The hook is intended to be
  // mounted once at the auth'd-shell root; if it's mounted per page,
  // each page gets its own session id, which is acceptable but
  // produces more rows. (Not a correctness issue.)
  if (sessionIdRef.current === "") {
    sessionIdRef.current = makeSessionId()
  }

  const flush = useCallback(() => {
    if (!isAuthed) return
    if (bufferRef.current.length === 0) return
    if (typeof window === "undefined") return

    const batch = bufferRef.current
    bufferRef.current = []

    const body = JSON.stringify({
      session_id: sessionIdRef.current,
      events: batch,
    })

    try {
      // Use fetch + keepalive so the JWT goes through (sendBeacon
      // cannot set Authorization headers).
      void fetch(ENDPOINT, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body,
        keepalive: true,
      }).catch(() => {
        /* swallow — traces are advisory, never block UX */
      })
    } catch {
      /* swallow */
    }
  }, [isAuthed, token])

  // Periodic flush. Only schedules when authed; tears down cleanly
  // on unmount or auth-state change.
  useEffect(() => {
    if (!isAuthed) return
    if (typeof window === "undefined") return

    const id = window.setInterval(flush, FLUSH_INTERVAL_MS)
    return () => {
      window.clearInterval(id)
      // Best-effort final flush on teardown.
      flush()
    }
  }, [isAuthed, flush])

  const enqueue = useCallback(
    (evt: SessionTraceEvent) => {
      if (!isAuthed) return
      if (sentCountRef.current + bufferRef.current.length >= MAX_EVENTS_PER_SESSION) {
        return
      }
      bufferRef.current.push(evt)
      sentCountRef.current += 1
      if (bufferRef.current.length >= 20) {
        // Soft batch threshold — flush early when we've accumulated
        // ~20 events to keep the per-POST payload small.
        flush()
      }
    },
    [isAuthed, flush]
  )

  const api = useMemo<SessionTraceApi>(
    () => ({
      trackPageView: (path: string) =>
        enqueue({ event_type: "page_view", event_data: { path } }),
      trackSearch: (query: string) =>
        // Don't log the query text itself by default — it could carry
        // company names users consider private. Log only the length
        // class. If we later want the query text, gate it behind an
        // explicit user opt-in.
        enqueue({
          event_type: "search_query",
          event_data: { length_class: classifyLength(query) },
        }),
      trackClick: (buttonId: string, extra?: Record<string, unknown>) =>
        enqueue({
          event_type: "button_click",
          event_data: { button_id: buttonId, ...(extra ?? {}) },
        }),
    }),
    [enqueue]
  )

  return api
}

function classifyLength(s: string): "empty" | "short" | "medium" | "long" {
  const len = (s ?? "").trim().length
  if (len === 0) return "empty"
  if (len < 4) return "short"
  if (len < 12) return "medium"
  return "long"
}

// Exposed for tests — not part of the public API.
export const __INTERNAL = {
  MAX_EVENTS_PER_SESSION,
  FLUSH_INTERVAL_MS,
  ENDPOINT,
  classifyLength,
}
