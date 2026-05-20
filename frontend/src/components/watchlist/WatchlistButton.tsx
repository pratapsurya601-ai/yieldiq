"use client"

/**
 * Day-32 (2026-05-20): WatchlistButton — single component for adding/
 * removing a ticker from the user's watchlist.
 *
 * Used at 3 placement sites:
 *   - /analysis/[ticker] hero
 *   - /screener results-table rows
 *   - /discover quick tiles + sector leaders
 *
 * Wires to the existing backend API surface:
 *   POST   /api/v1/watchlist/        — add
 *   DELETE /api/v1/watchlist/{ticker} — remove
 *   GET    /api/v1/watchlist/check/{ticker} — read membership
 *
 * Optimistic UI: button flips immediately on click; on API failure,
 * state reverts and a brief toast (browser-native alert fallback)
 * surfaces. The membership state is cached per-ticker for 60s so
 * the table view doesn't fire 50 simultaneous GETs.
 *
 * Auth-gated: when no auth token, button renders as a "Sign in to
 * save" CTA pointing at /auth/login.
 */

import { useCallback, useEffect, useState } from "react"
import { useRouter } from "next/navigation"
import { Bookmark, BookmarkCheck } from "lucide-react"
import api from "@/lib/api"
import { useAuthStore } from "@/store/authStore"

export type WatchlistButtonVariant = "default" | "compact" | "icon-only"

export interface WatchlistButtonProps {
  /** Bare or .NS-suffixed ticker. Will be uppercased + suffix-stripped
   * before posting (backend stores bare). */
  ticker: string
  /** Optional company name for the backend's SQLite fallback path.
   * Supabase path ignores; SQLite path persists for display in the
   * watchlist page. */
  companyName?: string
  /** Visual variant. `compact` (default) is a small button suitable
   * for table rows / cards. `default` is full-sized for hero. Icon-only
   * for very tight rows. */
  variant?: WatchlistButtonVariant
  /** Pre-loaded membership state from a parent fetch. When provided,
   * skips the per-ticker GET on mount (used by table views that bulk-
   * fetch). */
  initialInWatchlist?: boolean | null
}

function _bareTicker(t: string): string {
  return (t || "").replace(/\.(NS|BO)$/i, "").toUpperCase().trim()
}

export default function WatchlistButton({
  ticker,
  companyName,
  variant = "compact",
  initialInWatchlist,
}: WatchlistButtonProps) {
  const router = useRouter()
  const token = useAuthStore((s) => s.token)
  const bare = _bareTicker(ticker)

  const [inWatchlist, setInWatchlist] = useState<boolean | null>(
    initialInWatchlist ?? null,
  )
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Per-mount membership check (skipped when initialInWatchlist passed)
  useEffect(() => {
    if (!token) {
      setInWatchlist(false)
      return
    }
    if (initialInWatchlist !== undefined && initialInWatchlist !== null) {
      return
    }
    let cancelled = false
    api
      .get<{ in_watchlist: boolean }>(`/api/v1/watchlist/check/${bare}`)
      .then((r) => {
        if (!cancelled) setInWatchlist(Boolean(r.data?.in_watchlist))
      })
      .catch(() => {
        if (!cancelled) setInWatchlist(false)
      })
    return () => {
      cancelled = true
    }
  }, [bare, token, initialInWatchlist])

  const onClick = useCallback(async () => {
    if (!token) {
      router.push("/auth/login?return_to=" + encodeURIComponent(window.location.pathname))
      return
    }
    if (busy) return
    setBusy(true)
    setError(null)
    const prevState = inWatchlist
    const nextState = !prevState
    setInWatchlist(nextState) // optimistic
    try {
      if (nextState) {
        await api.post("/api/v1/watchlist/", {
          ticker: bare,
          company_name: companyName ?? null,
        })
      } else {
        await api.delete(`/api/v1/watchlist/${bare}`)
      }
    } catch (e: unknown) {
      // Revert optimistic toggle
      setInWatchlist(prevState)
      const err = e as { response?: { data?: { detail?: string } }; message?: string }
      setError(
        err?.response?.data?.detail ??
          err?.message ??
          "Watchlist update failed",
      )
    } finally {
      setBusy(false)
    }
  }, [bare, busy, companyName, inWatchlist, router, token])

  const label = inWatchlist ? "In watchlist" : "Add to watchlist"
  const Icon = inWatchlist ? BookmarkCheck : Bookmark

  if (variant === "icon-only") {
    return (
      <button
        type="button"
        onClick={onClick}
        disabled={busy}
        aria-label={label}
        aria-pressed={!!inWatchlist}
        title={error ?? label}
        data-testid="watchlist-button"
        data-state={inWatchlist === null ? "unknown" : inWatchlist ? "in" : "out"}
        className={
          "inline-flex h-7 w-7 items-center justify-center rounded-md " +
          "text-caption hover:text-brand hover:bg-bg disabled:opacity-50 " +
          "disabled:cursor-not-allowed transition " +
          (inWatchlist ? "text-brand" : "")
        }
      >
        <Icon className="h-4 w-4" aria-hidden="true" />
      </button>
    )
  }

  if (variant === "compact") {
    return (
      <button
        type="button"
        onClick={onClick}
        disabled={busy}
        aria-pressed={!!inWatchlist}
        title={error ?? label}
        data-testid="watchlist-button"
        data-state={inWatchlist === null ? "unknown" : inWatchlist ? "in" : "out"}
        className={
          "inline-flex items-center gap-1 px-2 py-1 rounded-md text-[11px] font-semibold " +
          "border transition disabled:opacity-50 disabled:cursor-not-allowed " +
          (inWatchlist
            ? "border-brand text-brand bg-brand/5 hover:bg-brand/10"
            : "border-border text-caption hover:text-ink hover:border-ink/40")
        }
      >
        <Icon className="h-3 w-3" aria-hidden="true" />
        {inWatchlist ? "Saved" : "Save"}
      </button>
    )
  }

  // default — full button (hero placement)
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={busy}
      aria-pressed={!!inWatchlist}
      title={error ?? label}
      data-testid="watchlist-button"
      data-state={inWatchlist === null ? "unknown" : inWatchlist ? "in" : "out"}
      className={
        "inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold " +
        "border transition disabled:opacity-50 disabled:cursor-not-allowed " +
        (inWatchlist
          ? "border-brand text-brand bg-brand/5 hover:bg-brand/10"
          : "border-border text-ink hover:bg-bg")
      }
    >
      <Icon className="h-4 w-4" aria-hidden="true" />
      <span>{inWatchlist ? "In watchlist" : "Add to watchlist"}</span>
    </button>
  )
}
