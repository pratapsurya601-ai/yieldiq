"use client"
import { useEffect, useState, useCallback } from "react"
import { useAuthStore } from "@/store/authStore"
import { useRouter } from "next/navigation"
import api from "@/lib/api"

const ADMIN_EMAILS = ["pratapsurya601@gmail.com", "suryasbss601@gmail.com"]

// Mirrors REALTY_TICKERS in backend/services/analysis/constants.py.
// Hard-coded so the form's <select> can't drift out of sync silently —
// the backend POST validates against the canonical set anyway.
const REALTY_TICKERS = [
  "DLF", "GODREJPROP", "LODHA", "OBEROIRLTY",
  "PRESTIGE", "PHOENIXLTD", "SOBHA", "BRIGADE",
  "MAHLIFE", "KEYSTONE", "MACROTECH", "NCC",
  "SHRIRAMPROP", "SUNTECK",
] as const

interface LandBankRow {
  ticker: string
  reporting_fy: string
  land_bank_acres: number | null
  land_bank_market_value_cr: number | null
  land_bank_book_value_cr: number | null
  unsold_inventory_cr: number | null
  pre_sales_pipeline_cr: number | null
  uplift_per_share: number | null
  source_url: string | null
  entered_by: string | null
  entered_at: string | null
}

interface FormState {
  ticker: string
  reporting_fy: string
  land_bank_acres: string
  land_bank_market_value_cr: string
  land_bank_book_value_cr: string
  unsold_inventory_cr: string
  pre_sales_pipeline_cr: string
  uplift_per_share: string
  source_url: string
}

const EMPTY_FORM: FormState = {
  ticker: "",
  reporting_fy: "",
  land_bank_acres: "",
  land_bank_market_value_cr: "",
  land_bank_book_value_cr: "",
  unsold_inventory_cr: "",
  pre_sales_pipeline_cr: "",
  uplift_per_share: "",
  source_url: "",
}

function toNum(s: string): number | null {
  if (s === "" || s === null || s === undefined) return null
  const n = Number(s)
  return Number.isFinite(n) ? n : null
}

function nextReviewDue(enteredAt: string | null): string {
  if (!enteredAt) return "—"
  const d = new Date(enteredAt)
  if (Number.isNaN(d.getTime())) return "—"
  d.setUTCFullYear(d.getUTCFullYear() + 1)
  return d.toISOString().slice(0, 10)
}

function isOverdue(enteredAt: string | null): boolean {
  if (!enteredAt) return false
  const d = new Date(enteredAt)
  if (Number.isNaN(d.getTime())) return false
  d.setUTCFullYear(d.getUTCFullYear() + 1)
  return d.getTime() < Date.now()
}

