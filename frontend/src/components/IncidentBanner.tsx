"use client"

import { useEffect, useState } from "react"
import Link from "next/link"

/**
 * IncidentBanner — dismissible top-of-page notice for the most recent
 * service incident.
 *
 * The trust premise: a visitor who landed on yieldiq.in *during* an
 * outage (or the day after) is not left guessing whether the site
 * is fine now. We poll /api/v1/public/incidents on mount and, if
 * the most recent incident is open OR resolved within the last 7 days,
 * render a slim bar at the top with a link to /status.
 *
 * Dismissal is per-incident (localStorage `incident-banner-dismissed-<id>`)
 * so an active visitor doesn't see the same notice on every page-view,
 * but a fresh incident still surfaces.
 *
 * Only the single most-recent incident is shown — we deliberately do
 * not stack banners. The /status page is the place for the full list.
 */

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL || "https://api.yieldiq.in"
const RECENT_DAYS = 7
const DISMISS_KEY_PREFIX = "incident-banner-dismissed-"

interface Incident {
  id: number
  started_at: string
  ended_at: string | null
  severity: "major" | "minor" | "partial" | string
  surface: string
  title: string
  description: string
  resolution: string | null
}

interface IncidentsPayload {
  incidents: Incident[]
  current_status: "operational" | "degraded" | "outage" | string
}

function formatShortDate(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleDateString("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
  })
}

function isWithinLastDays(iso: string, days: number): boolean {
  const t = new Date(iso).getTime()
  if (Number.isNaN(t)) return false
  const cutoff = Date.now() - days * 24 * 60 * 60 * 1000
  return t >= cutoff
}

export default function IncidentBanner() {
  const [incident, setIncident] = useState<Incident | null>(null)
  const [dismissed, setDismissed] = useState(false)

  useEffect(() => {
    let cancelled = false
    async function load() {
      try {
        const res = await fetch(`${API_BASE}/api/v1/public/incidents`, {
          // Banner cadence is independent of /status page caching;
          // a 5-min cached payload is plenty fresh for a banner.
          cache: "no-store",
        })
        if (!res.ok) return
        const data: IncidentsPayload = await res.json()
        if (cancelled) return

        // Pick the most recent incident that's either open or recently resolved.
        const candidate = data.incidents.find((inc) => {
          if (inc.ended_at === null || inc.ended_at === "") return true
          return isWithinLastDays(inc.ended_at, RECENT_DAYS)
        })
        if (!candidate) return

        // Per-incident dismissal — stored as `incident-banner-dismissed-<id>`.
        if (typeof window !== "undefined") {
          const key = `${DISMISS_KEY_PREFIX}${candidate.id}`
          if (window.localStorage.getItem(key) === "1") {
            return
          }
        }
        setIncident(candidate)
      } catch {
        // Silent fail — a banner that doesn't render is preferable to
        // a banner that errors out and breaks the layout.
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [])

  if (!incident || dismissed) return null

  const dateRef = incident.ended_at ?? incident.started_at
  const dismiss = () => {
    if (typeof window !== "undefined") {
      window.localStorage.setItem(
        `${DISMISS_KEY_PREFIX}${incident.id}`,
        "1",
      )
    }
    setDismissed(true)
  }

  // Tone: amber for "we had a thing", red if still open. Avoid green —
  // a banner with a green tone tells the visitor nothing useful.
  const isOpen = incident.ended_at === null || incident.ended_at === ""
  const toneClasses = isOpen
    ? "bg-red-50 border-red-200 text-red-900"
    : "bg-amber-50 border-amber-200 text-amber-900"

  return (
    <div
      className={`w-full border-b ${toneClasses}`}
      role="status"
      aria-live="polite"
    >
      <div className="max-w-6xl mx-auto px-4 py-2 flex items-center justify-between gap-3">
        <p className="text-xs sm:text-sm leading-snug">
          <span className="font-semibold">
            {isOpen ? "Service incident in progress" : "Service incident"}
          </span>{" "}
          on {formatShortDate(dateRef)} —{" "}
          <Link
            href="/status"
            className="underline underline-offset-2 hover:no-underline font-medium"
          >
            Read what happened &rarr;
          </Link>
        </p>
        <button
          type="button"
          onClick={dismiss}
          className="shrink-0 text-current/70 hover:text-current text-lg leading-none px-1"
          aria-label="Dismiss incident notice"
        >
          &times;
        </button>
      </div>
    </div>
  )
}
