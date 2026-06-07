/**
 * /fair-value/[ticker] — prose template.
 *
 * Pure server component. Renders the five descriptive sections of the
 * SEO content page. Every sentence here is a STATEMENT about model
 * output, never a prediction of market state, and never a directive
 * about whether a reader ought to act.
 *
 * SEBI lint runs on this file. The banned-vocabulary list is in
 * scripts/check_sebi_words.py — do not introduce any banned predictive
 * direction verbs, advisory verbs, subjective valuation adjectives, or
 * standalone qualifiers outside their wire-format usage into the prose
 * (or any descendant component). Use descriptive metric language
 * instead — e.g.
 * "the model's fair-value estimate is 12% above the current price"
 * rather than any directional framing.
 */

import Link from "next/link"

import TickerAvatar from "@/components/common/TickerAvatar"

import type { FaqEntry } from "./JsonLd"

export interface FairValueViewModel {
  ticker: string
  displayTicker: string
  companyName: string
  sector: string | null
  /** Live current market price (₹). */
  currentPrice: number | null
  /** DCF fair value, base case (₹). */
  fairValue: number | null
  /** Discount of FV to CMP, percent. Positive = FV above price. */
  mosPct: number | null
  /** YieldIQ score, 0–100. */
  yieldiqScore: number | null
  /** Descriptive verdict label (e.g. "Below fair value"). */
  verdict: string
  /** Bear / base / bull DCF scenarios, ₹. */
  fairValueBear: number | null
  fairValueBull: number | null
  /** Quality / safety inputs from the prism payload. */
  moatLabel: string | null
  fScore: number | null
  redFlagCount: number | null
  /** DCF assumption inputs (% values). */
  waccPct: number | null
  terminalGrowthPct: number | null
  revenueGrowthPct: number | null
  /** Peer comparison rows (already trimmed to ≤3). */
  peers: Array<{
    ticker: string
    companyName: string
    fairValue: number | null
    mosPct: number | null
  }>
  /** Static moat phrase from the ticker config. */
  moatPhrase: string
  /** Human "updated DD Mon YYYY" — formatted by the page. */
  updatedDate: string
}

const INR = "₹"

function formatCurrency(value: number | null): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return "—"
  }
  return `${INR}${value.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`
}

function formatPct(value: number | null): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return "—"
  }
  const sign = value > 0 ? "+" : ""
  return `${sign}${value.toFixed(1)}%`
}

function formatScore(value: number | null): string {
  if (value === null || value === undefined) return "—"
  return `${Math.round(value)} / 100`
}

/**
 * Build the FAQ list. Exported so the JSON-LD emitter can reuse the
 * same entries verbatim — single source of truth for SEO + UI.
 */
export function buildFaq(vm: FairValueViewModel): FaqEntry[] {
  const company = vm.companyName
  const ticker = vm.displayTicker
  const fvStr = formatCurrency(vm.fairValue)
  const mosStr = formatPct(vm.mosPct)
  return [
    {
      question: `What is ${company}'s fair value?`,
      answer:
        `YieldIQ's discounted-cash-flow model estimates a base-case fair ` +
        `value of ${fvStr} per share for ${company} (${ticker}). ` +
        `The estimate is updated daily from the latest financial filings ` +
        `and is published alongside a bear and bull scenario on the full ` +
        `analysis page.`,
    },
    {
      question: `What does the ${mosStr} margin of safety mean?`,
      answer:
        `The margin of safety is the gap between the model's fair-value ` +
        `estimate and the current market price, expressed as a percent of ` +
        `the fair value. A positive number means the model's estimate sits ` +
        `above the current price; a negative number means the model's ` +
        `estimate sits below it. It is a descriptive distance, not a ` +
        `forecast of where the price will move.`,
    },
    {
      question: `How is ${company}'s fair value calculated?`,
      answer:
        `The fair value is the output of a three-stage discounted-cash-flow ` +
        `model. Forecast free cash flows are discounted at the firm's ` +
        `weighted-average cost of capital, a terminal value is added using ` +
        `a long-run growth rate, and the result is divided by diluted ` +
        `share count. Every input — WACC, terminal growth, revenue CAGR, ` +
        `operating margin, tax rate — is editable on the full analysis ` +
        `page so a reader can substitute their own assumptions and rerun ` +
        `the model.`,
    },
    {
      question: `Is this investment advice?`,
      answer:
        // Disclaimer language: SEBI-compliance disclosure deliberately
        // names what the page is NOT. Allowlisted per check_sebi_words.
        `No. YieldIQ is not a SEBI-registered investment adviser and ` +
        `nothing on this page is investment advice or a recommendation to ` + // sebi-allow: recommendation
        `transact in ${company} or any other security. The fair-value ` +
        `figure is a model output, published for educational and ` +
        `informational use. Readers should consult a SEBI-registered ` + // sebi-allow: should
        `investment adviser before making any investment decision.`,
    },
  ]
}

