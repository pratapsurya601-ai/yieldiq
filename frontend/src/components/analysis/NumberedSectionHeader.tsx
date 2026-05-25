"use client"

// NumberedSectionHeader — Alpha-Spread-style large uppercase divider
// used on the Summary tab (#ASD-restyle, 2026-05-25).
//
// Format:   1. VALUATION SCENARIOS
//           <plain-English caption sentence, max-w-prose>
//
// The leading numeral is rendered muted so the eye lands on the label.
// Caption is required — every section must justify itself in one sentence.

import * as React from "react"

interface Props {
  number: number
  title: string        // already uppercase, e.g. "VALUATION SCENARIOS"
  caption: string      // plain-English, SEBI-safe
}

export default function NumberedSectionHeader({ number, title, caption }: Props) {
  return (
    <header className="mt-12 mb-6">
      <h2 className="text-2xl md:text-3xl font-bold uppercase tracking-tight text-ink">
        <span className="text-caption opacity-60">{number}.</span>{" "}
        {title}
      </h2>
      <p className="text-sm text-caption max-w-prose mb-4 mt-2">
        {caption}
      </p>
    </header>
  )
}
