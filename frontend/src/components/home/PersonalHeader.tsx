"use client"
// TODO: swap to design tokens
import { useEffect, useState } from "react"

function greetingForHour(hour: number): string {
  if (hour < 12) return "Good morning"
  if (hour < 17) return "Good afternoon"
  return "Good evening"
}

/**
 * Read the wall-clock hour in Asia/Kolkata, regardless of the browser's
 * own timezone. YieldIQ is India-only — a user in Dubai or London who
 * loads the homepage at 18:30 IST should still see "Good evening", not
 * the hour computed from their browser's local TZ.
 *
 * Uses Intl.DateTimeFormat which is the only reliable cross-browser way
 * to project a timestamp into a named IANA zone without pulling in a
 * tz library. If the parser ever fails (very old browser), we fall
 * back to the browser's local hour rather than throwing.
 */
function currentISTHour(): number {
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Kolkata",
    hour: "numeric",
    hour12: false,
  }).formatToParts(new Date())
  const hourPart = parts.find((p) => p.type === "hour")
  return hourPart ? parseInt(hourPart.value, 10) : new Date().getHours()
}

function nameFromEmail(email: string | null): string {
  if (!email) return "there"
  const local = email.split("@")[0] || ""
  if (!local) return "there"
  // Strip trailing digits/dots, grab first token
  const token = local.split(/[._\-+]/)[0] || local
  return token.charAt(0).toUpperCase() + token.slice(1).toLowerCase()
}

export default function PersonalHeader({ email }: { email: string | null }) {
  // Greeting MUST be computed client-side: `new Date().getHours()` on the
  // Node SSR pass runs in the server's timezone (UTC on Railway/Vercel),
  // which produced "Good morning" at 18:00 IST for users. We hydrate the
  // real local-time greeting only after mount, and render a neutral
  // "Welcome back" placeholder in the meantime to keep markup stable.
  const [greeting, setGreeting] = useState<string>("Welcome back")
  useEffect(() => {
    setGreeting(greetingForHour(currentISTHour()))
  }, [])
  const name = nameFromEmail(email)
  // No streak-tracking infrastructure exists yet — intentionally blank.
  const streakSuffix = ""

  return (
    <div className="px-4 pt-6 pb-2">
      <h1 className="font-display text-2xl md:text-3xl font-bold text-ink leading-tight">
        {greeting}, {name}.{streakSuffix ? ` ${streakSuffix}` : ""}
      </h1>
    </div>
  )
}
