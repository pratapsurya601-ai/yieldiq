"use client"

// Account → Notification preferences.
//
// Per-channel toggles for weekly digest, band alerts (future PR), and
// product updates. State is stored on auth.users.user_metadata via
// PUT /api/v1/email/preferences. Defaults are opted-in.
//
// Why on /account/notifications rather than /settings/notifications:
//   matches the existing /account hub layout (profile, api-keys) so
//   users don't have to learn a new top-level route.

import { useEffect, useState } from "react"
import Link from "next/link"
import api from "@/lib/api"

type Prefs = {
  weekly_digest: boolean
  band_alerts: boolean
  product_updates: boolean
}

const DEFAULT_PREFS: Prefs = {
  weekly_digest: true,
  band_alerts: true,
  product_updates: true,
}

export default function NotificationPreferencesPage() {
  const [prefs, setPrefs] = useState<Prefs>(DEFAULT_PREFS)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [toast, setToast] = useState<{ msg: string; tone: "ok" | "err" } | null>(null)

  useEffect(() => {
    api.get("/api/v1/email/preferences")
      .then((r) => setPrefs({ ...DEFAULT_PREFS, ...(r.data ?? {}) }))
      .catch(() => {/* fallback to defaults */})
      .finally(() => setLoading(false))
  }, [])

  const showToast = (msg: string, tone: "ok" | "err" = "ok") => {
    setToast({ msg, tone })
    setTimeout(() => setToast(null), 3000)
  }

  const update = async (key: keyof Prefs, value: boolean) => {
    const next: Prefs = { ...prefs, [key]: value }
    setPrefs(next)  // optimistic
    setSaving(true)
    try {
      await api.put("/api/v1/email/preferences", next)
      showToast("Saved")
    } catch {
      setPrefs(prefs)  // rollback
      showToast("Could not save — try again.", "err")
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <div className="max-w-2xl mx-auto p-6">
        <p className="text-sm text-caption">Loading preferences…</p>
      </div>
    )
  }

  return (
    <div className="max-w-2xl mx-auto p-6 space-y-6">
      <div>
        <Link href="/account" className="text-xs text-caption hover:text-ink">
          &larr; Account
        </Link>
        <h1 className="text-xl font-semibold text-ink mt-2">Email preferences</h1>
        <p className="text-sm text-caption mt-1">
          Choose which emails you want from YieldIQ. You can change this any time.
        </p>
      </div>

      <div className="bg-bg dark:bg-surface rounded-2xl border border-border divide-y divide-border">
        <Toggle
          label="Weekly digest"
          hint="Thursday morning: your watchlist update, or the YieldIQ-50 movers if your watchlist is empty."
          checked={prefs.weekly_digest}
          onChange={(v) => update("weekly_digest", v)}
          disabled={saving}
        />
        <Toggle
          label="Band alerts"
          hint="When a stock you own crosses your Below/Above Fair Value band. (Coming in the next release.)"
          checked={prefs.band_alerts}
          onChange={(v) => update("band_alerts", v)}
          disabled={saving}
        />
        <Toggle
          label="Product updates"
          hint="Occasional notes about new features and methodology improvements. No marketing spam."
          checked={prefs.product_updates}
          onChange={(v) => update("product_updates", v)}
          disabled={saving}
        />
      </div>

      {toast && (
        <p
          className={
            toast.tone === "ok"
              ? "text-xs text-emerald-600"
              : "text-xs text-rose-600"
          }
          role="status"
        >
          {toast.msg}
        </p>
      )}
    </div>
  )
}

function Toggle({
  label,
  hint,
  checked,
  onChange,
  disabled,
}: {
  label: string
  hint: string
  checked: boolean
  onChange: (v: boolean) => void
  disabled?: boolean
}) {
  return (
    <label className="flex items-start gap-4 p-5 cursor-pointer">
      <div className="flex-1 min-w-0">
        <div className="text-sm font-medium text-ink">{label}</div>
        <div className="text-xs text-caption mt-1 leading-relaxed">{hint}</div>
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={label}
        onClick={() => !disabled && onChange(!checked)}
        disabled={disabled}
        className={[
          "relative inline-flex h-6 w-11 flex-shrink-0 items-center rounded-full transition-colors",
          checked ? "bg-blue-600" : "bg-gray-300 dark:bg-gray-600",
          disabled ? "opacity-50 cursor-not-allowed" : "cursor-pointer",
        ].join(" ")}
      >
        <span
          className={[
            "inline-block h-4 w-4 transform rounded-full bg-white transition-transform",
            checked ? "translate-x-6" : "translate-x-1",
          ].join(" ")}
        />
      </button>
    </label>
  )
}
