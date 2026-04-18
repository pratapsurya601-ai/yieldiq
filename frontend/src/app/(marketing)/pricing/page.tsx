"use client"

import Link from "next/link"
import { useEffect, useState } from "react"
import { useAuthStore } from "@/store/authStore"
import {
  trackPricingViewed,
  trackBillingToggled,
  trackUpgradeClicked,
} from "@/lib/analytics"

function MarketingNav() {
  const [mobileOpen, setMobileOpen] = useState(false)
  return (
    <nav className="sticky top-0 z-50 border-b border-white/5 bg-gradient-to-br from-[#080E1A] via-[#0F172A] to-[#1E293B]">
      <div className="max-w-6xl mx-auto px-4 sm:px-6 py-3 flex items-center justify-between">
        <Link href="/" className="flex items-center gap-2">
          <img src="/logo-new.svg" alt="YieldIQ" className="w-8 h-8 rounded-lg" />
          <span className="text-white font-bold text-lg">YieldIQ</span>
        </Link>
        <div className="hidden md:flex items-center gap-8 text-sm">
          <Link href="/features" className="text-gray-400 hover:text-white transition">Features</Link>
          <Link href="/pricing" className="text-white font-semibold">Pricing</Link>
          <Link href="/auth/signup" className="bg-gradient-to-r from-blue-700 to-cyan-500 text-white font-semibold px-5 py-2 rounded-lg hover:opacity-90 transition">
            Launch App &rarr;
          </Link>
        </div>
        <button onClick={() => setMobileOpen(!mobileOpen)} className="md:hidden text-white">
          <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
          </svg>
        </button>
      </div>
      {mobileOpen && (
        <div className="md:hidden px-4 pb-4 space-y-3">
          <Link href="/features" className="block text-gray-400 hover:text-white text-sm">Features</Link>
          <Link href="/pricing" className="block text-white font-semibold text-sm">Pricing</Link>
          <Link href="/auth/signup" className="block bg-gradient-to-r from-blue-700 to-cyan-500 text-white font-semibold px-5 py-2 rounded-lg text-center text-sm">
            Launch App &rarr;
          </Link>
        </div>
      )}
    </nav>
  )
}

type Tier = "free" | "pro" | "analyst"
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
      { text: "5 analyses per day", included: true },
      { text: "All 6,000+ NSE/BSE stocks", included: true },
      { text: "DCF fair value + Margin of Safety", included: true },
      { text: "Quality score + Piotroski", included: true },
      { text: "Bear / Base / Bull scenarios", included: true },
      { text: "AI summary (short)", included: true },
      { text: "Shareable report card", included: true },
    ],
    ctaStyle: "border-2 border-gray-200 text-gray-700 hover:bg-gray-50",
  },
  {
    id: "pro",
    name: "Pro",
    monthly: 299,
    annual: 2499,
    subtitle: "7-day free trial. Cancel anytime.",
    highlighted: true,
    badge: "Most Popular",
    features: [
      { text: "Unlimited analyses", included: true },
      { text: "Interactive DCF sliders", included: true },
      { text: "Sensitivity heatmap", included: true },
      { text: "Monte Carlo (1,000 sims)", included: true },
      { text: "PDF & Excel export", included: true },
      { text: "10-year financial statements", included: true },
      { text: "50-stock watchlist + 10 alerts", included: true },
    ],
    ctaStyle: "bg-white text-blue-700 font-bold hover:bg-blue-50",
  },
  {
    id: "analyst",
    name: "Analyst",
    monthly: 799,
    annual: 5999,
    subtitle: "For serious investors and analysts.",
    highlighted: false,
    badge: null,
    features: [
      { text: "Everything in Pro", included: true },
      { text: "API access (500 calls/day)", included: true },
      { text: "Bulk screener", included: true },
      { text: "Unlimited watchlist & alerts", included: true },
      { text: "Google Sheets sync", included: true },
      { text: "Priority support", included: true },
      { text: "Early access to new features", included: true },
    ],
    ctaStyle: "border-2 border-gray-200 text-gray-700 hover:bg-gray-50",
  },
]

