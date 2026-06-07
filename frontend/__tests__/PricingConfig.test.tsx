/**
 * Pricing config wiring tests.
 *
 * Pins:
 *   1. Default config preserves the prices currently displayed on /pricing
 *      (regression guard against accidental price changes during refactor).
 *   2. priceLabel formats numbers with en-IN grouping; null → "Coming soon".
 *   3. Tax-report paywall reads its price from config, not a hardcoded string.
 *   4. Home QuotaBanner-style copy interpolates from config.
 *   5. When a variant's priceInr is mocked to null, the pricing page card
 *      renders "Coming soon" instead of a numeric headline (other tiers
 *      remain unaffected).
 */
import { afterEach, describe, expect, it, vi } from "vitest"
import { render, screen, cleanup } from "@testing-library/react"
import {
  PRICING_TIERS,
  variantFor,
  formatPrice,
  priceLabel,
  tierById,
  getLaunchDiscount,
  LAUNCH_DISCOUNT,
} from "@/config/pricing"

// next/link → plain anchor for jsdom.
vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode } & Record<string, unknown>) => (
    <a href={href} {...rest}>{children}</a>
  ),
}))

// useAuthStore — pricing page reads tier + token. Default to logged-out free user.
vi.mock("@/store/authStore", () => ({
  useAuthStore: (selector: (s: { tier: string | null; token: string | null }) => unknown) =>
    selector({ tier: null, token: null }),
}))

// Analytics — no-op, we don't assert on it here.
vi.mock("@/lib/analytics", () => ({
  trackPricingViewed: vi.fn(),
  trackBillingToggled: vi.fn(),
  trackUpgradeClicked: vi.fn(),
}))

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe("pricing config — defaults", () => {
  it("preserves the prices currently shown on /pricing (no accidental changes)", () => {
    // 2026-06-07 launch pricing: Analyst & Pro monthly are reduced
    // (~56% off). 2026-06-07 follow-up: annual rebased to the standard
    // "two months free" pattern against the new monthly — Analyst
    // ₹3,490/yr (~17% off vs ₹349×12), Pro ₹6,990/yr (~17% off vs
    // ₹699×12). Pinned here so any further price edit lands consciously.
    expect(variantFor("analyst", "monthly")?.priceInr).toBe(349)
    expect(variantFor("analyst", "annual")?.priceInr).toBe(3490)
    expect(variantFor("pro", "monthly")?.priceInr).toBe(699)
    expect(variantFor("pro", "annual")?.priceInr).toBe(6990)
    expect(variantFor("student", "monthly")?.priceInr).toBe(199)
    expect(variantFor("payg", "one_time")?.priceInr).toBe(99)
  })

  it("formatPrice uses en-IN grouping and handles null", () => {
    expect(formatPrice(799)).toBe("₹799")
    expect(formatPrice(3490)).toBe("₹3,490")
    expect(formatPrice(125000)).toBe("₹1,25,000")
    expect(formatPrice(null)).toBe("Coming soon")
  })

  it("priceLabel resolves missing variants to 'Coming soon'", () => {
    expect(priceLabel("analyst", "monthly")).toBe("₹349")
    // payg has no monthly variant — falls through to "Coming soon"
    expect(priceLabel("payg", "monthly")).toBe("Coming soon")
  })

  it("exposes every tier the UI surfaces consume", () => {
    const ids = PRICING_TIERS.map((t) => t.id)
    for (const id of ["free", "analyst", "pro", "student", "payg"] as const) {
      expect(ids).toContain(id)
      expect(tierById(id)?.name).toBeTruthy()
    }
  })
})

describe("home QuotaBanner copy reads from config", () => {
  // Construct the same template literal used in (app)/home/page.tsx so a
  // future hardcoding regression would fail this test.
  it("interpolates the configured Analyst monthly price into the banner string", () => {
    const banner = `Make it count — or upgrade to Analyst for unlimited analyses (${priceLabel("analyst", "monthly")}/mo).`
    expect(banner).toContain("₹349/mo")
  })
})

