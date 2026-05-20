/**
 * UpgradeActivationModal — Day-47/48 (2026-05-20).
 *
 * Renders a celebratory tier-specific modal after a successful Razorpay
 * checkout. Triggered by `?just_upgraded={tier}` in the URL (set by
 * /verify-subscription's redirect_to field). Once dismissed for a given
 * tier, persists in localStorage so the modal doesn't re-fire on every
 * /account visit.
 *
 * Per-tier content:
 *   analyst  → Portfolio Prism + broker import CTA
 *   pro      → CSV/PDF export + API key CTA
 *   student  → 5 daily analyses + watchlist CTA
 *
 * Dismiss key: `dismissed_upgrade_modal_{tier}` in localStorage.
 */
"use client"

import { useEffect, useState } from "react"
import Link from "next/link"
import { useSearchParams, useRouter, usePathname } from "next/navigation"

type Tier = "analyst" | "pro" | "student"

interface TierCopy {
  title: string
  subtitle: string
  features: string[]
  cta: { label: string; href: string }
}

const TIER_COPY: Record<Tier, TierCopy> = {
  analyst: {
    title: "Welcome to Analyst",
    subtitle: "Portfolio Prism is now unlocked.",
    features: [
      "Connect a broker account to value your live holdings",
      "Unlimited daily analyses across all 2,400+ tickers",
      "Sector heatmaps + peer benchmarking",
    ],
    cta: { label: "Import a broker account", href: "/portfolio/import" },
  },
  pro: {
    title: "Welcome to Pro",
    subtitle: "CSV/PDF export + API access unlocked.",
    features: [
      "Generate an API key for programmatic access",
      "Export any analysis to CSV or PDF",
      "Everything in Analyst, plus higher rate limits",
    ],
    cta: { label: "Generate your first API key", href: "/account/api-keys" },
  },
  student: {
    title: "Welcome to Student",
    subtitle: "5 daily analyses + watchlist unlocked.",
    features: [
      "5 in-depth analyses every day (vs. 2 on free)",
      "Save unlimited tickers to your watchlist",
      "Email alerts on big fair-value changes",
    ],
    cta: { label: "Start your first analysis", href: "/home" },
  },
}

function isValidTier(t: string | null): t is Tier {
  return t === "analyst" || t === "pro" || t === "student"
}

export default function UpgradeActivationModal() {
  const router = useRouter()
  const pathname = usePathname()
  const searchParams = useSearchParams()
  const justUpgraded = searchParams.get("just_upgraded")
  const [open, setOpen] = useState(false)
  const [tier, setTier] = useState<Tier | null>(null)

  useEffect(() => {
    if (!isValidTier(justUpgraded)) return
    // Don't re-fire if the user has already dismissed this modal for
    // this tier. Allows them to manually re-share the upgrade URL
    // without getting the modal again.
    try {
      const dismissed =
        typeof window !== "undefined" &&
        window.localStorage.getItem(`dismissed_upgrade_modal_${justUpgraded}`)
      if (dismissed) return
    } catch {
      // localStorage can throw in private-browsing — fall through and show.
    }
    setTier(justUpgraded)
    setOpen(true)
  }, [justUpgraded])

  const dismiss = () => {
    if (tier) {
      try {
        window.localStorage.setItem(
          `dismissed_upgrade_modal_${tier}`,
          new Date().toISOString(),
        )
      } catch {
        // ignore — non-fatal
      }
    }
    setOpen(false)
    // Strip the query param so a back/forward navigation doesn't re-open.
    if (pathname) {
      router.replace(pathname)
    }
  }

  if (!open || !tier) return null

  const copy = TIER_COPY[tier]

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="upgrade-activation-title"
      data-testid="upgrade-activation-modal"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 px-4"
    >
      <div className="w-full max-w-md rounded-2xl bg-bg dark:bg-surface border border-border p-6 shadow-2xl">
        <div className="text-xs uppercase tracking-[0.18em] text-success font-semibold">
          Upgrade complete
        </div>
        <h2
          id="upgrade-activation-title"
          className="mt-2 text-2xl font-bold text-ink"
        >
          {copy.title}
        </h2>
        <p className="mt-1 text-sm text-muted">{copy.subtitle}</p>

        <ul className="mt-5 space-y-2">
          {copy.features.map((f, i) => (
            <li
              key={i}
              className="flex items-start gap-2 text-sm text-ink"
            >
              <span aria-hidden className="mt-1 text-success">✓</span>
              <span>{f}</span>
            </li>
          ))}
        </ul>

        <div className="mt-6 flex flex-col gap-2">
          <Link
            href={copy.cta.href}
            onClick={dismiss}
            className="inline-flex items-center justify-center rounded-xl bg-success text-white px-4 py-3 text-sm font-semibold hover:opacity-90"
            data-testid="upgrade-activation-cta"
          >
            {copy.cta.label}
          </Link>
          <button
            type="button"
            onClick={dismiss}
            data-testid="upgrade-activation-dismiss"
            className="inline-flex items-center justify-center rounded-xl border border-border text-sm text-muted px-4 py-2 hover:text-ink"
          >
            Dismiss
          </button>
        </div>
      </div>
    </div>
  )
}
