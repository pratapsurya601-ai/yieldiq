"use client"

// /account/alerts — dedicated management surface for the user_alerts
// table (migration 009). Mirrors the look of /account/preferences and
// /account/notifications so the Account hub stays internally consistent.
//
// Unlike the in-Portfolio "Alerts" tab — which still reads the legacy
// {alert_type, target_price} shape used by the deprecated Supabase
// price_alerts table — this page reads the NEW {kind, threshold,
// status, notify_email, notify_push} response from
// GET /api/v1/alerts/. Once the Portfolio tab is migrated, we can
// retire the legacy AlertResponse type.
//
// SEBI vocabulary: never use "buy", "sell", "recommend", "should", etc.
// Copy here is purely descriptive — "notify when discount reaches X%".

import * as React from "react"
import Link from "next/link"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { Bell, BellOff, Trash2 } from "lucide-react"

import api from "@/lib/api"

// ── Types (mirror backend/routers/alerts.py response shape) ──

type AlertKind =
  | "mos_above"
  | "mos_below"
  | "price_above"
  | "price_below"
  | "verdict_change"

type AlertStatus = "active" | "paused" | "triggered"

interface AlertRow {
  id: number
  user_id: string
  ticker: string
  kind: AlertKind
  threshold: number | null
  last_checked_at: string | null
  last_triggered_at: string | null
  status: AlertStatus
  created_at: string
  notify_email: boolean
  notify_push: boolean
}

// ── API helpers ──────────────────────────────────────────────

const listMyAlerts = (): Promise<AlertRow[]> =>
  api.get("/api/v1/alerts/").then((r) => r.data)

const patchAlert = (alertId: number, patch: Partial<Pick<AlertRow, "status" | "notify_email" | "notify_push">>) =>
  api.patch(`/api/v1/alerts/${alertId}`, patch).then((r) => r.data)

const deleteAlertById = (alertId: number) =>
  api.delete(`/api/v1/alerts/${alertId}`).then((r) => r.data)

// ── Display helpers ──────────────────────────────────────────

function kindDescription(row: AlertRow): string {
  const t = row.threshold
  const display = row.ticker.replace(".NS", "").replace(".BO", "")
  switch (row.kind) {
    case "mos_above":
      // Descriptive — no "buy"/"recommend".
      return `Notify when ${display} discount-to-FV reaches ${t ?? "—"}%`
    case "mos_below":
      return `Notify when ${display} discount-to-FV falls below ${t ?? "—"}%`
    case "price_above":
      return `Notify when ${display} price crosses above ₹${t?.toLocaleString("en-IN") ?? "—"}`
    case "price_below":
      return `Notify when ${display} price drops below ₹${t?.toLocaleString("en-IN") ?? "—"}`
    case "verdict_change":
      return `Notify when ${display} verdict changes`
  }
}

function statusBadgeClasses(status: AlertStatus): string {
  switch (status) {
    case "active":
      return "bg-emerald-50 text-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-300"
    case "paused":
      return "bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300"
    case "triggered":
      return "bg-blue-50 text-blue-800 dark:bg-blue-950/40 dark:text-blue-300"
  }
}

function formatDate(iso: string | null): string {
  if (!iso) return "—"
  try {
    const d = new Date(iso)
    return d.toLocaleString("en-IN", {
      day: "numeric",
      month: "short",
      year: "numeric",
    })
  } catch {
    return iso
  }
}

// ── Page ─────────────────────────────────────────────────────