const faqs = [
  { q: "Can I cancel anytime?", a: "Yes. No lock-in. Cancel from your account settings." },
  { q: "What payment methods do you accept?", a: "UPI, credit/debit cards, and net banking via Razorpay." },
  { q: "Is there a refund policy?", a: "Yes, full refund within 7 days if you\u2019re not satisfied." },
  { q: "Do I need to sign up to use the free tier?", a: "You can run 5 free analyses/day without signing up. Create a free account to save your watchlist and get the full free experience." },
  { q: "How does annual billing work?", a: "Annual plans save you ~2 months. Pro is \u20B92,499/year (\u20B9208/mo) and Analyst is \u20B95,999/year (\u20B9500/mo)." },
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
      <MarketingNav />

      {/* Hero */}
      <section className="bg-gradient-to-br from-[#080E1A] via-[#0F172A] to-[#1E293B] py-20">
        <div className="max-w-4xl mx-auto px-4 text-center">
          <h1 className="text-4xl md:text-5xl font-black text-white mb-4">Simple Pricing. No Surprises.</h1>
          <p className="text-gray-400 text-lg">Start free. Upgrade when you need more power. Cancel anytime.</p>
        </div>
      </section>

      {/* Pricing Cards */}
      <section className="py-20 bg-gray-50">
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
                  Save ~30%
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

      {/* Feature Comparison */}
      <section className="py-20 bg-white">
        <div className="max-w-4xl mx-auto px-4">
          <h2 className="text-2xl font-black text-center mb-12">Compare Plans</h2>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-200">
                  <th className="text-left py-3 pr-4 font-semibold text-gray-500">Feature</th>
                  <th className="text-center py-3 px-4 font-semibold">Free</th>
                  <th className="text-center py-3 px-4 font-semibold text-blue-700">Pro</th>
                  <th className="text-center py-3 px-4 font-semibold">Analyst</th>
                </tr>
              </thead>
              <tbody>
                {[
                  { feature: "Analyses per day", free: "5", pro: "Unlimited", analyst: "Unlimited" },
                  { feature: "Stock coverage", free: "All 6,000+", pro: "All 6,000+", analyst: "All 6,000+" },
                  { feature: "DCF fair value + MoS", free: "\u2713", pro: "\u2713", analyst: "\u2713" },
                  { feature: "Quality score + Piotroski", free: "\u2713", pro: "\u2713", analyst: "\u2713" },
                  { feature: "Bear/Base/Bull scenarios", free: "\u2713", pro: "\u2713", analyst: "\u2713" },
                  { feature: "AI summary", free: "Short", pro: "Full deep-dive", analyst: "Full deep-dive" },
                  { feature: "Peer comparison", free: "Basic", pro: "Full", analyst: "Full" },
                  { feature: "Financial statements", free: "3 years", pro: "10 years", analyst: "10 years" },
                  { feature: "Interactive DCF sliders", free: "\u2717", pro: "\u2713", analyst: "\u2713" },
                  { feature: "Sensitivity heatmap", free: "\u2717", pro: "\u2713", analyst: "\u2713" },
                  { feature: "Monte Carlo simulation", free: "\u2717", pro: "\u2713", analyst: "\u2713" },
                  { feature: "PDF & Excel export", free: "\u2717", pro: "\u2713", analyst: "\u2713" },
                  { feature: "Portfolio X-Ray", free: "\u2717", pro: "\u2713", analyst: "\u2713" },
                  { feature: "Watchlist", free: "5 stocks", pro: "50 stocks", analyst: "Unlimited" },
                  { feature: "Price alerts", free: "\u2717", pro: "10 alerts", analyst: "Unlimited" },
                  { feature: "API access", free: "\u2717", pro: "\u2717", analyst: "500/day" },
                  { feature: "Bulk screener", free: "\u2717", pro: "\u2717", analyst: "\u2713" },
                  { feature: "Google Sheets sync", free: "\u2717", pro: "\u2717", analyst: "\u2713" },
                  { feature: "Priority support", free: "\u2717", pro: "\u2717", analyst: "\u2713" },
                ].map((row) => (
                  <tr key={row.feature} className="border-b border-gray-100">
                    <td className="py-3 pr-4 text-gray-700">{row.feature}</td>
                    <td className="text-center py-3 px-4">{row.free}</td>
                    <td className="text-center py-3 px-4 font-medium">{row.pro}</td>
                    <td className="text-center py-3 px-4">{row.analyst}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </section>

      {/* FAQ */}
      <section className="py-20 bg-gray-50">
        <div className="max-w-3xl mx-auto px-4">
          <h2 className="text-2xl font-black text-center mb-12">Frequently Asked Questions</h2>
          <div className="space-y-6">
            {faqs.map((faq) => (
              <div key={faq.q} className="border-b border-gray-200 pb-6">
                <h3 className="font-bold mb-2">{faq.q}</h3>
                <p className="text-gray-500 text-sm">{faq.a}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="bg-gradient-to-br from-[#080E1A] via-[#0F172A] to-[#1E293B] border-t border-white/5 py-12">
        <div className="max-w-6xl mx-auto px-4 flex flex-col md:flex-row justify-between items-center gap-4">
          <div className="flex items-center gap-2">
            <img src="/logo-new.svg" alt="YieldIQ" className="w-6 h-6 rounded-md" />
            <span className="text-gray-400 text-sm">&copy; 2026 YieldIQ. Made in India.</span>
          </div>
          <div className="flex items-center gap-4 text-xs">
            <Link href="/terms" className="text-gray-500 hover:text-gray-300 transition">Terms</Link>
            <Link href="/privacy" className="text-gray-500 hover:text-gray-300 transition">Privacy</Link>
          </div>
          <p className="text-gray-600 text-xs">
            Model output only &mdash; not investment advice. YieldIQ is not registered with SEBI as an investment adviser.
          </p>
        </div>
      </footer>
    </div>
  )
}
