"use client"

/* ------------------------------------------------------------------ *
 * SavedScenarios — per-user saved DCF bundles for the current ticker.
 *
 * Rendered as a child block of <SensitivityPanel/>. Paid-tier feature:
 *
 *   * Save button only renders when the parent panel has a fresh
 *     recompute result (otherwise there's nothing to save).
 *   * List is shown to everyone (free users see an empty list with
 *     the upgrade pitch); backend GET is open by design.
 *   * Loading a scenario calls back into the parent so the sliders +
 *     headline numbers update in lockstep — keeps state ownership
 *     in one place (the panel).
 *
 * Backend contract: see backend/routers/scenarios.py.
 * ------------------------------------------------------------------ */

import { useState } from "react"
import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query"
import {
  deleteScenario,
  listScenarios,
  saveScenario,
  type SavedScenario,
} from "@/lib/api"
import { formatCurrency, formatPct, trueMosFromUpside } from "@/lib/utils"

interface Props {
  ticker: string
  currency: string
  /** Current slider values — what gets saved when the user clicks Save. */
  current: {
    wacc: number
    growth: number
    margin: number
    terminal_growth?: number
  }
  /** Latest recompute result, captured at save time so the saved row
   *  carries the FV/MoS the user actually saw. */
  currentResult: {
    fair_value: number
    margin_of_safety: number
    verdict?: string
  } | null
  /** Called when the user picks a saved scenario from the list. The
   *  parent re-positions sliders and triggers a recompute. */
  onLoad: (s: SavedScenario) => void
  /** True if the user can save (paid tier). When false, the save
   *  button renders as an upgrade CTA. */
  canSave: boolean
}

const QK = (ticker: string) => ["saved-scenarios", ticker] as const