export default function AccountAlertsPage() {
  const qc = useQueryClient()

  const { data: rows, isLoading, error } = useQuery<AlertRow[]>({
    queryKey: ["account-alerts"],
    queryFn: listMyAlerts,
  })

  const [toast, setToast] = React.useState<string | null>(null)
  const showToast = React.useCallback((msg: string) => {
    setToast(msg)
    setTimeout(() => setToast(null), 2500)
  }, [])

  const patchMut = useMutation({
    mutationFn: ({ id, patch }: { id: number; patch: Partial<AlertRow> }) =>
      patchAlert(id, patch),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["account-alerts"] })
      showToast("Updated.")
    },
    onError: () => showToast("Could not update. Try again."),
  })

  const deleteMut = useMutation({
    mutationFn: (id: number) => deleteAlertById(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["account-alerts"] })
      showToast("Alert deleted.")
    },
    onError: () => showToast("Could not delete. Try again."),
  })

  const togglePause = (row: AlertRow) => {
    const nextStatus: AlertStatus =
      row.status === "active" ? "paused" : "active"
    patchMut.mutate({ id: row.id, patch: { status: nextStatus } })
  }

  // ── Render ───────────────────────────────────────────────

  return (
    <div className="max-w-3xl mx-auto px-4 py-8 pb-20">
      <nav className="text-xs text-caption mb-4">
        <Link href="/account" className="hover:text-ink">
          Account
        </Link>{" "}
        / <span className="text-ink">Alerts</span>
      </nav>

      <h1 className="font-display text-2xl md:text-3xl font-semibold text-ink">
        Active alerts
      </h1>
      <p className="text-sm text-body mt-2 max-w-prose">
        Notifications fire when a watched stock crosses your threshold.
        Set new alerts from any analysis page using the &ldquo;Notify me
        when discount reaches&rdquo; control.
      </p>

      <div className="mt-6">
        {isLoading ? (
          <div className="rounded-xl border border-border bg-surface p-6 text-sm text-caption">
            Loading…
          </div>
        ) : error ? (
          <div
            role="alert"
            className="rounded-xl border border-amber-300 bg-amber-50 p-4 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-200"
          >
            Could not load alerts. Refresh to try again.
          </div>
        ) : !rows || rows.length === 0 ? (
          <EmptyState />
        ) : (
          <ul className="space-y-2">
            {rows.map((row) => (
              <li
                key={row.id}
                className="flex items-start gap-3 rounded-xl border border-border bg-surface p-4"
              >
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <Link
                      href={`/analysis/${row.ticker}`}
                      className="text-sm font-semibold text-ink hover:underline"
                    >
                      {row.ticker.replace(".NS", "").replace(".BO", "")}
                    </Link>
                    <span
                      className={
                        "text-[10px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded-full " +
                        statusBadgeClasses(row.status)
                      }
                    >
                      {row.status}
                    </span>
                    {row.notify_email ? (
                      <span className="text-[10px] text-caption">Email</span>
                    ) : null}
                    {row.notify_push ? (
                      <span className="text-[10px] text-caption">Push</span>
                    ) : null}
                  </div>
                  <p className="text-sm text-body mt-1">
                    {kindDescription(row)}
                  </p>
                  <p className="text-[11px] text-caption mt-1.5">
                    Created {formatDate(row.created_at)}
                    {row.last_triggered_at
                      ? ` · Last fired ${formatDate(row.last_triggered_at)}`
                      : ""}
                  </p>
                </div>

                <div className="flex items-center gap-1 shrink-0">
                  <button
                    type="button"
                    onClick={() => togglePause(row)}
                    disabled={patchMut.isPending || row.status === "triggered"}
                    aria-label={
                      row.status === "active"
                        ? `Pause ${row.ticker} alert`
                        : `Resume ${row.ticker} alert`
                    }
                    title={
                      row.status === "active" ? "Pause" : "Resume"
                    }
                    className="inline-flex items-center justify-center h-9 w-9 rounded-lg border border-border text-caption hover:text-ink hover:border-ink/40 disabled:opacity-40 disabled:cursor-not-allowed transition"
                  >
                    {row.status === "active" ? (
                      <BellOff className="h-4 w-4" aria-hidden="true" />
                    ) : (
                      <Bell className="h-4 w-4" aria-hidden="true" />
                    )}
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      if (window.confirm("Delete this alert?")) {
                        deleteMut.mutate(row.id)
                      }
                    }}
                    disabled={deleteMut.isPending}
                    aria-label={`Delete ${row.ticker} alert`}
                    title="Delete"
                    className="inline-flex items-center justify-center h-9 w-9 rounded-lg border border-border text-caption hover:text-red-600 hover:border-red-300 disabled:opacity-40 disabled:cursor-not-allowed transition"
                  >
                    <Trash2 className="h-4 w-4" aria-hidden="true" />
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="mt-8 text-xs text-caption">
        <Link href="/account/notifications" className="hover:text-ink">
          Manage notification channels &rarr;
        </Link>
      </div>

      {toast ? (
        <div
          role="status"
          className="fixed bottom-20 left-1/2 -translate-x-1/2 bg-gray-900 text-white text-sm font-medium px-4 py-2.5 rounded-lg shadow-lg z-50"
        >
          {toast}
        </div>
      ) : null}
    </div>
  )
}

function EmptyState() {
  return (
    <div className="rounded-xl border border-border bg-surface p-8 text-center">
      <Bell
        className="h-10 w-10 mx-auto text-caption mb-3"
        aria-hidden="true"
      />
      <p className="text-base font-semibold text-ink">No active alerts</p>
      <p className="text-sm text-caption mt-1 max-w-prose mx-auto">
        Open any analysis page and use the &ldquo;Notify me when discount
        reaches&rdquo; control under the discount-to-FV stat to set one
        up.
      </p>
      <Link
        href="/search"
        className="inline-block mt-4 text-sm font-medium text-blue-600 hover:underline"
      >
        Browse stocks
      </Link>
    </div>
  )
}
