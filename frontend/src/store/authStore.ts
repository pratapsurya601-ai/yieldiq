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
  ) => void
  setDisplayName: (name: string | null, editsRemaining: number) => void
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
        })),
      setDisplayName: (name, editsRemaining) =>
        set({ displayName: name, displayNameEditsRemaining: editsRemaining }),
      logout: () => set({
        token: null, userId: null, email: null, tier: "free",
        analysesToday: 0,
        displayName: null, displayNameEditsRemaining: 3,
        featureFlags: {},
      }),
      incrementAnalyses: () => set((s) => ({ analysesToday: s.analysesToday + 1 })),
    }),
    { name: "yieldiq-auth" }
  )
)
