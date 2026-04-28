"use client"

/**
 * CookieAuthSync — keeps the `yieldiq_token` cookie in sync with the
 * Zustand auth store.
 *
 * Why this exists (CRITICAL bug, paid users locked out of /analysis):
 *
 *   - On login we set the cookie with `Cookies.set("yieldiq_token", token,
 *     { expires: 7 })`. After 7 days the browser drops the cookie even if
 *     the user has been actively using the app the whole time.
 *
 *   - The Zustand auth store, however, is persisted to localStorage with
 *     no expiry, so client-only surfaces (`/account`, the nav bell, the
 *     auth-store-driven counter) keep "looking" logged in.
 *
 *   - The `/analysis/[ticker]` route is a Server Component that branches
 *     on the SSR-readable cookie. Once the cookie expires, the page
 *     server-renders the anonymous `PublicAnalysis` template — paying
 *     ANALYST users see the signup wall instead of the product they paid
 *     for.
 *
 * Fix:
 *
 *   1. On every mount (root layout), if Zustand has a token but the
 *      cookie is missing (or about to expire), re-issue the cookie from
 *      the in-memory token. This rescues already-affected users on their
 *      next page load.
 *
 *   2. Subscribe to authStore changes so logout / login updates flow
 *      through to the cookie immediately, in both directions.
 *
 *   3. Use a sliding 30-day expiry. Active users effectively never have
 *      the cookie disappear out from under them again.
 *
 * Renders nothing.
 */

import { useEffect } from "react"
import Cookies from "js-cookie"
import { useAuthStore } from "@/store/authStore"

const COOKIE_NAME = "yieldiq_token"
const COOKIE_EXPIRY_DAYS = 30

export default function CookieAuthSync() {
  // Subscribe to token changes. On any mutation (login, logout, manual
  // setAuth from other code paths), re-sync the cookie to match.
  const token = useAuthStore((s) => s.token)

  useEffect(() => {
    const existing = Cookies.get(COOKIE_NAME)
    if (token) {
      // Refresh the cookie whenever Zustand has a token, regardless of
      // whether it already exists, so the sliding expiry actually slides.
      // Skip only if the cookie is identical AND we just set it this
      // session — but Cookies.set is idempotent and cheap, so always
      // write.
      Cookies.set(COOKIE_NAME, token, {
        expires: COOKIE_EXPIRY_DAYS,
        sameSite: "lax",
        // `secure` is auto-omitted on http://localhost so dev still
        // works. In production the page is served over HTTPS and the
        // browser keeps the cookie unless explicitly cleared.
        secure: typeof window !== "undefined" && window.location.protocol === "https:",
      })
    } else if (existing) {
      // Authoritative logout via the store should also clear the cookie.
      // (The login page already calls Cookies.remove on logout, but we
      // want a single source of truth.)
      Cookies.remove(COOKIE_NAME)
    }
  }, [token])

  return null
}
