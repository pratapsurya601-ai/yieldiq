import { describe, it, expect } from "vitest"
import {
  tokenFingerprint,
  isLocalHost,
  cookieDomainForHost,
} from "@/app/auth/callback/oauthCallbackHelpers"

const JWT =
  "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJzdXBhYmFzZS11c2VyIn0.sig-AAA_BBB_unique_signature_segment_here"
const JWT_DIFFERENT_SIG =
  "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJzdXBhYmFzZS11c2VyIn0.sig-ZZZ_QQQ_completely_different_signature"

describe("tokenFingerprint", () => {
  it("returns a stable fingerprint for the same JWT", () => {
    expect(tokenFingerprint(JWT)).toBe(tokenFingerprint(JWT))
  })

  it("differs for different signatures (so a new sign-in is not deduped)", () => {
    expect(tokenFingerprint(JWT)).not.toBe(tokenFingerprint(JWT_DIFFERENT_SIG))
  })

  it("handles non-JWT-shaped strings without throwing", () => {
    const fp = tokenFingerprint("opaque-token-xxx")
    expect(fp).toMatch(/^raw:/)
  })

  it("returns empty string for empty input", () => {
    expect(tokenFingerprint("")).toBe("")
  })

  it("uses the signature segment, not the payload (so payload changes don't matter)", () => {
    const a = "h.payloadA.sig-same"
    const b = "h.payloadB.sig-same"
    expect(tokenFingerprint(a)).toBe(tokenFingerprint(b))
  })
})

describe("isLocalHost", () => {
  it("treats localhost / 127.0.0.1 / ::1 as local", () => {
    expect(isLocalHost("localhost")).toBe(true)
    expect(isLocalHost("127.0.0.1")).toBe(true)
    expect(isLocalHost("::1")).toBe(true)
    expect(isLocalHost("0.0.0.0")).toBe(true)
  })

  it("treats *.localhost as local (browser convention)", () => {
    expect(isLocalHost("app.localhost")).toBe(true)
  })

  it("treats production hosts as non-local", () => {
    expect(isLocalHost("yieldiq.in")).toBe(false)
    expect(isLocalHost("www.yieldiq.in")).toBe(false)
  })

  it("empty hostname is treated as local (defensive)", () => {
    expect(isLocalHost("")).toBe(true)
  })
})

describe("cookieDomainForHost", () => {
  it("returns .yieldiq.in for the apex domain", () => {
    expect(cookieDomainForHost("yieldiq.in")).toBe(".yieldiq.in")
  })

  it("returns .yieldiq.in for www.yieldiq.in (the bug we are fixing)", () => {
    expect(cookieDomainForHost("www.yieldiq.in")).toBe(".yieldiq.in")
  })

  it("returns .yieldiq.in for deeper subdomains", () => {
    expect(cookieDomainForHost("app.staging.yieldiq.in")).toBe(".yieldiq.in")
  })

  it("returns null for localhost (host-only cookie)", () => {
    expect(cookieDomainForHost("localhost")).toBeNull()
    expect(cookieDomainForHost("127.0.0.1")).toBeNull()
  })

  it("returns null for unrelated hosts (don't accidentally widen scope)", () => {
    expect(cookieDomainForHost("some-preview.vercel.app")).toBeNull()
    expect(cookieDomainForHost("evil.example.com")).toBeNull()
  })

  it("is case-insensitive", () => {
    expect(cookieDomainForHost("WWW.YIELDIQ.IN")).toBe(".yieldiq.in")
  })

  it("returns null for empty hostname", () => {
    expect(cookieDomainForHost("")).toBeNull()
  })

  it("returns null for raw IP literals", () => {
    expect(cookieDomainForHost("203.0.113.1")).toBeNull()
  })
})
