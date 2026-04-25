// Public API documentation — single page covering the one v1 endpoint
// that's currently auth'd for API-key callers (/api/v1/analysis/{ticker}).
// Deliberately minimal — we'll grow this as we expose more endpoints.

import Link from "next/link"

export const metadata = {
  title: "YieldIQ API",
  description:
    "Programmatic access to YieldIQ stock analyses. Pro tier, 100 req/day per key.",
}

const CURL_EXAMPLE = `curl -H "Authorization: Bearer yk_<your-key-here>" \\
  https://api.yieldiq.in/api/v1/analysis/RELIANCE.NS`

const RESPONSE_EXAMPLE = `{
  "ticker": "RELIANCE.NS",
  "company_info": {
    "ticker": "RELIANCE.NS",
    "company_name": "Reliance Industries Ltd",
    "exchange": "NSE",
    "sector": "Energy",
    "currency": "INR",
    ...
  },
  "valuation": {
    "fair_value": 1450.20,
    "current_price": 1287.55,
    "margin_of_safety": 0.112,
    "verdict": "fairly_valued",
    "wacc": 0.118,
    "terminal_growth": 0.045,
    ...
  },
  "quality": { "score": 78, "grade": "B", "moat": "Wide", ... },
  "scenarios": { ... },
  "ai_summary": "..."
}`

