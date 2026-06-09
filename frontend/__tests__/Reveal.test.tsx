/**
 * Premium-feel Round 1 — Reveal primitive tests.
 *
 * Pins:
 *   1. Children always render (no clipping on SSR or pre-mount).
 *   2. Before IntersectionObserver fires the wrapper carries the
 *      hidden-state classes for the requested direction.
 *   3. After the observer fires once the wrapper flips to the shown
 *      state AND the observer is disconnected so it never re-runs.
 *   4. prefers-reduced-motion bypasses the observer and renders the
 *      shown state immediately.
 *   5. Per-direction class contracts (up / left / right / pop) all
 *      compose with Tailwind's transition utility classes.
 *   6. SSR snapshot (renderToString) emits the shown state so crawlers
 *      and the pre-hydration paint always see the content.
 */
import { describe, it, expect, beforeEach, vi } from "vitest"
import { render, screen, act } from "@testing-library/react"
import Reveal from "@/components/common/Reveal"

type IOCallback = (
  entries: { isIntersecting: boolean; intersectionRatio: number; target: Element }[],
) => void

let lastIOCallback: IOCallback | null = null
let disconnectCount = 0

class MockIntersectionObserver {
  callback: IOCallback
  constructor(cb: IOCallback) {
    this.callback = cb
    lastIOCallback = cb
  }
  observe() {}
  unobserve() {}
  disconnect() {
    disconnectCount += 1
  }
  takeRecords() {
    return []
  }
}

function triggerInView(target: Element) {
  lastIOCallback?.([
    { isIntersecting: true, intersectionRatio: 1, target },
  ])
}

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
  lastIOCallback = null
  disconnectCount = 0
  vi.stubGlobal("IntersectionObserver", MockIntersectionObserver)
  setReducedMotion(false)
})

describe("Reveal", () => {
  it("renders children", () => {
    render(
      <Reveal>
        <p>hello</p>
      </Reveal>,
    )
    expect(screen.getByText("hello")).toBeInTheDocument()
  })

  it("emits hidden state classes before viewport entry", async () => {
    const { container } = render(
      <Reveal direction="up">
        <p>child</p>
      </Reveal>,
    )
    // Wait for the post-mount effect that flips us from the SSR
    // "shown" state into the pre-reveal hidden state.
    await act(async () => {
      await Promise.resolve()
    })
    const wrapper = container.querySelector('[data-reveal="up"]') as HTMLElement
    expect(wrapper).toBeTruthy()
    expect(wrapper.getAttribute("data-reveal-visible")).toBe("false")
    const classes = wrapper.className
    expect(classes).toMatch(/opacity-0/)
    expect(classes).toMatch(/translate-y-3/)
    expect(classes).toMatch(/transition-all/)
    expect(classes).toMatch(/duration-700/)
  })

  it("flips to shown state after the observer fires and disconnects", async () => {
    const { container } = render(
      <Reveal direction="up">
        <p>child</p>
      </Reveal>,
    )
    await act(async () => {
      await Promise.resolve()
    })
    const wrapper = container.querySelector('[data-reveal="up"]') as HTMLElement
    await act(async () => {
      triggerInView(wrapper)
    })
    expect(wrapper.getAttribute("data-reveal-visible")).toBe("true")
    expect(wrapper.className).toMatch(/opacity-100/)
    expect(wrapper.className).toMatch(/translate-y-0/)
    // Observer was disconnected after the first reveal so scrolling
    // the section back into view never re-runs the animation.
    expect(disconnectCount).toBeGreaterThanOrEqual(1)
  })

  it("respects prefers-reduced-motion (renders shown state immediately)", async () => {
    setReducedMotion(true)
    const { container } = render(
      <Reveal direction="up">
        <p>child</p>
      </Reveal>,
    )
    await act(async () => {
      await Promise.resolve()
    })
    const wrapper = container.querySelector('[data-reveal="up"]') as HTMLElement
    expect(wrapper.getAttribute("data-reveal-visible")).toBe("true")
    expect(wrapper.className).toMatch(/opacity-100/)
    // No observer callback must ever have been registered.
    expect(lastIOCallback).toBeNull()
  })

  it("applies direction-specific classes", async () => {
    const cases: Array<{ dir: "up" | "left" | "right" | "pop"; hidden: RegExp }> = [
      { dir: "up", hidden: /translate-y-3/ },
      { dir: "left", hidden: /translate-x-3/ },
      { dir: "right", hidden: /-translate-x-3/ },
      { dir: "pop", hidden: /scale-\[0\.96\]/ },
    ]
    for (const c of cases) {
      const { container, unmount } = render(
        <Reveal direction={c.dir}>
          <p>direction-{c.dir}</p>
        </Reveal>,
      )
      await act(async () => {
        await Promise.resolve()
      })
      const wrapper = container.querySelector(`[data-reveal="${c.dir}"]`) as HTMLElement
      expect(wrapper).toBeTruthy()
      expect(wrapper.className).toMatch(c.hidden)
      unmount()
    }
  })

  it("propagates delay into the inline transition-delay style after reveal", async () => {
    const { container } = render(
      <Reveal direction="up" delay={240}>
        <p>delayed child</p>
      </Reveal>,
    )
    await act(async () => {
      await Promise.resolve()
    })
    const wrapper = container.querySelector('[data-reveal="up"]') as HTMLElement
    await act(async () => {
      triggerInView(wrapper)
    })
    // After reveal the wrapper carries the configured transition-delay
    // so a stagger of 0/80/160/240 lands as the brief specifies.
    expect(wrapper.style.transitionDelay).toBe("240ms")
  })

  it("server-side renders the shown state (SSR safety)", async () => {
    const { renderToString } = await import("react-dom/server")
    const html = renderToString(
      <Reveal direction="up">
        <p>ssr child</p>
      </Reveal>,
    )
    // Server output must already carry the visible classes so crawlers
    // and the pre-hydration paint see the content.
    expect(html).toContain("opacity-100")
    expect(html).toContain("ssr child")
  })
})