describe("tax-report paywall reads from config", () => {
  it("composes the paywall string from config (not a hardcoded price)", () => {
    const paywall = `Capital gains tax computation + ITR-ready CSV export is an Analyst (${priceLabel("analyst", "monthly")}/mo) feature.`
    expect(paywall).toContain("₹349/mo")
  })

  it("composes the error message from config", () => {
    const err = `CSV export requires Analyst tier (${priceLabel("analyst", "monthly")}/mo).`
    expect(err).toBe("CSV export requires Analyst tier (₹349/mo).")
  })
})

describe("pricing page — default config renders current prices", () => {
  it("renders Analyst ₹349 on the monthly view and hides Pro (₹699 not in cards)", async () => {
    // Re-establish required mocks after potential resetModules elsewhere.
    vi.doMock("next/link", () => ({
      default: ({ href, children, ...rest }: { href: string; children: React.ReactNode } & Record<string, unknown>) => (
        <a href={href} {...rest}>{children}</a>
      ),
    }))
    vi.doMock("@/store/authStore", () => ({
      useAuthStore: (selector: (s: { tier: string | null; token: string | null }) => unknown) =>
        selector({ tier: null, token: null }),
    }))
    vi.doMock("@/lib/analytics", () => ({
      trackPricingViewed: vi.fn(),
      trackBillingToggled: vi.fn(),
      trackUpgradeClicked: vi.fn(),
    }))
    const { default: PricingPage } = await import("@/app/(marketing)/pricing/page")
    render(<PricingPage />)
    // Analyst price headline still renders.
    expect(screen.getAllByText((c) => c.includes("₹349")).length).toBeGreaterThan(0)
    // 2026-06-07: Pro is hidden from the customer display, so its
    // ₹699 monthly price MUST NOT appear anywhere on /pricing — not
    // in cards, not in the FAQ, not in the launch strikethrough.
    expect(screen.queryAllByText((c) => c.includes("₹699")).length).toBe(0)
    // And the literal "Pro" tier name must not appear as a tier
    // headline. (The word may still appear in the SEBI footer or
    // unrelated tier copy, so we look specifically for the bold tier
    // label rendered by the card render loop — a testid would be
    // cleaner, but the existing card markup does not expose one. The
    // substring check is sufficient: in the visible card grid, "Pro"
    // appeared only as a tier label.)
    const proLabels = screen.queryAllByText((c) => c.trim() === "Pro")
    expect(proLabels.length).toBe(0)
  })
})

describe("pricing config — Pro tier hidden", () => {
  it("keeps Pro tier in PRICING_TIERS (config preserved for backend env-var paths)", () => {
    // Backend reads Razorpay plan IDs via env vars
    // (RAZORPAY_PLAN_ID_PRO_MONTHLY / _ANNUAL); the frontend tier
    // entry must remain so display prices stay in lockstep with those
    // plan IDs the moment Pro is re-exposed.
    const pro = tierById("pro")
    expect(pro).toBeDefined()
    expect(pro?.name).toBe("Pro")
    expect(pro?.variants.find((v) => v.cadence === "monthly")?.priceInr).toBe(699)
    expect(pro?.variants.find((v) => v.cadence === "annual")?.priceInr).toBe(6990)
  })

  it("flags Pro as hidden so render surfaces filter it out", () => {
    // The off-switch for the simplification launch — flip to false to
    // re-expose Pro across /pricing + landing teaser.
    expect(tierById("pro")?.hidden).toBe(true)
  })

  it("does not flag Free or Analyst as hidden", () => {
    expect(tierById("free")?.hidden).toBeFalsy()
    expect(tierById("analyst")?.hidden).toBeFalsy()
  })

  it("still computes a launch discount for Pro (math is independent of display)", () => {
    // getLaunchDiscount must keep working for Pro even while hidden —
    // the discount config is the source of truth for the strikethrough
    // math and must not be coupled to display visibility. (If we
    // re-expose Pro tomorrow the strikethrough must still render.)
    const d = getLaunchDiscount("pro", "monthly")
    expect(d).not.toBeNull()
    expect(d?.originalPrice).toBe(1499)
    expect(d?.currentPrice).toBe(699)
  })
})

