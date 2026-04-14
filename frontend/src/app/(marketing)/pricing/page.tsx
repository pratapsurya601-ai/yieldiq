"use client"

import Link from "next/link"
import { useState } from "react"

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

const plans = [
  {
    name: "Free",
    price: "\u20B90",
    period: "/month",
    subtitle: "No credit card required",
    highlighted: false,
    badge: null,
    features: [
      { text: "5 analyses per day", included: true },
      { text: "NSE/BSE large caps", included: true },
      { text: "Basic DCF valuation", included: true },
      { text: "Quality Snowflake score", included: true },
      { text: "PDF reports", included: false },
      { text: "Sensitivity heatmap", included: false },
      { text: "Interactive DCF sliders", included: false },
    ],
    cta: "Get Started Free",
    ctaStyle: "border-2 border-gray-200 text-gray-700 hover:bg-gray-50",
  },
  {
    name: "Starter",
    price: "\u20B9499",
    period: "/month",
    subtitle: "7-day free trial. Cancel anytime.",
    highlighted: true,
    badge: "Most Popular",
    features: [
      { text: "50 analyses per day", included: true },
      { text: "All 6,000+ stocks (large, mid, small)", included: true },
      { text: "Interactive DCF Engine (live sliders)", included: true },
      { text: "Sensitivity heatmap", included: true },
      { text: "PDF & Excel reports", included: true },
      { text: "Bear / Base / Bull scenarios", included: true },
      { text: "Price alerts & watchlist", included: true },
    ],
    cta: "Start 7-Day Free Trial \u2192",
    ctaStyle: "bg-white text-blue-700 font-bold hover:bg-blue-50",
  },
  {
    name: "Pro",
    price: "\u20B91,999",
    period: "/month",
    subtitle: "For serious investors and analysts.",
    highlighted: false,
    badge: null,
    features: [
      { text: "Unlimited analyses", included: true },
      { text: "Monte Carlo simulation", included: true },
      { text: "API access", included: true },
      { text: "Bulk screener", included: true },
      { text: "Portfolio health dashboard", included: true },
      { text: "AI-powered summary", included: true },
      { text: "Priority support", included: true },
    ],
    cta: "Get Pro Access \u2192",
    ctaStyle: "border-2 border-gray-200 text-gray-700 hover:bg-gray-50",
  },
]

const faqs = [
  { q: "Can I cancel anytime?", a: "Yes. No lock-in. Cancel from your account settings." },
  { q: "What payment methods do you accept?", a: "UPI, credit/debit cards, and net banking via Razorpay." },
  { q: "Is there a refund policy?", a: "Yes, full refund within 7 days if you\u2019re not satisfied." },
  { q: "Do I need to sign up to use the free tier?", a: "You can continue as a guest with 5 free analyses/day. Sign up to save your watchlist and get more features." },
  { q: "Is this investment advice?", a: "No. YieldIQ is a quantitative research tool. All outputs are model-generated estimates for educational purposes only. YieldIQ is not registered with SEBI as an investment adviser or research analyst." },
]

export default function PricingPage() {
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
          <div className="grid md:grid-cols-3 gap-8 max-w-5xl mx-auto">
            {plans.map((plan) => (
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
                  <span className="text-5xl font-black">{plan.price}</span>
                  <span className={plan.highlighted ? "text-blue-200" : "text-gray-400"}>{plan.period}</span>
                </div>
                <p className={`text-sm mb-8 ${plan.highlighted ? "text-blue-200" : "text-gray-400"}`}>{plan.subtitle}</p>

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

                <Link
                  href="/auth/signup"
                  className={`block w-full text-center py-3 rounded-xl font-semibold transition ${plan.ctaStyle}`}
                >
                  {plan.cta}
                </Link>
              </div>
            ))}
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
                  <th className="text-center py-3 px-4 font-semibold text-blue-700">Starter</th>
                  <th className="text-center py-3 px-4 font-semibold">Pro</th>
                </tr>
              </thead>
              <tbody>
                {[
                  { feature: "Analyses per day", free: "5", starter: "50", pro: "Unlimited" },
                  { feature: "Stock coverage", free: "Large cap", starter: "All 6,000+", pro: "All 6,000+" },
                  { feature: "DCF valuation", free: "\u2713", starter: "\u2713", pro: "\u2713" },
                  { feature: "Quality Snowflake", free: "\u2713", starter: "\u2713", pro: "\u2713" },
                  { feature: "Interactive sliders", free: "\u2717", starter: "\u2713", pro: "\u2713" },
                  { feature: "Sensitivity heatmap", free: "\u2717", starter: "\u2713", pro: "\u2713" },
                  { feature: "PDF & Excel reports", free: "\u2717", starter: "\u2713", pro: "\u2713" },
                  { feature: "Scenarios (Bear/Base/Bull)", free: "\u2717", starter: "\u2713", pro: "\u2713" },
                  { feature: "Monte Carlo simulation", free: "\u2717", starter: "\u2717", pro: "\u2713" },
                  { feature: "API access", free: "\u2717", starter: "\u2717", pro: "\u2713" },
                  { feature: "Bulk screener", free: "\u2717", starter: "\u2717", pro: "\u2713" },
                  { feature: "AI summary", free: "\u2717", starter: "\u2717", pro: "\u2713" },
                  { feature: "Priority support", free: "\u2717", starter: "\u2717", pro: "\u2713" },
                ].map((row) => (
                  <tr key={row.feature} className="border-b border-gray-100">
                    <td className="py-3 pr-4 text-gray-700">{row.feature}</td>
                    <td className="text-center py-3 px-4">{row.free}</td>
                    <td className="text-center py-3 px-4 font-medium">{row.starter}</td>
                    <td className="text-center py-3 px-4">{row.pro}</td>
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
          <p className="text-gray-600 text-xs">
            Model output only &mdash; not investment advice. YieldIQ is not registered with SEBI as an investment adviser.
          </p>
        </div>
      </footer>
    </div>
  )
}
