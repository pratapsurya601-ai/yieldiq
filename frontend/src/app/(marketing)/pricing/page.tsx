"use client"

import Link from "next/link"
import { useEffect, useState } from "react"
import { useAuthStore } from "@/store/authStore"
import {
  trackPricingViewed,
  trackBillingToggled,
  trackUpgradeClicked,
} from "@/lib/analytics"
import { variantFor, priceLabel, getLaunchDiscount, tierById } from "@/config/pricing"

// Nav is now provided by (marketing)/layout.tsx via the unified MarketingTopNav.

type Tier = "free" | "analyst" | "pro"
type Billing = "monthly" | "annual"

interface Plan {
  id: Tier
  name: string
  // null → variant not yet priced; the card renders "Coming soon" instead
  // of a numeric price. Useful for tiers in transition between price
  // revisions or while a new variant (e.g. annual) is being staged.
  monthly: number | null
  annual: number | null // per-year price; display as /year
  subtitle: string
  highlighted: boolean
  badge: string | null
  features: { text: string; included: boolean }[]
  ctaStyle: string
}

// 2026-04-21 restructure: dropped ₹299 Starter, added ₹99 pay-as-you-go,
// kept ₹799 Analyst as the sweet spot, added ₹1,499 Pro for power users.
// 2026-05-02: rebased Annual plans to a sharper "trust us with a year"
// discount — Analyst ₹4,999/yr and Pro ₹9,999/yr.
// 2026-06-07: monthly launch pricing (#726) cut Analyst to ₹349 and Pro
// to ₹699. Annual rebased to the standard "two months free" SaaS pattern
// against the new monthly: Analyst ₹3,490/yr (₹291/mo equiv, ~17% off
// vs ₹349×12 = ₹4,188) and Pro ₹6,990/yr (₹583/mo equiv, ~17% off vs
// ₹699×12 = ₹8,388). Annual is NOT bundled into the launch discount
// strikethrough — that remains monthly-only (see LAUNCH_DISCOUNT).
// Price values are read from @/config/pricing — see PRICING_TIERS for the
// canonical source. Tier names, taglines, and feature lists are kept inline
// here because the pricing-page layout is bespoke (highlighted card, "Most
// Popular" badge, per-feature included/excluded affordances) and goes well
// beyond what the shared config exposes.
// 2026-06-07: tiers flagged `hidden: true` in @/config/pricing are filtered
// out of `visiblePlans` below before render — Pro is hidden for the
// simplification launch but remains in `plans` so Razorpay plan-id wiring
// stays intact. Flip the config flag back to re-expose.
const plans: Plan[] = [
  {
    id: "free",
    name: "Free",
    monthly: variantFor("free", "monthly")?.priceInr ?? 0,
    annual: variantFor("free", "annual")?.priceInr ?? 0, // Free has no annual variant — fall back to 0 so the toggle still renders ₹0/year.
    subtitle: "No credit card required",
    highlighted: false,
    badge: null,
    features: [
      { text: "5 deep analyses per day", included: true },
      { text: "All 2,300+ NSE & BSE stocks searchable", included: true },
      { text: "DCF Fair Value + Margin of Safety", included: true },
      { text: "YieldIQ Prism (Signature mode)", included: true },
      { text: "10-stock watchlist", included: true },
      { text: "1 portfolio / 1 broker account", included: true },
      { text: "Discover rails (YieldIQ 50, Sector Leaders)", included: true },
    ],
    ctaStyle: "border-2 border-border text-ink hover:bg-surface",
  },
  {
    id: "analyst",
    name: "Analyst",
    monthly: variantFor("analyst", "monthly")?.priceInr ?? null,
    annual: variantFor("analyst", "annual")?.priceInr ?? null,
    subtitle: "The sweet spot for serious DIY investors.",
    highlighted: true,
    badge: "Most Popular",
    features: [
      { text: "Unlimited analyses", included: true },
      { text: "Unlimited watchlist & alerts", included: true },
      { text: "5 broker accounts / multi-account portfolio", included: true },
      { text: "Portfolio Prism + Portfolio Health score", included: true },
      { text: "AI summaries (sub-second)", included: true },
      { text: "Concall AI transcript summaries", included: true },
      { text: "Full Time Machine (12-month score trend)", included: true },
      { text: "Tax Report (capital gains calc) — FY 2025-26 logic per Budget 2024", included: true },
      { text: "Compare up to 3 stocks side-by-side", included: true },
    ],
    ctaStyle: "bg-bg dark:bg-surface text-blue-700 font-bold hover:bg-blue-50",
  },
  {
    id: "pro",
    name: "Pro",
    monthly: variantFor("pro", "monthly")?.priceInr ?? null,
    annual: variantFor("pro", "annual")?.priceInr ?? null,
    subtitle: "For power users, bloggers, and advisors.",
    highlighted: false,
    badge: null,
    features: [
      { text: "Everything in Analyst", included: true },
      { text: "CSV + PDF export of any analysis", included: true },
      { text: "API access (100 req/day) for custom workflows", included: true },
      { text: "10 broker accounts / multi-account", included: true },
      { text: "Save + share custom screens", included: true },
      { text: "Priority analysis recompute (faster cache warm)", included: true },
      { text: "Earnings-day morning email digest", included: true },
      { text: "Compare up to 5 stocks side-by-side", included: true },
      { text: "Early access to new features (beta ring)", included: true },
    ],
    ctaStyle: "border-2 border-border text-ink hover:bg-surface",
  },
]

