import { create } from "zustand"
import { persist } from "zustand/middleware"
import type { Tier } from "@/types/api"

interface AuthState {
  token: string | null
  userId: string | null
  email: string | null
  tier: Tier
  analysesToday: number
  analysisLimit: number
  // Editable display name (PR #72). Null when the user has never set
  // one — PersonalHeader falls back to nameFromEmail(email).
  displayName: string | null
  // Lifetime edit budget. Defaults to 3 for new sessions; backend is
  // authoritative and refreshes this on every login + on profile PATCH.
  displayNameEditsRemaining: number
  // Feature flags resolved server-side at login / /auth/me. Empty
  // object on logged-out sessions; useFeatureFlag() treats missing
  // keys as disabled (mirrors the backend's "unknown flag = False"
  // safe default).
  featureFlags: Record<string, boolean>
  // Soft email-verify state (feat/soft-email-verify-gates). True when
  // backend reports users_meta.email_verified=true, the user is a
  // superuser, or the user is a legacy (pre-migration) account.
  // EmailVerifyBanner + the gated buttons read this. Defaults true so
  // a pre-PR backend that doesn't send the field doesn't spuriously
  // pop the banner.
  emailVerified: boolean
  setAuth: (
    token: string,
    userId: string,
    email: string,
    tier: Tier,
    analysesToday: number,
    analysisLimit: number,
    displayName?: string | null,
    displayNameEditsRemaining?: number,
    featureFlags?: Record<string, boolean>,
    emailVerified?: boolean,
  ) => void
  setDisplayName: (name: string | null, editsRemaining: number) => void
  setEmailVerified: (verified: boolean) => void
  logout: () => void
  incrementAnalyses: () => void
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      token: null, userId: null, email: null, tier: "free",
      analysesToday: 0, analysisLimit: 5,
      displayName: null, displayNameEditsRemaining: 3,
      featureFlags: {},
      emailVerified: true,
      setAuth: (
        token,
        userId,
        email,
        tier,
        analysesToday,
        analysisLimit,
        displayName,
        displayNameEditsRemaining,
        featureFlags,
        emailVerified,
      ) =>
        set((s) => ({
          token,
          userId,
          email,
          tier,
          analysesToday,
          analysisLimit,
          // Preserve previous values when callers omit the new optional
          // args (signup flow doesn't have them yet on day 1).
          displayName: displayName === undefined ? s.displayName : displayName,
          displayNameEditsRemaining:
            displayNameEditsRemaining === undefined
              ? s.displayNameEditsRemaining
              : displayNameEditsRemaining,
          // featureFlags is purely additive — pre-PR backends won't
          // send the field, so undefined leaves prior state intact.
          featureFlags:
            featureFlags === undefined ? s.featureFlags : featureFlags,
          // Same pattern for emailVerified — undefined means a
          // pre-PR backend response; leave the prior value alone.
          emailVerified:
            emailVerified === undefined ? s.emailVerified : emailVerified,
        })),
      setDisplayName: (name, editsRemaining) =>
        set({ displayName: name, displayNameEditsRemaining: editsRemaining }),
      setEmailVerified: (verified) => set({ emailVerified: verified }),
      logout: () => set({
        token: null, userId: null, email: null, tier: "free",
        // Reset BOTH counter fields on logout. Previously analysisLimit
        // was omitted here, so a user who logged out from a paid tier
        // (limit=999999) left the persisted Zustand state with tier
        // "free" + analysisLimit 999999. Account page header reads
        // `analysisLimit >= 999999 ? "Unlimited"` and rendered
        // "Unlimited analyses" while the nav AnalysisCounter (which
        // derives its limit from TIER_LIMITS[tier]) correctly showed
        // "0/5 analyses today" — a visible contradiction on the
        // anon/Account screen reported 2026-05-17.
        analysesToday: 0, analysisLimit: 5,
        displayName: null, displayNameEditsRemaining: 3,
        featureFlags: {},
        emailVerified: true,
      }),
      incrementAnalyses: () => set((s) => ({ analysesToday: s.analysesToday + 1 })),
    }),
    { name: "yieldiq-auth" }
  )
)
