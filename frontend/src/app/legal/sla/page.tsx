import type { Metadata } from "next"
import Link from "next/link"

export const metadata: Metadata = {
  title: "Service Level Agreement (SLA) — YieldIQ",
  description:
    "YieldIQ commits to 99.5% monthly uptime for paying tiers, with service credits if we miss the target. Live status at status.yieldiq.in.",
  alternates: { canonical: "https://yieldiq.in/legal/sla" },
}

/**
 * /legal/sla — Public SLA page.
 *
 * Server component. Hardcoded markdown-equivalent JSX so we don't pull in
 * a runtime markdown renderer just for one page. The canonical source is
 * docs/sla.md; keep these two in sync when editing.
 */
export default function SLAPage() {
  return (
    <div className="bg-white text-gray-900 min-h-screen">
      <header className="border-b border-gray-200 bg-gradient-to-br from-[#080E1A] via-[#0F172A] to-[#1E293B]">
        <div className="max-w-3xl mx-auto px-4 sm:px-6 py-4 flex items-center justify-between">
          <Link href="/" className="flex items-center gap-2">
            <img src="/logo-new.svg" alt="YieldIQ" className="w-8 h-8 rounded-lg" />
            <span className="text-white font-bold text-lg">YieldIQ</span>
          </Link>
          <a
            href="https://status.yieldiq.in"
            target="_blank"
            rel="noopener noreferrer"
            className="text-xs sm:text-sm text-cyan-300 hover:text-white transition"
          >
            Live status &rarr;
          </a>
        </div>
      </header>

      <main className="max-w-3xl mx-auto px-4 sm:px-6 py-12">
        <h1 className="text-3xl font-black text-gray-900 mb-2">
          Service Level Agreement
        </h1>
        <p className="text-sm text-gray-500 mb-8">
          Version 1.0 &middot; Effective 27 April 2026
        </p>

        <div className="bg-blue-50 border border-blue-200 rounded-xl p-4 mb-8">
          <p className="text-sm text-blue-900">
            <strong>The short version:</strong> on paying tiers we aim for{" "}
            <strong>99.5% monthly uptime</strong>. If we miss that, you get an
            automatic credit on your next invoice. Live status:{" "}
            <a
              href="https://status.yieldiq.in"
              target="_blank"
              rel="noopener noreferrer"
              className="underline font-medium"
            >
              status.yieldiq.in
            </a>
            .
          </p>
        </div>

        <section className="prose prose-sm sm:prose-base max-w-none">
          <h2 className="text-xl font-bold mt-8 mb-3">1. Uptime commitment</h2>
          <p>
            YieldIQ commits to <strong>99.5% monthly uptime</strong> for the
            paying tier across the web app at{" "}
            <code>https://yieldiq.in</code> and the public API at{" "}
            <code>https://api.yieldiq.in</code>. 99.5% allows up to{" "}
            <strong>~3 hours 36 minutes</strong> of unplanned downtime per
            calendar month. The free tier is best-effort and not covered.
          </p>

          <h2 className="text-xl font-bold mt-8 mb-3">2. What counts as downtime</h2>
          <p>
            A minute counts as down if two consecutive checks from our
            third-party monitoring (Better Stack) fail against any of our
            primary monitors: marketing home, API health, public stock summary,
            or all-tickers. Slow responses under 30s are not counted, but
            persistent slowness (P95 &gt; 5s for &gt; 1 hour) is treated as a
            P2 incident.
          </p>

          <h2 className="text-xl font-bold mt-8 mb-3">3. Maintenance windows</h2>
          <p>
            Planned maintenance is excluded from the SLA calculation.
          </p>
          <ul>
            <li>
              <strong>Sundays, 03:00–05:00 IST</strong> — weekly window, used
              as needed.
            </li>
            <li>Announced on the status page at least 24 hours in advance.</li>
            <li>
              Emergency security patches may happen outside this window with
              as much notice as practical; also excluded from the SLA.
            </li>
          </ul>

          <h2 className="text-xl font-bold mt-8 mb-3">4. Service credits</h2>
          <p>
            If we miss 99.5% in a calendar month, paying customers receive a
            credit on the next invoice:
          </p>
          <table className="w-full text-sm border border-gray-200 rounded-lg overflow-hidden">
            <thead className="bg-gray-50">
              <tr>
                <th className="text-left px-3 py-2 border-b border-gray-200">
                  Breach in rolling 12 months
                </th>
                <th className="text-left px-3 py-2 border-b border-gray-200">
                  Credit
                </th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td className="px-3 py-2 border-b border-gray-100">1st</td>
                <td className="px-3 py-2 border-b border-gray-100">
                  10% of monthly fee
                </td>
              </tr>
              <tr>
                <td className="px-3 py-2 border-b border-gray-100">2nd</td>
                <td className="px-3 py-2 border-b border-gray-100">
                  20% of monthly fee
                </td>
              </tr>
              <tr>
                <td className="px-3 py-2 border-b border-gray-100">3rd</td>
                <td className="px-3 py-2 border-b border-gray-100">
                  40% of monthly fee
                </td>
              </tr>
              <tr>
                <td className="px-3 py-2">4th and beyond</td>
                <td className="px-3 py-2">100% of monthly fee</td>
              </tr>
            </tbody>
          </table>
          <p className="mt-3 text-sm text-gray-600">
            Credits are applied automatically — no claim form. The credit is
            the sole and exclusive remedy for an SLA breach.
          </p>

          <h2 className="text-xl font-bold mt-8 mb-3">5. Out of scope</h2>
          <p>The SLA does not cover downtime caused by:</p>
          <ul>
            <li>
              <strong>Third-party providers</strong> (Vercel, Railway, Neon,
              Cloudflare, payment gateways). We report these on the status
              page but cannot refund for them.
            </li>
            <li>
              <strong>Force majeure</strong> — natural disasters, internet
              backbone failures, state-level censorship.
            </li>
            <li>
              <strong>User-side issues</strong> — unstable internet, outdated
              browsers, ad blockers or extensions that strip cookies / break
              the app.
            </li>
            <li>
              <strong>Beta or experimental features</strong> clearly marked as
              such in the product.
            </li>
            <li>
              <strong>Free-tier traffic</strong>, which we run on a
              best-effort basis.
            </li>
          </ul>

          <h2 className="text-xl font-bold mt-8 mb-3">6. Your responsibilities</h2>
          <p>To be eligible for SLA credit:</p>
          <ul>
            <li>Your account must be in good standing (payments current).</li>
            <li>
              The breach must be visible in the public history at{" "}
              <a
                href="https://status.yieldiq.in"
                target="_blank"
                rel="noopener noreferrer"
                className="underline"
              >
                status.yieldiq.in
              </a>
              .
            </li>
            <li>
              You access YieldIQ via a modern browser (Chrome / Edge / Safari
              / Firefox, last 2 major versions).
            </li>
          </ul>

          <h2 className="text-xl font-bold mt-8 mb-3">7. Reporting an outage</h2>
          <ol>
            <li>
              Check{" "}
              <a
                href="https://status.yieldiq.in"
                target="_blank"
                rel="noopener noreferrer"
                className="underline"
              >
                status.yieldiq.in
              </a>{" "}
              first — if it&apos;s red, we already know.
            </li>
            <li>
              If status is green but you&apos;re seeing problems, email{" "}
              <a href="mailto:hello@yieldiq.in" className="underline">
                hello@yieldiq.in
              </a>{" "}
              with URL, ticker, screenshot, browser, and time.
            </li>
            <li>We respond per the documented incident severity matrix.</li>
          </ol>

          <h2 className="text-xl font-bold mt-8 mb-3">8. Changes to this SLA</h2>
          <p>
            We may update this SLA. Material changes (lowering the uptime
            target, shrinking credits, expanding exclusions) will be
            communicated by email to active paying customers at least{" "}
            <strong>30 days</strong> before they take effect. The current
            version is always at{" "}
            <a href="/legal/sla" className="underline">
              yieldiq.in/legal/sla
            </a>
            .
          </p>
        </section>

        <footer className="mt-12 pt-6 border-t border-gray-200 text-sm text-gray-500 flex flex-col sm:flex-row justify-between gap-2">
          <span>Version 1.0 &middot; Effective 27 April 2026</span>
          <span>
            Contact:{" "}
            <a href="mailto:hello@yieldiq.in" className="underline">
              hello@yieldiq.in
            </a>
          </span>
        </footer>
      </main>
    </div>
  )
}
