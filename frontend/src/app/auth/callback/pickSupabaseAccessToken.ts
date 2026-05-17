/**
 * Pure helper for selecting the Supabase session access_token from the
 * Supabase OAuth callback URL hash.
 *
 * Background: Supabase's URL hash on /auth/callback contains:
 *   - `access_token`   — Supabase's OWN session JWT (3-segment, signed by
 *                        Supabase). This is the one the backend can validate
 *                        via `admin.auth.get_user(jwt)`.
 *   - `refresh_token`  — Supabase refresh token (opaque, not a JWT)
 *   - `expires_in`     — number of seconds the access_token is valid for
 *   - `token_type`     — usually "bearer"
 *   - `provider_token` — Google's OPAQUE OAuth access_token (NOT a JWT)
 *   - `provider_id_token` — Google's id_token JWT, ONLY present if the
 *                           Supabase project has "Skip nonce checks" on
 *
 * We use `access_token` (the Supabase JWT) regardless of the nonce setting.
 * That's the whole point of the refactor — relying on `provider_id_token`
 * was the bug.
 */

const JWT_SHAPE = /^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/

export function isJwtShape(value: string | null | undefined): boolean {
  if (!value) return false
  return JWT_SHAPE.test(value)
}

export interface PickResult {
  /** Supabase session JWT to POST to /api/v1/auth/supabase, or null. */
  accessToken: string | null
  /** Which hash key the token came from (for logging / debugging). */
  source: "access_token" | null
}

/**
 * Pick the Supabase session access_token from a URLSearchParams parsed
 * from the Supabase callback URL hash. Returns null when the value is
 * absent or not a valid 3-segment JWT shape.
 */
export function pickSupabaseAccessToken(params: URLSearchParams): PickResult {
  const accessToken = params.get("access_token")
  if (isJwtShape(accessToken)) {
    return { accessToken, source: "access_token" }
  }
  return { accessToken: null, source: null }
}
