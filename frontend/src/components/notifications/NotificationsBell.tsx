"use client"

// frontend/src/components/notifications/NotificationsBell.tsx
// Dhan/Zerodha-style bell + drawer in the nav.
//
// Behaviour:
//   - Polls /api/v1/notifications/unread-count every 60s for the badge.
//   - refetchIntervalInBackground=false → ZERO polling when the tab is
//     hidden, which saves Neon bandwidth and keeps the free-tier
//     Postgres pool happy on a sleeping laptop.
//   - Click bell → drawer pops open and triggers a one-shot fetch of
//     /api/v1/notifications/recent (read + unread, last 50). We don't
//     poll the recent list; the user only sees it when they open the
//     drawer, so a poll there is wasted bandwidth.
//   - Click an item: PATCH /{id}/read, then navigate to `link` if set.
//   - "Mark all read" is disabled when count = 0.
//
// Design tokens only (bg-bg, bg-surface, text-ink, border-border).
// Uses dark: variants where palette colors are referenced so both
// themes look clean (per the dark-mode sweep PR #80 conventions).

import { useEffect, useRef, useState } from "react"
import { useRouter } from "next/navigation"
import { useQuery, useQueryClient, useMutation } from "@tanstack/react-query"
import axios from "axios"
import Cookies from "js-cookie"

import { cn } from "@/lib/utils"
import { useAuthStore } from "@/store/authStore"
import { relativeTime } from "@/lib/relativeTime"
import type {
  Notification,
  NotificationsUnreadCountResponse,
  NotificationsRecentResponse,
  NotificationType,
} from "@/types/api"

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

function authHeaders(): Record<string, string> {
  const token = Cookies.get("yieldiq_token")
  return token ? { Authorization: `Bearer ${token}` } : {}
}

async function fetchUnreadCount(): Promise<number> {
  const res = await axios.get<NotificationsUnreadCountResponse>(
    `${API_BASE}/api/v1/notifications/unread-count`,
    { headers: authHeaders(), timeout: 10000 },
  )
  return res.data.count ?? 0
}

async function fetchRecent(): Promise<Notification[]> {
  const res = await axios.get<NotificationsRecentResponse>(
    `${API_BASE}/api/v1/notifications/recent`,
    { headers: authHeaders(), timeout: 10000 },
  )
  return res.data.items ?? []
}

async function markRead(id: number): Promise<void> {
  await axios.patch(
    `${API_BASE}/api/v1/notifications/${id}/read`,
    null,
    { headers: authHeaders(), timeout: 10000 },
  )
}

async function markAllRead(): Promise<void> {
  await axios.post(
    `${API_BASE}/api/v1/notifications/mark-all-read`,
    null,
    { headers: authHeaders(), timeout: 10000 },
  )
}

// Type → tiny color dot. Token-driven where possible so dark mode
// works without a per-token branch.
const TYPE_DOT: Record<NotificationType, string> = {
  alert_fired: "bg-amber-500",
  portfolio_event: "bg-emerald-500",
  earnings_reminder: "bg-blue-500",
  market_event: "bg-purple-500",
  model_update: "bg-indigo-500",
  system: "bg-slate-400",
}

