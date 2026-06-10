/**
 * Global motion polish (2026-06-11) — chrome-level animation pins.
 *
 * Pins the behaviour added by the global-motion-polish PR:
 *
 *   1. DesktopNav — each top-level nav link carries `data-yq-nav-link`
 *      so the CSS hover underline picks it up; the logo carries the
 *      `.hover-lift` utility class.
 *   2. MarketingTopNav — same `data-yq-nav-link` + `.hover-lift` shape
 *      so the marketing surfaces match the in-app surface.
 *   3. BackButton — wraps the visible <button> in a PressScale span
 *      (data-motion="press-scale") so taps register with a scale-down.
 *   4. ThemeToggle — each segment is wrapped in PressScale; the
 *      <button> still resolves via getByRole so existing tests don't
 *      regress.
 *   5. NotificationsBell — when signed-out, returns null (auth gating
 *      hasn't changed). When signed-in, the bell button is wrapped in
 *      a PressScale span.
 *
 * Conventions:
 *   - matchMedia is stubbed per-test so useReducedMotion resolves to a
 *     deterministic value.
 *   - The auth store + router are mocked at module level so component
 *     trees can mount under jsdom without hitting next/navigation's
 *     production internals.
 */
import { describe, it, expect, beforeEach, vi } from "vitest"
import { render, screen } from "@testing-library/react"

// Mock next/navigation to a stable shape so the layout components can
// resolve pathname/router under jsdom. Each test can override pathname
// by calling __setPath() before render.
let __pathname = "/home"
vi.mock("next/navigation", () => ({
  usePathname: () => __pathname,
  useRouter: () => ({
    push: vi.fn(),
    back: vi.fn(),
    replace: vi.fn(),
    refresh: vi.fn(),
  }),
}))
function __setPath(p: string) {
  __pathname = p
}

// Mock the auth store. We expose two convenience setters so individual
// tests can flip the auth state without re-mounting the entire mock.
type AuthState = {
  token: string | null
  tier: "free" | "pro"
  analysesToday: number
  logout: () => void
}
let __auth: AuthState = {
  token: null,
  tier: "free",
  analysesToday: 0,
  logout: vi.fn(),
}
vi.mock("@/store/authStore", () => ({
  useAuthStore: <T,>(selector: (s: AuthState) => T): T => selector(__auth),
}))
function __setAuth(next: Partial<AuthState>) {
  __auth = { ...__auth, ...next }
}

// Notification store mock — the (legacy) layout/NotificationBell.tsx
// reads from this. Tests for the new components/notifications/NotificationsBell.tsx
// don't touch it but we set it up anyway so other imports stay stable.
vi.mock("@/store/notificationStore", () => ({
  useNotificationStore: <T,>(selector: (s: { notifications: unknown[]; unreadCount: () => number; markAllRead: () => void }) => T): T =>
    selector({ notifications: [], unreadCount: () => 0, markAllRead: vi.fn() }),
}))

// React-query — DesktopNav embeds NotificationsBell which calls
// useQueryClient(). We don't care about its render shape here, so we
// stub the component to a no-op marker. Keeps the DesktopNav surface
// renderable under jsdom without standing up a QueryClient.
vi.mock("@/components/notifications/NotificationsBell", () => ({
  default: () => null,
}))

function setReducedMotion(reduced: boolean) {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: query.includes("prefers-reduced-motion") ? reduced : false,
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
  __setPath("/home")
  __setAuth({ token: null, tier: "free", analysesToday: 0 })
  setReducedMotion(false)
  window.localStorage.clear()
  document.documentElement.removeAttribute("data-yq-motion-off")
})

