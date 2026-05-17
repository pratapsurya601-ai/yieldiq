/**
 * Pure helper for selecting the Google ID token from the Supabase OAuth
 * callback URL hash.
 *
 * Background: Supabase's URL hash returns several token-shaped values:
 *   - `provider_token`     — Google's OPAQUE OAuth access_token (NOT a JWT).
 *                            Cannot be verified by Google's tokeninfo endpoint.
 *   - `provider_id_token`  — Google's id_token JWT. This is what the backend
 *                            needs to call tokeninfo / verify.
 *   - `id_token`           — Supabase's own session id_token JWT. Acceptable
 *                            ONLY as a fallback and only when it is a real
 *                            3-segment JWT.
 *
 * We MUST prefer `provider_id_token` and we MUST refuse to send opaque tokens
 * to the backend, otherwise Google rejects the exchange with HTTP 400 and the
 * user sees "Google rejected the sign-in token."
 */

const JWT_SHAPE = /^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/

export function isJwtShape(value: string | null | undefined): boolean {
  if (!value) return false
  return JWT_SHAPE.test(value)
}

export interface PickResult {
  /** The Google id_token to POST to the backend, or null when none usable. */
  idToken: string | null
  /** Which hash key the token came from (for logging / debugging). */
  source: "provider_id_token" | "id_token" | null
  /**
   * True when we fell back from the preferred `provider_id_token` to
   * Supabase's own `id_token`. Caller should console.warn in this case.
   */
  fellBack: boolean
}

/**
 * Pick the best Google ID token from a URLSearchParams parsed from the
 * Supabase callback URL hash. NEVER returns `provider_token` (opaque).
 */
export function pickGoogleIdToken(params: URLSearchParams): PickResult {
  const providerIdToken = params.get("provider_id_token")
  if (isJwtShape(providerIdToken)) {
    return { idToken: providerIdToken, source: "provider_id_token", fellBack: false }
  }

  const idToken = params.get("id_token")
  if (isJwtShape(idToken)) {
    return { idToken, source: "id_token", fellBack: true }
  }

  return { idToken: null, source: null, fellBack: false }
}
