"use client"

/**
 * MosBandAlertModal — task #131.
 *
 * Triggered by the "Set alert" button on the analysis page hero, this
 * modal lets the user stack multiple margin-of-safety thresholds per
 * ticker — one row per (threshold, direction) tuple — so a watcher
 * can be notified at +20% MoS AND at +30% AND at -10% all on the
 * same stock. Distinct from <MosAlertChip/> which creates a single
 * one-shot UserAlert via the legacy /api/v1/alerts/create endpoint.
 *
 * Backend: POST/GET/DELETE /api/v1/alerts/mos-band — see
 * backend/routers/mos_band_alerts.py.
 *
 * SEBI vocabulary: copy uses "Margin of safety" + "Notify me when".
 * No directives, no banned tokens.
 */

import { useCallback, useEffect, useMemo, useState } from "react"

import { useAuthStore } from "@/store/authStore"

const THRESHOLD_STEPS = [
  -50, -40, -30, -20, -10, 0, 10, 20, 30, 40, 50,
] as const

type Direction = "positive" | "negative"

interface BandAlertRow {
  user_id: string
  ticker: string
  threshold_pct: number
  direction: Direction
  last_fired_at: string | null
  created_at: string
}

export interface MosBandAlertModalProps {
  open: boolean
  onClose: () => void
  ticker: string
  /** Current SSR-rendered MoS for context. */
  currentMos: number | null
}

function _apiBase(): string {
  return process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"
}

async function _listAlerts(token: string): Promise<BandAlertRow[]> {
  const res = await fetch(`${_apiBase()}/api/v1/alerts/mos-band`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  })
  if (!res.ok) throw new Error(`list failed (${res.status})`)
  const data = (await res.json()) as { alerts?: BandAlertRow[] }
  return data.alerts ?? []
}

async function _createAlert(
  token: string,
  payload: { ticker: string; threshold_pct: number; direction: Direction },
): Promise<BandAlertRow> {
  const res = await fetch(`${_apiBase()}/api/v1/alerts/mos-band`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(payload),
  })
  if (!res.ok) {
    let detail = "Could not create alert"
    try {
      const j = (await res.json()) as { detail?: string }
      if (j.detail) detail = j.detail
    } catch {
      /* swallow */
    }
    throw new Error(detail)
  }
  return (await res.json()) as BandAlertRow
}

