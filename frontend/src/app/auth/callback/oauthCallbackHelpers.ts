/**
 * Pure helpers for the OAuth callback page.
 *
 * Extracted so the cookie-domain and idempotency logic can be unit-tested
 * without spinning up a jsdom router + auth store harness.
 */

/**
 * Stable, short fingerprint of a Supabase access_token. We don't need
 * a cryptographic hash here — just something unique enough to dedupe
 * a remount within a single browser session. Uses the JWT's signature
 * segment when the token is shaped like a JWT, otherwise a length-tagged
 * prefix.
 */
export function tokenFingerprint(token: string): string {
  if (!token) return ""
  const parts = token.split(".")
  if (parts.length === 3) {
    // Use the signature segment — opaque to us but stable per token.
    return `jwt:${parts[2].slice(0, 32)}`
  }
  return `raw:${token.length}:${token.slice(0, 16)}`
}

/**
 * Return true for localhost-ish hosts where we deliberately skip setting
 * an explicit cookie domain (browsers reject `.localhost`, and a host-only
 * cookie is the right thing anyway).
 */
export function isLocalHost(hostname: string): boolean {
  if (!hostname) return true
  const h = hostname.toLowerCase()
  if (h === "localhost" || h === "127.0.0.1" || h === "::1" || h === "0.0.0.0") return true
  if (h.endsWith(".localhost")) return true
  return false
}

/**
 * Compute the cookie `domain` attribute for a hostname so the auth cookie
 * survives an apex ↔ www bounce.
 *
 *   yieldiq.in            → .yieldiq.in
 *   www.yieldiq.in        → .yieldiq.in
 *   app.staging.yieldiq.in→ .yieldiq.in
 *   localhost             → null    (host-only)
 *   127.0.0.1             → null    (host-only)
 *   some-preview.vercel.app → null  (don't widen — keep host-only)
 *
 * Returns null when no explicit domain attribute applies.
 */
export function cookieDomainForHost(hostname: string): string | null {
  if (!hostname) return null
  if (isLocalHost(hostname)) return null

  const h = hostname.toLowerCase().replace(/\.$/, "")

  // IP literal — host-only cookie.
  if (/^\d{1,3}(?:\.\d{1,3}){3}$/.test(h)) return null

  // Match the yieldiq.in family explicitly. We don't want to attach to
  // preview deploys on vercel.app or other unrelated hosts.
  if (h === "yieldiq.in" || h.endsWith(".yieldiq.in")) {
    return ".yieldiq.in"
  }

  return null
}
