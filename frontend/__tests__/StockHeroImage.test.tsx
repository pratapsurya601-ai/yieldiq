/**
 * StockHeroImage — contextual-sector hero rendering tests.
 *
 * Pins the post-redesign (AlphaSpread-style) invariants:
 *   - Hero background is a /hero-sectors/{slug}.webp photo, NEVER a
 *     stretched company logo or marquee /hero/{TICKER}.jpg
 *   - The bottom glass panel renders price + market cap
 *   - The identity row sits BELOW the hero (not inside it) and carries
 *     the small TickerAvatar chip + company name + EXCHANGE:TICKER +
 *     WatchlistButton
 *   - Unknown sector → default.webp fallback
 *   - Every sector slug exposed by sectorToHeroImagePath has a real
 *     on-disk asset (asset-existence guard)
 */
import { describe, it, expect, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import { existsSync } from "node:fs"
import path from "node:path"

import StockHeroImage from "@/components/analysis/StockHeroImage"
import {
  HERO_SECTOR_SLUGS,
  sectorToHeroImagePath,
} from "@/lib/sectorHeroImage"

// WatchlistButton hits /api/v1/watchlist/check on mount via axios and
// reads the auth store — neither matters for layout assertions, so we
// stub both. The shape returned ({} default export) matches both the
// `import api from "@/lib/api"` default-export and the named hook
// shape `useAuthStore` consumes.
vi.mock("@/lib/api", () => ({
  default: {
    get: vi.fn().mockResolvedValue({ data: { in_watchlist: false } }),
    post: vi.fn().mockResolvedValue({ data: {} }),
    delete: vi.fn().mockResolvedValue({ data: {} }),
  },
}))
vi.mock("@/store/authStore", () => ({
  useAuthStore: (selector: (s: { token: string | null }) => unknown) =>
    selector({ token: null }),
}))
// WatchlistButton calls `useRouter()` from next/navigation, which throws
// without an AppRouter context. Stub the hooks it actually reads.
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn() }),
  usePathname: () => "/analysis/HDFCBANK",
  useSearchParams: () => new URLSearchParams(),
}))

const BASE = {
  ticker: "HDFCBANK.NS",
  displayTicker: "HDFCBANK",
  companyName: "HDFC Bank Ltd",
  currentPrice: 1700.5,
  currency: "INR",
  marginOfSafetyPct: 43.7,
  verdict: "undervalued",
  marketCapCr: 1_300_000,
  exchange: "NSE",
}

describe("StockHeroImage — contextual-sector hero", () => {
  it("renders the banking sector photo for HDFCBANK", () => {
    render(<StockHeroImage {...BASE} sector="Private Bank" />)
    const photo = screen.getByTestId("stock-hero-photo")
    expect(photo.getAttribute("src")).toBe("/hero-sectors/banking.webp")
    expect(photo.getAttribute("data-sector-slug")).toBe("banking")
  })

  it("renders the fmcg sector photo for ITC", () => {
    render(
      <StockHeroImage
        {...BASE}
        ticker="ITC.NS"
        displayTicker="ITC"
        companyName="ITC Ltd"
        sector="FMCG - Tobacco"
      />,
    )
    const photo = screen.getByTestId("stock-hero-photo")
    expect(photo.getAttribute("src")).toBe("/hero-sectors/fmcg.webp")
  })

  it("falls back to default.webp for an unknown sector", () => {
    render(
      <StockHeroImage
        {...BASE}
        ticker="UNKNOWN.NS"
        displayTicker="UNKNOWN"
        companyName="Unknown Co"
        sector="Some Brand New Sector"
      />,
    )
    const photo = screen.getByTestId("stock-hero-photo")
    expect(photo.getAttribute("src")).toBe("/hero-sectors/default.webp")
  })

  it("never renders a stretched company logo or marquee /hero/ jpeg as the hero background", () => {
    render(<StockHeroImage {...BASE} sector="Private Bank" />)
    const allImgs = Array.from(
      screen.getByTestId("stock-hero-section").querySelectorAll("img"),
    )
    for (const img of allImgs) {
      const src = img.getAttribute("src") || ""
      expect(src).not.toMatch(/^\/hero\//) // retired marquee path
      expect(src).not.toMatch(/wikipedia/i)
      expect(src).not.toMatch(/company-image/) // retired backend endpoint
    }
  })

  it("renders the glass panel with price + market cap", () => {
    render(<StockHeroImage {...BASE} sector="Private Bank" />)
    const panel = screen.getByTestId("hero-glass-panel")
    expect(panel.textContent || "").toMatch(/Market Cap/)
    // formatMarketCap renders >=100,000 Cr as "₹X.XX Lakh Cr"
    expect(panel.textContent || "").toMatch(/Lakh Cr/)
  })

  it("renders the identity row BELOW the hero with TickerAvatar + watchlist button", () => {
    render(<StockHeroImage {...BASE} sector="Private Bank" />)
    const heroSection = screen.getByTestId("stock-hero-section")
    const identityRow = screen.getByTestId("hero-identity-row")
    // Identity row is a sibling AFTER the hero in DOM order — not a
    // descendant. compareDocumentPosition returns the FOLLOWING bit
    // (0x04) when `identityRow` comes after `heroSection`.
    const rel = heroSection.compareDocumentPosition(identityRow)
    expect(rel & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(heroSection.contains(identityRow)).toBe(false)
    // Identity row carries name + EXCHANGE:TICKER + a watchlist button
    expect(identityRow.textContent || "").toContain("HDFC Bank Ltd")
    expect(identityRow.textContent || "").toContain("NSE:HDFCBANK")
  })

  it("renders the verdict pill in the top-right of the hero", () => {
    render(<StockHeroImage {...BASE} sector="Private Bank" />)
    const pill = screen.getByTestId("hero-verdict-pill")
    expect(pill.textContent || "").toMatch(/undervalued/i)
  })
})

describe("sectorToHeroImagePath — asset-existence guard", () => {
  const publicDir = path.resolve(__dirname, "../public/hero-sectors")

  it.each(HERO_SECTOR_SLUGS)(
    "ships a real WebP asset for the %s slug",
    (slug) => {
      expect(existsSync(path.join(publicDir, `${slug}.webp`))).toBe(true)
    },
  )

  it("resolves a missing/null sector to the default photo", () => {
    expect(sectorToHeroImagePath(null)).toBe("/hero-sectors/default.webp")
    expect(sectorToHeroImagePath(undefined)).toBe("/hero-sectors/default.webp")
    expect(sectorToHeroImagePath("")).toBe("/hero-sectors/default.webp")
  })
})