async function _deleteAlert(
  token: string,
  ticker: string,
  threshold_pct: number,
  direction: Direction,
): Promise<void> {
  const url =
    `${_apiBase()}/api/v1/alerts/mos-band/` +
    `${encodeURIComponent(ticker)}/${threshold_pct}/${direction}`
  const res = await fetch(url, {
    method: "DELETE",
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok && res.status !== 404) {
    throw new Error(`delete failed (${res.status})`)
  }
}

export default function MosBandAlertModal({
  open,
  onClose,
  ticker,
  currentMos,
}: MosBandAlertModalProps) {
  // Read auth state via the store hook so the caller doesn't have to
  // thread a token prop into every hero in the codebase.
  const token = useAuthStore((s) => s.token)
  const [threshold, setThreshold] = useState<number>(20)
  const [direction, setDirection] = useState<Direction>("positive")
  const [alerts, setAlerts] = useState<BandAlertRow[]>([])
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<boolean>(false)

  // Pre-seed direction based on current MoS so the default makes
  // sense — if the stock is already in the discount zone, the user
  // probably wants a deeper-discount positive trigger; if at premium
  // the relevant alert is the pullback. Same heuristic MosAlertChip uses.
  useEffect(() => {
    if (currentMos != null && Number.isFinite(currentMos)) {
      if (currentMos >= 0) {
        setDirection("positive")
        const next = THRESHOLD_STEPS.find((s) => s > currentMos)
        setThreshold(next ?? 30)
      } else {
        setDirection("negative")
        const next = [...THRESHOLD_STEPS].reverse().find((s) => s < currentMos)
        setThreshold(next ?? -20)
      }
    }
  }, [currentMos])

  const _refresh = useCallback(async () => {
    if (!token) return
    try {
      const rows = await _listAlerts(token)
      setAlerts(rows.filter((r) => r.ticker === ticker.toUpperCase()))
    } catch {
      // non-fatal — leave the list as-is so the user can still create.
    }
  }, [token, ticker])

  useEffect(() => {
    if (open) void _refresh()
  }, [open, _refresh])

  const _onSubmit = useCallback(async () => {
    if (!token) return
    setBusy(true)
    setError(null)
    try {
      await _createAlert(token, {
        ticker: ticker.toUpperCase(),
        threshold_pct: threshold,
        direction,
      })
      await _refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save alert")
    } finally {
      setBusy(false)
    }
  }, [token, ticker, threshold, direction, _refresh])

  const _onDelete = useCallback(
    async (row: BandAlertRow) => {
      if (!token) return
      setBusy(true)
      setError(null)
      try {
        await _deleteAlert(token, row.ticker, row.threshold_pct, row.direction)
        await _refresh()
      } catch (e) {
        setError(e instanceof Error ? e.message : "Could not remove alert")
      } finally {
        setBusy(false)
      }
    },
    [token, _refresh],
  )

  // Close on Escape
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose()
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [open, onClose])

  const currentMosLabel = useMemo<string>(() => {
    if (currentMos == null || !Number.isFinite(currentMos)) return "n/a"
    const r = Math.round(currentMos * 10) / 10
    return `${r > 0 ? "+" : ""}${r.toFixed(1)}%`
  }, [currentMos])

  if (!open) return null

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="mos-band-modal-title"
      data-testid="mos-band-alert-modal"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div className="w-full max-w-md rounded-xl bg-bg border border-border shadow-xl">
        <header className="flex items-center justify-between border-b border-border px-4 py-3">
          <h2
            id="mos-band-modal-title"
            className="text-sm font-semibold text-ink"
          >
            Set MoS alert · {ticker.toUpperCase()}
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="text-caption hover:text-ink text-sm"
            aria-label="Close"
          >
            ✕
          </button>
        </header>

        <div className="px-4 py-4 space-y-4">
          {!token ? (
            <p className="text-sm text-body">
              Sign in to manage MoS-band alerts for this ticker.
            </p>
          ) : (
            <>
              <p className="text-[12px] text-caption">
                Current margin of safety:{" "}
                <span className="font-mono font-semibold text-ink">
                  {currentMosLabel}
                </span>
              </p>

              <fieldset
                aria-labelledby="mos-band-direction-legend"
                className="space-y-1.5"
              >
                <legend
                  id="mos-band-direction-legend"
                  className="text-[10px] uppercase tracking-[0.15em] text-caption"
                >
                  Notify me when MoS
                </legend>
                <div className="flex gap-2" role="radiogroup">
                  {([
                    ["positive", "rises above"],
                    ["negative", "falls below"],
                  ] as const).map(([val, label]) => (
                    <button
                      key={val}
                      type="button"
                      role="radio"
                      aria-checked={direction === val}
                      data-testid={`mos-band-direction-${val}`}
                      onClick={() => setDirection(val)}
                      className={
                        "px-3 py-1.5 rounded-md text-[12px] border " +
                        (direction === val
                          ? "border-brand text-brand bg-brand/5"
                          : "border-border text-caption hover:text-ink")
                      }
                    >
                      {label}
                    </button>
                  ))}
                </div>
              </fieldset>

              <div className="space-y-1.5">
                <label
                  htmlFor="mos-band-threshold"
                  className="text-[10px] uppercase tracking-[0.15em] text-caption block"
                >
                  Threshold ({direction === "positive" ? "≥" : "≤"})
                </label>
                <div
                  role="radiogroup"
                  aria-label="MoS threshold percent"
                  className="flex flex-wrap gap-1"
                >
                  {THRESHOLD_STEPS.map((step) => {
                    const selected = step === threshold
                    return (
                      <button
                        key={step}
                        type="button"
                        role="radio"
                        aria-checked={selected}
                        data-testid={`mos-band-threshold-${step}`}
                        onClick={() => setThreshold(step)}
                        className={
                          "px-2 py-0.5 rounded-md text-[11px] font-mono " +
                          "tabular-nums border " +
                          (selected
                            ? "border-brand text-brand bg-brand/5"
                            : "border-border text-caption hover:text-ink")
                        }
                      >
                        {step > 0 ? "+" : ""}
                        {step}%
                      </button>
                    )
                  })}
                </div>
              </div>

              {error && (
                <p
                  role="alert"
                  className="text-[12px] text-amber-700 dark:text-amber-300"
                >
                  {error}
                </p>
              )}

              <button
                type="button"
                onClick={_onSubmit}
                disabled={busy}
                data-testid="mos-band-submit"
                className={
                  "w-full px-3 py-2 rounded-md text-[13px] font-semibold " +
                  "border border-brand text-brand bg-brand/5 " +
                  "hover:bg-brand/10 disabled:opacity-50 " +
                  "disabled:cursor-not-allowed"
                }
              >
                {busy ? "Saving…" : "Save alert"}
              </button>

              {alerts.length > 0 && (
                <div className="border-t border-border pt-3">
                  <p className="text-[10px] uppercase tracking-[0.15em] text-caption mb-2">
                    Active alerts on {ticker.toUpperCase()}
                  </p>
                  <ul className="space-y-1.5">
                    {alerts.map((a) => (
                      <li
                        key={`${a.threshold_pct}-${a.direction}`}
                        data-testid="mos-band-row"
                        className="flex items-center justify-between text-[12px]"
                      >
                        <span className="text-body">
                          MoS {a.direction === "positive" ? "≥" : "≤"}{" "}
                          <span className="font-mono font-semibold text-ink">
                            {a.threshold_pct > 0 ? "+" : ""}
                            {a.threshold_pct}%
                          </span>
                        </span>
                        <button
                          type="button"
                          onClick={() => void _onDelete(a)}
                          disabled={busy}
                          className="text-caption hover:text-rose-700 dark:hover:text-rose-300 text-[11px]"
                          aria-label={`Remove alert at ${a.threshold_pct}% ${a.direction}`}
                        >
                          Remove
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}
