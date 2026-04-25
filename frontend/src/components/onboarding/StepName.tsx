"use client"

// First onboarding screen (PR #72) — capture editable display name.
// Pre-fills with the email-local-part suggestion so the user can
// either accept it (one tap) or edit it before continuing. Server
// enforces 1-60 chars + no @<>, the input mirrors those rules so we
// can validate-on-blur without a round-trip.

import { useEffect, useState } from "react"
import { updateProfileDisplayName } from "@/lib/api"
import { useAuthStore } from "@/store/authStore"

const MAX = 60

function nameFromEmailSuggestion(email: string | null): string {
  if (!email) return ""
  const local = email.split("@")[0] || ""
  if (!local) return ""
  const token = local.split(/[._\-+]/)[0] || local
  return token.charAt(0).toUpperCase() + token.slice(1).toLowerCase()
}

function localValidate(raw: string): string | null {
  const name = raw.trim()
  if (!name) return "Please enter a name."
  if (name.length > MAX) return `Keep it under ${MAX} characters.`
  if (name.includes("@")) return "No '@' please — that looks like an email."
  if (name.includes("<") || name.includes(">")) return "No '<' or '>' characters."
  return null
}

interface StepNameProps {
  onContinue: () => void
}

export default function StepName({ onContinue }: StepNameProps) {
  const email = useAuthStore((s) => s.email)
  const setDisplayName = useAuthStore((s) => s.setDisplayName)
  const existing = useAuthStore((s) => s.displayName)

  const [value, setValue] = useState<string>("")
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  // Seed the input on first mount: prefer an existing display name
  // (re-entering the wizard), otherwise the email-derived suggestion.
  useEffect(() => {
    if (existing && existing.trim()) {
      setValue(existing)
    } else {
      setValue(nameFromEmailSuggestion(email))
    }
  }, [email, existing])

  const handleBlur = () => {
    const msg = localValidate(value)
    setError(msg)
  }

  const handleSubmit = async () => {
    const msg = localValidate(value)
    if (msg) {
      setError(msg)
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      const res = await updateProfileDisplayName(value.trim())
      setDisplayName(res.display_name, res.edits_remaining)
      onContinue()
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(detail || "Couldn't save your name. Try again.")
    } finally {
      setSubmitting(false)
    }
  }

  const trimmedLen = value.trim().length
  const canContinue = trimmedLen > 0 && trimmedLen <= MAX && !submitting

  return (
    <div className="flex flex-col min-h-[calc(100vh-56px)] px-5 pb-8">
      <header className="pt-6 pb-6">
        <h1 className="font-editorial text-3xl sm:text-4xl text-ink leading-tight">
          What should we call you?
        </h1>
        <p className="mt-2 text-base text-body">
          We&apos;ll use this for your greeting and around the app.
        </p>
      </header>

      <div className="flex-1">
        <label htmlFor="display-name" className="block text-sm font-medium text-ink mb-2">
          Display name
        </label>
        <input
          id="display-name"
          type="text"
          autoComplete="off"
          value={value}
          maxLength={MAX}
          onChange={(e) => {
            setValue(e.target.value)
            if (error) setError(null)
          }}
          onBlur={handleBlur}
          onKeyDown={(e) => {
            if (e.key === "Enter" && canContinue) handleSubmit()
          }}
          aria-invalid={Boolean(error)}
          aria-describedby={error ? "display-name-error" : "display-name-hint"}
          className={
            "w-full rounded-2xl border bg-surface px-4 py-3 text-base text-ink " +
            "focus:outline-none focus:ring-2 focus:ring-brand/60 " +
            (error ? "border-red-400" : "border-border")
          }
          placeholder="Your name"
        />
        <div className="flex items-center justify-between mt-2">
          {error ? (
            <p id="display-name-error" className="text-xs text-red-600">
              {error}
            </p>
          ) : (
            <p id="display-name-hint" className="text-xs text-caption">
              You can change this later in Account.
            </p>
          )}
          <span className="text-xs text-caption">
            {trimmedLen}/{MAX}
          </span>
        </div>
      </div>

      <div className="pt-6 sticky bottom-0 bg-bg">
        <button
          type="button"
          disabled={!canContinue}
          onClick={handleSubmit}
          className={
            "w-full min-h-[52px] rounded-full font-semibold text-base transition-all " +
            (canContinue
              ? "bg-ink text-bg hover:opacity-90 active:scale-[0.99]"
              : "bg-border text-caption cursor-not-allowed")
          }
        >
          {submitting ? "Saving..." : "Continue"}
        </button>
      </div>
    </div>
  )
}
