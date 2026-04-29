import { Redirect } from 'expo-router';
import { useAuthStore } from '@/store/authStore';

/**
 * Root route: punt to (app) if a token is hydrated, else login.
 * Note: zustand-persist hydration is async; on cold start we may briefly
 * see token=null and redirect to login. Acceptable for MVP — Phase 2 can
 * add a splash gate that waits for `useAuthStore.persist.hasHydrated()`.
 */
export default function Index() {
  const token = useAuthStore((s) => s.token);
  if (token) return <Redirect href="/(app)/home" />;
  return <Redirect href="/(auth)/login" />;
}
