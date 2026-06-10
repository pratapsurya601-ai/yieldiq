/**
 * Educational Content Layer tests.
 *
 * Covers:
 *   1. educational-content.ts library — shape, lookup, alias resolution,
 *      category grouping, related-topic integrity.
 *   2. MetricExplainer component — trigger renders, modal opens/closes
 *      on click + Esc, Continue-reading link points at /learn/<slug>.
 *   3. Inline MetricTooltip — the new "Learn more" link surfaces when a
 *      long-form topic exists, lands on /learn/<slug>.
 *   4. SEBI vocabulary regression — every topic field rendered by the
 *      modal contains zero banned vocabulary. Backstop to the lint
 *      script.
 *
 * SEBI fixtures use Pattern B (fragment-built strings) to keep this
 * file scan-clean under check_sebi_words.py --diff-only.
 */
import { describe, it, expect, beforeEach, vi } from "vitest"
import { render, screen, act, fireEvent, cleanup } from "@testing-library/react"
import MetricExplainer from "@/components/analysis/MetricExplainer"
import MetricTooltip from "@/components/common/MetricTooltip"
import {
  EDUCATIONAL_TOPICS,
  getAllTopicSlugs,
  getEducationalTopic,
  getTopicsByCategory,
  resolveTopic,
} from "@/lib/educational-content"

// Banned vocabulary tokens — built from string fragments so this test
// file itself stays SEBI-lint clean under the diff-only scanner.
const BANNED_WORDS = [
  "ap" + "pears",
  "sh" + "ould",
  "co" + "ncern",
  "stre" + "ngth",
  "weak" + "ness",
  "bu" + "y",
  "se" + "ll",
  "ho" + "ld",
  "outper" + "form",
  "underper" + "form",
  "expen" + "sive",
  "che" + "ap",
  "attrac" + "tive",
  "po" + "or",
  "accumu" + "late",
  "recom" + "mend",
  "recommen" + "dation",
  "invest" + "able",
  "investa" + "bility",
]

function setReducedMotion(matches: boolean) {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: query.includes("prefers-reduced-motion") ? matches : false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }))
}

beforeEach(() => {
  setReducedMotion(false)
  cleanup()
})

describe("educational-content library", () => {
  it("ships at least 30 topics", () => {
    const slugs = getAllTopicSlugs()
    expect(slugs.length).toBeGreaterThanOrEqual(30)
  })

  it("every topic has all required fields populated", () => {
    for (const [key, topic] of Object.entries(EDUCATIONAL_TOPICS)) {
      expect(topic.slug, `${key}.slug`).toBeTruthy()
      expect(topic.title, `${key}.title`).toBeTruthy()
      expect(topic.subtitle, `${key}.subtitle`).toBeTruthy()
      expect(topic.definition.length, `${key}.definition`).toBeGreaterThan(40)
      expect(
        topic.whyItMatters.length,
        `${key}.whyItMatters`,
      ).toBeGreaterThan(40)
      expect(topic.ranges.length, `${key}.ranges`).toBeGreaterThanOrEqual(2)
      expect(topic.example.length, `${key}.example`).toBeGreaterThan(40)
      expect(
        ["beginner", "intermediate", "advanced"],
        `${key}.difficulty`,
      ).toContain(topic.difficulty)
    }
  })

  it("every related-topic key resolves to an existing topic", () => {
    for (const [key, topic] of Object.entries(EDUCATIONAL_TOPICS)) {
      for (const rel of topic.relatedTopics) {
        expect(
          EDUCATIONAL_TOPICS[rel],
          `${key} → related "${rel}" must exist`,
        ).toBeDefined()
      }
    }
  })

  it("getEducationalTopic returns the entry for a known key and null for unknown", () => {
    expect(getEducationalTopic("roe")).not.toBeNull()
    expect(getEducationalTopic("this-slug-does-not-exist")).toBeNull()
  })

  it("resolveTopic understands aliases (pe-ratio → pe)", () => {
    const direct = resolveTopic("pe")
    const aliased = resolveTopic("pe-ratio")
    expect(direct).not.toBeNull()
    expect(aliased).not.toBeNull()
    expect(direct?.slug).toBe(aliased?.slug)
  })

  it("getTopicsByCategory groups every topic into exactly one category", () => {
    const groups = getTopicsByCategory()
    let total = 0
    for (const arr of Object.values(groups)) total += arr.length
    expect(total).toBe(Object.keys(EDUCATIONAL_TOPICS).length)
  })
})

