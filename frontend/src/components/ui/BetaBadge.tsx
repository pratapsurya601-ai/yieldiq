"use client"
import { useFeatureFlag } from "@/lib/useFeatureFlag"

/**
 * Tiny "BETA" pill that renders only for users with the beta_ring
 * feature flag enabled (Pro tier today; can be widened via
 * tier_overrides / user_overrides in
 * backend/services/feature_flags.py).
 *
 * Usage: drop next to any feature label you want to soft-launch.
 *   <h2>Bond Yield Override <BetaBadge /></h2>
 *
 * Returns null for logged-out users and any tier without beta_ring,
 * so it's safe to leave in place after general release -- just flip
 * the flag default to True (or remove the badge in the same PR).
 */
export function BetaBadge() {
  const enabled = useFeatureFlag("beta_ring")
  if (!enabled) return null
  return (
    <span className="inline-flex items-center px-1.5 py-0.5 rounded-md text-[10px] font-bold bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300">
      BETA
    </span>
  )
}
