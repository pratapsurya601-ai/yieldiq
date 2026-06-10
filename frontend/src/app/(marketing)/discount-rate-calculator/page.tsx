import type { Metadata } from "next"
import Link from "next/link"

import Calculator from "./Calculator"

/**
 * /discount-rate-calculator — public WACC explainer + interactive widget.
 *
 * Server Component shell. The interactive widget is a sibling client
 * component (./Calculator.tsx) — the page body is fully SSR so the hero
 * and the "Notable cases" / footer sections are crawlable static HTML.
 *
 * Voice: descriptive, never prescriptive. SEBI-clean copy throughout
 * (no advisory verbs anywhere). The page exists so a reviewer
 * — internal or external — can see exactly how we arrive at the discount
 * rate for any sector.
 *
 * Engine refinement roadmap T6.1.
 */

export const dynamic = "force-static"
export const revalidate = 86400 // 24h — the defaults are slow-moving

export function generateMetadata(): Metadata {
  const title = "WACC Calculator — How we arrive at the discount rate"
  const description =
    "Interactive WACC calculator. Pick a sector to load calibrated defaults — " +
    "risk-free rate, equity risk premium, beta, cost of debt, tax rate, debt " +
    "ratio — and see the discount rate update live. The exact same engine YieldIQ " +
    "uses for DCF valuation."
  return {
    title,
    description,
    alternates: { canonical: "https://yieldiq.in/discount-rate-calculator" },
    openGraph: {
      title,
      description,
      url: "https://yieldiq.in/discount-rate-calculator",
      siteName: "YieldIQ",
      type: "article",
      locale: "en_IN",
      images: [
        {
          url: "https://yieldiq.in/icon-512.png",
          width: 512,
          height: 512,
          alt: "YieldIQ",
        },
      ],
    },
    twitter: {
      card: "summary",
      title,
      description,
      images: ["https://yieldiq.in/icon-512.png"],
    },
    robots: { index: true, follow: true },
  }
}

/**
 * A single "Notable cases" example row. Plain prose — descriptive only.
 */
function NotableCase({
  ticker,
  wacc,
  reason,
}: {
  ticker: string
  wacc: string
  reason: string
}) {
  return (
    <li className="flex flex-col gap-1 border-b border-border py-4 last:border-b-0 sm:flex-row sm:items-baseline sm:gap-6">
      <div className="flex items-baseline gap-3 sm:w-64 sm:shrink-0">
        <span className="font-mono text-sm font-semibold text-foreground">
          {ticker}
        </span>
        <span className="font-mono text-sm text-muted-foreground">
          WACC &asymp; {wacc}
        </span>
      </div>
      <span className="text-sm leading-relaxed text-muted-foreground">
        {reason}
      </span>
    </li>
  )
}

export default function DiscountRateCalculatorPage() {
  return (
    <main className="mx-auto w-full max-w-4xl px-4 py-12 md:py-16">
      {/* ── Hero ─────────────────────────────────────────────── */}
      <header className="mx-auto max-w-3xl">
        <div className="text-xs uppercase tracking-wide text-muted-foreground">
          Tools &middot; Methodology
        </div>
        <h1 className="mt-3 font-serif text-3xl leading-tight text-foreground md:text-4xl">
          WACC Calculator
        </h1>
        <p className="mt-4 text-base leading-relaxed text-muted-foreground">
          How we arrive at the discount rate for any sector. Pick a
          sector to load calibrated defaults &mdash; risk-free rate,
          equity risk premium, beta, cost of debt, tax rate, debt ratio
          &mdash; and watch the discount rate update as you change them.
          The same WACC then feeds the DCF behind every analysis page.
        </p>

        {/* The formula itself — small, monospaced, visible */}
        <div className="mt-6 rounded-md border border-border bg-muted/30 p-4 font-mono text-sm leading-relaxed text-foreground">
          <div>WACC = (D/V) &middot; Kd &middot; (1 &minus; t) + (E/V) &middot; Ke</div>
          <div className="mt-1 text-muted-foreground">
            Ke = Rf + &beta; &middot; ERP
          </div>
        </div>
      </header>

      {/* ── Calculator (client component) ────────────────────── */}
      <Calculator />

      {/* ── Notable cases ────────────────────────────────────── */}
      <section className="mt-12">
        <h2 className="font-serif text-xl text-foreground">
          Notable cases
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Three live examples showing how the same formula produces
          different discount rates depending on the business mix.
        </p>
        <ul className="mt-4 rounded-2xl border border-border bg-card px-5">
          <NotableCase
            ticker="HDFCBANK"
            wacc="11.8%"
            reason="Cost of equity only — for a bank, customer deposits are funding rather than capital, so we drop the debt term and the discount rate equals Ke = Rf + β · ERP."
          />
          <NotableCase
            ticker="TCS"
            wacc="11.5%"
            reason="Low-beta export earnings (beta ≈ 0.85) plus minimal long-term debt. Most of the capital is equity, so the discount rate sits close to cost of equity with a tiny after-tax debt benefit."
          />
          <NotableCase
            ticker="TATASTEEL"
            wacc="14.5%"
            reason="Cyclical, capital-intensive, high-beta (≈ 1.40) and a heavier debt load. The higher beta lifts Ke and the larger debt weight only partially offsets it because steel pre-tax cost of debt is also high."
          />
        </ul>
      </section>

      {/* ── How the formula maps to a DCF ────────────────────── */}
      <section className="mt-12 rounded-2xl border border-border bg-card p-6">
        <h2 className="font-serif text-xl text-foreground">
          Why the WACC matters in a DCF
        </h2>
        <p className="mt-3 text-sm leading-relaxed text-muted-foreground">
          Every forecast rupee in a discounted-cash-flow model is divided
          by{" "}
          <code className="rounded bg-muted px-1 py-0.5 text-[0.85em]">
            (1 + WACC)^year
          </code>{" "}
          to convert it to today&rsquo;s money. A 1pp move in the
          discount rate can change a long-dated fair value by 10&minus;20%
          &mdash; which is why we publish the sector defaults rather than
          hide them behind a single global WACC.
        </p>
        <p className="mt-3 text-sm leading-relaxed text-muted-foreground">
          Sectors with heavier debt loads typically arrive at a lower
          WACC because after-tax debt is the cheaper leg of the capital
          stack. Sectors with higher beta arrive at a higher cost of
          equity. The calculator above lets you see both effects play
          out on the same screen.
        </p>
      </section>

      {/* ── Methodology link strip ──────────────────────────── */}
      <section className="mt-12 border-t border-border pt-6 text-sm text-muted-foreground">
        See also:{" "}
        <Link
          href="/methodology"
          className="text-foreground underline underline-offset-2"
        >
          full methodology
        </Link>
        {" · "}
        <Link
          href="/methodology/accuracy"
          className="text-foreground underline underline-offset-2"
        >
          fair-value accuracy backtest
        </Link>
        {" · "}
        <Link
          href="/how-it-works"
          className="text-foreground underline underline-offset-2"
        >
          how YieldIQ works
        </Link>
      </section>

      {/* ── Footer disclaimer ───────────────────────────────── */}
      <footer className="mt-10 rounded-md border border-border bg-muted/20 p-4 text-xs leading-relaxed text-muted-foreground">
        These are calibrated defaults sourced from Damodaran India 2026
        data plus local cross-checks against NSE filings. Your specific
        assumptions may vary &mdash; cost of debt for a particular issuer
        depends on its bond curve, statutory tax rates change between
        budgets, and beta is sensitive to the lookback window. The
        calculator is provided for transparency and educational use only.
      </footer>
    </main>
  )
}