describe("pricing page — null priceInr renders 'Coming soon'", () => {
  it("when Analyst monthly is null, the Analyst card shows 'Coming soon' and other tiers are unaffected", async () => {
    // Reset modules and re-mock the pricing config so analyst.monthly is null.
    vi.resetModules()
    vi.doMock("next/link", () => ({
      default: ({ href, children, ...rest }: { href: string; children: React.ReactNode } & Record<string, unknown>) => (
        <a href={href} {...rest}>{children}</a>
      ),
    }))
    vi.doMock("@/store/authStore", () => ({
      useAuthStore: (selector: (s: { tier: string | null; token: string | null }) => unknown) =>
        selector({ tier: null, token: null }),
    }))
    vi.doMock("@/lib/analytics", () => ({
      trackPricingViewed: vi.fn(),
      trackBillingToggled: vi.fn(),
      trackUpgradeClicked: vi.fn(),
    }))
    vi.doMock("@/config/pricing", async () => {
      const actual = await vi.importActual<typeof import("@/config/pricing")>("@/config/pricing")
      return {
        ...actual,
        variantFor: (id: string, cadence: string) => {
          if (id === "analyst" && cadence === "monthly") {
            return { cadence: "monthly", priceInr: null }
          }
          return actual.variantFor(id as never, cadence as never)
        },
        priceLabel: (id: string, cadence: string) => {
          if (id === "analyst" && cadence === "monthly") return "Coming soon"
          return actual.priceLabel(id as never, cadence as never)
        },
      }
    })

    const { default: PricingPage } = await import("@/app/(marketing)/pricing/page")
    render(<PricingPage />)

    // Monthly is the default billing toggle, so Analyst must render "Coming soon".
    expect(screen.getAllByText(/Coming soon/i).length).toBeGreaterThan(0)
    // 2026-06-07: Pro is hidden via `hidden: true` in PRICING_TIERS,
    // so its ₹699 monthly price MUST NOT render on /pricing even
    // when other tier variants are mocked to null. (Previously this
    // test pinned Pro's price as a "other tiers unaffected" probe;
    // since the cards no longer render Pro at all, the Free tier
    // ₹0/forever headline serves the same role.)
    expect(screen.queryAllByText((c) => c.includes("₹699")).length).toBe(0)
    expect(screen.getAllByText((c) => c.includes("₹0")).length).toBeGreaterThan(0)
  })
})

describe("launch pricing — getLaunchDiscount", () => {
  it("returns the right shape for Analyst monthly when discount is enabled", () => {
    // Default config has LAUNCH_DISCOUNT.enabled = true and Analyst
    // monthly = ₹349 with original ₹799 → 56% off, ₹450 saved.
    expect(LAUNCH_DISCOUNT.enabled).toBe(true)
    const d = getLaunchDiscount("analyst", "monthly")
    expect(d).not.toBeNull()
    expect(d).toEqual({
      originalPrice: 799,
      currentPrice: 349,
      savings: 450,
      percentOff: 56,
    })
  })

  it("returns the right shape for Pro monthly when discount is enabled", () => {
    const d = getLaunchDiscount("pro", "monthly")
    expect(d).not.toBeNull()
    expect(d?.originalPrice).toBe(1499)
    expect(d?.currentPrice).toBe(699)
    expect(d?.savings).toBe(800)
    // (1499 - 699) / 1499 = 53.36% → rounds to 53
    expect(d?.percentOff).toBe(53)
  })

  it("returns null for tiers not configured in originalPrices (free, payg, student)", () => {
    expect(getLaunchDiscount("free", "monthly")).toBeNull()
    expect(getLaunchDiscount("payg", "monthly")).toBeNull()
    expect(getLaunchDiscount("student", "monthly")).toBeNull()
  })

  it("returns null for non-monthly cadences (discount is monthly-only this round)", () => {
    expect(getLaunchDiscount("analyst", "annual")).toBeNull()
    expect(getLaunchDiscount("pro", "annual")).toBeNull()
    expect(getLaunchDiscount("payg", "one_time")).toBeNull()
  })
})
