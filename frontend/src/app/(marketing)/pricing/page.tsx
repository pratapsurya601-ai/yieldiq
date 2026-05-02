"use client"

import Link from "next/link"
import { useEffect, useState } from "react"
import { useAuthStore } from "@/store/authStore"
import {
  trackPricingViewed,
  trackBillingToggled,
  trackUpgradeClicked,
} from "@/lib/analytics"

// Nav is now provided by (marketing)/layout.tsx via the unified MarketingTopNav.

type Tier = "free" | "analyst" | "pro"
type Billing = "monthly" | "annual"

interface Plan {
  id: Tier
  name: string
  monthly: number
  annual: number // per-year price; display as /year
  subtitle: string
  highlighted: boolean
  badge: string | null
  features: { text: string; included: boolean }[]
  ctaStyle: string
}

// 2026-04-21 restructure: dropped ₹299 Starter, added ₹99 pay-as-you-go,
// kept ₹799 Analyst as the sweet spot, added ₹1,499 Pro for power users.
// 2026-05-02: rebased Annual plans to a sharper "trust us with a year"
// discount — Analyst ₹4,999/yr (~48% off vs ₹799×12) and Pro ₹9,999/yr
// (~44% off vs ₹1,499×12). Old ₹6,999 / ₹13,999 anchors retired.
// Rationale is in docs/pricing_analysis.md (see this PR).
const plans: Plan[] = [
  {
    id: "free",
    name: "Free",
    monthly: 0,
    annual: 0,
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
    ctaStyle: "border-2 border-gray-200 text-gray-700 hover:bg-gray-50",
  },
  {
    id: "analyst",
    name: "Analyst",
    monthly: 799,
    annual: 4999,
    subtitle: "The sweet spot for serious DIY investors.",
    highlighted: true,
    badge: "Most Popular",
    features: [
      { text: "Unlimited analyses", included: true },
      { text: "Unlimited watchlist & alerts", included: true },
      { text: "5 broker accounts / multi-account portfolio", included: true },
      { text: "Portfolio Prism + Portfolio Health score", included: true },
      { text: "AI summaries (Groq, sub-second)", included: true },
      { text: "Concall AI transcript summaries", included: true },
      { text: "Full Time Machine (12-month score trend)", included: true },
      { text: "Tax Report (capital gains calc) — FY 2025-26 logic per Budget 2024", included: true },
      { text: "Compare up to 3 stocks side-by-side", included: true },
    ],
    ctaStyle: "bg-white text-blue-700 font-bold hover:bg-blue-50",
  },
  {
    id: "pro",
    name: "Pro",
    monthly: 1499,
    annual: 9999,
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
    ctaStyle: "border-2 border-gray-200 text-gray-700 hover:bg-gray-50",
  },
]

