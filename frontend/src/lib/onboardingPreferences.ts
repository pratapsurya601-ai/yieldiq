// Onboarding preferences — localStorage is the source of truth.
// If a future backend endpoint exists for user preferences, we POST to it
// best-effort and swallow errors (see persistPreferencesRemote).

import api from "@/lib/api"

export type InterestKey = "value" | "quality" | "growth" | "income"

export interface OnboardingPreferences {
  interests: InterestKey[]
  firstStock?: string | null
  completed: boolean
  completedAt?: string | null
}

const STORAGE_KEY = "yieldiq_prefs"

const EMPTY: OnboardingPreferences = {
  interests: [],
  firstStock: null,
  completed: false,
  completedAt: null,
}

export function readPreferences(): OnboardingPreferences {
  if (typeof window === "undefined") return EMPTY
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) return EMPTY
    const parsed = JSON.parse(raw) as Partial<OnboardingPreferences>
    return {
      interests: Array.isArray(parsed.interests)
        ? parsed.interests.filter((k): k is InterestKey =>
            ["value", "quality", "growth", "income"].includes(k as string),
          )
        : [],
      firstStock: typeof parsed.firstStock === "string" ? parsed.firstStock : null,
      completed: parsed.completed === true,
      completedAt: typeof parsed.completedAt === "string" ? parsed.completedAt : null,
    }
  } catch {
    return EMPTY
  }
}

export function writePreferences(patch: Partial<OnboardingPreferences>): OnboardingPreferences {
  const current = readPreferences()
  const next: OnboardingPreferences = { ...current, ...patch }
  try {
    if (typeof window !== "undefined") {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next))
    }
  } catch {
    // storage quota / disabled — ignore, localStorage is soft
  }
  // Fire-and-forget backend sync (endpoint may not exist — we swallow errors).
  void persistPreferencesRemote(next)
  return next
}

export function markCompleted(patch: Partial<OnboardingPreferences> = {}): OnboardingPreferences {
  return writePreferences({
    ...patch,
    completed: true,
    completedAt: new Date().toISOString(),
  })
}

export function isOnboardingComplete(): boolean {
  return readPreferences().completed === true
}

async function persistPreferencesRemote(prefs: OnboardingPreferences): Promise<void> {
  // No backend preferences endpoint exists today. If one is added later
  // (e.g. POST /api/v1/users/me/preferences), this will silently succeed.
  try {
    await api.post("/api/v1/users/me/preferences", prefs, { timeout: 3000 })
  } catch {
    // Expected today — localStorage is the source of truth.
  }
}
