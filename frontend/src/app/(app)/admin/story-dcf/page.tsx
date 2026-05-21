"use client"
/**
 * Story-DCF overrides admin page.
 *
 * Read-only + preview-only by design — see commit message for
 * `feat(day11)`. To actually change config/story_dcf_overrides.json
 * the operator submits a PR. This page lets them:
 *
 *   1. See the current state of all overrides + industry defaults.
 *   2. See the back-test audit (which overrides are out-of-band, why).
 *   3. Simulate a hypothetical override against arbitrary (revenue,
 *      shares, CMP) without writing anything.
 *
 * Three backend endpoints:
 *   GET  /api/v1/admin/story-dcf-overrides
 *   GET  /api/v1/admin/story-dcf-overrides/audit
 *   POST /api/v1/admin/story-dcf-overrides/preview
 */
import { useCallback, useEffect, useState } from "react"
import { useAuthStore } from "@/store/authStore"
import { useRouter } from "next/navigation"
import api from "@/lib/api"
import { formatNumberWithSuffix, formatRateDecimal } from "@/lib/utils"

const ADMIN_EMAILS = ["pratapsurya601@gmail.com", "suryasbss601@gmail.com"]

const SUPPORTED_SECTORS = [
  "payments",
  "ecommerce",
  "fintech_broker",
  "wealth management",
  "insurance aggregator",
] as const

type StoryParamFields = {
  initial_growth?: number | null
  target_op_margin?: number | null
  terminal_growth?: number | null
  fade_years?: number | null
  margin_convergence_yr?: number | null
  reinvestment_rate?: number | null
  wacc?: number | null
  tax_rate?: number | null
}

interface OverridesResponse {
  overrides: Record<string, StoryParamFields & { _notes?: string }>
  industry_defaults: Record<string, StoryParamFields & {
    confidence_floor?: number
    confidence_cap?: number
  }>
  _meta: { note: string }
}

interface AuditRow {
  ticker: string
  status: "ok" | "model_collapsed" | "no_anchor"
  fair_value?: number
  anchor_cmp?: number
  fv_cmp_ratio?: number
  in_safety_net_band?: boolean
  needs_review?: boolean
  review_reason?: string | null
}

interface AuditResponse {
  total: number
  needs_review_count: number
  known_out_of_band: string[]
  known_default_out_of_band: string[]
  rows: AuditRow[]
}

interface PreviewResponse {
  status: "ok" | "engine_returned_none"
  industry_key: string
  reason?: string
  params: StoryParamFields
  result?: {
    fair_value: number
    cmp: number
    fv_cmp_ratio: number | null
    in_safety_net_band: boolean
    confidence_score: number | null
    verdict: string | null
    bear_case: number | null
    bull_case: number | null
    meta: Record<string, unknown> | null
  }
}

// Day-35 (2026-05-20): local fmtPct / fmtNum replaced by canonical
// helpers from lib/utils.ts. The local fmtPct multiplied by 100 since
// admin story-dcf params are stored as DECIMALS (0.18 = 18%) — use
// formatRateDecimal which handles this convention canonically. The
// local fmtNum defaulted to 2 dp vs PeerComparisonCard's 1 dp; now
// both go through formatNumberWithSuffix(value, 2) for admin and
// formatNumberWithSuffix(value, 1) elsewhere — explicit per caller.
const fmtPct = (n: number | null | undefined) => formatRateDecimal(n, 1)
const fmtNum = (n: number | null | undefined, digits = 2) =>
  formatNumberWithSuffix(n, digits)

function ParamRow({
  label,
  value,
  hint,
}: {
  label: string
  value: string
  hint?: string
}) {
  return (
    <div className="flex items-center justify-between py-1 text-xs">
      <span className="text-caption">{label}</span>
      <span className="font-mono text-ink">{value}</span>
      {hint && <span className="ml-2 text-[10px] text-caption">{hint}</span>}
    </div>
  )
}