describe("MetricExplainer", () => {
  it("renders the trigger button when topic exists", () => {
    render(<MetricExplainer topic="roe" />)
    const trigger = screen.getByTestId("metric-explainer-trigger-roe")
    expect(trigger).toBeInTheDocument()
    expect(trigger.getAttribute("aria-expanded")).toBe("false")
  })

  it("renders nothing when topic does not exist", () => {
    const { container } = render(
      <MetricExplainer topic="this-key-does-not-exist" />,
    )
    expect(container.querySelector("button")).toBeNull()
  })

  it("opens the modal on click and shows title + definition", async () => {
    render(<MetricExplainer topic="roe" />)
    const trigger = screen.getByTestId("metric-explainer-trigger-roe")
    await act(async () => {
      fireEvent.click(trigger)
    })
    const modal = screen.getByTestId("metric-explainer-modal")
    expect(modal).toBeInTheDocument()
    expect(modal.getAttribute("aria-modal")).toBe("true")
    const entry = EDUCATIONAL_TOPICS.roe
    expect(modal.textContent).toContain(entry.title)
    expect(modal.textContent).toContain(entry.definition)
    expect(modal.textContent).toContain(entry.whyItMatters)
    expect(modal.textContent).toContain(entry.example)
  })

  it("renders Continue reading link to /learn/<slug>", async () => {
    render(<MetricExplainer topic="roe" />)
    const trigger = screen.getByTestId("metric-explainer-trigger-roe")
    await act(async () => {
      fireEvent.click(trigger)
    })
    const link = screen.getByTestId("metric-explainer-continue-link")
    expect(link).toBeInTheDocument()
    expect(link.getAttribute("href")).toBe("/learn/roe")
  })

  it("closes the modal on Escape", async () => {
    render(<MetricExplainer topic="roe" />)
    const trigger = screen.getByTestId("metric-explainer-trigger-roe")
    await act(async () => {
      fireEvent.click(trigger)
    })
    expect(screen.getByTestId("metric-explainer-modal")).toBeInTheDocument()
    await act(async () => {
      fireEvent.keyDown(document, { key: "Escape" })
    })
    expect(screen.queryByTestId("metric-explainer-modal")).toBeNull()
  })

  it("closes the modal on close button click", async () => {
    render(<MetricExplainer topic="roe" />)
    const trigger = screen.getByTestId("metric-explainer-trigger-roe")
    await act(async () => {
      fireEvent.click(trigger)
    })
    expect(screen.getByTestId("metric-explainer-modal")).toBeInTheDocument()
    const closeButton = screen.getByTestId("metric-explainer-close")
    await act(async () => {
      fireEvent.click(closeButton)
    })
    expect(screen.queryByTestId("metric-explainer-modal")).toBeNull()
  })

  it("renders typical ranges as a list", async () => {
    render(<MetricExplainer topic="pe" />)
    await act(async () => {
      fireEvent.click(screen.getByTestId("metric-explainer-trigger-pe"))
    })
    const modal = screen.getByTestId("metric-explainer-modal")
    // Every band label is present.
    for (const range of EDUCATIONAL_TOPICS.pe.ranges) {
      expect(modal.textContent).toContain(range.label)
    }
  })
})

describe("MetricTooltip Learn more link", () => {
  it("renders a Learn more link when a long-form topic exists for the metric", async () => {
    render(<MetricTooltip label="ROE" value="18.3%" metric="roe" />)
    const wrapper = screen.getByTestId("metric-tooltip-roe")
    const trigger = wrapper.querySelector("button") as HTMLButtonElement
    await act(async () => {
      fireEvent.mouseEnter(trigger)
    })
    const learnMore = screen.getByTestId("metric-tooltip-learn-more")
    expect(learnMore).toBeInTheDocument()
    expect(learnMore.getAttribute("href")).toBe("/learn/roe")
  })

  it("does not render a Learn more link when the metric has no long-form topic", async () => {
    // bull_case is in metric-explainers but NOT in educational-content,
    // so no /learn/ link should appear.
    render(<MetricTooltip label="Bull Case" value="₹100" metric="bull_case" />)
    const wrapper = screen.getByTestId("metric-tooltip-bull-case")
    const trigger = wrapper.querySelector("button") as HTMLButtonElement
    await act(async () => {
      fireEvent.mouseEnter(trigger)
    })
    expect(screen.queryByTestId("metric-tooltip-learn-more")).toBeNull()
  })
})

describe("SEBI vocabulary regression — entire educational-content library", () => {
  it("no banned token surfaces in any rendered topic", async () => {
    for (const [key, entry] of Object.entries(EDUCATIONAL_TOPICS)) {
      const { unmount, getByTestId } = render(
        <MetricExplainer topic={key} />,
      )
      const trigger = getByTestId(`metric-explainer-trigger-${entry.slug}`)
      await act(async () => {
        fireEvent.click(trigger)
      })
      const modal = getByTestId("metric-explainer-modal")
      const rendered = modal.textContent ?? ""
      for (const banned of BANNED_WORDS) {
        const pattern = new RegExp(`\\b${banned}\\b`, "i")
        expect(
          pattern.test(rendered),
          `entry "${key}" rendered text contains banned word "${banned}"`,
        ).toBe(false)
      }
      unmount()
    }
  })
})
