"use client"

import { useState } from "react"

/**
 * DisputeForm — client component powering /disputes.
 *
 * Phase A wiring: no backend. The submit control is an <a href=mailto:>
 * built live from the form fields. This is deliberate — a database
 * table + admin triage UI is Phase B work and out of scope for T5.8.
 *
 * The mailto link encodes a structured body so the triage inbox can
 * grep / parse submissions consistently.
 */

export interface DisputeFormFields {
  ticker: string
  category: string
  whatsWrong: string
  whatsRight: string
  name: string
  email: string
}

interface CategoryOption {
  value: string
  label: string
  example: string
}

export const DISPUTE_CATEGORIES: readonly CategoryOption[] = [
  {
    value: "data",
    label: "Data correction",
    example: "e.g. RELIANCE FY24 capex figure looks off vs the annual report.",
  },
  {
    value: "model",
    label: "Model challenge",
    example:
      "e.g. ITC terminal growth assumption — explain the number you think is right and your reasoning.",
  },
  {
    value: "copy",
    label: "Copy / methodology bug",
    example:
      "e.g. The sector-medians caption on /sector/it is unclear about which percentile is shown.",
  },
] as const

/**
 * Build the mailto: URL for the structured dispute email.
 *
 * Exported so the unit test can assert on the encoded subject + body
 * without driving a JSDOM click. Pure function — no side effects.
 */
export function buildMailto(opts: DisputeFormFields): string {
  const tickerPart = opts.ticker.trim() || "(unspecified)"
  const subject = `Dispute: ${tickerPart} - ${opts.category}`

  const bodyLines: string[] = [
    `Ticker: ${opts.ticker.trim() || "(not specified)"}`,
    `Category: ${opts.category}`,
    "",
    "What's wrong:",
    opts.whatsWrong || "(empty)",
    "",
    "What's right + source:",
    opts.whatsRight || "(empty)",
    "",
    `Submitter: ${opts.name.trim() || "anonymous"} (${
      opts.email.trim() || "no email"
    })`,
  ]

  return (
    "mailto:disputes@yieldiq.in" +
    "?subject=" +
    encodeURIComponent(subject) +
    "&body=" +
    encodeURIComponent(bodyLines.join("\n"))
  )
}

export default function DisputeForm() {
  const [ticker, setTicker] = useState("")
  const [category, setCategory] = useState<string>(DISPUTE_CATEGORIES[0].value)
  const [whatsWrong, setWhatsWrong] = useState("")
  const [whatsRight, setWhatsRight] = useState("")
  const [name, setName] = useState("")
  const [email, setEmail] = useState("")

  const activeCategory =
    DISPUTE_CATEGORIES.find((c) => c.value === category) ??
    DISPUTE_CATEGORIES[0]

  const mailtoLink = buildMailto({
    ticker,
    category,
    whatsWrong,
    whatsRight,
    name,
    email,
  })

  return (
    <form
      data-testid="dispute-form"
      onSubmit={(e) => e.preventDefault()}
      className="rounded-2xl border border-border bg-surface p-6 sm:p-8 space-y-6"
    >
      {/* Ticker */}
      <div>
        <label
          htmlFor="dispute-ticker"
          className="block text-xs font-semibold uppercase tracking-wider text-caption mb-2"
        >
          Ticker (optional)
        </label>
        <input
          id="dispute-ticker"
          name="ticker"
          type="text"
          value={ticker}
          onChange={(e) => setTicker(e.target.value.toUpperCase())}
          placeholder="e.g. RELIANCE"
          className="w-full rounded-md border border-border bg-bg px-3 py-2 text-sm text-ink placeholder:text-caption focus:outline-none focus:ring-2 focus:ring-brand/40"
        />
      </div>

      {/* Category radios */}
      <fieldset>
        <legend className="block text-xs font-semibold uppercase tracking-wider text-caption mb-2">
          Category
        </legend>
        <div className="grid sm:grid-cols-3 gap-2">
          {DISPUTE_CATEGORIES.map((opt) => (
            <label
              key={opt.value}
              className={`flex items-start gap-2 rounded-md border px-3 py-2 cursor-pointer transition ${
                category === opt.value
                  ? "border-brand bg-brand/5"
                  : "border-border hover:border-ink/30"
              }`}
            >
              <input
                type="radio"
                name="dispute-category"
                value={opt.value}
                checked={category === opt.value}
                onChange={() => setCategory(opt.value)}
                className="mt-1"
              />
              <span className="text-sm text-ink">{opt.label}</span>
            </label>
          ))}
        </div>
        <p
          className="mt-3 text-xs text-caption leading-relaxed"
          data-testid="category-example"
        >
          {activeCategory.example}
        </p>
      </fieldset>

      {/* What's wrong */}
      <div>
        <label
          htmlFor="dispute-whats-wrong"
          className="block text-xs font-semibold uppercase tracking-wider text-caption mb-2"
        >
          What&apos;s wrong
        </label>
        <textarea
          id="dispute-whats-wrong"
          name="whatsWrong"
          rows={4}
          value={whatsWrong}
          onChange={(e) => setWhatsWrong(e.target.value)}
          placeholder="Describe the issue. Include the page URL if helpful."
          className="w-full rounded-md border border-border bg-bg px-3 py-2 text-sm text-ink placeholder:text-caption focus:outline-none focus:ring-2 focus:ring-brand/40"
        />
      </div>

      {/* What's right + source */}
      <div>
        <label
          htmlFor="dispute-whats-right"
          className="block text-xs font-semibold uppercase tracking-wider text-caption mb-2"
        >
          What&apos;s right + source
        </label>
        <textarea
          id="dispute-whats-right"
          name="whatsRight"
          rows={4}
          value={whatsRight}
          onChange={(e) => setWhatsRight(e.target.value)}
          placeholder="The correct figure or fact, and where it comes from (filing URL, page number, etc)."
          className="w-full rounded-md border border-border bg-bg px-3 py-2 text-sm text-ink placeholder:text-caption focus:outline-none focus:ring-2 focus:ring-brand/40"
        />
      </div>

      {/* Name + email */}
      <div className="grid sm:grid-cols-2 gap-4">
        <div>
          <label
            htmlFor="dispute-name"
            className="block text-xs font-semibold uppercase tracking-wider text-caption mb-2"
          >
            Your name (optional)
          </label>
          <input
            id="dispute-name"
            name="name"
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="For public credit on /errata"
            className="w-full rounded-md border border-border bg-bg px-3 py-2 text-sm text-ink placeholder:text-caption focus:outline-none focus:ring-2 focus:ring-brand/40"
          />
        </div>
        <div>
          <label
            htmlFor="dispute-email"
            className="block text-xs font-semibold uppercase tracking-wider text-caption mb-2"
          >
            Email (optional)
          </label>
          <input
            id="dispute-email"
            name="email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="So we can follow up with questions"
            className="w-full rounded-md border border-border bg-bg px-3 py-2 text-sm text-ink placeholder:text-caption focus:outline-none focus:ring-2 focus:ring-brand/40"
          />
        </div>
      </div>

      {/* Submit */}
      <div className="pt-2">
        <a
          href={mailtoLink}
          data-testid="dispute-submit"
          className="inline-flex items-center justify-center rounded-md bg-ink px-5 py-2.5 text-sm font-semibold text-bg hover:bg-ink/90 transition"
        >
          Submit via email
        </a>
        <p className="mt-3 text-xs text-caption leading-relaxed">
          Opens your email client with the fields pre-filled. Triage usually
          within 3 business days.
        </p>
      </div>
    </form>
  )
}