export default function StoryDcfAdminPage() {
  const { email } = useAuthStore()
  const router = useRouter()

  const [hydrated, setHydrated] = useState(false)
  useEffect(() => {
    if (useAuthStore.persist.hasHydrated()) {
      setHydrated(true)
      return
    }
    const unsub = useAuthStore.persist.onFinishHydration(() =>
      setHydrated(true),
    )
    return unsub
  }, [])

  const [overrides, setOverrides] = useState<OverridesResponse | null>(null)
  const [audit, setAudit] = useState<AuditResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")

  const refresh = useCallback(async () => {
    setLoading(true)
    setError("")
    try {
      const [o, a] = await Promise.all([
        api.get<OverridesResponse>("/api/v1/admin/story-dcf-overrides"),
        api.get<AuditResponse>("/api/v1/admin/story-dcf-overrides/audit"),
      ])
      setOverrides(o.data)
      setAudit(a.data)
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } }
      setError(err?.response?.data?.detail || "Failed to load")
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (!hydrated) return
    if (!email || !ADMIN_EMAILS.includes(email)) {
      router.push("/home")
      return
    }
    refresh()
  }, [hydrated, email, router, refresh])

  // ── Preview form state ────────────────────────────────────────
  const [previewForm, setPreviewForm] = useState({
    ticker: "PAYTM",
    sector: "payments",
    revenue_cr: "10000",
    shares_cr: "63",
    current_price: "900",
    initial_growth: "",
    target_op_margin: "",
    reinvestment_rate: "",
    wacc: "",
  })
  const [previewResult, setPreviewResult] = useState<PreviewResponse | null>(
    null,
  )
  const [previewLoading, setPreviewLoading] = useState(false)
  const [previewError, setPreviewError] = useState("")

  async function runPreview(e: React.FormEvent) {
    e.preventDefault()
    setPreviewLoading(true)
    setPreviewError("")
    setPreviewResult(null)
    try {
      const override: StoryParamFields = {}
      const num = (s: string) => (s === "" ? null : Number(s))
      const ig = num(previewForm.initial_growth)
      const tm = num(previewForm.target_op_margin)
      const rr = num(previewForm.reinvestment_rate)
      const wc = num(previewForm.wacc)
      if (ig !== null) override.initial_growth = ig
      if (tm !== null) override.target_op_margin = tm
      if (rr !== null) override.reinvestment_rate = rr
      if (wc !== null) override.wacc = wc

      const payload = {
        ticker: previewForm.ticker.trim().toUpperCase(),
        sector: previewForm.sector,
        revenue_cr: Number(previewForm.revenue_cr),
        shares_cr: Number(previewForm.shares_cr),
        current_price: Number(previewForm.current_price),
        override: Object.keys(override).length > 0 ? override : undefined,
      }
      const r = await api.post<PreviewResponse>(
        "/api/v1/admin/story-dcf-overrides/preview",
        payload,
      )
      setPreviewResult(r.data)
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } }
      setPreviewError(err?.response?.data?.detail || "Preview failed")
    } finally {
      setPreviewLoading(false)
    }
  }

  if (!hydrated) return null
  if (!email || !ADMIN_EMAILS.includes(email)) return null

  return (
    <div className="max-w-5xl mx-auto px-4 py-8 space-y-6 pb-20">
      <div>
        <h1 className="text-xl font-bold text-ink">Story-DCF overrides</h1>
        <p className="text-sm text-caption">
          Read-only + preview-only. To change a value, submit a PR
          editing <code className="text-xs">config/story_dcf_overrides.json</code>.
          Use the preview below to validate the change first.
        </p>
      </div>

      {error && (
        <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {/* ── Audit ─────────────────────────────────────────── */}
      <div className="bg-bg dark:bg-surface rounded-2xl border border-gray-100 overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-100 flex items-baseline justify-between">
          <div>
            <h2 className="text-sm font-semibold text-ink">
              Override back-test audit
            </h2>
            <p className="text-xs text-caption">
              Synthetic FY25 anchors vs. operator-curated parameters.
            </p>
          </div>
          {audit && (
            <span className="text-xs text-caption">
              {audit.needs_review_count}/{audit.total} need review
            </span>
          )}
        </div>
        {loading ? (
          <div className="p-8 text-center text-sm text-caption">Loading…</div>
        ) : !audit ? (
          <div className="p-8 text-center text-sm text-caption">No audit data.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-bg dark:bg-surface text-xs uppercase tracking-wide text-caption">
                <tr>
                  <th className="px-4 py-2 text-left">Ticker</th>
                  <th className="px-4 py-2 text-right">Story FV (₹)</th>
                  <th className="px-4 py-2 text-right">Anchor CMP (₹)</th>
                  <th className="px-4 py-2 text-right">FV/CMP</th>
                  <th className="px-4 py-2 text-center">In band</th>
                  <th className="px-4 py-2 text-left">Status</th>
                </tr>
              </thead>
              <tbody>
                {audit.rows.map((row) => (
                  <tr
                    key={row.ticker}
                    className={`border-t border-gray-100 ${
                      row.needs_review ? "bg-amber-50/40" : ""
                    }`}
                  >
                    <td className="px-4 py-2 font-medium">{row.ticker}</td>
                    <td className="px-4 py-2 text-right font-mono">
                      {fmtNum(row.fair_value, 0)}
                    </td>
                    <td className="px-4 py-2 text-right font-mono">
                      {fmtNum(row.anchor_cmp, 0)}
                    </td>
                    <td className="px-4 py-2 text-right font-mono">
                      {fmtNum(row.fv_cmp_ratio, 2)}
                    </td>
                    <td className="px-4 py-2 text-center">
                      {row.in_safety_net_band === undefined
                        ? "—"
                        : row.in_safety_net_band
                          ? "✓"
                          : "✗"}
                    </td>
                    <td className="px-4 py-2 text-xs text-caption">
                      {row.status === "model_collapsed"
                        ? "Model collapsed"
                        : row.needs_review
                          ? row.review_reason || "Review needed"
                          : "OK"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* ── Industry defaults reference ───────────────────── */}
      {overrides && (
        <div className="bg-bg dark:bg-surface rounded-2xl border border-gray-100 p-5">
          <h2 className="text-sm font-semibold text-ink mb-3">
            Industry defaults
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {Object.entries(overrides.industry_defaults).map(([key, p]) => (
              <div
                key={key}
                className="rounded-xl border border-gray-100 p-3"
              >
                <p className="text-xs font-semibold text-ink mb-1">{key}</p>
                <ParamRow label="initial_growth" value={fmtPct(p.initial_growth)} />
                <ParamRow label="target_op_margin" value={fmtPct(p.target_op_margin)} />
                <ParamRow label="reinvestment_rate" value={fmtPct(p.reinvestment_rate)} />
                <ParamRow label="wacc" value={fmtPct(p.wacc)} />
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Preview simulator ─────────────────────────────── */}
      <form
        onSubmit={runPreview}
        className="bg-bg dark:bg-surface rounded-2xl border border-gray-100 p-5 space-y-4"
      >
        <div>
          <h2 className="text-sm font-semibold text-ink">
            Preview a hypothetical override
          </h2>
          <p className="text-xs text-caption">
            Leave override fields blank to use the industry default.
          </p>
        </div>

        {previewError && (
          <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-xs text-red-700">
            {previewError}
          </div>
        )}

        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <label className="block">
            <span className="text-xs font-medium text-ink">Ticker</span>
            <input
              required
              type="text"
              value={previewForm.ticker}
              onChange={(e) =>
                setPreviewForm({ ...previewForm, ticker: e.target.value })
              }
              className="mt-1 w-full rounded-lg border border-border px-3 py-2 text-sm"
            />
          </label>
          <label className="block">
            <span className="text-xs font-medium text-ink">Sector</span>
            <select
              required
              value={previewForm.sector}
              onChange={(e) =>
                setPreviewForm({ ...previewForm, sector: e.target.value })
              }
              className="mt-1 w-full rounded-lg border border-border px-3 py-2 text-sm"
            >
              {SUPPORTED_SECTORS.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </label>
          <label className="block">
            <span className="text-xs font-medium text-ink">CMP (₹)</span>
            <input
              required
              type="number"
              step="any"
              value={previewForm.current_price}
              onChange={(e) =>
                setPreviewForm({ ...previewForm, current_price: e.target.value })
              }
              className="mt-1 w-full rounded-lg border border-border px-3 py-2 text-sm"
            />
          </label>
          <label className="block">
            <span className="text-xs font-medium text-ink">Revenue (₹ Cr)</span>
            <input
              required
              type="number"
              step="any"
              value={previewForm.revenue_cr}
              onChange={(e) =>
                setPreviewForm({ ...previewForm, revenue_cr: e.target.value })
              }
              className="mt-1 w-full rounded-lg border border-border px-3 py-2 text-sm"
            />
          </label>
          <label className="block">
            <span className="text-xs font-medium text-ink">Shares (Cr)</span>
            <input
              required
              type="number"
              step="any"
              value={previewForm.shares_cr}
              onChange={(e) =>
                setPreviewForm({ ...previewForm, shares_cr: e.target.value })
              }
              className="mt-1 w-full rounded-lg border border-border px-3 py-2 text-sm"
            />
          </label>
        </div>

        <div className="border-t border-gray-100 pt-3">
          <p className="text-xs font-semibold text-ink mb-2">
            Override fields (optional)
          </p>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {(
              [
                ["initial_growth", "initial_growth"],
                ["target_op_margin", "target_op_margin"],
                ["reinvestment_rate", "reinvestment_rate"],
                ["wacc", "wacc"],
              ] as const
            ).map(([field, label]) => (
              <label key={field} className="block">
                <span className="text-xs text-caption">{label}</span>
                <input
                  type="number"
                  step="any"
                  placeholder="(use default)"
                  value={previewForm[field]}
                  onChange={(e) =>
                    setPreviewForm({ ...previewForm, [field]: e.target.value })
                  }
                  className="mt-1 w-full rounded-lg border border-border px-2 py-1.5 text-xs font-mono"
                />
              </label>
            ))}
          </div>
        </div>

        <button
          type="submit"
          disabled={previewLoading}
          className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
        >
          {previewLoading ? "Running…" : "Run preview"}
        </button>

        {/* ── Preview result ───────────────────────────────── */}
        {previewResult && (
          <div className="mt-3 rounded-xl border border-border bg-bg dark:bg-surface p-4 space-y-3">
            <div className="flex items-baseline justify-between">
              <h3 className="text-sm font-semibold text-ink">
                Preview result
              </h3>
              <span className="text-xs text-caption">
                industry: {previewResult.industry_key}
              </span>
            </div>

            {previewResult.status === "engine_returned_none" ? (
              <p className="text-xs text-amber-700">
                Model collapsed: {previewResult.reason}
              </p>
            ) : (
              previewResult.result && (
                <>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
                    <div>
                      <p className="text-caption">Fair value</p>
                      <p className="font-mono text-lg font-semibold">
                        ₹{fmtNum(previewResult.result.fair_value, 0)}
                      </p>
                    </div>
                    <div>
                      <p className="text-caption">FV/CMP</p>
                      <p
                        className={`font-mono text-lg font-semibold ${
                          previewResult.result.in_safety_net_band
                            ? "text-emerald-700"
                            : "text-red-700"
                        }`}
                      >
                        {fmtNum(previewResult.result.fv_cmp_ratio, 2)}
                      </p>
                      <p className="text-[10px] text-caption">
                        band [0.30, 3.5]
                      </p>
                    </div>
                    <div>
                      <p className="text-caption">Confidence</p>
                      <p className="font-mono text-lg font-semibold">
                        {previewResult.result.confidence_score ?? "—"}
                      </p>
                    </div>
                    <div>
                      <p className="text-caption">Verdict</p>
                      <p className="font-mono text-sm font-semibold">
                        {previewResult.result.verdict ?? "—"}
                      </p>
                    </div>
                  </div>
                  <div className="border-t border-border pt-3">
                    <p className="text-xs font-semibold text-ink mb-1">
                      Final params used
                    </p>
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-x-4">
                      <ParamRow
                        label="initial_growth"
                        value={fmtPct(previewResult.params.initial_growth)}
                      />
                      <ParamRow
                        label="target_op_margin"
                        value={fmtPct(previewResult.params.target_op_margin)}
                      />
                      <ParamRow
                        label="reinvestment_rate"
                        value={fmtPct(previewResult.params.reinvestment_rate)}
                      />
                      <ParamRow label="wacc" value={fmtPct(previewResult.params.wacc)} />
                    </div>
                  </div>
                </>
              )
            )}
          </div>
        )}
      </form>

      {overrides && (
        <p className="text-xs text-caption italic">
          {overrides._meta.note}
        </p>
      )}
    </div>
  )
}
