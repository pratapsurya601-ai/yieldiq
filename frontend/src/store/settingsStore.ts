import { create } from "zustand"
import { persist } from "zustand/middleware"

interface SettingsState {
  learnMode: boolean
  proMode: boolean
  investorType: "beginner" | "intermediate" | "advanced" | null
  onboardingComplete: boolean
  toggleLearnMode: () => void
  toggleProMode: () => void
  setInvestorType: (type: "beginner" | "intermediate" | "advanced") => void
  completeOnboarding: () => void
}

export const useSettingsStore = create<SettingsState>()(
  persist(
    (set) => ({
      learnMode: true, proMode: false, investorType: null, onboardingComplete: false,
      toggleLearnMode: () => set((s) => ({ learnMode: !s.learnMode })),
      toggleProMode: () => set((s) => ({ proMode: !s.proMode })),
      setInvestorType: (type) => set({ investorType: type }),
      completeOnboarding: () => set({ onboardingComplete: true }),
    }),
    { name: "yieldiq-settings" }
  )
)