// 2026-06-07: Pro-specific FAQ entries ("Analyst vs Pro?" and the
// Pro annual price mention in "Do you have annual plans?") removed
// as part of the Pro-tier hide. The remaining entries are tier-
// agnostic or Analyst-only. If Pro is re-exposed later (flip
// `hidden: false` in @/config/pricing), restore the "Analyst vs Pro"
// comparison entry and add Pro back to the annual-plans answer.
const faqs = [
  { q: "Can I cancel anytime?", a: "Yes. No lock-in on monthly plans — cancel from your account settings and you won\u2019t be charged next cycle. Annual plans are non-refundable beyond the 7-day money-back window (below)." },
  { q: "How does the ₹99 per-analysis option work?", a: "Pay ₹99 once for 24-hour full access to one stock \u2014 Prism, Fair Value, scenarios, Moat, AI summary, Compare, Report Card. Great if you\u2019re weighing a single decision. Upgrade to Analyst anytime; what you\u2019ve already paid for stays unlocked." },
  { q: "Do you have annual plans?", a: "Yes. Analyst is ₹3,490/year (₹291/mo equivalent) and Pro is ₹6,990/year (₹583/mo equivalent) — about 17% off vs paying monthly (the standard \"two months free\" pattern). Annual users get priority support and first access to new features." },
  { q: "Why annual?", a: "It signals you trust us with a year. We give you the equivalent of two months free (~17% off vs paying monthly). Simple deal — less churn for us, materially cheaper for you." },
  { q: "Can I switch between monthly and annual?", a: "Yes — switch either direction from your account settings. Switches are prorated: when you upgrade monthly → annual we credit the unused portion of your current cycle against the annual price; downgrades take effect at the next renewal." },
  { q: "How does student / CA verification work?", a: "Email a photo of your current student ID OR articleship registration to hello@yieldiq.in from the same address you signed up with. We approve within 24 hours and your account flips to the ₹199/mo Student tier. The tier auto-expires when your graduation or articleship completion date passes — you can renew with updated proof or roll onto Analyst." },
  { q: "What payment methods do you accept?", a: "UPI, credit/debit cards, and net banking via Razorpay. All prices in INR; GST is included." },
  { q: "Is there a refund policy?", a: "Yes \u2014 full refund within 7 days of the first charge if you\u2019re not satisfied. Applies to monthly and annual plans both. Per-analysis ₹99 purchases are non-refundable once unlocked." },
  { q: "Is this investment advice?", a: "No. YieldIQ is a quantitative research tool. All outputs are model-generated estimates for educational purposes only. YieldIQ is not registered with SEBI as an investment adviser or research analyst." },
]

