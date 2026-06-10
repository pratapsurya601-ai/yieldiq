/**
 * Tests for /disputes — the public dispute / errata input channel.
 *
 * The page is a server component that hosts the <DisputeForm /> client
 * component. We render the page directly (no async data fetch, no
 * providers) and assert on the rendered DOM plus the pure mailto
 * builder exported from DisputeForm.
 *
 * Pinned behaviours:
 *
 *   1. Smoke — hero + lede + 3 category cards + form all render.
 *   2. Form fields — ticker, category radios, both textareas, name,
 *      email, submit anchor all present.
 *   3. Category selection updates the displayed example caption.
 *   4. buildMailto encodes subject + body correctly for a fully-
 *      populated submission AND for an empty one (still valid).
 *   5. SEBI vocab guard — rendered DOM contains none of the banned
 *      advisory tokens. Per root-CLAUDE.md standing rule #5, the
 *      BANNED array is built from string fragments (Pattern B) so the
 *      diff-only sebi-lint scanner over THIS file's literals produces
 *      zero false positives.
 */

import { describe, it, expect, beforeEach } from "vitest"
import { render, fireEvent } from "@testing-library/react"

import DisputesPage from "@/app/(marketing)/disputes/page"
import DisputeForm, {
  buildMailto,
  DISPUTE_CATEGORIES,
} from "@/components/marketing/DisputeForm"

describe("DisputesPage — server component shell", () => {
  let container: HTMLElement

  beforeEach(() => {
    container = render(<DisputesPage />).container
  })

  it("smoke — renders the hero H1", () => {
    const h1 = container.querySelector("h1")
    expect(h1).not.toBeNull()
    expect(h1?.textContent).toContain("Found a mistake")
  })

  it("renders the lede paragraph naming /errata as the publish target", () => {
    const text = container.textContent ?? ""
    expect(text).toContain("computed algorithmically")
    expect(text).toContain("/errata")
  })

  it("renders three category cards", () => {
    const text = container.textContent ?? ""
    expect(text).toContain("Data correction")
    expect(text).toContain("Model challenge")
    expect(text).toContain("Copy / methodology bug")
  })

  it("renders the form with all expected fields", () => {
    expect(container.querySelector("#dispute-ticker")).not.toBeNull()
    expect(container.querySelector("#dispute-whats-wrong")).not.toBeNull()
    expect(container.querySelector("#dispute-whats-right")).not.toBeNull()
    expect(container.querySelector("#dispute-name")).not.toBeNull()
    expect(container.querySelector("#dispute-email")).not.toBeNull()

    const radios = container.querySelectorAll(
      'input[name="dispute-category"]',
    )
    expect(radios.length).toBe(DISPUTE_CATEGORIES.length)

    const submit = container.querySelector(
      '[data-testid="dispute-submit"]',
    ) as HTMLAnchorElement | null
    expect(submit).not.toBeNull()
    expect(submit?.getAttribute("href")).toMatch(/^mailto:disputes@yieldiq\.in/)
  })

  it("footer cross-links Past corrections + methodology + status + help", () => {
    const text = container.textContent ?? ""
    expect(text).toContain("Past corrections")
    expect(text).toContain("How we value stocks")
    expect(text).toContain("Status")
    expect(text).toContain("Help")
  })
})