export default function ApiDocsPage() {
  return (
    <div className="min-h-screen bg-gradient-to-br from-[#080E1A] via-[#0F172A] to-[#1E293B] text-white">
      {/* Simple nav */}
      <nav className="sticky top-0 z-50 border-b border-white/5 bg-[#080E1A]/80 backdrop-blur">
        <div className="max-w-4xl mx-auto px-4 sm:px-6 py-3 flex items-center justify-between">
          <Link href="/" className="flex items-center gap-2">
            <img src="/logo-new.svg" alt="YieldIQ" className="w-8 h-8 rounded-lg" />
            <span className="text-white font-bold text-lg">YieldIQ</span>
          </Link>
          <div className="flex items-center gap-6 text-sm">
            <Link href="/pricing" className="text-gray-400 hover:text-white transition">
              Pricing
            </Link>
            <Link
              href="/account/api-keys"
              className="bg-gradient-to-r from-blue-700 to-cyan-500 text-white font-semibold px-4 py-2 rounded-lg hover:opacity-90 transition"
            >
              Create your API key
            </Link>
          </div>
        </div>
      </nav>

      <main className="max-w-3xl mx-auto px-4 sm:px-6 py-12 space-y-10">
        <header className="space-y-3">
          <h1 className="text-4xl font-bold">YieldIQ API</h1>
          <p className="text-lg text-gray-300 leading-relaxed">
            Programmatic access to YieldIQ{"’"}s fair-value estimates and
            quality analysis. Available on the{" "}
            <Link href="/pricing" className="text-cyan-400 hover:underline">
              Pro plan
            </Link>
            . Each API key is rate-limited to{" "}
            <span className="font-semibold text-white">
              100 requests per day
            </span>
            . You can have up to 5 active keys per account.
          </p>
        </header>

        {/* Authentication */}
        <section className="space-y-3">
          <h2 className="text-2xl font-semibold">Authentication</h2>
          <p className="text-gray-300">
            Pass your API key in the{" "}
            <code className="text-cyan-300 bg-white/5 px-1.5 py-0.5 rounded">
              Authorization
            </code>{" "}
            header (or{" "}
            <code className="text-cyan-300 bg-white/5 px-1.5 py-0.5 rounded">
              X-API-Key
            </code>
            ):
          </p>
          <pre className="bg-black/40 border border-white/10 rounded-xl p-4 text-sm overflow-x-auto">
            <code>Authorization: Bearer yk_a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8</code>
          </pre>
          <p className="text-sm text-gray-400">
            Keys begin with{" "}
            <code className="text-cyan-300">yk_</code>. The full key is shown
            once at creation time and cannot be retrieved later — store it
            securely. If you lose it, revoke and create a new one.
          </p>
        </section>

        {/* Endpoint */}
        <section className="space-y-4">
          <h2 className="text-2xl font-semibold">Endpoint</h2>

          <div className="bg-black/30 border border-white/10 rounded-2xl p-5 space-y-4">
            <div className="flex items-center gap-3">
              <span className="px-2.5 py-1 bg-green-600/20 text-green-300 text-xs font-mono font-bold rounded">
                GET
              </span>
              <code className="text-base font-mono">
                /api/v1/analysis/{"{ticker}"}
              </code>
            </div>
            <p className="text-sm text-gray-300">
              Returns a full DCF-driven analysis: fair value, margin of
              safety, scenarios, quality + moat scores, and an AI-generated
              summary.
            </p>

            <div>
              <h3 className="text-sm font-semibold text-gray-200 mb-2">
                Path parameters
              </h3>
              <ul className="text-sm text-gray-300 space-y-1">
                <li>
                  <code className="text-cyan-300">ticker</code>: NSE/BSE
                  symbol with suffix, e.g.{" "}
                  <code className="text-cyan-300">RELIANCE.NS</code>,{" "}
                  <code className="text-cyan-300">TCS.NS</code>.
                </li>
              </ul>
            </div>

            <div>
              <h3 className="text-sm font-semibold text-gray-200 mb-2">
                Example request
              </h3>
              <pre className="bg-black/40 border border-white/10 rounded-xl p-4 text-sm overflow-x-auto">
                <code>{CURL_EXAMPLE}</code>
              </pre>
            </div>

            <div>
              <h3 className="text-sm font-semibold text-gray-200 mb-2">
                Example response (truncated)
              </h3>
              <pre className="bg-black/40 border border-white/10 rounded-xl p-4 text-xs overflow-x-auto">
                <code>{RESPONSE_EXAMPLE}</code>
              </pre>
            </div>
          </div>
        </section>

        {/* Rate limits + errors */}
        <section className="space-y-4">
          <h2 className="text-2xl font-semibold">Rate limits</h2>
          <p className="text-gray-300">
            Each API key may make up to{" "}
            <span className="font-semibold text-white">100 requests per day</span>
            . The counter resets at midnight UTC.
          </p>

          <h2 className="text-2xl font-semibold pt-4">Error codes</h2>
          <div className="bg-black/30 border border-white/10 rounded-2xl overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-white/10 text-left">
                  <th className="px-4 py-3 font-semibold">Status</th>
                  <th className="px-4 py-3 font-semibold">Meaning</th>
                </tr>
              </thead>
              <tbody className="text-gray-300">
                <tr className="border-b border-white/5">
                  <td className="px-4 py-3 font-mono text-cyan-300">401</td>
                  <td className="px-4 py-3">
                    Missing or invalid API key.
                  </td>
                </tr>
                <tr className="border-b border-white/5">
                  <td className="px-4 py-3 font-mono text-cyan-300">403</td>
                  <td className="px-4 py-3">
                    Key valid but the user is not on the Pro tier.
                  </td>
                </tr>
                <tr>
                  <td className="px-4 py-3 font-mono text-cyan-300">429</td>
                  <td className="px-4 py-3">
                    Daily 100-request cap reached for this key. Wait until
                    midnight UTC or use a different key.
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>

        {/* CTA */}
        <section className="bg-gradient-to-br from-blue-700/20 to-cyan-500/20 border border-blue-500/30 rounded-2xl p-6 text-center space-y-3">
          <h2 className="text-xl font-semibold">Ready to start?</h2>
          <p className="text-gray-300 text-sm">
            Create an API key from your account settings.
          </p>
          <Link
            href="/account/api-keys"
            className="inline-block bg-gradient-to-r from-blue-700 to-cyan-500 text-white font-semibold px-6 py-3 rounded-xl hover:opacity-90 transition"
          >
            Create your API key
          </Link>
        </section>

        <footer className="pt-8 border-t border-white/5 text-center text-xs text-gray-500">
          YieldIQ is not registered with SEBI as an investment adviser. All
          API outputs are model estimates only.
        </footer>
      </main>
    </div>
  )
}