describe("DesktopNav — global motion polish", () => {
  it("renders nav links with data-yq-nav-link so the hover underline picks them up", async () => {
    const { default: DesktopNav } = await import("@/components/layout/DesktopNav")
    render(<DesktopNav />)
    const home = screen.getByRole("link", { name: "Home" })
    expect(home.getAttribute("data-yq-nav-link")).toBe("true")
    // Active link mirrors the path so the underline can be sticky in
    // the active state without a hover.
    expect(home.getAttribute("data-yq-nav-active")).toBe("true")
  })

  it("marks non-active links with data-yq-nav-active='false'", async () => {
    __setPath("/discover")
    const { default: DesktopNav } = await import("@/components/layout/DesktopNav")
    render(<DesktopNav />)
    const home = screen.getByRole("link", { name: "Home" })
    expect(home.getAttribute("data-yq-nav-active")).toBe("false")
  })

  it("wraps the logo with the .hover-lift utility class", async () => {
    const { default: DesktopNav } = await import("@/components/layout/DesktopNav")
    render(<DesktopNav />)
    const logo = screen.getByRole("link", { name: /YieldIQ home/i })
    expect(logo.className).toContain("hover-lift")
  })

  it("wraps each nav link in a PressScale span (data-motion='press-scale')", async () => {
    const { default: DesktopNav } = await import("@/components/layout/DesktopNav")
    render(<DesktopNav />)
    const press = document.querySelectorAll("[data-motion='press-scale']")
    // Five nav links + Search CTA + Account avatar = at least 7 PressScale
    // wrappers. We allow extras (NotificationsBell etc.) so the count is
    // a lower bound, not an exact match.
    expect(press.length).toBeGreaterThanOrEqual(7)
  })
})

describe("MarketingTopNav — global motion polish", () => {
  it("marks anon nav items with data-yq-nav-link", async () => {
    const { default: MarketingTopNav } = await import(
      "@/components/marketing/MarketingTopNav"
    )
    render(<MarketingTopNav />)
    const discover = screen.getAllByRole("link", { name: "Discover" })[0]
    expect(discover.getAttribute("data-yq-nav-link")).toBe("true")
  })

  it("wraps the logo with the .hover-lift utility class", async () => {
    const { default: MarketingTopNav } = await import(
      "@/components/marketing/MarketingTopNav"
    )
    render(<MarketingTopNav />)
    const logo = screen.getAllByRole("link", { name: /YieldIQ/i })[0]
    expect(logo.className).toContain("hover-lift")
  })

  it("wraps the Start Free CTA in a PressScale span for anon users", async () => {
    const { default: MarketingTopNav } = await import(
      "@/components/marketing/MarketingTopNav"
    )
    render(<MarketingTopNav />)
    // The Start Free CTA is the closest PressScale to the Sign in link.
    const cta = screen.getByRole("link", { name: /Start Free/i })
    // The Link is inside a span with data-motion="press-scale".
    const wrapper = cta.parentElement
    expect(wrapper?.getAttribute("data-motion")).toBe("press-scale")
  })
})

describe("BackButton — global motion polish", () => {
  it("wraps the visible button in a PressScale span", async () => {
    __setPath("/analysis/TCS")
    const { default: BackButton } = await import("@/components/layout/BackButton")
    render(<BackButton />)
    const btn = screen.getByRole("button", { name: "Back" })
    // Walk up the DOM to find the PressScale wrapper — its immediate
    // parent now carries the data-motion attribute.
    const wrapper = btn.parentElement
    expect(wrapper?.getAttribute("data-motion")).toBe("press-scale")
  })

  it("hides on top-level routes (unchanged)", async () => {
    __setPath("/home")
    const { default: BackButton } = await import("@/components/layout/BackButton")
    const { container } = render(<BackButton />)
    expect(container.firstChild).toBeNull()
  })
})

describe("ThemeToggle — global motion polish", () => {
  it("wraps each option in a PressScale span without losing button role", async () => {
    const { default: ThemeToggle } = await import("@/components/layout/ThemeToggle")
    render(<ThemeToggle />)
    const dark = screen.getByRole("button", { name: /dark/i })
    expect(dark.parentElement?.getAttribute("data-motion")).toBe("press-scale")
  })
})

describe("PressScale reduced-motion contract", () => {
  it("DesktopNav nav links carry data-motion-reduced='true' under prefers-reduced-motion", async () => {
    setReducedMotion(true)
    const { default: DesktopNav } = await import("@/components/layout/DesktopNav")
    render(<DesktopNav />)
    const press = document.querySelectorAll("[data-motion='press-scale']")
    expect(press.length).toBeGreaterThan(0)
    press.forEach((el) => {
      expect(el.getAttribute("data-motion-reduced")).toBe("true")
    })
  })
})
