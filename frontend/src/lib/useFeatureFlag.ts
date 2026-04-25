import { useAuthStore } from "@/store/authStore"

/** Returns true iff the named flag is enabled for the current user.
 *  Returns false for logged-out users (matches backend default).
 *
 *  Usage:
 *    const showBetaInput = useFeatureFlag("experimental_bond_yield_input")
 *    if (showBetaInput) return <BondYieldOverride />
 */
export function useFeatureFlag(flag: string): boolean {
  return useAuthStore((s) => s.featureFlags?.[flag] === true)
}
