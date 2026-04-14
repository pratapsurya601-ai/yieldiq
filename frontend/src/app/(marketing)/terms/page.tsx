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
          <Link href="/pricing" className="text-gray-400 hover:text-white transition">Pricing</Link>
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
          <Link href="/pricing" className="block text-gray-400 hover:text-white text-sm">Pricing</Link>
          <Link href="/auth/signup" className="block bg-gradient-to-r from-blue-700 to-cyan-500 text-white font-semibold px-5 py-2 rounded-lg text-center text-sm">
            Launch App &rarr;
          </Link>
        </div>
      )}
    </nav>
  )
}

export default function TermsOfServicePage() {
  return (
    <div className="bg-white text-gray-900 min-h-screen">
      <MarketingNav />

      <div className="max-w-3xl mx-auto px-4 sm:px-6 py-12">
        <h1 className="text-3xl font-black text-gray-900 mb-2">Terms of Service</h1>
        <p className="text-sm text-gray-400 mb-8">Last updated: April 14, 2026</p>

        <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 mb-8">
          <p className="text-sm text-amber-800 font-semibold mb-1">SEBI Disclaimer</p>
          <p className="text-sm text-amber-700">
            YieldIQ is not registered with the Securities and Exchange Board of India (SEBI) as an
            investment adviser, research analyst, or portfolio manager. The service provides
            quantitative analysis tools for educational and informational purposes only. Nothing on
            this platform constitutes investment advice, a recommendation, or solicitation to buy or
            sell any security.
          </p>
        </div>

        <div className="prose prose-gray prose-sm max-w-none space-y-8">

          {/* 1. Acceptance of Terms */}
          <section>
            <h2 className="text-lg font-bold text-gray-900 mb-3">1. Acceptance of Terms</h2>
            <p className="text-gray-600 leading-relaxed">
              By accessing or using YieldIQ (&quot;the Service&quot;), operated by YieldIQ (&quot;we&quot;, &quot;us&quot;, or &quot;our&quot;),
              you agree to be bound by these Terms of Service. If you do not agree to these terms, do
              not use the Service. We may update these terms from time to time, and your continued use
              of the Service after such changes constitutes acceptance of the updated terms.
            </p>
          </section>

          {/* 2. Description of Service */}
          <section>
            <h2 className="text-lg font-bold text-gray-900 mb-3">2. Description of Service</h2>
            <p className="text-gray-600 leading-relaxed">
              YieldIQ is a software-as-a-service (SaaS) platform that provides Discounted Cash Flow
              (DCF) valuation models, financial quality scores, and quantitative analysis for publicly
              listed stocks on the National Stock Exchange (NSE) and Bombay Stock Exchange (BSE) of India.
            </p>
            <p className="text-gray-600 leading-relaxed mt-2">
              The Service generates model-based estimates using publicly available financial data. These
              outputs are mathematical calculations based on stated assumptions and are provided for
              educational and informational purposes only. The Service does not provide investment advice,
              personal financial recommendations, or portfolio management services.
            </p>
          </section>

          {/* 3. User Accounts */}
          <section>
            <h2 className="text-lg font-bold text-gray-900 mb-3">3. User Accounts</h2>
            <p className="text-gray-600 leading-relaxed">
              You may use limited features as a guest. To access full features, you must create an
              account by providing a valid email address. You are responsible for maintaining the
              confidentiality of your account credentials and for all activity that occurs under your
              account. You must notify us immediately of any unauthorized use.
            </p>
            <p className="text-gray-600 leading-relaxed mt-2">
              You must be at least 18 years old to create an account. One person or entity may not
              maintain more than one free account.
            </p>
          </section>

          {/* 4. Subscription & Payments */}
          <section>
            <h2 className="text-lg font-bold text-gray-900 mb-3">4. Subscription &amp; Payments</h2>
            <p className="text-gray-600 leading-relaxed">
              YieldIQ offers free and paid subscription plans. Paid subscriptions are billed monthly
              or annually as selected at the time of purchase. Payments are processed securely through
              Razorpay. We do not store your payment card details on our servers.
            </p>
            <ul className="list-disc pl-5 text-gray-600 space-y-1 mt-2">
              <li>Free trial: Starter plan includes a 7-day free trial. You will be charged at the
                end of the trial unless you cancel before it expires.</li>
              <li>Cancellation: You may cancel your subscription at any time from your account settings.
                Access continues until the end of the current billing period.</li>
              <li>Refunds: Full refund within 7 days of your first paid charge if you are not satisfied.
                Refunds after 7 days are not available. Contact hello@yieldiq.in for refund requests.</li>
              <li>Price changes: We may adjust pricing with 30 days&apos; notice. Existing subscribers
                retain their rate until the next renewal.</li>
            </ul>
          </section>

          {/* 5. Intellectual Property */}
          <section>
            <h2 className="text-lg font-bold text-gray-900 mb-3">5. Intellectual Property</h2>
            <p className="text-gray-600 leading-relaxed">
              All content, software, algorithms, design, and branding on the Service are the
              intellectual property of YieldIQ. You may not reproduce, distribute, reverse-engineer,
              or create derivative works from the Service without our prior written consent.
            </p>
            <p className="text-gray-600 leading-relaxed mt-2">
              You retain ownership of any data you provide (e.g., watchlists, portfolio holdings).
              By using the Service, you grant us a limited license to process your data solely to
              provide the Service to you.
            </p>
          </section>

          {/* 6. Disclaimer */}
          <section>
            <h2 className="text-lg font-bold text-gray-900 mb-3">6. Disclaimer</h2>
            <div className="bg-red-50 border border-red-200 rounded-lg p-4">
              <p className="text-sm text-red-800 leading-relaxed">
                <strong>YieldIQ is NOT investment advice.</strong> The Service is a quantitative
                research tool that generates model-based estimates. All fair value calculations,
                scores, and verdicts are outputs of mathematical models based on assumptions that
                may or may not reflect reality.
              </p>
              <p className="text-sm text-red-800 leading-relaxed mt-2">
                YieldIQ is not registered with SEBI as an investment adviser or research analyst.
                We do not recommend any specific stocks. Past model outputs do not predict future
                results. Always consult a qualified, SEBI-registered financial adviser before making
                investment decisions.
              </p>
              <p className="text-sm text-red-800 leading-relaxed mt-2">
                The financial data used by the Service is sourced from third-party providers and
                may contain errors, delays, or omissions. We do not guarantee the accuracy,
                completeness, or timeliness of any data or model output.
              </p>
            </div>
          </section>

          {/* 7. Limitation of Liability */}
          <section>
            <h2 className="text-lg font-bold text-gray-900 mb-3">7. Limitation of Liability</h2>
            <p className="text-gray-600 leading-relaxed">
              To the maximum extent permitted by applicable law, YieldIQ and its founders, employees,
              and affiliates shall not be liable for any indirect, incidental, special, consequential,
              or punitive damages, including but not limited to loss of profits, data, or investment
              losses, arising out of or related to your use of the Service.
            </p>
            <p className="text-gray-600 leading-relaxed mt-2">
              Our total liability for any claim arising from the Service shall not exceed the amount
              you paid to YieldIQ in the 12 months preceding the claim.
            </p>
          </section>

          {/* 8. Governing Law */}
          <section>
            <h2 className="text-lg font-bold text-gray-900 mb-3">8. Governing Law</h2>
            <p className="text-gray-600 leading-relaxed">
              These Terms are governed by and construed in accordance with the laws of India. Any
              disputes arising from or relating to these Terms or the Service shall be subject to the
              exclusive jurisdiction of the courts in Bengaluru, Karnataka, India.
            </p>
          </section>

          {/* 9. Changes to Terms */}
          <section>
            <h2 className="text-lg font-bold text-gray-900 mb-3">9. Changes to Terms</h2>
            <p className="text-gray-600 leading-relaxed">
              We reserve the right to modify these Terms at any time. Material changes will be
              communicated via email or a notice on the Service. Continued use after such changes
              constitutes acceptance. If you disagree with the updated terms, you may cancel your
              account.
            </p>
          </section>

          {/* 10. Contact */}
          <section>
            <h2 className="text-lg font-bold text-gray-900 mb-3">10. Contact</h2>
            <p className="text-gray-600 leading-relaxed">
              For questions about these Terms, contact us at:{" "}
              <a href="mailto:hello@yieldiq.in" className="text-blue-600 hover:underline">
                hello@yieldiq.in
              </a>
            </p>
          </section>
        </div>

        <div className="mt-12 pt-8 border-t border-gray-100 flex items-center justify-between text-sm text-gray-400">
          <Link href="/privacy" className="hover:text-gray-600 transition">Privacy Policy</Link>
          <Link href="/" className="hover:text-gray-600 transition">Back to Home</Link>
        </div>
      </div>
    </div>
  )
}
