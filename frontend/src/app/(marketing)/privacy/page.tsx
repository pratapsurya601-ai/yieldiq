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

export default function PrivacyPolicyPage() {
  return (
    <div className="bg-white text-gray-900 min-h-screen">
      <MarketingNav />

      <div className="max-w-3xl mx-auto px-4 sm:px-6 py-12">
        <h1 className="text-3xl font-black text-gray-900 mb-2">Privacy Policy</h1>
        <p className="text-sm text-gray-400 mb-8">Last updated: April 14, 2026</p>

        <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 mb-8">
          <p className="text-sm text-amber-800 font-semibold mb-1">SEBI Disclaimer</p>
          <p className="text-sm text-amber-700">
            YieldIQ is not registered with SEBI as an investment adviser or research analyst. We
            collect data solely to provide our quantitative analysis service. We do not share your
            personal data with any financial institution or use it for investment recommendations.
          </p>
        </div>

        <div className="prose prose-gray prose-sm max-w-none space-y-8">

          {/* 1. Information We Collect */}
          <section>
            <h2 className="text-lg font-bold text-gray-900 mb-3">1. Information We Collect</h2>
            <p className="text-gray-600 leading-relaxed">We collect the following types of information:</p>
            <ul className="list-disc pl-5 text-gray-600 space-y-1 mt-2">
              <li>
                <strong>Account information:</strong> Email address and name when you sign up. We use
                email/OTP-based authentication &mdash; we do not collect passwords.
              </li>
              <li>
                <strong>Usage data:</strong> Stocks you analyse, watchlist items, alerts you set, and
                how you interact with the Service (page views, feature usage, session duration).
              </li>
              <li>
                <strong>Device &amp; browser data:</strong> IP address, browser type, operating system,
                device type, and screen resolution. This is collected automatically via analytics tools.
              </li>
              <li>
                <strong>Payment data:</strong> Payment transactions are processed by Razorpay. We receive
                confirmation of payment status but do not store card numbers or bank account details on
                our servers.
              </li>
            </ul>
            <p className="text-gray-600 leading-relaxed mt-2">
              We do not collect any financial portfolio data from external sources. Any holdings data
              you enter is provided voluntarily and stored only to power your portfolio dashboard.
            </p>
          </section>

          {/* 2. How We Use Your Information */}
          <section>
            <h2 className="text-lg font-bold text-gray-900 mb-3">2. How We Use Your Information</h2>
            <ul className="list-disc pl-5 text-gray-600 space-y-1">
              <li>To provide, maintain, and improve the Service</li>
              <li>To send transactional emails (account verification, password resets, price alerts)</li>
              <li>To process subscriptions and payments</li>
              <li>To understand how users interact with our product (aggregated analytics)</li>
              <li>To detect and prevent abuse or fraud</li>
              <li>To comply with legal obligations</li>
            </ul>
            <p className="text-gray-600 leading-relaxed mt-2">
              We do not sell your personal data to third parties. We do not use your data to provide
              personalized investment advice or recommendations.
            </p>
          </section>

          {/* 3. Data Storage */}
          <section>
            <h2 className="text-lg font-bold text-gray-900 mb-3">3. Data Storage</h2>
            <p className="text-gray-600 leading-relaxed">
              Your data is stored on cloud infrastructure provided by the following services:
            </p>
            <ul className="list-disc pl-5 text-gray-600 space-y-1 mt-2">
              <li><strong>Supabase:</strong> User authentication and account data (hosted on AWS).</li>
              <li><strong>Aiven:</strong> Application database (PostgreSQL) for analysis results, watchlists, alerts, and usage data.</li>
              <li><strong>Railway:</strong> Backend API hosting and task processing.</li>
              <li><strong>Vercel:</strong> Frontend hosting and edge delivery.</li>
            </ul>
            <p className="text-gray-600 leading-relaxed mt-2">
              All data is transmitted over HTTPS. Database connections use TLS encryption. We follow
              industry-standard practices for securing cloud infrastructure, but no system is 100%
              secure. We cannot guarantee absolute security.
            </p>
          </section>

          {/* 4. Third-Party Services */}
          <section>
            <h2 className="text-lg font-bold text-gray-900 mb-3">4. Third-Party Services</h2>
            <p className="text-gray-600 leading-relaxed">
              We use the following third-party services that may collect data independently under
              their own privacy policies:
            </p>
            <ul className="list-disc pl-5 text-gray-600 space-y-1 mt-2">
              <li><strong>Razorpay:</strong> Payment processing. Subject to <a href="https://razorpay.com/privacy/" target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:underline">Razorpay&apos;s Privacy Policy</a>.</li>
              <li><strong>SendGrid:</strong> Transactional email delivery (price alerts, OTP codes).</li>
              <li><strong>Google Analytics (GA4):</strong> Aggregated website analytics &mdash; page views, user flows, demographics.</li>
              <li><strong>Microsoft Clarity:</strong> Session recordings and heatmaps to understand user interaction patterns. Clarity masks sensitive input fields by default.</li>
              <li><strong>Vercel Analytics:</strong> Performance monitoring and web vitals.</li>
            </ul>
          </section>

          {/* 5. Cookies */}
          <section>
            <h2 className="text-lg font-bold text-gray-900 mb-3">5. Cookies</h2>
            <p className="text-gray-600 leading-relaxed">We use cookies and similar technologies for:</p>
            <ul className="list-disc pl-5 text-gray-600 space-y-1 mt-2">
              <li><strong>Essential cookies:</strong> Authentication session tokens. Required for the Service to function.</li>
              <li><strong>Analytics cookies:</strong> Google Analytics and Microsoft Clarity use cookies to track anonymous usage patterns.</li>
              <li><strong>Preference cookies:</strong> To remember your settings (e.g., theme, last viewed stocks).</li>
            </ul>
            <p className="text-gray-600 leading-relaxed mt-2">
              You can disable non-essential cookies through your browser settings, though this may
              affect some features.
            </p>
          </section>

          {/* 6. Data Retention */}
          <section>
            <h2 className="text-lg font-bold text-gray-900 mb-3">6. Data Retention</h2>
            <p className="text-gray-600 leading-relaxed">
              We retain your account data for as long as your account is active. If you delete your
              account, we will remove your personal data within 30 days, except where we are required
              to retain it for legal or financial record-keeping purposes (e.g., payment records may
              be retained for up to 7 years as required by Indian tax law).
            </p>
            <p className="text-gray-600 leading-relaxed mt-2">
              Aggregated, anonymized analytics data may be retained indefinitely as it cannot be
              used to identify you.
            </p>
          </section>

          {/* 7. Your Rights */}
          <section>
            <h2 className="text-lg font-bold text-gray-900 mb-3">7. Your Rights</h2>
            <p className="text-gray-600 leading-relaxed">You have the right to:</p>
            <ul className="list-disc pl-5 text-gray-600 space-y-1 mt-2">
              {/* sebi-allow: hold */}
              <li><strong>Access:</strong> Request a copy of the personal data we hold about you.</li>
              <li><strong>Correction:</strong> Request correction of inaccurate data.</li>
              <li><strong>Deletion:</strong> Request deletion of your account and associated data.</li>
              <li><strong>Export:</strong> Request your data in a portable format.</li>
              <li><strong>Withdraw consent:</strong> Opt out of non-essential data collection at any time.</li>
            </ul>
            <p className="text-gray-600 leading-relaxed mt-2">
              To exercise any of these rights, email us at{" "}
              <a href="mailto:hello@yieldiq.in" className="text-blue-600 hover:underline">hello@yieldiq.in</a>.
              We will respond within 30 days.
            </p>
          </section>

          {/* 8. Children's Privacy */}
          <section>
            <h2 className="text-lg font-bold text-gray-900 mb-3">8. Children&apos;s Privacy</h2>
            <p className="text-gray-600 leading-relaxed">
              YieldIQ is not intended for use by anyone under the age of 18. We do not knowingly
              collect personal data from children. If we learn that we have collected data from a
              child under 18, we will delete it promptly.
            </p>
          </section>

          {/* 9. Changes to Policy */}
          <section>
            <h2 className="text-lg font-bold text-gray-900 mb-3">9. Changes to This Policy</h2>
            <p className="text-gray-600 leading-relaxed">
              We may update this Privacy Policy from time to time. Material changes will be
              communicated via email or a notice on the Service. The &quot;Last updated&quot; date at the top
              of this page reflects the most recent revision.
            </p>
          </section>

          {/* 10. Contact */}
          <section>
            <h2 className="text-lg font-bold text-gray-900 mb-3">10. Contact</h2>
            <p className="text-gray-600 leading-relaxed">
              For questions or concerns about this Privacy Policy, contact us at:{" "}
              <a href="mailto:hello@yieldiq.in" className="text-blue-600 hover:underline">
                hello@yieldiq.in
              </a>
            </p>
          </section>
        </div>

        <div className="mt-12 pt-8 border-t border-gray-100 flex items-center justify-between text-sm text-gray-400">
          <Link href="/terms" className="hover:text-gray-600 transition">Terms of Service</Link>
          <Link href="/" className="hover:text-gray-600 transition">Back to Home</Link>
        </div>
      </div>
    </div>
  )
}
