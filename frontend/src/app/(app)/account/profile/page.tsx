"use client"

// Account → Display name editor (PR #72).
// Server enforces a 3-edit lifetime cap. UI mirrors that: the input is
// read-only with an explanatory hint when editsRemaining hits 0.

import { useEffect, useState } from "react"
import Link from "next/link"
import { updateProfileDisplayName } from "@/lib/api"
import { useAuthStore } from "@/store/authStore"

const MAX = 60

function localValidate(raw: string): string | null {
  const name = raw.trim()
  if (!name) return "Please enter a name."
  if (name.length > MAX) return `Keep it under ${MAX} characters.`
  if (name.includes("@")) return "No '@' please — that looks like an email."
  if (name.includes("<") || name.includes(">")) return "No '<' or '>' characters."
  return null
}

export default function AccountProfilePage() {
  const displayName = useAuthStore((s) => s.displayName)
  const editsRemaining = useAuthStore((s) => s.displayNameEditsRemaining)
  const setDisplayNameStore = useAuthStore((s) => s.setDisplayName)

  const [value, setValue] = useState<string>(displayName ?? "")
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [toast, setToast] = useState<{ msg: string; tone: "ok" | "err" } | null>(null)

  // Keep the input in sync if the store value changes (e.g. another
  // tab updated it).
  useEffect(() => {
    setValue(displayName ?? "")
  }, [displayName])

  const showToast = (msg: string, tone: "ok" | "err" = "ok") => {
    setToast({ msg, tone })
    setTimeout(() => setToast(null), 4000)
  }

  const exhausted = editsRemaining <= 0
  const trimmed = value.trim()
  const noDiff = trimmed === (displayName ?? "")
  const canSave = !exhausted && !saving && !noDiff && trimmed.length > 0 && trimmed.length <= MAX

  const handleBlur = () => {
    if (!exhausted) setError(localValidate(value))
  }

  const handleSave = async () => {
    const msg = localValidate(value)
    if (msg) {
      setError(msg)
      return
    }
    setSaving(true)
    setError(null)
    try {
      const res = await updateProfileDisplayName(trimmed)
      setDisplayNameStore(res.display_name, res.edits_remaining)
      showToast("Display name saved.", "ok")
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      const status = (err as { response?: { status?: number } })?.response?.status
      if (status === 403) {
        // Server says we hit the cap — sync the store so the UI locks
        // immediately even if the page was loaded before the limit was
        // reached on another device.
        setDisplayNameStore(displayName ?? null, 0)
      }
      showToast(detail || "Couldn't save display name.", "err")
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="max-w-md md:max-w-2xl mx-auto px-4 py-8 space-y-6 pb-20">
      {toast && (
        <div
          className={`fixed bottom-20 md:top-20 md:bottom-auto left-1/2 -translate-x-1/2 text-white text-sm font-medium px-4 py-2.5 rounded-lg shadow-lg z-50 max-w-sm text-center ${
            toast.tone === "err" ? "bg-red-600" : "bg-gray-900"
          }`}
          role="status"
        >
          {toast.msg}
        </div>
      )}

      <div className="flex items-center gap-3">
        <Link
          href="/account"
          className="text-sm text-caption hover:text-ink"
        >
          ← Account
        </Link>
      </div>
      <h1 className="text-xl font-bold text-ink">Display name</h1>

      <div className="bg-bg dark:bg-surface rounded-2xl border border-border p-5 space-y-4">
        <div>
          <p className="text-xs uppercase tracking-wide text-caption">Current</p>
          <p className="text-base font-semibold text-ink mt-0.5">
            {displayName && displayName.trim() ? displayName : <span className="text-caption font-normal">Not set</span>}
          </p>
        </div>

        <div>
          <label htmlFor="display-name" className="block text-sm font-medium text-ink mb-2">
            New display name
          </label>
          <input
            id="display-name"
            type="text"
            autoComplete="off"
            value={value}
            maxLength={MAX}
            disabled={exhausted}
            readOnly={exhausted}
            onChange={(e) => {
              setValue(e.target.value)
              if (error) setError(null)
            }}
            onBlur={handleBlur}
            aria-invalid={Boolean(error)}
            aria-describedby={error ? "display-name-error" : "display-name-hint"}
            className={
              "w-full rounded-xl border px-4 py-3 text-sm text-ink " +
              "focus:outline-none focus:ring-2 focus:ring-blue-500 " +
              (exhausted
                ? "bg-surface border-border cursor-not-allowed text-caption"
                : error
                  ? "border-red-400 bg-bg dark:bg-surface"
                  : "border-border bg-bg dark:bg-surface")
            }
            placeholder="Your name"
            title={
              exhausted
                ? "You've used all 3 display-name edits. Contact support to change it again."
                : undefined
            }
          />
          <div className="flex items-center justify-between mt-2">
            {error ? (
              <p id="display-name-error" className="text-xs text-red-600 dark:text-red-400">
                {error}
              </p>
            ) : (
              <p id="display-name-hint" className="text-xs text-caption">
                {exhausted
                  ? "You've used all 3 display-name edits. Contact support to change it again."
                  : `${editsRemaining} edit${editsRemaining === 1 ? "" : "s"} remaining (lifetime).`}
              </p>
            )}
            <span className="text-xs text-caption">
              {value.trim().length}/{MAX}
            </span>
          </div>
        </div>

        <button
          type="button"
          disabled={!canSave}
          onClick={handleSave}
          className={
            "w-full py-3 rounded-xl text-sm font-semibold transition " +
            (canSave
              ? "bg-blue-600 text-white hover:bg-blue-700 active:scale-[0.99]"
              : "bg-surface text-caption cursor-not-allowed")
          }
        >
          {saving ? "Saving..." : "Save"}
        </button>
      </div>
    </div>
  )
}
