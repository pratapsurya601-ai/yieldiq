import { describe, it, expect } from "vitest"
import {
  isJwtShape,
  pickSupabaseAccessToken,
} from "@/app/auth/callback/pickSupabaseAccessToken"

// Syntactically valid 3-segment JWT (header.payload.signature). The
// contents are not verified — only the shape matters for the picker.
const JWT =
  "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJzdXBhYmFzZS11c2VyIn0.sig-AAA_BBB"
// Supabase refresh_token and Google provider_token are opaque (not JWTs).
const OPAQUE = "v1.MfA-opaque-refresh-token"

function hashParams(record: Record<string, string>): URLSearchParams {
  return new URLSearchParams(record)
}

describe("isJwtShape (supabase picker)", () => {
  it("accepts 3-segment JWTs", () => {
    expect(isJwtShape(JWT)).toBe(true)
  })
  it("rejects opaque tokens", () => {
    expect(isJwtShape(OPAQUE)).toBe(false)
  })
  it("rejects empty / null", () => {
    expect(isJwtShape(null)).toBe(false)
    expect(isJwtShape("")).toBe(false)
  })
})

describe("pickSupabaseAccessToken", () => {
  it("returns the access_token when it is a valid JWT", () => {
    const p = hashParams({
      access_token: JWT,
      refresh_token: OPAQUE,
      expires_in: "3600",
      token_type: "bearer",
    })
    const out = pickSupabaseAccessToken(p)
    expect(out.accessToken).toBe(JWT)
    expect(out.source).toBe("access_token")
  })

  it("ignores opaque values in access_token (defensive)", () => {
    const p = hashParams({ access_token: OPAQUE })
    const out = pickSupabaseAccessToken(p)
    expect(out.accessToken).toBeNull()
    expect(out.source).toBeNull()
  })

  it("returns null when access_token is absent", () => {
    const p = hashParams({
      refresh_token: OPAQUE,
      expires_in: "3600",
    })
    const out = pickSupabaseAccessToken(p)
    expect(out.accessToken).toBeNull()
  })

  it("returns null on an empty hash", () => {
    const out = pickSupabaseAccessToken(new URLSearchParams(""))
    expect(out.accessToken).toBeNull()
  })

  it("ignores provider_token / provider_id_token — only uses access_token", () => {
    const p = hashParams({
      provider_token: OPAQUE,
      provider_id_token: JWT,
    })
    const out = pickSupabaseAccessToken(p)
    expect(out.accessToken).toBeNull()
  })
})
