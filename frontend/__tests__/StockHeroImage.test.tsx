/**
 * StockHeroImage — dark identity band rendering tests
 * (feat/alphaspread-style-opening).
 *
 * Pins the post-restyle invariants:
 *   - The band keeps the sector photo as a dim texture layer
 *     (/hero-sectors/{slug}.webp), NEVER a stretched company logo or
 *     marquee /hero/{TICKER}.jpg
 *   - The data row renders "Price:" + the delayed quote + market cap
 *   - The "Market Open/Closed" pill renders deterministically from the
 *     injected `marketOpen` prop (and not at all when omitted)
 *   - The identity row sits INSIDE the band: TickerAvatar chip +
 *     company-name h1 + EXCHANGE:TICKER + WatchlistButton
 *   - The retired floating verdict pill stays retired (verdict lives
 *     in the "1. INTRINSIC VALUE" section only)
 *   - Unknown sector → default.webp fallback + asset-existence guard
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
  marketCapCr: 1_300_000,
  exchange: "NSE",
}

describe("StockHeroImage — dark identity band", () => {
  it("renders the banking sector texture photo for HDFCBANK", () => {
    render(<StockHeroImage {...BASE} sector="Private Bank" />)
    const photo = screen.getByTestId("stock-hero-photo")
    expect(photo.getAttribute("src")).toBe("/hero-sectors/banking.webp")
    expect(photo.getAttribute("data-sector-slug")).toBe("banking")
  })

  it("renders the fmcg sector texture for ITC", () => {
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

  it("never renders a stretched company logo or marquee /hero/ jpeg as the band background", () => {
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

  it("renders the data row with the Price label + market cap", () => {
    render(<StockHeroImage {...BASE} sector="Private Bank" />)
    const panel = screen.getByTestId("hero-glass-panel")
    expect(panel.textContent || "").toMatch(/Price:/)
    expect(panel.textContent || "").toMatch(/Market Cap/)
    // formatMarketCap renders >=100,000 Cr as "₹X.XX Lakh Cr"
    expect(panel.textContent || "").toMatch(/Lakh Cr/)
  })

  it("renders the identity row INSIDE the band with name + EXCHANGE:TICKER + watchlist button", () => {
    render(<StockHeroImage {...BASE} sector="Private Bank" />)
    const heroSection = screen.getByTestId("stock-hero-section")
    const identityRow = screen.getByTestId("hero-identity-row")
    expect(heroSection.contains(identityRow)).toBe(true)
    expect(identityRow.textContent || "").toContain("HDFC Bank Ltd")
    expect(identityRow.textContent || "").toContain("NSE:HDFCBANK")
    // Company name is the page h1 inside the band.
    expect(identityRow.querySelector("h1")).not.toBeNull()
  })

  it("does NOT render the retired floating verdict pill", () => {
    render(<StockHeroImage {...BASE} sector="Private Bank" />)
    expect(screen.queryByTestId("hero-verdict-pill")).toBeNull()
  })
})

describe("StockHeroImage — market-hours pill (deterministic via prop)", () => {
  it("renders 'Market Open' with data-open=true when marketOpen is true", () => {
    render(
      <StockHeroImage
        {...BASE}
        sector="Private Bank"
        marketOpen={true}
        marketStatusCaption="NSE regular hours: Mon-Fri 09:15-15:30 IST. Exchange holidays are not tracked."
      />,
    )
    const pill = screen.getByTestId("market-status-pill")
    expect(pill.textContent || "").toMatch(/Market Open/)
    expect(pill.getAttribute("data-open")).toBe("true")
    expect(pill.getAttribute("title") || "").toMatch(/regular hours/i)
  })

  it("renders 'Market Closed' with data-open=false when marketOpen is false", () => {
    render(
      <StockHeroImage {...BASE} sector="Private Bank" marketOpen={false} />,
    )
    const pill = screen.getByTestId("market-status-pill")
    expect(pill.textContent || "").toMatch(/Market Closed/)
    expect(pill.getAttribute("data-open")).toBe("false")
  })

  it("renders no pill at all when marketOpen is omitted (no fake signal)", () => {
    render(<StockHeroImage {...BASE} sector="Private Bank" />)
    expect(screen.queryByTestId("market-status-pill")).toBeNull()
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
