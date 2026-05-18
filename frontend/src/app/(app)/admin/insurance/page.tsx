"use client"

// Insurance EV/VNB admin entry page.
//
// Operator workflow (~30 min/quarter) for the Appraisal Value engine
// in backend/services/insurance_appraisal_service.py. See
// docs/design/insurance-dcf-fix.md §3 Approach A and §8.4 for the
// product rationale.
//
// Endpoints wired (require admin auth — backend/routers/admin.py):
//   GET    /api/v1/admin/insurance-inputs
//   POST   /api/v1/admin/insurance-inputs
//   DELETE /api/v1/admin/insurance-inputs?ticker=X&period_end=Y

import { useEffect, useState, useCallback } from "react"
import { useAuthStore } from "@/store/authStore"
import { useRouter } from "next/navigation"
import api from "@/lib/api"

const ADMIN_EMAILS = ["pratapsurya601@gmail.com", "suryasbss601@gmail.com"]

// Must mirror backend `_INSURANCE_TICKERS` (life-insurer subset).
const INSURANCE_TICKERS = [
  "HDFCLIFE",
  "SBILIFE",
  "ICICIPRULI",
  "LICI",
  "ICICIGI",
  "NIACL",
  "STARHEALTH",
] as const

interface InsuranceRow {
  ticker: string
  period_end: string | null
  embedded_value_cr: number | null
  value_new_business_cr: number | null
  vnb_margin_pct: number | null
  ev_growth_yoy_pct: number | null
  source_url: string | null
  entered_by: string | null
  entered_at: string | null
  notes: string | null
}

interface FormState {
  ticker: string
  period_end: string
  embedded_value_cr: string
  value_new_business_cr: string
  vnb_margin_pct: string
  ev_growth_yoy_pct: string
  source_url: string
  notes: string
}

const EMPTY_FORM: FormState = {
  ticker: "HDFCLIFE",
  period_end: "",
  embedded_value_cr: "",
  value_new_business_cr: "",
  vnb_margin_pct: "",
  ev_growth_yoy_pct: "",
  source_url: "",
  notes: "",
}

function todayISO(): string {
  return new Date().toISOString().slice(0, 10)
}

