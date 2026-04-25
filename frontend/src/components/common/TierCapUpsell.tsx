"use client"
import Link from "next/link"

/**
 * Inline upsell card shown when a backend tier-cap is hit.
 *
 * The backend returns 403 with a structured body like:
 *   {
 *     error: "broker_account_cap_reached" | "compare_ticker_cap_reached",
 *     tier: "free" | "analyst" | "pro",
 *     cap: number,
 *     current?: number,
 *     requested?: number,
 *     message: string,
 *     upgrade_link: "/pricing",
 *   }
 *
 * Pass that `detail` payload here and we render an inline card with
 * an "Upgrade to Pro" button. Don't use a generic toast — the card is
 * deliberately heavier so the user understands the limit + the upgrade
 * path, instead of dismissing a transient notification.
 */
export interface TierCapDetail {
  error: string
  tier: string
  cap: number
  current?: number
  requested?: number
  message: string
  upgrade_link?: string
}

export function TierCapUpsell({
  detail,
  onDismiss,
}: {
  detail: TierCapDetail
  onDismiss?: () => void
}) {
  const upgradeHref = detail.upgrade_link || "/pricing"
  const isPro = detail.tier === "pro"

  return (
    <div
      role="alert"
      className="bg-gradient-to-br from-amber-50 to-white border border-amber-200 rounded-xl p-4 mb-4"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1">
          <p className="text-xs font-bold text-amber-800 uppercase tracking-wider mb-1">
            {isPro ? "Plan limit reached" : "Upgrade to do more"}
          </p>
          <p className="text-sm text-amber-900 leading-relaxed">{detail.message}</p>
          {detail.current != null && (
            <p className="text-xs text-amber-700 mt-1">
              Currently using {detail.current} of {detail.cap}.
            </p>
          )}
        </div>
        {onDismiss && (
          <button
            onClick={onDismiss}
            className="text-amber-400 hover:text-amber-700 text-xs flex-shrink-0"
            aria-label="Dismiss"
          >
            &times;
          </button>
        )}
      </div>
      {!isPro && (
        <div className="mt-3 flex gap-2">
          <Link
            href={upgradeHref}
            className="inline-flex items-center justify-center px-4 py-2 bg-amber-600 text-white text-xs font-semibold rounded-lg hover:bg-amber-700 transition"
          >
            Upgrade to Pro
          </Link>
          <Link
            href={upgradeHref}
            className="inline-flex items-center justify-center px-4 py-2 bg-white border border-amber-300 text-amber-800 text-xs font-semibold rounded-lg hover:bg-amber-50 transition"
          >
            See plans
          </Link>
        </div>
      )}
    </div>
  )
}

/**
 * Best-effort extractor: pulls a TierCapDetail out of an axios-style
 * error if the backend returned one of our structured 403s. Returns
 * null when the error isn't a tier-cap error so callers can keep
 * their existing error path for everything else.
 */
export function extractTierCapDetail(err: unknown): TierCapDetail | null {
  if (!err || typeof err !== "object") return null
  const ax = err as { response?: { status?: number; data?: { detail?: unknown } } }
  if (ax.response?.status !== 403) return null
  const detail = ax.response?.data?.detail
  if (!detail || typeof detail !== "object") return null
  const d = detail as Record<string, unknown>
  if (typeof d.error !== "string") return null
  if (
    d.error !== "broker_account_cap_reached" &&
    d.error !== "compare_ticker_cap_reached"
  ) {
    return null
  }
  return {
    error: d.error,
    tier: typeof d.tier === "string" ? d.tier : "free",
    cap: typeof d.cap === "number" ? d.cap : 0,
    current: typeof d.current === "number" ? d.current : undefined,
    requested: typeof d.requested === "number" ? d.requested : undefined,
    message: typeof d.message === "string" ? d.message : "Plan limit reached.",
    upgrade_link: typeof d.upgrade_link === "string" ? d.upgrade_link : "/pricing",
  }
}
