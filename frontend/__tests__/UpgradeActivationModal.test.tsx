/**
 * Day-77 (2026-05-22) — UpgradeActivationModal smoke tests.
 *
 * Pins the Day-47/48 post-checkout activation modal contract:
 *   1. Without the `?just_upgraded=` query param the modal renders
 *      nothing (no fixed-overlay leak on every /account visit).
 *   2. With a valid tier param the modal renders the tier-specific
 *      title.
 *   3. The dismiss control writes a `dismissed_upgrade_modal_{tier}`
 *      key into localStorage and strips the query param via the
 *      Next router replace.
 */

import { describe, it, expect, vi, beforeEach } from "vitest"
import { render, screen, fireEvent } from "@testing-library/react"

// ── Mocks for next/navigation ────────────────────────────────────
const replaceMock = vi.fn()
let currentParams = new URLSearchParams()

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: replaceMock, push: vi.fn() }),
  usePathname: () => "/account",
  useSearchParams: () => currentParams,
}))

// Next's <Link> renders an anchor in tests — no need to mock unless
// it explodes on the runtime. Stubbing keeps the test environment
// independent of Next's internal app-router context.
vi.mock("next/link", () => ({
  default: ({
    children,
    href,
    onClick,
  }: {
    children: React.ReactNode
    href: string
    onClick?: () => void
  }) => (
    <a href={href} onClick={onClick}>
      {children}
    </a>
  ),
}))

import UpgradeActivationModal from "@/components/account/UpgradeActivationModal"

beforeEach(() => {
  replaceMock.mockReset()
  currentParams = new URLSearchParams()
  window.localStorage.clear()
})

describe("UpgradeActivationModal", () => {
  it("renders nothing without a just_upgraded query param", () => {
    const { container } = render(<UpgradeActivationModal />)
    expect(container.firstChild).toBeNull()
    expect(screen.queryByTestId("upgrade-activation-modal")).toBeNull()
  })

  it("renders the tier-specific title when ?just_upgraded=pro is present", () => {
    currentParams = new URLSearchParams("just_upgraded=pro")
    render(<UpgradeActivationModal />)
    expect(screen.getByTestId("upgrade-activation-modal")).toBeInTheDocument()
    expect(screen.getByText("Welcome to Pro")).toBeInTheDocument()
  })

  it("persists dismissal into localStorage and strips the query param", () => {
    currentParams = new URLSearchParams("just_upgraded=analyst")
    render(<UpgradeActivationModal />)
    expect(screen.getByTestId("upgrade-activation-modal")).toBeInTheDocument()

    fireEvent.click(screen.getByTestId("upgrade-activation-dismiss"))

    expect(
      window.localStorage.getItem("dismissed_upgrade_modal_analyst"),
    ).not.toBeNull()
    expect(replaceMock).toHaveBeenCalledWith("/account")
    // Modal removed from the DOM after dismiss.
    expect(screen.queryByTestId("upgrade-activation-modal")).toBeNull()
  })

  it("does not re-open the modal when the tier has already been dismissed", () => {
    window.localStorage.setItem(
      "dismissed_upgrade_modal_student",
      new Date().toISOString(),
    )
    currentParams = new URLSearchParams("just_upgraded=student")
    render(<UpgradeActivationModal />)
    expect(screen.queryByTestId("upgrade-activation-modal")).toBeNull()
  })
})