function ctaFor(plan: Plan, billing: Billing, userTier: Tier | null, loggedIn: boolean): { href: string; label: string; disabled: boolean } {
  // Already on this plan → show "Current plan" disabled state
  if (loggedIn && userTier === plan.id) {
    return { href: "/account", label: "Current plan", disabled: true }
  }
  // Free tier button — send to signup if logged out, otherwise hide (show manage link)
  if (plan.id === "free") {
    return loggedIn
      ? { href: "/account", label: "Manage account", disabled: false }
      : { href: "/auth/signup", label: "Get Started Free", disabled: false }
  }
  // Paid plans
  if (loggedIn) {
    // Logged-in users go straight to the in-app upgrade flow
    return {
      href: `/account?upgrade=${plan.id}&billing=${billing}`,
      label: plan.id === "pro" ? "Upgrade to Pro \u2192" : "Upgrade to Analyst \u2192",
      disabled: false,
    }
  }
  // Logged-out — go to signup with a redirect hint
  return {
    href: `/auth/signup?next=${encodeURIComponent(`/account?upgrade=${plan.id}&billing=${billing}`)}`,
    label: plan.id === "pro" ? "Start 7-Day Free Trial \u2192" : "Get Analyst Access \u2192",
    disabled: false,
  }
}

export default function PricingPage() {
  const tier = useAuthStore((s) => s.tier)
  const token = useAuthStore((s) => s.token)
  const loggedIn = !!token
  const [billing, setBilling] = useState<Billing>("monthly")

  // GA4: fire pricing_viewed once on mount. Captures tier so we can
  // segment upgrade-funnel metrics by audience (cold traffic vs.
  // existing free users vs. upsell attempts on paid users).
  useEffect(() => {
    trackPricingViewed(loggedIn, tier || "anonymous")
  }, [loggedIn, tier])

  const handleBillingToggle = (next: Billing) => {
    if (next !== billing) trackBillingToggled(next)
    setBilling(next)
  }

  return (
    <div className="bg-bg dark:bg-surface text-ink">
      {/* Hero */}
      <section className="bg-gradient-to-br from-[#080E1A] via-[#0F172A] to-[#1E293B] py-10 md:py-14">
        <div className="max-w-4xl mx-auto px-4 text-center">
          <h1 className="text-3xl md:text-5xl font-black text-white mb-3">Simple Pricing. No Surprises.</h1>
          <p className="text-caption text-base md:text-lg">Start free. Upgrade when you need more power. Cancel anytime.</p>
        </div>
      </section>

      {/* Pricing Cards */}
      <section className="py-10 md:py-16 bg-bg dark:bg-surface">
        <div className="max-w-6xl mx-auto px-4">
          {/* Billing toggle */}
          <div className="flex justify-center mb-8">
            <div className="inline-flex bg-bg dark:bg-surface border border-border rounded-xl p-1 shadow-sm">
              <button
                onClick={() => handleBillingToggle("monthly")}
                className={`px-4 py-2 min-h-[40px] rounded-lg text-sm font-semibold transition ${billing === "monthly" ? "bg-blue-600 text-white shadow" : "text-body hover:text-ink"}`}
              >
                Monthly
              </button>
              <button
                onClick={() => handleBillingToggle("annual")}
                className={`px-4 py-2 min-h-[40px] rounded-lg text-sm font-semibold transition inline-flex items-center gap-2 ${billing === "annual" ? "bg-blue-600 text-white shadow" : "text-body hover:text-ink"}`}
              >
                Annual
                <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${billing === "annual" ? "bg-bg dark:bg-bg/90 text-blue-700 dark:text-blue-300" : "bg-green-100 text-green-700 dark:bg-emerald-950/40 dark:text-emerald-300"}`}>
                  Save ~17%
                </span>
              </button>
            </div>
          </div>

          <div className="grid md:grid-cols-3 gap-8 max-w-5xl mx-auto">
            {/* 2026-06-07: filter out tiers flagged `hidden: true` in
                @/config/pricing. Currently hides Pro for the
                simplification launch; the tier itself stays in `plans`
                and in PRICING_TIERS so backend Razorpay wiring + future
                reactivation remain a single-flag flip. */}
            {plans.filter((p) => !tierById(p.id)?.hidden).map((plan) => {
              const price = billing === "annual" ? plan.annual : plan.monthly
              const period = plan.id === "free"
                ? "/forever"
                : billing === "annual" ? "/year" : "/month"
              // null \u2192 tier variant not yet priced (e.g. mid-revision). Card
              // shows "Coming soon" in place of the numeric headline.
              const priceStr = price === null
                ? "Coming soon"
                : price === 0 ? "\u20B90" : `\u20B9${price.toLocaleString("en-IN")}`
              // Launch-pricing strikethrough + badge. Only applies to
              // monthly view, and only for tiers configured in
              // LAUNCH_DISCOUNT.originalPrices (analyst, pro).
              const launch = billing === "monthly" ? getLaunchDiscount(plan.id, "monthly") : null
              // Annual-vs-monthly savings sub-text. Only renders on the
              // annual tab for paid tiers with both prices configured.
              // NOT a launch-discount strikethrough \u2014 annual is a steady
              // "two months free" pattern against the current monthly.
              const annualSavings =
                billing === "annual" && plan.id !== "free" && plan.monthly !== null && plan.annual !== null && plan.annual > 0
                  ? plan.monthly * 12 - plan.annual
                  : null
              const subtitle = plan.id !== "free" && billing === "annual" && price !== null && price > 0
                ? `That\u2019s \u20B9${Math.round(price / 12).toLocaleString("en-IN")}/mo. Cancel anytime.`
                : plan.subtitle
              const cta = ctaFor(plan, billing, (tier as Tier | null) ?? null, loggedIn)
              return (
              <div
                key={plan.name}
                className={
                  plan.highlighted
                    ? "bg-gradient-to-br from-blue-900 to-blue-700 rounded-2xl p-8 text-white relative overflow-hidden shadow-xl"
                    : "bg-bg dark:bg-surface rounded-2xl p-8 border border-border shadow-sm"
                }
              >
                {plan.badge && (
                  <div className="absolute top-4 right-4 bg-yellow-400 text-yellow-900 text-xs font-black px-3 py-1 rounded-full uppercase tracking-wider">
                    {plan.badge}
                  </div>
                )}
                <div className={`text-sm font-bold uppercase tracking-wider mb-3 ${plan.highlighted ? "text-blue-200" : "text-caption"}`}>
                  {plan.name}
                </div>
                {launch && (
                  <div className="flex items-center gap-2 mb-2">
                    <span
                      data-testid={`launch-strikethrough-${plan.id}`}
                      className={`line-through text-lg font-semibold ${plan.highlighted ? "text-blue-200/70" : "text-caption"}`}
                    >
                      ₹{launch.originalPrice.toLocaleString("en-IN")}
                    </span>
                    <span
                      data-testid={`launch-badge-${plan.id}`}
                      className="bg-orange-100 text-orange-800 px-2 py-0.5 rounded-full text-xs font-bold uppercase tracking-wider"
                    >
                      {launch.percentOff}% off — Launch
                    </span>
                  </div>
                )}
                <div className="flex items-baseline gap-1 mb-2">
                  <span className="text-5xl font-black">{priceStr}</span>
                  <span className={plan.highlighted ? "text-blue-200" : "text-caption"}>{period}</span>
                </div>
                {launch && (
                  <p
                    data-testid={`launch-savings-${plan.id}`}
                    className={`text-xs font-semibold mb-2 ${plan.highlighted ? "text-cyan-200" : "text-orange-700"}`}
                  >
                    Save ₹{launch.savings.toLocaleString("en-IN")}/mo during launch
                  </p>
                )}
                {annualSavings !== null && annualSavings > 0 && (
                  <p
                    data-testid={`annual-savings-${plan.id}`}
                    className={`text-xs font-semibold mb-2 ${plan.highlighted ? "text-cyan-200" : "text-green-700"}`}
                  >
                    Save ₹{annualSavings.toLocaleString("en-IN")}/year vs monthly (~17% off)
                  </p>
                )}
                <p className={`text-sm mb-8 ${plan.highlighted ? "text-blue-200" : "text-caption"}`}>{subtitle}</p>

                <ul className="space-y-3 mb-8">
                  {plan.features.map((f) => (
                    <li key={f.text} className={`flex items-start gap-3 text-sm ${!f.included && !plan.highlighted ? "text-caption" : ""}`}>
                      <span className={`font-bold mt-0.5 ${f.included ? (plan.highlighted ? "text-green-300" : "text-green-500") : ""}`}>
                        {f.included ? "\u2713" : "\u2717"}
                      </span>
                      <span>{f.text}</span>
                    </li>
                  ))}
                </ul>

                {cta.disabled ? (
                  <div className={`block w-full text-center py-3 rounded-xl font-semibold ${plan.highlighted ? "bg-bg dark:bg-surface/20 text-white" : "bg-surface text-caption"}`}>
                    {cta.label}
                  </div>
                ) : (
                  <Link
                    href={cta.href}
                    onClick={() => {
                      // GA4: upgrade_clicked (or equivalent for Free tier).
                      // Source = "pricing" so we can compare vs. account-page
                      // clicks (which already fire their own event below).
                      trackUpgradeClicked(plan.id, `pricing:${billing}`)
                    }}
                    className={`block w-full text-center py-3 min-h-[44px] rounded-xl font-semibold transition active:scale-[0.98] ${plan.ctaStyle}`}
                  >
                    {cta.label}
                  </Link>
                )}
              </div>
              )
            })}
          </div>
        </div>
      </section>

      {/* Student / CA articleship tier — sits below the main 3-tier
          grid because it's gated by manual verification (not self-serve)
          and we don't want to clutter the primary upgrade decision.
          Acquisition logic: cheap CAC for a long-tail audience that
          graduates into full-price Analyst once they start earning. */}
      <section className="py-8 md:py-10 bg-bg dark:bg-surface border-t border-border">
        <div className="max-w-4xl mx-auto px-4">
          <div className="rounded-2xl border-2 border-dashed border-blue-200 bg-bg dark:bg-surface p-6 md:p-8 shadow-sm">
            <div className="flex flex-col md:flex-row md:items-start gap-6">
              <div className="flex-1">
                <div className="inline-block text-[10px] font-black uppercase tracking-[0.2em] text-blue-700 bg-blue-50 rounded-full px-3 py-1 mb-2">
                  Verified students &amp; CA articleship
                </div>
                <h3 className="text-xl md:text-2xl font-black text-ink mb-1">
                  Student / CA articleship — {priceLabel("student", "monthly")}/mo
                </h3>
                <p className="text-sm text-caption mb-4">
                  ~75% off Analyst. For verified students and articleship
                  trainees only.
                </p>
                <ul className="space-y-2 text-sm text-ink mb-4">
                  <li className="flex items-start gap-2">
                    <span className="text-green-500 font-bold mt-0.5">&#10003;</span>
                    <span>5 deep analyses per day (same as Analyst)</span>
                  </li>
                  <li className="flex items-start gap-2">
                    <span className="text-green-500 font-bold mt-0.5">&#10003;</span>
                    <span>Watchlist + portfolio</span>
                  </li>
                  <li className="flex items-start gap-2">
                    <span className="text-caption font-bold mt-0.5">&#10007;</span>
                    <span className="text-caption">No Pro tier features (no API, no CSV/PDF export)</span>
                  </li>
                  <li className="flex items-start gap-2">
                    <span className="text-caption font-bold mt-0.5">&#10003;</span>
                    <span>Auto-expires when your graduation / articleship date passes</span>
                  </li>
                </ul>
                <div className="rounded-lg bg-blue-50 border border-blue-100 p-3 text-xs text-blue-900 leading-relaxed">
                  <span className="font-bold">Verification:</span> upload your current
                  student ID OR articleship registration to{" "}
                  <a href="mailto:hello@yieldiq.in" className="underline font-semibold">
                    hello@yieldiq.in
                  </a>{" "}
                  from your YieldIQ signup email. Approval within 24h.
                </div>
              </div>
              <div className="shrink-0 flex flex-col items-stretch gap-2 md:min-w-[200px]">
                <div className="flex items-baseline justify-center gap-1">
                  <span className="text-4xl font-black text-ink">{priceLabel("student", "monthly")}</span>
                  <span className="text-xs text-caption font-semibold">/ month</span>
                </div>
                <a
                  href="mailto:hello@yieldiq.in?subject=Student%20%2F%20CA%20verification%20for%20YieldIQ&body=Hi%20YieldIQ%20team%2C%0A%0AI%27d%20like%20to%20apply%20for%20the%20%E2%82%B9199%2Fmo%20Student%20tier.%20Attached%20is%20my%20current%20student%20ID%20%2F%20articleship%20registration.%0A%0AYieldIQ%20signup%20email%3A%20%0AInstitution%20%2F%20firm%3A%20%0AExpected%20graduation%20%2F%20completion%20date%3A%20%0A%0AThanks."
                  className="inline-flex items-center justify-center px-4 py-2.5 rounded-xl bg-ink text-bg font-semibold text-sm hover:opacity-90 transition"
                >
                  Email verification &rarr;
                </a>
                <p className="text-[11px] text-caption text-center leading-snug">
                  No payment until we approve.
                </p>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Pay-as-you-go strip — for the casual visitor who wants ONE
          analysis and isn't ready for a subscription. ₹99 for 24h
          access to a single ticker. At 8 PAYG analyses the math
          already favours Analyst — a natural self-serve upsell. */}
      <section className="py-10 md:py-12 bg-surface border-y border-border">
        <div className="max-w-4xl mx-auto px-4">
          <div className="rounded-2xl border border-border bg-bg dark:bg-surface p-6 md:p-8 flex flex-col md:flex-row md:items-center gap-4 shadow-sm">
            <div className="flex-1">
              <div className="inline-block text-[10px] font-black uppercase tracking-[0.2em] text-blue-700 bg-blue-50 rounded-full px-3 py-1 mb-2">
                No subscription?
              </div>
              <h3 className="text-xl md:text-2xl font-black text-ink mb-1">
                Just one analysis — {priceLabel("payg", "one_time")}
              </h3>
              <p className="text-sm text-caption leading-relaxed">
                24-hour full access to a single stock: Prism, Fair Value,
                scenarios, Moat, AI summary, and shareable Report Card.
                Perfect if you&apos;re weighing one decision. Upgrade to
                Analyst anytime — most users do within 2-3 analyses.
              </p>
            </div>
            <div className="shrink-0 flex flex-col items-stretch gap-2 md:min-w-[180px]">
              <div className="flex items-baseline justify-center gap-1">
                <span className="text-3xl md:text-4xl font-black text-ink">{priceLabel("payg", "one_time")}</span>
                <span className="text-xs text-caption font-semibold">/ analysis</span>
              </div>
              <Link
                href="/search"
                className="inline-flex items-center justify-center px-4 py-2.5 rounded-xl bg-ink text-bg font-semibold text-sm hover:opacity-90 transition"
              >
                Browse stocks &rarr;
              </Link>
            </div>
          </div>
        </div>
      </section>

      {/* FAQ */}
      <section className="py-12 md:py-16 bg-bg dark:bg-surface">
        <div className="max-w-3xl mx-auto px-4">
          <h2 className="text-2xl font-black text-center mb-8">Frequently Asked Questions</h2>
          <div className="space-y-4">
            {faqs.map((faq) => (
              <div key={faq.q} className="border-b border-border pb-4">
                <h3 className="font-bold mb-1.5 text-sm">{faq.q}</h3>
                <p className="text-caption text-sm">{faq.a}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Footer rendered by (marketing)/layout.tsx via <TrustFooter /> */}
    </div>
  )
}
