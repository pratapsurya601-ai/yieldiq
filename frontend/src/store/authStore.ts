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
  setAuth: (token: string, userId: string, email: string, tier: Tier, analysesToday: number, analysisLimit: number) => void
  logout: () => void
  incrementAnalyses: () => void
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      token: null, userId: null, email: null, tier: "free",
      analysesToday: 0, analysisLimit: 5,
      setAuth: (token, userId, email, tier, analysesToday, analysisLimit) =>
        set({ token, userId, email, tier, analysesToday, analysisLimit }),
      logout: () => set({ token: null, userId: null, email: null, tier: "free", analysesToday: 0 }),
      incrementAnalyses: () => set((s) => ({ analysesToday: s.analysesToday + 1 })),
    }),
    { name: "yieldiq-auth" }
  )
)
