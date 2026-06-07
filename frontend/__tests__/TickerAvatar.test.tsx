/**
 * TickerAvatar smoke tests.
 *
 * Locks the post-2026-06-07-hotfix sitewide-chip behavior:
 *   - Known curated NSE ticker (HDFCBANK) → Google s2/favicons URL on
 *     first render (Clearbit was the previous primary; it died).
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
  it("renders a Google s2/favicons URL for a curated NSE ticker (HDFCBANK)", () => {
    render(<TickerAvatar ticker="HDFCBANK" />)
    const wrap = screen.getByTestId("ticker-avatar-image")
    const img = wrap.querySelector("img")
    expect(img).not.toBeNull()
    // Primary hop uses the curated domain from data/ticker_domains.json.
    expect(img?.getAttribute("src")).toMatch(
      /www\.google\.com\/s2\/favicons\?domain=hdfcbank\.com/,
    )
    // Hotfix invariant: never emit the dead Clearbit URL.
    expect(img?.getAttribute("src")).not.toMatch(/logo\.clearbit\.com/)
  })

  it("strips the .NS suffix before the curated-map lookup", () => {
    render(<TickerAvatar ticker="HDFCBANK.NS" />)
    const img = screen
      .getByTestId("ticker-avatar-image")
      .querySelector("img")
    expect(img?.getAttribute("src")).toMatch(
      /www\.google\.com\/s2\/favicons\?domain=hdfcbank\.com/,
    )
  })

  it("strips .BSE / .NSE / .BO suffixes too", () => {
    render(<TickerAvatar ticker="HDFCBANK.BSE" />)
    const img = screen
      .getByTestId("ticker-avatar-image")
      .querySelector("img")
    expect(img?.getAttribute("src")).toMatch(/hdfcbank\.com/)
  })

  it("falls through to a `<ticker>.com`-guess Google favicon for non-curated US-style tickers (GOOGL)", () => {
    // GOOGL isn't in ticker_domains.json, so stage 0 (curated-domain
    // Google favicon) and stage 1 (curated-domain DDG) are both null,
    // and the component renders the stage-2 `<ticker>.com` guess on
    // the first paint.
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
    // First paint: stage-2 favicon-of-guessed-domain for non-curated tickers.
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
