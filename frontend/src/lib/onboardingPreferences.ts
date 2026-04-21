// Onboarding preferences
// ─────────────────────────────────────────────────────────────────
// localStorage is the FAST-PATH cache (instant render, prevents
// flash-of-wizard). Backend (/api/v1/auth/complete-onboarding, backed
// by Supabase user_onboarding) is the cross-device source of truth
// for the `completed` flag. Interests/firstStock stay local-only for
// now — the server endpoint accepts them but doesn't persist them yet
// (ready for a future sync without another frontend change).
//
// Previously we POSTed EVERY writePreferences call to a nonexistent
// /api/v1/users/me/preferences endpoint which silently 404'd. That's
// fixed by (a) changing the endpoint and (b) only firing the network
// call when completed=true, which is the only state we persist.

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
  // Only sync to backend when onboarding is actually completed — the
  // user_onboarding table only cares about the terminal completed=true
  // event. Writes during intermediate steps (interest selection, first
  // stock pick) stay local.
  if (next.completed === true) {
    void persistPreferencesRemote(next)
  }
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
  // POST to the completion endpoint. Only call this when prefs.completed is
  // true — the caller (writePreferences / markCompleted) enforces that.
  try {
    await api.post(
      "/api/v1/auth/complete-onboarding",
      {
        last_step: 3,
        interests: prefs.interests,
        firstStock: prefs.firstStock ?? null,
      },
      { timeout: 4000 },
    )
  } catch {
    // Soft-fail — localStorage already holds the completion flag, and
    // the login-time getOnboardingStatus() check will resolve any drift
    // by re-POSTing from resolveOnboardingDone() when it sees localStorage
    // says completed but backend says not completed.
  }
}
