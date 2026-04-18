"use client"
// TODO: swap to design tokens
import { useEffect, useState } from "react"

function greetingForHour(hour: number): string {
  if (hour < 12) return "Good morning"
  if (hour < 17) return "Good afternoon"
  return "Good evening"
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
  const [mounted, setMounted] = useState(false)
  useEffect(() => setMounted(true), [])
  const greeting = mounted ? greetingForHour(new Date().getHours()) : "Welcome back"
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
