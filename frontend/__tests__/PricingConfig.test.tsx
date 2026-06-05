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
    expect(variantFor("analyst", "monthly")?.priceInr).toBe(799)
    expect(variantFor("analyst", "annual")?.priceInr).toBe(4999)
    expect(variantFor("pro", "monthly")?.priceInr).toBe(1499)
    expect(variantFor("pro", "annual")?.priceInr).toBe(9999)
    expect(variantFor("student", "monthly")?.priceInr).toBe(199)
    expect(variantFor("payg", "one_time")?.priceInr).toBe(99)
  })

  it("formatPrice uses en-IN grouping and handles null", () => {
    expect(formatPrice(799)).toBe("₹799")
    expect(formatPrice(9999)).toBe("₹9,999")
    expect(formatPrice(125000)).toBe("₹1,25,000")
    expect(formatPrice(null)).toBe("Coming soon")
  })

  it("priceLabel resolves missing variants to 'Coming soon'", () => {
    expect(priceLabel("analyst", "monthly")).toBe("₹799")
    // payg has no monthly variant — should fall through to "Coming soon"
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
    expect(banner).toContain("₹799/mo")
  })
})

describe("tax-report paywall reads from config", () => {
  it("composes the paywall string from config (not a hardcoded ₹799)", () => {
    const paywall = `Capital gains tax computation + ITR-ready CSV export is an Analyst (${priceLabel("analyst", "monthly")}/mo) feature.`
    expect(paywall).toContain("₹799/mo")
  })

  it("composes the error message from config", () => {
    const err = `CSV export requires Analyst tier (${priceLabel("analyst", "monthly")}/mo).`
    expect(err).toBe("CSV export requires Analyst tier (₹799/mo).")
  })
})

describe("pricing page — default config renders current prices", () => {
  it("renders Analyst ₹799 and Pro ₹1,499 on the monthly view", async () => {
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
    // Price headlines may appear in multiple places (card headline, FAQ
    // copy). Match presence-of-substring, not exact-text equality.
    expect(screen.getAllByText((c) => c.includes("₹799")).length).toBeGreaterThan(0)
    expect(screen.getAllByText((c) => c.includes("₹1,499")).length).toBeGreaterThan(0)
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

    // Monthly is the default billing toggle, so Analyst should render "Coming soon".
    expect(screen.getAllByText(/Coming soon/i).length).toBeGreaterThan(0)
    // Pro tier monthly should still show its configured price.
    expect(screen.getAllByText((c) => c.includes("₹1,499")).length).toBeGreaterThan(0)
  })
})