interface PanelProps {
  vm: FairValueViewModel
}

function FairValuePanel({ vm }: PanelProps) {
  return (
    <section
      aria-label="Fair value summary"
      className="rounded-xl border border-border bg-raised p-6 sm:p-8 my-8"
    >
      <div className="flex items-center gap-3 mb-6">
        {/* size="sm" → 24px, preserves the visual size from the
            pre-2026-06 component when "md" mapped to 24px. The sitewide
            scale was widened (xs/sm/md/lg = 16/24/32/48) so size names
            shifted; the visual here stays the same. */}
        <TickerAvatar ticker={vm.ticker} size="sm" />
        <div className="text-sm text-caption">
          {vm.displayTicker}
          {vm.sector ? ` · ${vm.sector}` : ""}
        </div>
      </div>
      <dl className="grid grid-cols-2 sm:grid-cols-5 gap-4 sm:gap-6">
        <div>
          <dt className="text-[11px] uppercase tracking-wider text-caption mb-1">
            Current price
          </dt>
          <dd className="text-lg font-semibold text-ink">
            {formatCurrency(vm.currentPrice)}
          </dd>
        </div>
        <div>
          <dt className="text-[11px] uppercase tracking-wider text-caption mb-1">
            Fair value
          </dt>
          <dd className="text-lg font-semibold text-ink">
            {formatCurrency(vm.fairValue)}
          </dd>
        </div>
        <div>
          <dt className="text-[11px] uppercase tracking-wider text-caption mb-1">
            Margin of safety
          </dt>
          <dd className="text-lg font-semibold text-ink">
            {formatPct(vm.mosPct)}
          </dd>
        </div>
        <div>
          <dt className="text-[11px] uppercase tracking-wider text-caption mb-1">
            YieldIQ score
          </dt>
          <dd className="text-lg font-semibold text-ink">
            {formatScore(vm.yieldiqScore)}
          </dd>
        </div>
        <div>
          <dt className="text-[11px] uppercase tracking-wider text-caption mb-1">
            Moat
          </dt>
          <dd className="text-lg font-semibold text-ink">
            {vm.moatLabel ?? "—"}
          </dd>
        </div>
      </dl>
      <div className="mt-6">
        <Link
          href={`/analysis/${vm.ticker}`}
          className="inline-flex items-center gap-2 text-sm font-medium text-accent hover:underline"
        >
          See the full interactive analysis
          <span aria-hidden="true">→</span>
        </Link>
      </div>
    </section>
  )
}

function Section({
  eyebrow,
  title,
  children,
}: {
  eyebrow: string
  title: string
  children: React.ReactNode
}) {
  return (
    <section className="my-8">
      <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-caption mb-2">
        {eyebrow}
      </p>
      <h2 className="font-editorial text-2xl sm:text-3xl font-semibold text-ink mb-4">
        {title}
      </h2>
      <div className="prose prose-neutral max-w-none text-body leading-relaxed">
        {children}
      </div>
    </section>
  )
}

