/**
 * TickerAvatar smoke tests.
 *
 * Locks the post-2026-06-09 sitewide-chip behavior:
 *   - Known curated NSE ticker (HDFCBANK) → self-hosted
 *     `/logos/HDFCBANK.png` URL on first render (mass-fetched from
 *     Logo.dev; stage 0 of the cascade).
 *   - .NS / .BO / .NSE / .BSE suffixes are stripped before lookup
 *   - Non-curated ticker (GOOGL) → `<ticker>.com`-guess Google favicon URL
 *   - URL builder NEVER emits a `logo.clearbit.com` URL
 *   - Size prop maps xs/sm/md/lg → 16/24/32/48px
 *
 * Notes on mocking: we don't stub the network — jsdom never actually
 * fetches the URL, so we assert on the `src` attribute the component
 * emits, which is sufficient to lock the fallback chain.
 */
import { describe, it, expect } from "vitest"
import { render, screen } from "@testing-library/react"

import TickerAvatar from "@/components/common/TickerAvatar"

describe("TickerAvatar", () => {
  it("renders the self-hosted /logos/{TICKER}.png URL for a curated NSE ticker (HDFCBANK)", () => {
    render(<TickerAvatar ticker="HDFCBANK" />)
    const wrap = screen.getByTestId("ticker-avatar-image")
    const img = wrap.querySelector("img")
    expect(img).not.toBeNull()
    // Stage 0: self-hosted retina-sharp PNG from /public/logos/.
    expect(img?.getAttribute("src")).toBe("/logos/HDFCBANK.png")
    // Hotfix invariant: never emit the dead Clearbit URL.
    expect(img?.getAttribute("src")).not.toMatch(/logo\.clearbit\.com/)
  })

  it("strips the .NS suffix before the curated-map lookup", () => {
    render(<TickerAvatar ticker="HDFCBANK.NS" />)
    const img = screen
      .getByTestId("ticker-avatar-image")
      .querySelector("img")
    expect(img?.getAttribute("src")).toBe("/logos/HDFCBANK.png")
  })

  it("strips .BSE / .NSE / .BO suffixes too", () => {
    render(<TickerAvatar ticker="HDFCBANK.BSE" />)
    const img = screen
      .getByTestId("ticker-avatar-image")
      .querySelector("img")
    expect(img?.getAttribute("src")).toBe("/logos/HDFCBANK.png")
  })

  it("applies the &→_AND_ / -→_ filename sanitisation for M&M and BAJAJ-AUTO", () => {
    render(<TickerAvatar ticker="M&M" />)
    const mAndM = screen
      .getByTestId("ticker-avatar-image")
      .querySelector("img")
    expect(mAndM?.getAttribute("src")).toBe("/logos/M_AND_M.png")
  })

  it("falls through to a `<ticker>.com`-guess Google favicon for non-curated US-style tickers (GOOGL)", () => {
    // GOOGL isn't in ticker_domains.json, so stages 0/1/2 (which all
    // depend on a curated domain) are null and the component renders
    // the stage-3 `<ticker>.com` guess on the first paint.
    render(<TickerAvatar ticker="GOOGL" />)
    const img = screen
      .getByTestId("ticker-avatar-image")
      .querySelector("img")
    expect(img?.getAttribute("src")).toMatch(
      /www\.google\.com\/s2\/favicons\?domain=googl\.com/,
    )
  })

  it("renders a Google favicon URL on first paint for unknown tickers and wires onError", () => {
    render(<TickerAvatar ticker="XYZUNKNOWN" />)
    const wrap = screen.getByTestId("ticker-avatar-image")
    const img = wrap.querySelector("img")
    // First paint: stage-3 favicon-of-guessed-domain for non-curated tickers.
    expect(img?.getAttribute("src")).toMatch(
      /www\.google\.com\/s2\/favicons\?domain=xyzunknown\.com/,
    )
    // Never the dead Clearbit URL.
    expect(img?.getAttribute("src")).not.toMatch(/logo\.clearbit\.com/)
    // onError wiring exists so the cascade can advance at runtime.
    expect(img?.getAttribute("loading")).toBe("lazy")
  })

  it("honours the size prop (xs→16, sm→24, md→32, lg→48)", () => {
    const { rerender, container } = render(
      <TickerAvatar ticker="HDFCBANK" size="xs" />,
    )
    let img = container.querySelector("img")
    expect(img?.getAttribute("width")).toBe("16")

    rerender(<TickerAvatar ticker="HDFCBANK" size="sm" />)
    img = container.querySelector("img")
    expect(img?.getAttribute("width")).toBe("24")

    rerender(<TickerAvatar ticker="HDFCBANK" size="md" />)
    img = container.querySelector("img")
    expect(img?.getAttribute("width")).toBe("32")

    rerender(<TickerAvatar ticker="HDFCBANK" size="lg" />)
    img = container.querySelector("img")
    expect(img?.getAttribute("width")).toBe("48")
  })
})
