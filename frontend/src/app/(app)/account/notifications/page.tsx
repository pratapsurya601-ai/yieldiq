"use client"

// Account → Notification preferences.
//
// Per-channel toggles for weekly digest, band alerts, and product
// updates. State is stored on auth.users.user_metadata via
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
          hint="When a stock you own crosses your Below/Above Fair Value band. Delivered as part of the daily 09:00 IST digest email."
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

      <WebPushPanel onToast={showToast} />

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

// ── Day-98: Web Push (PWA) panel ────────────────────────────────
//
// Two buttons:
//   1. "Enable mobile notifications"  -> requests Notification permission,
//      subscribes via PushManager (using NEXT_PUBLIC_VAPID_PUBLIC_KEY),
//      POSTs subscription to /api/v1/notifications/subscribe.
//   2. "Send test notification"      -> POSTs to /api/v1/notifications/test
//      which fires a Web Push to every registered subscription.
//
// Notification copy is informational only (SEBI vocab — see push_service).
// The panel is a no-op (with explanatory text) on browsers that lack
// either Notification, ServiceWorker, or PushManager.

function urlBase64ToUint8Array(base64: string): Uint8Array<ArrayBuffer> {
  const padding = "=".repeat((4 - (base64.length % 4)) % 4)
  const b64 = (base64 + padding).replace(/-/g, "+").replace(/_/g, "/")
  const raw = typeof window !== "undefined" ? window.atob(b64) : ""
  const buf = new ArrayBuffer(raw.length)
  const out = new Uint8Array(buf)
  for (let i = 0; i < raw.length; i += 1) out[i] = raw.charCodeAt(i)
  return out
}

function WebPushPanel({ onToast }: { onToast: (msg: string, tone?: "ok" | "err") => void }) {
  const [supported, setSupported] = useState(false)
  const [permission, setPermission] = useState<NotificationPermission | "unknown">("unknown")
  const [subscribed, setSubscribed] = useState(false)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (typeof window === "undefined") return
    const ok =
      "Notification" in window &&
      "serviceWorker" in navigator &&
      "PushManager" in window
    setSupported(ok)
    if (ok) {
      setPermission(Notification.permission)
      navigator.serviceWorker.ready.then(async (reg) => {
        const sub = await reg.pushManager.getSubscription()
        setSubscribed(!!sub)
      }).catch(() => { /* SW not registered yet */ })
    }
  }, [])

  const enable = async () => {
    setBusy(true)
    try {
      const vapid = process.env.NEXT_PUBLIC_VAPID_PUBLIC_KEY
      if (!vapid) {
        onToast("Push not configured on this build.", "err")
        return
      }
      const perm = await Notification.requestPermission()
      setPermission(perm)
      if (perm !== "granted") {
        onToast("Permission denied.", "err")
        return
      }
      const reg = await navigator.serviceWorker.ready
      let sub = await reg.pushManager.getSubscription()
      if (!sub) {
        sub = await reg.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: urlBase64ToUint8Array(vapid),
        })
      }
      const json = sub.toJSON() as { endpoint?: string; keys?: { p256dh?: string; auth?: string } }
      await api.post("/api/v1/notifications/subscribe", {
        endpoint: json.endpoint,
        p256dh: json.keys?.p256dh,
        auth: json.keys?.auth,
      })
      setSubscribed(true)
      onToast("Mobile notifications enabled.")
    } catch (e) {
      onToast("Could not enable — try again.", "err")
    } finally {
      setBusy(false)
    }
  }

  const sendTest = async () => {
    setBusy(true)
    try {
      await api.post("/api/v1/notifications/test", {})
      onToast("Test notification sent.")
    } catch {
      onToast("Test failed — try again.", "err")
    } finally {
      setBusy(false)
    }
  }

  if (!supported) {
    return (
      <div className="bg-bg dark:bg-surface rounded-2xl border border-border p-4">
        <div className="text-sm font-medium text-ink">Mobile notifications</div>
        <p className="text-xs text-caption mt-1">
          This browser does not support Web Push. Install YieldIQ as a PWA on
          a supported browser (Chrome, Edge, or Firefox) to enable mobile alerts.
        </p>
      </div>
    )
  }

  return (
    <div className="bg-bg dark:bg-surface rounded-2xl border border-border p-4 space-y-3">
      <div>
        <div className="text-sm font-medium text-ink">Mobile notifications</div>
        <p className="text-xs text-caption mt-1 leading-relaxed">
          Get notified on your phone when a watchlist alert condition is met.
          Permission: <span className="font-bold">{permission}</span>.
        </p>
      </div>
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={enable}
          disabled={busy || subscribed || permission === "denied"}
          className="text-xs px-3 py-2 rounded-lg bg-blue-600 text-white disabled:opacity-50"
        >
          {subscribed ? "Enabled" : "Enable mobile notifications"}
        </button>
        <button
          type="button"
          onClick={sendTest}
          disabled={busy || !subscribed}
          className="text-xs px-3 py-2 rounded-lg border border-border text-ink disabled:opacity-50"
        >
          Send test notification
        </button>
      </div>
      {permission === "denied" && (
        <div
          role="status"
          className="text-xs leading-relaxed text-amber-700 dark:text-amber-400 bg-amber-50 dark:bg-amber-950/30 border border-amber-200 dark:border-amber-900 rounded-lg p-3"
        >
          <p className="font-medium">Notifications are blocked for this site.</p>
          <p className="mt-1">
            Browsers do not let pages re-prompt for permission once it has been
            denied. To enable, click the lock icon in your address bar, find
            <span className="font-medium"> Notifications</span>, and switch it
            to <span className="font-medium">Allow</span>. Then reload this page.
          </p>
        </div>
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
    <label className="flex items-start gap-4 p-4 cursor-pointer">
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