export default function SavedScenarios({
  ticker,
  currency,
  current,
  currentResult,
  onLoad,
  canSave,
}: Props) {
  const qc = useQueryClient()
  const [name, setName] = useState("")
  const [showSaveRow, setShowSaveRow] = useState(false)

  const listQuery = useQuery({
    queryKey: QK(ticker),
    queryFn: () => listScenarios(ticker),
    // Per-user data — cache for the session, refetch on window focus
    // so a delete in another tab is reflected here.
    staleTime: 30_000,
  })

  const saveMut = useMutation({
    mutationFn: () =>
      saveScenario({
        ticker,
        name: name.trim(),
        assumptions: {
          wacc: current.wacc,
          growth_5y_pct: current.growth,
          margin_pct: current.margin,
          terminal_growth: current.terminal_growth ?? 0.03,
        },
        result: currentResult
          ? {
              fair_value: currentResult.fair_value,
              margin_of_safety: currentResult.margin_of_safety,
              verdict: currentResult.verdict ?? null,
            }
          : {},
      }),
    onSuccess: () => {
      setName("")
      setShowSaveRow(false)
      qc.invalidateQueries({ queryKey: QK(ticker) })
    },
  })

  const delMut = useMutation({
    mutationFn: (id: number) => deleteScenario(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: QK(ticker) }),
  })

  const scenarios = listQuery.data?.scenarios ?? []
  const cap = listQuery.data?.cap ?? 50

  const saveError = (() => {
    const err = saveMut.error as
      | {
          response?: {
            status?: number
            data?: { detail?: { error?: string; message?: string } | string }
          }
          message?: string
        }
      | null
    if (!err) return null
    if (err.response?.status === 403) {
      const d = err.response?.data?.detail
      if (typeof d === "object" && d?.message) return d.message
      return "Saving scenarios is a paid feature."
    }
    if (err.response?.status === 422) return "Name is required."
    return err.message ?? "Save failed"
  })()

  return (
    <div className="mt-4 pt-5 border-t border-border">
      <div className="flex items-baseline justify-between mb-3">
        <div>
          <h3 className="text-xs font-semibold text-ink uppercase tracking-wide">
            My scenarios
          </h3>
          <p className="text-[11px] text-caption mt-0.5">
            Save your assumptions to revisit later.
          </p>
        </div>
        {canSave ? (
          <button
            type="button"
            onClick={() => setShowSaveRow(v => !v)}
            disabled={!currentResult || currentResult.fair_value <= 0}
            className="text-xs font-medium text-brand hover:underline disabled:text-caption disabled:no-underline disabled:cursor-not-allowed"
          >
            {showSaveRow ? "Cancel" : "+ Save current"}
          </button>
        ) : (
          <a
            href="/pricing"
            className="text-xs font-medium text-brand hover:underline"
          >
            Upgrade to save
          </a>
        )}
      </div>

      {showSaveRow && canSave ? (
        <div className="flex gap-2 mb-3">
          <input
            type="text"
            value={name}
            onChange={e => setName(e.target.value)}
            placeholder="Name this scenario (e.g. Bear case)"
            maxLength={80}
            className="flex-1 px-3 py-1.5 text-sm rounded-lg border border-border bg-bg text-ink focus:outline-none focus:ring-1 focus:ring-brand"
            aria-label="Scenario name"
          />
          <button
            type="button"
            onClick={() => saveMut.mutate()}
            disabled={!name.trim() || saveMut.isPending}
            className="px-3 py-1.5 text-sm font-medium rounded-lg bg-brand text-white hover:opacity-90 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {saveMut.isPending ? "Saving…" : "Save"}
          </button>
        </div>
      ) : null}

      {saveError ? (
        <p className="mb-2 text-[11px] text-danger">{saveError}</p>
      ) : null}

      {listQuery.isLoading ? (
        <p className="text-[11px] text-caption">Loading…</p>
      ) : scenarios.length === 0 ? (
        <p className="text-[11px] text-caption">
          No saved scenarios yet for this ticker.
        </p>
      ) : (
        <ul className="space-y-1.5">
          {scenarios.map(s => {
            const fv = Number(s.result?.fair_value ?? 0)
            const mos = Number(s.result?.margin_of_safety ?? 0)
            const trueMos = trueMosFromUpside(Number.isFinite(mos) ? mos : null)
            const trueMosDisplay = trueMos != null && Number.isFinite(trueMos)
              ? formatPct(trueMos)
              : null
            const mosColor =
              (trueMos ?? mos) >= 20
                ? "text-success"
                : (trueMos ?? mos) >= -10
                ? "text-brand"
                : "text-danger"
            return (
              <li
                key={s.id}
                className="flex items-center gap-2 rounded-lg border border-border bg-surface px-3 py-2"
              >
                <button
                  type="button"
                  onClick={() => onLoad(s)}
                  className="flex-1 text-left"
                  aria-label={`Load scenario ${s.name}`}
                >
                  <p className="text-xs font-semibold text-ink truncate">
                    {s.name}
                  </p>
                  <p className="text-[10px] font-mono tabular-nums text-caption">
                    WACC {formatPct(Number(s.assumptions?.wacc ?? 0) * 100)} ·
                    {" g "}
                    {formatPct(
                      Number(s.assumptions?.growth_5y_pct ?? 0) * 100,
                    )}
                  </p>
                </button>
                <div className="text-right">
                  <p className="text-xs font-mono tabular-nums font-semibold text-ink">
                    {fv > 0 ? formatCurrency(fv, currency) : "—"}
                  </p>
                  <p className={`text-[10px] font-mono tabular-nums ${mosColor}`}>
                    {trueMosDisplay ?? "—"}
                  </p>
                  {Number.isFinite(mos) && trueMosDisplay && (
                    <p className="text-[10px] font-mono tabular-nums text-caption">
                      Implied upside {formatPct(mos)}
                    </p>
                  )}
                </div>
                <button
                  type="button"
                  onClick={() => {
                    if (confirm(`Delete scenario "${s.name}"?`)) {
                      delMut.mutate(s.id)
                    }
                  }}
                  className="text-caption hover:text-danger text-sm leading-none"
                  aria-label={`Delete scenario ${s.name}`}
                  title="Delete"
                >
                  ×
                </button>
              </li>
            )
          })}
        </ul>
      )}

      {scenarios.length >= cap * 0.8 ? (
        <p className="mt-2 text-[10px] text-caption">
          {scenarios.length}/{cap} scenarios used.
        </p>
      ) : null}
    </div>
  )
}