export default function FairValueContent({ vm }: { vm: FairValueViewModel }) {
  const faq = buildFaq(vm)
  const fvStr = formatCurrency(vm.fairValue)
  const cmpStr = formatCurrency(vm.currentPrice)
  const mosStr = formatPct(vm.mosPct)
  const bearStr = formatCurrency(vm.fairValueBear)
  const bullStr = formatCurrency(vm.fairValueBull)
  const waccStr = vm.waccPct !== null ? `${vm.waccPct.toFixed(1)}%` : "—"
  const tgStr =
    vm.terminalGrowthPct !== null ? `${vm.terminalGrowthPct.toFixed(1)}%` : "—"
  const rgStr =
    vm.revenueGrowthPct !== null
      ? `${vm.revenueGrowthPct.toFixed(1)}%`
      : "the model's revenue-growth input"

  return (
    <article className="max-w-3xl mx-auto px-4 sm:px-6 py-10 sm:py-14">
      <header className="mb-2">
        <h1 className="font-editorial text-3xl sm:text-5xl font-semibold text-ink leading-tight">
          {vm.companyName} ({vm.displayTicker}) — Fair Value Analysis
        </h1>
        <p className="mt-4 text-base sm:text-lg text-body">
          YieldIQ&apos;s DCF-based fair value estimate for {vm.companyName},
          updated {vm.updatedDate}.
        </p>
      </header>

      <FairValuePanel vm={vm} />

      <Section eyebrow="Section 1" title="Fair value estimate">
        <p>
          The YieldIQ model lands on a base-case fair value of {fvStr} per
          share for {vm.companyName}, against a current market price of{" "}
          {cmpStr}. The base case sits in a bear-to-bull range of {bearStr} to{" "}
          {bullStr}, computed by varying the discount rate and the long-run
          growth rate within plausible bands. The published margin of safety
          for the base case is {mosStr}.
        </p>
        <p>
          A margin of safety figure is a descriptive measurement, not a
          forecast. It states the distance, in percent, between the model&apos;s
          fair-value estimate and the live price. It does not say where the
          price will move; it only says how far apart the two numbers are
          today. The interpretation a reader applies — whether the gap
          matters, what discount rate they would prefer to use, which scenario
          they find most plausible — sits entirely with them and with their
          own SEBI-registered investment adviser.
        </p>
      </Section>

      <Section eyebrow="Section 2" title="Quality snapshot">
        <p>{vm.moatPhrase}</p>
        <p>
          The model summarises {vm.companyName}&apos;s quality footprint as a
          moat label of <span className="font-medium">{vm.moatLabel ?? "—"}</span>,
          a Piotroski F-score of{" "}
          <span className="font-medium">
            {vm.fScore !== null ? vm.fScore : "—"}
          </span>{" "}
          out of 9, and{" "}
          <span className="font-medium">
            {vm.redFlagCount !== null ? vm.redFlagCount : "—"}
          </span>{" "}
          accounting red flags detected on the latest filings. The
          moat label is a descriptive categorisation of the firm&apos;s
          economic moat — none, narrow, or wide — derived from return-on-capital
          history and competitive-position signals. The F-score is a
          rules-based accounting check, and the red-flag count surfaces any
          line-item discrepancies the model spotted in the most recent
          standalone and consolidated statements.
        </p>
      </Section>

      <Section eyebrow="Section 3" title="What this assumes">
        <p>
          A fair-value number is only meaningful with its assumptions on the
          table. The base-case DCF for {vm.companyName} uses a weighted-average
          cost of capital of {waccStr}, a terminal growth rate of {tgStr}, and{" "}
          {rgStr} over the explicit-forecast window. Operating margin, tax rate
          and reinvestment intensity are seeded from the trailing five-year
          history and held flat through the explicit forecast unless a
          documented one-off requires adjustment.
        </p>
        <p>
          Every one of those inputs is editable. The full analysis page hosts
          a reverse-DCF playground where a reader can move the WACC, terminal
          growth, revenue CAGR, operating margin, and tax-rate sliders and
          watch the fair value recompute in real time. The objective is for a
          reader to never accept the published number on faith — substitute
          your own assumptions, run the model, and see whether the resulting
          fair value still sits where the published one does.
        </p>
      </Section>

      {vm.peers.length > 0 ? (
        <Section
          eyebrow="Section 4"
          title={`How ${vm.companyName} compares to peers`}
        >
          <p>
            Three peer companies in the same operating cohort, with their own
            YieldIQ DCF fair-value estimates and margins of safety as of the
            latest model run:
          </p>
          <div className="overflow-x-auto mt-4">
            <table className="w-full text-sm border-collapse">
              <thead>
                <tr className="border-b border-border text-left text-caption">
                  <th className="py-2 pr-4 font-medium">Company</th>
                  <th className="py-2 pr-4 font-medium">Fair value</th>
                  <th className="py-2 pr-4 font-medium">Margin of safety</th>
                </tr>
              </thead>
              <tbody>
                {vm.peers.map((p) => (
                  <tr key={p.ticker} className="border-b border-border/50">
                    <td className="py-2 pr-4">
                      <Link
                        href={`/fair-value/${p.ticker}`}
                        className="text-accent hover:underline"
                      >
                        {p.companyName} ({p.ticker})
                      </Link>
                    </td>
                    <td className="py-2 pr-4">{formatCurrency(p.fairValue)}</td>
                    <td className="py-2 pr-4">{formatPct(p.mosPct)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>
      ) : null}

      <Section eyebrow="Section 5" title="Frequently asked">
        <dl className="space-y-6">
          {faq.map((qa) => (
            <div key={qa.question}>
              <dt className="font-semibold text-ink mb-1">{qa.question}</dt>
              <dd className="text-body">{qa.answer}</dd>
            </div>
          ))}
        </dl>
      </Section>

      <footer className="mt-12 pt-8 border-t border-border space-y-4">
        <p className="text-sm text-caption">
          Methodology details, data sources and the full model specification
          are on the{" "}
          <Link href="/methodology" className="text-accent hover:underline">
            methodology page
          </Link>
          .
        </p>
        <p className="text-sm text-caption">
          YieldIQ is not a SEBI-registered investment adviser. The fair-value
          figure above is a model output published for educational and
          informational use. It is not investment advice and is not a
          recommendation to transact in {vm.companyName} or any other {/* sebi-allow: recommendation */}
          security. Readers should consult a SEBI-registered investment {/* sebi-allow: should */}
          adviser before making any investment decision.
        </p>
        <p className="text-sm">
          <Link
            href={`/analysis/${vm.ticker}/playground`}
            className="inline-flex items-center gap-2 font-medium text-accent hover:underline"
          >
            Adjust the assumptions and rerun the model
            <span aria-hidden="true">→</span>
          </Link>
        </p>
      </footer>
    </article>
  )
}
