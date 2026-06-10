/**
 * PostMergerRatioCaption tests.
 *
 * ROOT CAUSE #2 (2026-06-11) — additive Quality-tab caption that
 * explains depressed trailing ROE/ROA on tickers inside an 8-quarter
 * M&A normalisation window.
 *
 * Scope:
 *   * HDFCBANK fixture (`ma_event` populated, in-window) renders the
 *     caption with the company name, the event date, the magnitude
 *     range, and both ROE/ROA values.
 *   * TCS fixture (`ma_event=null`) renders nothing — the component
 *     self-hides for non-M&A tickers.
 *   * Out-of-window event (`is_within_normalization_window=false`)
 *     also self-hides.
 *   * Filing link surfaces when `source_url` is provided.
 */
import { describe, it, expect } from "vitest"
import { render, screen } from "@testing-library/react"

import PostMergerRatioCaption from "@/components/analysis/PostMergerRatioCaption"

const HDFC_MA = {
  event_date: "2023-07-01",
  event_type: "REVERSE_MERGER",
  magnitude_pct: 100,
  multiplier: 2.0,
  normalization_window_quarters: 8,
  quarters_since_event: 3,
  description:
    "Reverse merger — HDFC Ltd parent absorbed into HDFC Bank; effective date 2023-07-01.",
  source_url: "https://www.sebi.gov.in/sebiweb/home/HomeAction.do",
  source_doc:
    "RBI/SEBI joint approval — HDFC Ltd into HDFC Bank reverse merger",
  is_within_normalization_window: true,
}

describe("PostMergerRatioCaption", () => {
  it("renders the caption for HDFCBANK when ma_event is populated", () => {
    render(
      <PostMergerRatioCaption
        maEvent={HDFC_MA}
        companyName="HDFC Bank"
        roePct={8.8}
        roaPct={1.4}
      />,
    )
    const caption = screen.getByTestId("post-merger-ratio-caption")
    expect(caption).toBeInTheDocument()
    // Company name + descriptive verb make it clear what happened.
    expect(caption.textContent).toContain("HDFC Bank")
    expect(caption.textContent).toMatch(/reverse merger/i)
    expect(caption.textContent).toMatch(/July 2023/i)
    // Magnitude % surfaces in the descriptive copy.
    expect(caption.textContent).toContain("100%")
    // Trailing ratios are quoted with their actual values.
    expect(caption.textContent).toContain("8.8%")
    expect(caption.textContent).toContain("1.4%")
    // Eight-quarter normalisation window is named explicitly.
    expect(caption.textContent).toMatch(/8 quarters post-event|FY/i)
  })

  it("renders the filing link when source_url is provided", () => {
    render(
      <PostMergerRatioCaption
        maEvent={HDFC_MA}
        companyName="HDFC Bank"
        roePct={8.8}
        roaPct={1.4}
      />,
    )
    const link = screen.getByRole("link", { name: /filing/i })
    expect(link).toHaveAttribute(
      "href",
      "https://www.sebi.gov.in/sebiweb/home/HomeAction.do",
    )
  })

  it("returns null when ma_event is null (TCS-style non-M&A ticker)", () => {
    const { container } = render(
      <PostMergerRatioCaption
        maEvent={null}
        companyName="Tata Consultancy Services"
        roePct={47.5}
        roaPct={28.0}
      />,
    )
    expect(container).toBeEmptyDOMElement()
  })

  it("returns null when ma_event is undefined", () => {
    const { container } = render(
      <PostMergerRatioCaption
        maEvent={undefined}
        companyName="Random Co"
      />,
    )
    expect(container).toBeEmptyDOMElement()
  })

  it("returns null when the event sits outside the normalisation window", () => {
    const oldEvent = {
      ...HDFC_MA,
      is_within_normalization_window: false,
      quarters_since_event: 32,
    }
    const { container } = render(
      <PostMergerRatioCaption
        maEvent={oldEvent}
        companyName="Old Merger Co"
        roePct={15}
        roaPct={2}
      />,
    )
    expect(container).toBeEmptyDOMElement()
  })

  it("falls back gracefully when ROE/ROA are missing", () => {
    render(
      <PostMergerRatioCaption
        maEvent={HDFC_MA}
        companyName="HDFC Bank"
        roePct={null}
        roaPct={null}
      />,
    )
    const caption = screen.getByTestId("post-merger-ratio-caption")
    // Caption still renders — just without quoted ratio values.
    expect(caption.textContent).not.toContain("8.8%")
    expect(caption.textContent).toMatch(/trailing return ratios/i)
  })
})
