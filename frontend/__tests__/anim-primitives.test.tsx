import { describe, it, expect, beforeEach, vi } from "vitest"
import { render, screen, act } from "@testing-library/react"
import { CountUp } from "@/components/anim/CountUp"
import { FadeStagger } from "@/components/anim/FadeStagger"
import { ChartDrawIn } from "@/components/anim/ChartDrawIn"
import { RevealOnScroll } from "@/components/anim/RevealOnScroll"

/**
 * Lightweight IntersectionObserver harness: the primitives all rely on
 * the same hook (`useInViewOnce`) so we control viewport entry by
 * holding a reference to the last-registered observer and triggering
 * `inView=true` whenever the test wants it.
 */
type IOCallback = (entries: { isIntersecting: boolean }[]) => void
let lastIOCallback: IOCallback | null = null

class MockIntersectionObserver {
  callback: IOCallback
  constructor(cb: IOCallback) {
    this.callback = cb
    lastIOCallback = cb
  }
  observe() {}
  unobserve() {}
  disconnect() {}
  takeRecords() {
    return []
  }
}

function triggerInView() {
  lastIOCallback?.([{ isIntersecting: true }])
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
  vi.stubGlobal("IntersectionObserver", MockIntersectionObserver)
  setReducedMotion(false)
})

describe("CountUp", () => {
  it("renders the final value on the server (SSR-safe)", async () => {
    const { renderToString } = await import("react-dom/server")
    const html = renderToString(<CountUp to={1131} prefix="₹" />)
    // Server render must match the post-animation final value so that
    // non-JS users (and pre-hydration paint) see the right number.
    expect(html).toContain("₹1,131")
  })

  it("respects prefers-reduced-motion (snaps to final, no RAF)", async () => {
    setReducedMotion(true)
    const rafSpy = vi.spyOn(window, "requestAnimationFrame")
    render(<CountUp to={500} from={0} duration={1} />)
    // Let the post-mount effect flush.
    await act(async () => {
      await Promise.resolve()
    })
    expect(screen.getByText("500")).toBeInTheDocument()
    expect(rafSpy).not.toHaveBeenCalled()
    rafSpy.mockRestore()
  })

  it("does not animate until the element enters the viewport", async () => {
    const rafSpy = vi.spyOn(window, "requestAnimationFrame")
    render(<CountUp to={1000} from={0} duration={0.5} />)
    // Pre-viewport: shows final value (SSR-consistent), no RAF yet.
    await act(async () => {
      await Promise.resolve()
    })
    expect(screen.getByText("1,000")).toBeInTheDocument()
    expect(rafSpy).not.toHaveBeenCalled()

    // Trigger viewport entry → RAF kicks in.
    await act(async () => {
      triggerInView()
    })
    expect(rafSpy).toHaveBeenCalled()
    rafSpy.mockRestore()
  })
})

describe("FadeStagger", () => {
  it("applies staggered transition delays per child", async () => {
    render(
      <FadeStagger staggerMs={150} durationMs={400} direction="up">
        <span>a</span>
        <span>b</span>
        <span>c</span>
      </FadeStagger>,
    )
    await act(async () => {
      triggerInView()
    })
    const a = screen.getByText("a").parentElement!
    const b = screen.getByText("b").parentElement!
    const c = screen.getByText("c").parentElement!
    expect(a.getAttribute("data-stagger-index")).toBe("0")
    expect(b.getAttribute("data-stagger-index")).toBe("1")
    expect(c.getAttribute("data-stagger-index")).toBe("2")
    // The inline-style transition string includes the per-child delay.
    expect(a.getAttribute("style")).toContain("0ms")
    expect(b.getAttribute("style")).toContain("150ms")
    expect(c.getAttribute("style")).toContain("300ms")
  })

  it("disables transitions under prefers-reduced-motion", () => {
    setReducedMotion(true)
    render(
      <FadeStagger staggerMs={200}>
        <span>x</span>
        <span>y</span>
      </FadeStagger>,
    )
    const x = screen.getByText("x").parentElement!
    expect(x.getAttribute("style")).toContain("transition: none")
  })
})

describe("ChartDrawIn", () => {
  it("passes children through and injects Recharts animation props", () => {
    function FakeChart(props: {
      isAnimationActive?: boolean
      animationDuration?: number
      children?: React.ReactNode
    }) {
      return (
        <div
          data-testid="fake-chart"
          data-active={props.isAnimationActive ? "true" : "false"}
          data-duration={props.animationDuration}
        >
          {props.children}
        </div>
      )
    }
    render(
      <ChartDrawIn animationDuration={750}>
        <FakeChart>
          <span>inside</span>
        </FakeChart>
      </ChartDrawIn>,
    )
    expect(screen.getByText("inside")).toBeInTheDocument()
    const chart = screen.getByTestId("fake-chart")
    // Before viewport entry: animation must be inactive so Recharts
    // doesn't burn its one-shot animation off-screen.
    expect(chart.getAttribute("data-active")).toBe("false")
    expect(chart.getAttribute("data-duration")).toBe("750")
  })

  it("activates animation after viewport entry", async () => {
    function FakeChart(props: { isAnimationActive?: boolean }) {
      return (
        <div
          data-testid="fc"
          data-active={props.isAnimationActive ? "true" : "false"}
        />
      )
    }
    render(
      <ChartDrawIn>
        <FakeChart />
      </ChartDrawIn>,
    )
    await act(async () => {
      triggerInView()
    })
    expect(screen.getByTestId("fc").getAttribute("data-active")).toBe("true")
  })
})

describe("RevealOnScroll", () => {
  it("renders children and applies hidden style before viewport entry", () => {
    render(
      <RevealOnScroll>
        <p>hello world</p>
      </RevealOnScroll>,
    )
    expect(screen.getByText("hello world")).toBeInTheDocument()
    const wrapper = screen.getByText("hello world").parentElement!
    expect(wrapper.getAttribute("style")).toContain("opacity: 0")
  })

  it("reveals immediately under prefers-reduced-motion", () => {
    setReducedMotion(true)
    render(
      <RevealOnScroll>
        <p>hi</p>
      </RevealOnScroll>,
    )
    const wrapper = screen.getByText("hi").parentElement!
    expect(wrapper.getAttribute("style")).toContain("opacity: 1")
  })
})
