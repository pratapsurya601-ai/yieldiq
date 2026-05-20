/**
 * /account/student-verify — Day-49 (2026-05-20).
 *
 * Form that lets a free-tier user submit a college ID or CA
 * articleship enrolment letter for student-tier verification. On
 * submit we POST multipart/form-data to /api/v1/billing/student-verify
 * and surface the application_id + pending status.
 *
 * Friction the audit (P1 Day-49) called out:
 *   - Previously this flow was "email hello@yieldiq.in" with no
 *     in-app surface, no status visibility, and no auto-notification.
 *   - This page makes the upload one click and the result lands in
 *     the user's inbox automatically once ops reviews it.
 */
"use client"

import { useState } from "react"
import api from "@/lib/api"

const MAX_BYTES = 5 * 1024 * 1024
const ACCEPTED = "image/jpeg,image/png,image/webp,application/pdf"

export default function StudentVerifyPage() {
  const [fullName, setFullName] = useState("")
  const [institution, setInstitution] = useState("")
  const [file, setFile] = useState<File | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [result, setResult] = useState<{
    ok: boolean
    message: string
    applicationId?: string
  } | null>(null)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setResult(null)

    if (!file) {
      setResult({ ok: false, message: "Please attach your ID document." })
      return
    }
    if (file.size > MAX_BYTES) {
      setResult({
        ok: false,
        message: `File is too large (${(file.size / 1024 / 1024).toFixed(1)} MB). Max is 5 MB.`,
      })
      return
    }
    if (fullName.trim().length < 2 || institution.trim().length < 2) {
      setResult({ ok: false, message: "Name and institution are required." })
      return
    }

    setSubmitting(true)
    try {
      const fd = new FormData()
      fd.append("file", file)
      fd.append("full_name", fullName.trim())
      fd.append("institution", institution.trim())
      // Axios picks the right multipart boundary automatically when
      // FormData is the body; do NOT set Content-Type manually.
      const res = await api.post("/api/v1/billing/student-verify", fd)
      setResult({
        ok: true,
        applicationId: res.data?.application_id,
        message:
          res.data?.message ||
          "Submitted. We'll email you within 2 business days.",
      })
    } catch (err) {
      const msg =
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        (err as any)?.response?.data?.detail ||
        "Could not submit — please try again."
      setResult({ ok: false, message: String(msg) })
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="max-w-md md:max-w-2xl mx-auto px-4 py-8 space-y-6">
      <header className="space-y-1">
        <h1 className="text-2xl font-bold text-ink">Student verification</h1>
        <p className="text-sm text-muted">
          Free for verified students and CA articleship trainees. 5 deep
          analyses per day. Upload a clear scan of your college ID or
          current articleship enrolment letter.
        </p>
      </header>

      <form
        onSubmit={handleSubmit}
        data-testid="student-verify-form"
        className="space-y-4 rounded-2xl border border-border bg-bg dark:bg-surface p-5"
      >
        <div className="space-y-1">
          <label htmlFor="full_name" className="text-xs font-semibold uppercase tracking-[0.14em] text-caption">
            Full name (as on ID)
          </label>
          <input
            id="full_name"
            name="full_name"
            type="text"
            required
            minLength={2}
            maxLength={120}
            value={fullName}
            onChange={(e) => setFullName(e.target.value)}
            className="w-full rounded-xl border border-border bg-bg dark:bg-surface px-3 py-2 text-sm text-ink"
          />
        </div>

        <div className="space-y-1">
          <label htmlFor="institution" className="text-xs font-semibold uppercase tracking-[0.14em] text-caption">
            Institution / CA institute
          </label>
          <input
            id="institution"
            name="institution"
            type="text"
            required
            minLength={2}
            maxLength={200}
            value={institution}
            onChange={(e) => setInstitution(e.target.value)}
            className="w-full rounded-xl border border-border bg-bg dark:bg-surface px-3 py-2 text-sm text-ink"
          />
        </div>

        <div className="space-y-1">
          <label htmlFor="id_file" className="text-xs font-semibold uppercase tracking-[0.14em] text-caption">
            ID document (PDF, PNG, JPG, ≤5 MB)
          </label>
          <input
            id="id_file"
            name="id_file"
            type="file"
            required
            accept={ACCEPTED}
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            data-testid="student-verify-file"
            className="w-full text-sm text-ink"
          />
          {file && (
            <p className="text-xs text-muted">
              {file.name} — {(file.size / 1024).toFixed(0)} KB
            </p>
          )}
        </div>

        <button
          type="submit"
          disabled={submitting}
          data-testid="student-verify-submit"
          className="inline-flex items-center justify-center rounded-xl bg-success text-white px-4 py-3 text-sm font-semibold hover:opacity-90 disabled:opacity-50"
        >
          {submitting ? "Submitting…" : "Submit application"}
        </button>

        {result && (
          <div
            role="status"
            data-testid="student-verify-result"
            className={
              result.ok
                ? "rounded-xl border border-success/30 bg-success/10 px-3 py-2 text-sm text-success"
                : "rounded-xl border border-red-300 bg-red-50 dark:bg-red-950/30 px-3 py-2 text-sm text-red-700 dark:text-red-300"
            }
          >
            {result.message}
            {result.applicationId && (
              <div className="mt-1 text-xs opacity-80">
                Application ID: <span className="font-mono">{result.applicationId}</span>
              </div>
            )}
          </div>
        )}
      </form>

      <p className="text-xs text-muted">
        We store your document privately and only use it to verify
        eligibility. You can request deletion any time at
        {" "}<a href="mailto:hello@yieldiq.in" className="underline">hello@yieldiq.in</a>.
      </p>
    </div>
  )
}
