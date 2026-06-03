/**
 * TickerAvatar smoke tests.
 *
 * Asserts the two render branches we care about:
 *   - Known ticker (HDFCBANK is in ticker_domains.json) → image branch
 *   - Unknown ticker → monogram fallback
 *   - Size prop maps to expected px dimension on the rendered <img>
 */
import { describe, it, expect } from "vitest"
import { render, screen } from "@testing-library/react"

import TickerAvatar from "@/components/common/TickerAvatar"

describe("TickerAvatar", () => {
  it("renders the image branch for a known ticker (HDFCBANK)", () => {
    render(<TickerAvatar ticker="HDFCBANK" />)
    const img = screen.getByTestId("ticker-avatar-image")
    expect(img).toBeInTheDocument()
    // sanity: an <img> child with a non-empty src
    const innerImg = img.querySelector("img")
    expect(innerImg).not.toBeNull()
    expect(innerImg?.getAttribute("src")).toBeTruthy()
  })

  it("renders the monogram fallback for an unknown ticker", () => {
    render(<TickerAvatar ticker="NOSUCHTICKER" />)
    const monogram = screen.getByTestId("ticker-avatar-monogram")
    expect(monogram).toBeInTheDocument()
    // first two letters of the ticker, uppercased
    expect(monogram.textContent).toBe("NO")
  })

  it("honours the size prop (sm → 16px, lg → 32px)", () => {
    const { rerender, container } = render(
      <TickerAvatar ticker="HDFCBANK" size="sm" />,
    )
    let img = container.querySelector("img")
    expect(img?.getAttribute("width")).toBe("16")
    expect(img?.getAttribute("height")).toBe("16")

    rerender(<TickerAvatar ticker="HDFCBANK" size="lg" />)
    img = container.querySelector("img")
    expect(img?.getAttribute("width")).toBe("32")
    expect(img?.getAttribute("height")).toBe("32")
  })

  it("strips .NS suffix when deriving the monogram", () => {
    render(<TickerAvatar ticker="UNKNOWN.NS" />)
    const monogram = screen.getByTestId("ticker-avatar-monogram")
    expect(monogram.textContent).toBe("UN")
  })
})
