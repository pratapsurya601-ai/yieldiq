/**
 * Mobile auth store — mirrors frontend/src/store/authStore.ts.
 *
 * Persistence: zustand/middleware persist with expo-secure-store as the
 * storage adapter. The bearer token is ALSO mirrored into SecureStore by
 * src/lib/api.ts so apiFetch() can read it from a single source without
 * round-tripping through React state.
 */

import { create } from 'zustand';
import { persist, createJSONStorage, type StateStorage } from 'zustand/middleware';
import * as SecureStore from 'expo-secure-store';

export type Tier = 'free' | 'pro' | 'enterprise';

interface AuthState {
  token: string | null;
  userId: string | null;
  email: string | null;
  tier: Tier;
  analysesToday: number;
  analysisLimit: number;
  displayName: string | null;
  displayNameEditsRemaining: number;
  featureFlags: Record<string, boolean>;
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
  ) => void;
  logout: () => void;
}

const secureStorage: StateStorage = {
  getItem: (name) => SecureStore.getItemAsync(name).then((v) => v ?? null),
  setItem: (name, value) => SecureStore.setItemAsync(name, value),
  removeItem: (name) => SecureStore.deleteItemAsync(name),
};

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      token: null,
      userId: null,
      email: null,
      tier: 'free',
      analysesToday: 0,
      analysisLimit: 5,
      displayName: null,
      displayNameEditsRemaining: 3,
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
          displayName: displayName === undefined ? s.displayName : displayName,
          displayNameEditsRemaining:
            displayNameEditsRemaining === undefined
              ? s.displayNameEditsRemaining
              : displayNameEditsRemaining,
          featureFlags: featureFlags === undefined ? s.featureFlags : featureFlags,
        })),
      logout: () =>
        set({
          token: null,
          userId: null,
          email: null,
          tier: 'free',
          analysesToday: 0,
          displayName: null,
          displayNameEditsRemaining: 3,
          featureFlags: {},
        }),
    }),
    {
      name: 'yieldiq-auth',
      storage: createJSONStorage(() => secureStorage),
      // Don't persist transient counters — they're refreshed from server
      // headers on every request anyway (see src/lib/api.ts).
      partialize: (s) => ({
        token: s.token,
        userId: s.userId,
        email: s.email,
        tier: s.tier,
        displayName: s.displayName,
        featureFlags: s.featureFlags,
      }),
    },
  ),
);