const faqs = [
  { q: "Can I cancel anytime?", a: "Yes. No lock-in on monthly plans — cancel from your account settings and you won\u2019t be charged next cycle. Annual plans are non-refundable beyond the 7-day money-back window (below)." },
  { q: "What\u2019s the difference between Analyst and Pro?", a: "Analyst covers unlimited analyses, the Portfolio Prism, multi-account import, AI summaries, and Concall AI \u2014 the sweet spot for most serious DIY investors. Pro adds CSV/PDF export, API access (100 req/day), save-and-share custom screens, and priority compute \u2014 built for bloggers, newsletter writers, and advisors." },
  { q: "How does the ₹99 per-analysis option work?", a: "Pay ₹99 once for 24-hour full access to one stock \u2014 Prism, Fair Value, scenarios, Moat, AI summary, Compare, Report Card. Great if you\u2019re weighing a single decision. Upgrade to Analyst anytime; what you\u2019ve already paid for stays unlocked." },
  { q: "Do you have annual plans?", a: "Yes. Analyst is ₹4,999/year (save ~48% vs monthly × 12) and Pro is ₹9,999/year (save ~44%). Annual users get priority support and first access to new features." },
  { q: "Why annual?", a: "It signals you trust us with a year. We give you ~half off in return. Simple deal — less churn for us, materially cheaper for you." },
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
    <div className="bg-white text-gray-900">
      {/* Hero */}
      <section className="bg-gradient-to-br from-[#080E1A] via-[#0F172A] to-[#1E293B] py-10 md:py-14">
        <div className="max-w-4xl mx-auto px-4 text-center">
          <h1 className="text-3xl md:text-5xl font-black text-white mb-3">Simple Pricing. No Surprises.</h1>
          <p className="text-gray-400 text-base md:text-lg">Start free. Upgrade when you need more power. Cancel anytime.</p>
        </div>
      </section>

      {/* Pricing Cards */}
      <section className="py-10 md:py-16 bg-gray-50">
        <div className="max-w-6xl mx-auto px-4">
          {/* Billing toggle */}
          <div className="flex justify-center mb-10">
            <div className="inline-flex bg-white border border-gray-200 rounded-xl p-1 shadow-sm">
              <button
                onClick={() => handleBillingToggle("monthly")}
                className={`px-5 py-2 min-h-[40px] rounded-lg text-sm font-semibold transition ${billing === "monthly" ? "bg-blue-600 text-white shadow" : "text-gray-600 hover:text-gray-900"}`}
              >
                Monthly
              </button>
              <button
                onClick={() => handleBillingToggle("annual")}
                className={`px-5 py-2 min-h-[40px] rounded-lg text-sm font-semibold transition inline-flex items-center gap-2 ${billing === "annual" ? "bg-blue-600 text-white shadow" : "text-gray-600 hover:text-gray-900"}`}
              >
                Annual
                <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${billing === "annual" ? "bg-white text-blue-700" : "bg-green-100 text-green-700"}`}>
                  Save up to 48%
                </span>
              </button>
            </div>
          </div>

          <div className="grid md:grid-cols-3 gap-8 max-w-5xl mx-auto">
            {plans.map((plan) => {
              const price = billing === "annual" ? plan.annual : plan.monthly
              const period = plan.id === "free"
                ? "/forever"
                : billing === "annual" ? "/year" : "/month"
              const priceStr = price === 0 ? "\u20B90" : `\u20B9${price.toLocaleString("en-IN")}`
              const subtitle = plan.id !== "free" && billing === "annual"
                ? `That\u2019s \u20B9${Math.round(price / 12).toLocaleString("en-IN")}/mo. Cancel anytime.`
                : plan.subtitle
              const cta = ctaFor(plan, billing, (tier as Tier | null) ?? null, loggedIn)
              return (
              <div
                key={plan.name}
                className={
                  plan.highlighted
                    ? "bg-gradient-to-br from-blue-900 to-blue-700 rounded-2xl p-8 text-white relative overflow-hidden shadow-xl"
                    : "bg-white rounded-2xl p-8 border border-gray-200 shadow-sm"
                }
              >
                {plan.badge && (
                  <div className="absolute top-4 right-4 bg-yellow-400 text-yellow-900 text-xs font-black px-3 py-1 rounded-full uppercase tracking-wider">
                    {plan.badge}
                  </div>
                )}
                <div className={`text-sm font-bold uppercase tracking-wider mb-3 ${plan.highlighted ? "text-blue-200" : "text-gray-500"}`}>
                  {plan.name}
                </div>
                <div className="flex items-baseline gap-1 mb-2">
                  <span className="text-5xl font-black">{priceStr}</span>
                  <span className={plan.highlighted ? "text-blue-200" : "text-gray-400"}>{period}</span>
                </div>
                <p className={`text-sm mb-8 ${plan.highlighted ? "text-blue-200" : "text-gray-400"}`}>{subtitle}</p>

                <ul className="space-y-3 mb-8">
                  {plan.features.map((f) => (
                    <li key={f.text} className={`flex items-start gap-3 text-sm ${!f.included && !plan.highlighted ? "text-gray-400" : ""}`}>
                      <span className={`font-bold mt-0.5 ${f.included ? (plan.highlighted ? "text-green-300" : "text-green-500") : ""}`}>
                        {f.included ? "\u2713" : "\u2717"}
                      </span>
                      <span>{f.text}</span>
                    </li>
                  ))}
                </ul>

                {cta.disabled ? (
                  <div className={`block w-full text-center py-3 rounded-xl font-semibold ${plan.highlighted ? "bg-white/20 text-white" : "bg-gray-100 text-gray-500"}`}>
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
      <section className="py-8 md:py-10 bg-gray-50 border-t border-gray-100">
        <div className="max-w-4xl mx-auto px-4">
          <div className="rounded-2xl border-2 border-dashed border-blue-200 bg-white p-6 md:p-8 shadow-sm">
            <div className="flex flex-col md:flex-row md:items-start gap-6">
              <div className="flex-1">
                <div className="inline-block text-[10px] font-black uppercase tracking-[0.2em] text-blue-700 bg-blue-50 rounded-full px-3 py-1 mb-2">
                  Verified students &amp; CA articleship
                </div>
                <h3 className="text-xl md:text-2xl font-black text-gray-900 mb-1">
                  Student / CA articleship — &#8377;199/mo
                </h3>
                <p className="text-sm text-gray-500 mb-4">
                  ~75% off Analyst. For verified students and articleship
                  trainees only.
                </p>
                <ul className="space-y-2 text-sm text-gray-700 mb-4">
                  <li className="flex items-start gap-2">
                    <span className="text-green-500 font-bold mt-0.5">&#10003;</span>
                    <span>5 deep analyses per day (same as Analyst)</span>
                  </li>
                  <li className="flex items-start gap-2">
                    <span className="text-green-500 font-bold mt-0.5">&#10003;</span>
                    <span>Watchlist + portfolio</span>
                  </li>
                  <li className="flex items-start gap-2">
                    <span className="text-gray-400 font-bold mt-0.5">&#10007;</span>
                    <span className="text-gray-500">No Pro tier features (no API, no CSV/PDF export)</span>
                  </li>
                  <li className="flex items-start gap-2">
                    <span className="text-gray-400 font-bold mt-0.5">&#10003;</span>
                    <span>Auto-expires when your graduation / articleship date passes</span>
                  </li>
                </ul>
                <div className="rounded-lg bg-blue-50 border border-blue-100 p-3 text-xs text-blue-900 leading-relaxed">
                  <strong>Verification:</strong> upload your current
                  student ID OR articleship registration to{" "}
                  <a href="mailto:hello@yieldiq.in" className="underline font-semibold">
                    hello@yieldiq.in
                  </a>{" "}
                  from your YieldIQ signup email. Approval within 24h.
                </div>
              </div>
              <div className="shrink-0 flex flex-col items-stretch gap-2 md:min-w-[200px]">
                <div className="flex items-baseline justify-center gap-1">
                  <span className="text-4xl font-black text-gray-900">&#8377;199</span>
                  <span className="text-xs text-gray-400 font-semibold">/ month</span>
                </div>
                <a
                  href="mailto:hello@yieldiq.in?subject=Student%20%2F%20CA%20verification%20for%20YieldIQ&body=Hi%20YieldIQ%20team%2C%0A%0AI%27d%20like%20to%20apply%20for%20the%20%E2%82%B9199%2Fmo%20Student%20tier.%20Attached%20is%20my%20current%20student%20ID%20%2F%20articleship%20registration.%0A%0AYieldIQ%20signup%20email%3A%20%0AInstitution%20%2F%20firm%3A%20%0AExpected%20graduation%20%2F%20completion%20date%3A%20%0A%0AThanks."
                  className="inline-flex items-center justify-center px-5 py-2.5 rounded-xl bg-gray-900 text-white font-semibold text-sm hover:bg-gray-800 transition"
                >
                  Email verification &rarr;
                </a>
                <p className="text-[11px] text-gray-400 text-center leading-snug">
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
      <section className="py-10 md:py-12 bg-gradient-to-br from-gray-50 to-white border-y border-gray-100">
        <div className="max-w-4xl mx-auto px-4">
          <div className="rounded-2xl border border-gray-200 bg-white p-6 md:p-8 flex flex-col md:flex-row md:items-center gap-5 shadow-sm">
            <div className="flex-1">
              <div className="inline-block text-[10px] font-black uppercase tracking-[0.2em] text-blue-700 bg-blue-50 rounded-full px-3 py-1 mb-2">
                No subscription?
              </div>
              <h3 className="text-xl md:text-2xl font-black text-gray-900 mb-1">
                Just one analysis — ₹99
              </h3>
              <p className="text-sm text-gray-500 leading-relaxed">
                24-hour full access to a single stock: Prism, Fair Value,
                scenarios, Moat, AI summary, and shareable Report Card.
                Perfect if you&apos;re weighing one decision. Upgrade to
                Analyst anytime — most users do within 2-3 analyses.
              </p>
            </div>
            <div className="shrink-0 flex flex-col items-stretch gap-2 md:min-w-[180px]">
              <div className="flex items-baseline justify-center gap-1">
                <span className="text-3xl md:text-4xl font-black text-gray-900">&#8377;99</span>
                <span className="text-xs text-gray-400 font-semibold">/ analysis</span>
              </div>
              <Link
                href="/search"
                className="inline-flex items-center justify-center px-5 py-2.5 rounded-xl bg-gray-900 text-white font-semibold text-sm hover:bg-gray-800 transition"
              >
                Browse stocks &rarr;
              </Link>
            </div>
          </div>
        </div>
      </section>

      {/* FAQ */}
      <section className="py-12 md:py-16 bg-white">
        <div className="max-w-3xl mx-auto px-4">
          <h2 className="text-2xl font-black text-center mb-8">Frequently Asked Questions</h2>
          <div className="space-y-5">
            {faqs.map((faq) => (
              <div key={faq.q} className="border-b border-gray-200 pb-4">
                <h3 className="font-bold mb-1.5 text-sm">{faq.q}</h3>
                <p className="text-gray-500 text-sm">{faq.a}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Footer rendered by (marketing)/layout.tsx via <TrustFooter /> */}
    </div>
  )
}