export default function InsuranceAdminPage() {
  const { email } = useAuthStore()
  const router = useRouter()

  const [rows, setRows] = useState<InsuranceRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [info, setInfo] = useState("")
  const [warning, setWarning] = useState("")

  const [form, setForm] = useState<FormState>(EMPTY_FORM)
  const [submitting, setSubmitting] = useState(false)
  const [formError, setFormError] = useState("")

  const isAdmin = !!email && ADMIN_EMAILS.includes(email)

  const refresh = useCallback(async () => {
    setLoading(true)
    setError("")
    setWarning("")
    try {
      const r = await api.get("/api/v1/admin/insurance-inputs")
      setRows(Array.isArray(r.data?.rows) ? r.data.rows : [])
      if (r.data?.warning) setWarning(String(r.data.warning))
    } catch (e: any) {
      setError(e?.response?.data?.detail || "Failed to load entries")
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (!isAdmin) {
      router.push("/home")
      return
    }
    void refresh()
  }, [isAdmin, refresh, router])

  function validate(state: FormState): string {
    if (!state.ticker) return "Ticker is required"
    if (!INSURANCE_TICKERS.includes(state.ticker as (typeof INSURANCE_TICKERS)[number])) {
      return `Ticker must be one of: ${INSURANCE_TICKERS.join(", ")}`
    }
    if (!state.period_end) return "Period end is required"
    if (state.period_end > todayISO()) return "Period end cannot be in the future"
    const ev = parseFloat(state.embedded_value_cr)
    if (!Number.isFinite(ev) || ev <= 0) return "Embedded Value (Cr) must be > 0"
    // Optional numerics: reject non-numeric strings only when filled.
    for (const k of [
      "value_new_business_cr",
      "vnb_margin_pct",
      "ev_growth_yoy_pct",
    ] as const) {
      const v = state[k]
      if (v && !Number.isFinite(parseFloat(v))) {
        return `${k} must be numeric or empty`
      }
    }
    return ""
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault()
    setFormError("")
    setInfo("")
    const err = validate(form)
    if (err) {
      setFormError(err)
      return
    }
    setSubmitting(true)
    try {
      const payload: Record<string, unknown> = {
        ticker: form.ticker,
        period_end: form.period_end,
        embedded_value_cr: parseFloat(form.embedded_value_cr),
      }
      if (form.value_new_business_cr)
        payload.value_new_business_cr = parseFloat(form.value_new_business_cr)
      if (form.vnb_margin_pct)
        payload.vnb_margin_pct = parseFloat(form.vnb_margin_pct)
      if (form.ev_growth_yoy_pct)
        payload.ev_growth_yoy_pct = parseFloat(form.ev_growth_yoy_pct)
      if (form.source_url) payload.source_url = form.source_url
      if (form.notes) payload.notes = form.notes

      await api.post("/api/v1/admin/insurance-inputs", payload)
      setInfo(`Saved ${form.ticker} @ ${form.period_end}`)
      setForm(EMPTY_FORM)
      await refresh()
    } catch (e: any) {
      setFormError(e?.response?.data?.detail || "Save failed")
    } finally {
      setSubmitting(false)
    }
  }

  async function onEdit(row: InsuranceRow) {
    setForm({
      ticker: row.ticker,
      period_end: row.period_end || "",
      embedded_value_cr: row.embedded_value_cr?.toString() || "",
      value_new_business_cr: row.value_new_business_cr?.toString() || "",
      vnb_margin_pct: row.vnb_margin_pct?.toString() || "",
      ev_growth_yoy_pct: row.ev_growth_yoy_pct?.toString() || "",
      source_url: row.source_url || "",
      notes: row.notes || "",
    })
    setFormError("")
    setInfo(`Editing ${row.ticker} @ ${row.period_end}. Submit to upsert.`)
    if (typeof window !== "undefined") window.scrollTo({ top: 0, behavior: "smooth" })
  }

  async function onDelete(row: InsuranceRow) {
    if (!row.period_end) return
    if (
      typeof window !== "undefined" &&
      !window.confirm(`Delete ${row.ticker} @ ${row.period_end}?`)
    ) {
      return
    }
    try {
      await api.delete("/api/v1/admin/insurance-inputs", {
        params: { ticker: row.ticker, period_end: row.period_end },
      })
      setInfo(`Deleted ${row.ticker} @ ${row.period_end}`)
      await refresh()
    } catch (e: any) {
      setError(e?.response?.data?.detail || "Delete failed")
    }
  }

  if (!isAdmin) return null

  return (
    <div className="max-w-5xl mx-auto px-4 py-8 space-y-6 pb-20">
      <div>
        <h1 className="text-xl font-bold text-gray-900">
          Insurance Embedded Value &amp; VNB
        </h1>
        <p className="text-sm text-gray-500">
          Quarterly operator entry that activates the Appraisal Value engine
          for life insurers. See
          {" "}
          <code className="text-xs">docs/design/insurance-dcf-fix.md</code>.
        </p>
      </div>

      {warning && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
          {warning}
        </div>
      )}
      {error && (
        <div className="rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {error}
        </div>
      )}
      {info && (
        <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800">
          {info}
        </div>
      )}

      {/* Entry form */}
      <form
        onSubmit={onSubmit}
        className="bg-white rounded-2xl border border-gray-100 p-5 space-y-4"
      >
        <h2 className="text-sm font-semibold text-gray-900">Add / Update Entry</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <label className="block text-sm">
            <span className="text-gray-700">Ticker</span>
            <select
              value={form.ticker}
              onChange={(e) => setForm({ ...form, ticker: e.target.value })}
              className="mt-1 block w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
              required
            >
              {INSURANCE_TICKERS.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </label>

          <label className="block text-sm">
            <span className="text-gray-700">Period End (quarter / half-year)</span>
            <input
              type="date"
              value={form.period_end}
              max={todayISO()}
              onChange={(e) => setForm({ ...form, period_end: e.target.value })}
              className="mt-1 block w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
              required
            />
          </label>

          <label className="block text-sm">
            <span className="text-gray-700">Embedded Value (₹ Cr) *</span>
            <input
              type="number"
              step="0.01"
              min="0.01"
              value={form.embedded_value_cr}
              onChange={(e) =>
                setForm({ ...form, embedded_value_cr: e.target.value })
              }
              className="mt-1 block w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
              required
            />
          </label>

          <label className="block text-sm">
            <span className="text-gray-700">VNB (₹ Cr) — trailing 4Q</span>
            <input
              type="number"
              step="0.01"
              value={form.value_new_business_cr}
              onChange={(e) =>
                setForm({ ...form, value_new_business_cr: e.target.value })
              }
              className="mt-1 block w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
            />
          </label>

          <label className="block text-sm">
            <span className="text-gray-700">VNB margin (%)</span>
            <input
              type="number"
              step="0.01"
              value={form.vnb_margin_pct}
              onChange={(e) =>
                setForm({ ...form, vnb_margin_pct: e.target.value })
              }
              className="mt-1 block w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
            />
          </label>

          <label className="block text-sm">
            <span className="text-gray-700">EV growth YoY (%)</span>
            <input
              type="number"
              step="0.01"
              value={form.ev_growth_yoy_pct}
              onChange={(e) =>
                setForm({ ...form, ev_growth_yoy_pct: e.target.value })
              }
              className="mt-1 block w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
            />
          </label>

          <label className="block text-sm md:col-span-2">
            <span className="text-gray-700">Source URL (insurer IR PDF)</span>
            <input
              type="url"
              placeholder="https://www.hdfclife.com/about-us/investor-relations"
              value={form.source_url}
              onChange={(e) => setForm({ ...form, source_url: e.target.value })}
              className="mt-1 block w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
            />
          </label>

          <label className="block text-sm md:col-span-2">
            <span className="text-gray-700">Notes</span>
            <textarea
              rows={2}
              value={form.notes}
              onChange={(e) => setForm({ ...form, notes: e.target.value })}
              className="mt-1 block w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
            />
          </label>
        </div>

        {formError && (
          <div className="text-sm text-red-600">{formError}</div>
        )}

        <div className="flex items-center gap-3">
          <button
            type="submit"
            disabled={submitting}
            className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-60"
          >
            {submitting ? "Saving…" : "Save entry"}
          </button>
          <button
            type="button"
            onClick={() => {
              setForm(EMPTY_FORM)
              setFormError("")
              setInfo("")
            }}
            className="rounded-lg border border-gray-300 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50"
          >
            Reset
          </button>
        </div>
      </form>

      {/* Existing rows */}
      <div className="bg-white rounded-2xl border border-gray-100 p-5">
        <h2 className="text-sm font-semibold text-gray-900 mb-3">
          Existing entries ({rows.length})
        </h2>
        {loading ? (
          <div className="text-sm text-gray-500">Loading…</div>
        ) : rows.length === 0 ? (
          <div className="text-sm text-gray-500">
            No rows yet. Add the first quarterly entry to activate the
            Appraisal Value engine.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full text-xs">
              <thead className="text-gray-600">
                <tr className="border-b border-gray-200">
                  <th className="py-2 pr-3 text-left font-semibold">Ticker</th>
                  <th className="py-2 pr-3 text-left font-semibold">Period</th>
                  <th className="py-2 pr-3 text-right font-semibold">EV (Cr)</th>
                  <th className="py-2 pr-3 text-right font-semibold">VNB (Cr)</th>
                  <th className="py-2 pr-3 text-right font-semibold">VNB %</th>
                  <th className="py-2 pr-3 text-right font-semibold">EV g%</th>
                  <th className="py-2 pr-3 text-left font-semibold">Source</th>
                  <th className="py-2 pr-3 text-left font-semibold">By</th>
                  <th className="py-2 pr-3 text-right font-semibold">Actions</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr
                    key={`${r.ticker}-${r.period_end}`}
                    className="border-b border-gray-100"
                  >
                    <td className="py-2 pr-3 font-medium text-gray-900">
                      {r.ticker}
                    </td>
                    <td className="py-2 pr-3">{r.period_end}</td>
                    <td className="py-2 pr-3 text-right">
                      {r.embedded_value_cr?.toLocaleString() ?? "—"}
                    </td>
                    <td className="py-2 pr-3 text-right">
                      {r.value_new_business_cr?.toLocaleString() ?? "—"}
                    </td>
                    <td className="py-2 pr-3 text-right">
                      {r.vnb_margin_pct ?? "—"}
                    </td>
                    <td className="py-2 pr-3 text-right">
                      {r.ev_growth_yoy_pct ?? "—"}
                    </td>
                    <td className="py-2 pr-3 max-w-[200px] truncate">
                      {r.source_url ? (
                        <a
                          href={r.source_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-blue-600 hover:underline"
                        >
                          link
                        </a>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td className="py-2 pr-3 text-gray-500">
                      {r.entered_by ?? "—"}
                    </td>
                    <td className="py-2 pr-3 text-right space-x-2">
                      <button
                        onClick={() => onEdit(r)}
                        className="text-blue-600 hover:underline"
                      >
                        Edit
                      </button>
                      <button
                        onClick={() => onDelete(r)}
                        className="text-red-600 hover:underline"
                      >
                        Delete
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