export default function RealtyLandBankAdminPage() {
  const { email } = useAuthStore()
  const router = useRouter()
  const [rows, setRows] = useState<LandBankRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [form, setForm] = useState<FormState>(EMPTY_FORM)
  const [editingTicker, setEditingTicker] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  const refresh = useCallback(async () => {
    setLoading(true)
    setError("")
    try {
      const r = await api.get("/api/v1/admin/realty-land-bank")
      setRows(r.data.rows || [])
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } }
      setError(err?.response?.data?.detail || "Failed to load rows")
    } finally {
      setLoading(false)
    }
  }, [])

  // Wait for Zustand persist hydration before checking admin status.
  // Without this, the first render sees email=null (before localStorage
  // rehydrates) and redirects to /home — even for valid admins.
  const [hydrated, setHydrated] = useState(false)
  useEffect(() => {
    if (useAuthStore.persist.hasHydrated()) {
      setHydrated(true)
      return
    }
    const unsub = useAuthStore.persist.onFinishHydration(() => setHydrated(true))
    return unsub
  }, [])

  useEffect(() => {
    if (!hydrated) return
    if (!email || !ADMIN_EMAILS.includes(email)) {
      router.push("/home")
      return
    }
    refresh()
  }, [hydrated, email, router, refresh])

  function startEdit(row: LandBankRow) {
    setEditingTicker(row.ticker)
    setForm({
      ticker: row.ticker,
      reporting_fy: row.reporting_fy ?? "",
      land_bank_acres: row.land_bank_acres?.toString() ?? "",
      land_bank_market_value_cr: row.land_bank_market_value_cr?.toString() ?? "",
      land_bank_book_value_cr: row.land_bank_book_value_cr?.toString() ?? "",
      unsold_inventory_cr: row.unsold_inventory_cr?.toString() ?? "",
      pre_sales_pipeline_cr: row.pre_sales_pipeline_cr?.toString() ?? "",
      uplift_per_share: row.uplift_per_share?.toString() ?? "",
      source_url: row.source_url ?? "",
    })
    window.scrollTo({ top: 0, behavior: "smooth" })
  }

  function resetForm() {
    setEditingTicker(null)
    setForm(EMPTY_FORM)
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault()
    setSaving(true)
    setError("")
    try {
      const payload = {
        ticker: form.ticker.trim().toUpperCase(),
        reporting_fy: form.reporting_fy.trim(),
        land_bank_acres: toNum(form.land_bank_acres),
        land_bank_market_value_cr: toNum(form.land_bank_market_value_cr),
        land_bank_book_value_cr: toNum(form.land_bank_book_value_cr),
        unsold_inventory_cr: toNum(form.unsold_inventory_cr),
        pre_sales_pipeline_cr: toNum(form.pre_sales_pipeline_cr),
        uplift_per_share: toNum(form.uplift_per_share),
        source_url: form.source_url.trim() || null,
      }
      if (payload.land_bank_market_value_cr === null || payload.uplift_per_share === null) {
        throw new Error("land_bank_market_value_cr and uplift_per_share are required")
      }
      await api.post("/api/v1/admin/realty-land-bank", payload)
      resetForm()
      await refresh()
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string }
      setError(err?.response?.data?.detail || err?.message || "Save failed")
    } finally {
      setSaving(false)
    }
  }

  async function onDelete(ticker: string) {
    if (!confirm(`Delete land-bank row for ${ticker}? The engine will fall back to Tier 2 generic for this ticker.`)) return
    setError("")
    try {
      await api.delete(`/api/v1/admin/realty-land-bank/${ticker}`)
      await refresh()
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } }
      setError(err?.response?.data?.detail || "Delete failed")
    }
  }

  if (!hydrated) return null
  if (!email || !ADMIN_EMAILS.includes(email)) return null

  return (
    <div className="max-w-5xl mx-auto px-4 py-8 space-y-6 pb-20">
      <div>
        <h1 className="text-xl font-bold text-ink">Realty Land-Bank Inputs</h1>
        <p className="text-sm text-caption">
          Annual operator pass — populates the Approach C (P/B + land-bank multiplier) engine.
          See <code className="text-xs">docs/design/realty-developers-dcf-fix.md</code>.
        </p>
      </div>

      {error && (
        <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {/* Form */}
      <form
        onSubmit={onSubmit}
        className="bg-bg dark:bg-surface rounded-2xl border border-gray-100 p-4 space-y-4"
      >
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-ink">
            {editingTicker ? `Edit ${editingTicker}` : "Add new entry"}
          </h2>
          {editingTicker && (
            <button
              type="button"
              onClick={resetForm}
              className="text-xs text-caption hover:text-gray-700"
            >
              Cancel edit
            </button>
          )}
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <label className="block">
            <span className="text-xs font-medium text-ink">Ticker *</span>
            <select
              required
              disabled={!!editingTicker}
              value={form.ticker}
              onChange={(e) => setForm({ ...form, ticker: e.target.value })}
              className="mt-1 w-full rounded-lg border border-border px-3 py-2 text-sm"
            >
              <option value="">— select —</option>
              {REALTY_TICKERS.map((t) => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
          </label>

          <label className="block">
            <span className="text-xs font-medium text-ink">Reporting FY *</span>
            <input
              required
              type="text"
              placeholder="FY25"
              value={form.reporting_fy}
              onChange={(e) => setForm({ ...form, reporting_fy: e.target.value })}
              className="mt-1 w-full rounded-lg border border-border px-3 py-2 text-sm"
            />
          </label>

          <label className="block">
            <span className="text-xs font-medium text-ink">Land bank acres</span>
            <input
              type="number"
              step="any"
              value={form.land_bank_acres}
              onChange={(e) => setForm({ ...form, land_bank_acres: e.target.value })}
              className="mt-1 w-full rounded-lg border border-border px-3 py-2 text-sm"
            />
          </label>

          <label className="block">
            <span className="text-xs font-medium text-ink">
              Land bank market value (₹ Cr) *
            </span>
            <input
              required
              type="number"
              step="any"
              value={form.land_bank_market_value_cr}
              onChange={(e) =>
                setForm({ ...form, land_bank_market_value_cr: e.target.value })
              }
              className="mt-1 w-full rounded-lg border border-border px-3 py-2 text-sm"
            />
          </label>

          <label className="block">
            <span className="text-xs font-medium text-ink">
              Land bank book value (₹ Cr)
            </span>
            <input
              type="number"
              step="any"
              value={form.land_bank_book_value_cr}
              onChange={(e) =>
                setForm({ ...form, land_bank_book_value_cr: e.target.value })
              }
              className="mt-1 w-full rounded-lg border border-border px-3 py-2 text-sm"
            />
          </label>

          <label className="block">
            <span className="text-xs font-medium text-ink">
              Unsold inventory (₹ Cr)
            </span>
            <input
              type="number"
              step="any"
              value={form.unsold_inventory_cr}
              onChange={(e) => setForm({ ...form, unsold_inventory_cr: e.target.value })}
              className="mt-1 w-full rounded-lg border border-border px-3 py-2 text-sm"
            />
          </label>

          <label className="block">
            <span className="text-xs font-medium text-ink">
              Pre-sales pipeline (₹ Cr)
            </span>
            <input
              type="number"
              step="any"
              value={form.pre_sales_pipeline_cr}
              onChange={(e) =>
                setForm({ ...form, pre_sales_pipeline_cr: e.target.value })
              }
              className="mt-1 w-full rounded-lg border border-border px-3 py-2 text-sm"
            />
          </label>

          <label className="block">
            <span className="text-xs font-medium text-ink">
              Uplift per share (₹) *
            </span>
            <input
              required
              type="number"
              step="any"
              value={form.uplift_per_share}
              onChange={(e) => setForm({ ...form, uplift_per_share: e.target.value })}
              className="mt-1 w-full rounded-lg border border-border px-3 py-2 text-sm"
            />
            <span className="text-[10px] text-caption mt-0.5 block">
              (mkt_value − book_value) × 1e7 ÷ shares
            </span>
          </label>

          <label className="block md:col-span-2">
            <span className="text-xs font-medium text-ink">Source URL</span>
            <input
              type="url"
              placeholder="https://www.bseindia.com/.../annual-report.pdf"
              value={form.source_url}
              onChange={(e) => setForm({ ...form, source_url: e.target.value })}
              className="mt-1 w-full rounded-lg border border-border px-3 py-2 text-sm"
            />
          </label>
        </div>

        <div className="flex items-center gap-3">
          <button
            type="submit"
            disabled={saving}
            className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
          >
            {saving ? "Saving…" : editingTicker ? "Update" : "Add entry"}
          </button>
        </div>
      </form>

      {/* List */}
      <div className="bg-bg dark:bg-surface rounded-2xl border border-gray-100 overflow-hidden">
        <div className="px-4 py-4 border-b border-gray-100">
          <h2 className="text-sm font-semibold text-ink">
            Curated entries ({rows.length}/{REALTY_TICKERS.length})
          </h2>
          <p className="text-xs text-caption">
            Engine routes through Approach C only for tickers with a row here.
            Missing tickers fall back to Tier 2 generic.
          </p>
        </div>
        {loading ? (
          <div className="p-8 text-center text-sm text-caption">Loading…</div>
        ) : rows.length === 0 ? (
          <div className="p-8 text-center text-sm text-caption">No entries yet.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-bg dark:bg-surface text-xs uppercase tracking-wide text-caption">
                <tr>
                  <th className="px-4 py-2 text-left">Ticker</th>
                  <th className="px-4 py-2 text-left">FY</th>
                  <th className="px-4 py-2 text-right">Mkt Val (₹ Cr)</th>
                  <th className="px-4 py-2 text-right">Uplift/share (₹)</th>
                  <th className="px-4 py-2 text-left">Next review due</th>
                  <th className="px-4 py-2 text-left">Entered by</th>
                  <th className="px-4 py-2 text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => {
                  const overdue = isOverdue(row.entered_at)
                  return (
                    <tr key={row.ticker} className="border-t border-gray-100">
                      <td className="px-4 py-2 font-medium">{row.ticker}</td>
                      <td className="px-4 py-2">{row.reporting_fy}</td>
                      <td className="px-4 py-2 text-right">
                        {row.land_bank_market_value_cr?.toLocaleString() ?? "—"}
                      </td>
                      <td className="px-4 py-2 text-right">
                        {row.uplift_per_share?.toLocaleString() ?? "—"}
                      </td>
                      <td className={`px-4 py-2 ${overdue ? "text-red-600 font-medium" : ""}`}>
                        {nextReviewDue(row.entered_at)}
                        {overdue && <span className="ml-1 text-[10px]">(overdue)</span>}
                      </td>
                      <td className="px-4 py-2 text-xs text-caption">
                        {row.entered_by ?? "—"}
                      </td>
                      <td className="px-4 py-2 text-right">
                        <button
                          onClick={() => startEdit(row)}
                          className="text-xs text-blue-600 hover:text-blue-800 mr-3"
                        >
                          Edit
                        </button>
                        <button
                          onClick={() => onDelete(row.ticker)}
                          className="text-xs text-red-600 hover:text-red-800"
                        >
                          Delete
                        </button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