export default function NotificationsBell() {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const router = useRouter()
  const qc = useQueryClient()
  const isAuthed = useAuthStore((s) => Boolean(s.token))

  // Bell-badge polling. Cheap endpoint; runs every 60s but ONLY while
  // the tab is visible (refetchIntervalInBackground: false).
  const countQuery = useQuery({
    queryKey: ["notif-count"],
    queryFn: fetchUnreadCount,
    refetchInterval: 60_000,
    refetchIntervalInBackground: false,
    enabled: isAuthed,
    staleTime: 30_000,
  })

  // Recent list — only fetched when the drawer is open, so the user
  // has to actively look at notifications to incur the heavier query.
  const recentQuery = useQuery({
    queryKey: ["notif-recent"],
    queryFn: fetchRecent,
    enabled: isAuthed && open,
    staleTime: 30_000,
  })

  const markReadMut = useMutation({
    mutationFn: markRead,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["notif-count"] })
      qc.invalidateQueries({ queryKey: ["notif-recent"] })
    },
  })

  const markAllReadMut = useMutation({
    mutationFn: markAllRead,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["notif-count"] })
      qc.invalidateQueries({ queryKey: ["notif-recent"] })
    },
  })

  // Outside-click closes the drawer.
  useEffect(() => {
    function onClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    if (open) document.addEventListener("mousedown", onClick)
    return () => document.removeEventListener("mousedown", onClick)
  }, [open])

  // Hide entirely when not logged in — bell only makes sense for users.
  if (!isAuthed) return null

  const count = countQuery.data ?? 0
  const items = recentQuery.data ?? []
  const isLoading = open && recentQuery.isLoading

  const handleItemClick = (n: Notification) => {
    if (!n.read_at) markReadMut.mutate(n.id)
    if (n.link) {
      setOpen(false)
      router.push(n.link)
    }
  }

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-label={`Notifications${count > 0 ? `, ${count} unread` : ""}`}
        aria-haspopup="dialog"
        aria-expanded={open}
        className={cn(
          "relative inline-flex h-8 w-8 items-center justify-center rounded-full",
          "text-caption hover:bg-surface hover:text-ink transition",
          "dark:hover:bg-surface",
        )}
      >
        {/* Heroicons solid bell, 20x20 */}
        <svg
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 20 20"
          fill="currentColor"
          className="h-5 w-5"
          aria-hidden="true"
        >
          <path
            fillRule="evenodd"
            d="M10 2a6 6 0 00-6 6v3.586l-.707.707A1 1 0 004 14h12a1 1 0 00.707-1.707L16 11.586V8a6 6 0 00-6-6zM10 18a3 3 0 01-3-3h6a3 3 0 01-3 3z"
            clipRule="evenodd"
          />
        </svg>
        {count > 0 && (
          <span
            className={cn(
              "absolute -top-0.5 -right-0.5 inline-flex min-w-[16px] h-4 items-center justify-center",
              "rounded-full bg-danger px-1 text-[10px] font-bold leading-none text-white",
              "ring-2 ring-bg dark:ring-bg",
            )}
          >
            {count > 9 ? "9+" : count}
          </span>
        )}
      </button>

      {open && (
        <div
          role="dialog"
          aria-label="Notifications"
          className={cn(
            "absolute right-0 top-full mt-2 w-80 max-h-[480px]",
            "rounded-xl border border-border bg-bg shadow-xl",
            "z-50 overflow-hidden flex flex-col",
            "dark:bg-bg dark:border-border",
          )}
        >
          {/* Header */}
          <div className="flex items-center justify-between px-4 py-3 border-b border-border">
            <p className="text-sm font-semibold text-ink">Notifications</p>
            <button
              type="button"
              onClick={() => markAllReadMut.mutate()}
              disabled={count === 0 || markAllReadMut.isPending}
              className={cn(
                "text-xs font-medium transition",
                count === 0
                  ? "text-caption opacity-50 cursor-not-allowed"
                  : "text-brand hover:underline",
              )}
            >
              Mark all read
            </button>
          </div>

          {/* Body */}
          <div className="flex-1 overflow-y-auto">
            {isLoading ? (
              <ul className="divide-y divide-border">
                {[0, 1, 2].map((i) => (
                  <li key={i} className="px-4 py-3 animate-pulse">
                    <div className="h-3 w-3/4 bg-surface rounded mb-2" />
                    <div className="h-2 w-1/2 bg-surface rounded" />
                  </li>
                ))}
              </ul>
            ) : items.length === 0 ? (
              <div className="px-4 py-10 text-center">
                <p className="text-sm text-caption">No notifications yet</p>
              </div>
            ) : (
              <ul className="divide-y divide-border">
                {items.map((n) => {
                  const unread = !n.read_at
                  return (
                    <li
                      key={n.id}
                      className={cn(
                        "relative px-4 py-3 cursor-pointer transition",
                        unread ? "bg-brand-50/40 dark:bg-brand-50/20" : "bg-bg",
                        "hover:bg-surface dark:hover:bg-surface",
                      )}
                      onClick={() => handleItemClick(n)}
                    >
                      {unread && (
                        <span
                          aria-hidden="true"
                          className="absolute left-1.5 top-4 h-2 w-2 rounded-full bg-brand"
                        />
                      )}
                      <div className="flex items-start gap-2 pl-3">
                        <span
                          aria-hidden="true"
                          className={cn(
                            "mt-1.5 h-1.5 w-1.5 flex-shrink-0 rounded-full",
                            TYPE_DOT[n.type] ?? "bg-slate-400",
                          )}
                        />
                        <div className="flex-1 min-w-0">
                          <p
                            className={cn(
                              "text-sm text-ink truncate",
                              unread ? "font-semibold" : "font-medium",
                            )}
                          >
                            {n.title}
                          </p>
                          {n.body && (
                            <p className="mt-0.5 text-xs text-caption line-clamp-2">
                              {n.body}
                            </p>
                          )}
                          <p className="mt-1 text-[11px] text-caption">
                            {relativeTime(n.created_at)}
                          </p>
                        </div>
                      </div>
                    </li>
                  )
                })}
              </ul>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