describe("DisputeForm — category selection updates example caption", () => {
  it("changes the displayed example when a different category is selected", () => {
    const { container } = render(<DisputeForm />)
    const caption = container.querySelector(
      '[data-testid="category-example"]',
    ) as HTMLElement
    expect(caption.textContent).toContain(DISPUTE_CATEGORIES[0].example)

    const modelRadio = container.querySelector(
      'input[name="dispute-category"][value="model"]',
    ) as HTMLInputElement
    fireEvent.click(modelRadio)
    expect(caption.textContent).toContain(
      DISPUTE_CATEGORIES.find((c) => c.value === "model")!.example,
    )

    const copyRadio = container.querySelector(
      'input[name="dispute-category"][value="copy"]',
    ) as HTMLInputElement
    fireEvent.click(copyRadio)
    expect(caption.textContent).toContain(
      DISPUTE_CATEGORIES.find((c) => c.value === "copy")!.example,
    )
  })

  it("submit anchor href updates as user types into the form", () => {
    const { container } = render(<DisputeForm />)
    const tickerInput = container.querySelector(
      "#dispute-ticker",
    ) as HTMLInputElement
    fireEvent.change(tickerInput, { target: { value: "RELIANCE" } })

    const wrongInput = container.querySelector(
      "#dispute-whats-wrong",
    ) as HTMLTextAreaElement
    fireEvent.change(wrongInput, { target: { value: "FY24 capex wrong" } })

    const submit = container.querySelector(
      '[data-testid="dispute-submit"]',
    ) as HTMLAnchorElement
    const href = submit.getAttribute("href") ?? ""
    expect(href).toContain("mailto:disputes@yieldiq.in")
    expect(decodeURIComponent(href)).toContain("RELIANCE")
    expect(decodeURIComponent(href)).toContain("FY24 capex wrong")
  })
})

describe("buildMailto — pure URL composer", () => {
  it("encodes subject + body for a fully-populated submission", () => {
    const url = buildMailto({
      ticker: "RELIANCE",
      category: "data",
      whatsWrong: "FY24 capex shows 75000 Cr, filing says 131000 Cr",
      whatsRight: "RIL FY24 annual report p.142",
      name: "Asha Iyer",
      email: "asha@example.com",
    })

    expect(url.startsWith("mailto:disputes@yieldiq.in?")).toBe(true)

    const qIdx = url.indexOf("?")
    const qs = new URLSearchParams(url.slice(qIdx + 1))
    const subject = qs.get("subject") ?? ""
    const body = qs.get("body") ?? ""

    expect(subject).toContain("RELIANCE")
    expect(subject).toContain("data")

    expect(body).toContain("Ticker: RELIANCE")
    expect(body).toContain("Category: data")
    expect(body).toContain("FY24 capex shows 75000 Cr")
    expect(body).toContain("RIL FY24 annual report p.142")
    expect(body).toContain("Asha Iyer")
    expect(body).toContain("asha@example.com")
  })

  it("still produces a valid mailto for an empty submission", () => {
    const url = buildMailto({
      ticker: "",
      category: "data",
      whatsWrong: "",
      whatsRight: "",
      name: "",
      email: "",
    })

    expect(url.startsWith("mailto:disputes@yieldiq.in?")).toBe(true)
    const qs = new URLSearchParams(url.slice(url.indexOf("?") + 1))
    const subject = qs.get("subject") ?? ""
    const body = qs.get("body") ?? ""

    expect(subject).toContain("(unspecified)")
    expect(body).toContain("(not specified)")
    expect(body).toContain("anonymous")
    expect(body).toContain("no email")
  })
})

describe("DisputesPage — SEBI vocab guard", () => {
  it("rendered DOM contains no banned advisory tokens", () => {
    // Pattern B from CLAUDE.md §5: build banned tokens from fragments so
    // the diff-only sebi-lint pass over THIS file's literals produces
    // zero false positives. Runtime assertion is identical to a literal
    // array.
    const BANNED: readonly string[] = [
      "b" + "uy",
      "se" + "ll",
      "ho" + "ld",
      "recomm" + "end",
      "shou" + "ld",
      "outper" + "form",
      "underper" + "form",
      "accumu" + "late",
      "attrac" + "tive",
      "che" + "ap",
      "expen" + "sive",
      "wea" + "k",
      "stro" + "ng",
      "appe" + "ars",
      "conc" + "ern",
      "po" + "or",
      "investa" + "ble",
      "investabi" + "lity",
    ]

    const { container } = render(<DisputesPage />)
    const text = (container.textContent ?? "").toLowerCase()

    const hits: string[] = []
    for (const word of BANNED) {
      const re = new RegExp(`\\b${word}\\b`, "i")
      if (re.test(text)) {
        hits.push(word)
      }
    }

    expect(
      hits,
      `Disputes page DOM leaked banned SEBI vocabulary: ${hits.join(", ")}`,
    ).toEqual([])
  })
})
