import { describe, it, expect } from "vitest"
import {
  isJwtShape,
  pickGoogleIdToken,
} from "@/app/auth/callback/pickGoogleIdToken"

// A syntactically valid 3-segment JWT (header.payload.signature). The
// contents are not verified — only the shape matters for the picker.
const JWT_A =
  "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJhYWEifQ.sig-a_AAA"
const JWT_B =
  "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJiYmIifQ.sig-b_BBB"
// Google's OAuth access_token is opaque (ya29.…), not a JWT.
const OPAQUE = "ya29.a0AfH6SMABCdefGhiJklMnoPqrStuVwxYz"

function hashParams(record: Record<string, string>): URLSearchParams {
  return new URLSearchParams(record)
}

describe("isJwtShape", () => {
  it("accepts 3-segment JWTs", () => {
    expect(isJwtShape(JWT_A)).toBe(true)
  })

  it("rejects opaque Google access tokens", () => {
    expect(isJwtShape(OPAQUE)).toBe(false)
  })

  it("rejects empty / null", () => {
    expect(isJwtShape(null)).toBe(false)
    expect(isJwtShape("")).toBe(false)
  })
})

describe("pickGoogleIdToken", () => {
  it("prefers provider_id_token when all 3 keys are present", () => {
    const p = hashParams({
      provider_token: OPAQUE,
      provider_id_token: JWT_A,
      id_token: JWT_B,
    })
    const out = pickGoogleIdToken(p)
    expect(out.idToken).toBe(JWT_A)
    expect(out.source).toBe("provider_id_token")
    expect(out.fellBack).toBe(false)
  })

  it("falls back to id_token (when it is a valid JWT) and flags it", () => {
    const p = hashParams({ id_token: JWT_B })
    const out = pickGoogleIdToken(p)
    expect(out.idToken).toBe(JWT_B)
    expect(out.source).toBe("id_token")
    expect(out.fellBack).toBe(true)
  })

  it("refuses opaque provider_token — returns null", () => {
    const p = hashParams({ provider_token: OPAQUE })
    const out = pickGoogleIdToken(p)
    expect(out.idToken).toBeNull()
    expect(out.source).toBeNull()
    expect(out.fellBack).toBe(false)
  })

  it("refuses non-JWT id_token", () => {
    const p = hashParams({ id_token: "not-a-jwt" })
    const out = pickGoogleIdToken(p)
    expect(out.idToken).toBeNull()
    expect(out.source).toBeNull()
  })

  it("returns null when no recognized keys are present", () => {
    const p = hashParams({ access_token: "abc", expires_in: "3600" })
    const out = pickGoogleIdToken(p)
    expect(out.idToken).toBeNull()
    expect(out.source).toBeNull()
    expect(out.fellBack).toBe(false)
  })

  it("returns null on an empty hash", () => {
    const out = pickGoogleIdToken(new URLSearchParams(""))
    expect(out.idToken).toBeNull()
  })
})
