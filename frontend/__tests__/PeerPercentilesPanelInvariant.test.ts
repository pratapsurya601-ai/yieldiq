/**
 * ROOT CAUSE #5 regression guard (2026-06-11) for the "Where you
 * stand vs peers" panel on AnalysisBody.tsx.
 *
 * The bug being prevented:
 *   The earlier per-row JSX layout interleaved label/value/median
 *   props inline for each metric. Under copy edits — for example
 *   PR #136's deposits-inclusive D/E rewrite — it was easy to drift
 *   the label/key pairing on one row so the slider rendered with an
 *   empty metric name and an "—" value but the sector median was
 *   still visible. The visible artefact was a row with no label and
 *   no number, only "sector median 0.70" in the corner.
 *
 *   The fix moves the rows to a single explicit-key row spec where
 *   {label, metricKey, format, direction} travel together. This test
 *   pins that shape by source-text inspection so a future refactor
 *   that re-introduces per-row inline JSX (and the drift surface)
 *   trips CI before shipping.
 *
 * Mode: source-text. AnalysisBody.tsx is too heavy to mount in jsdom
 * (it pulls react-query, tanstack store, framer-motion, ~50 dynamic
 * imports). The grep guards are strict enough that a hand-rolled
 * regression slips through only if it actively defeats the spec.
 */

import { describe, it, expect } from "vitest"
import { readFileSync } from "node:fs"
import path from "node:path"

const BODY_PATH = path.resolve(
  __dirname,
  "../src/app/(app)/analysis/[ticker]/AnalysisBody.tsx",
)
const body = readFileSync(BODY_PATH, "utf-8")

// All four canonical row labels the panel can render. ROE is shared
// across cohorts; the rest split bank vs non-bank cohorts.
const EXPECTED_LABELS = ["ROE", "NIM", "CASA", "GNPA", "PE", "D/E", "Net margin"]

describe("PeerPercentilesPanel — row-spec invariant (ROOT CAUSE #5)", () => {
  it("uses a data-testid-tagged panel so the regression test below can pin it", () => {
    expect(body).toMatch(/data-testid="peer-percentiles-panel"/)
  })

  it("declares an explicit row spec rather than inline per-row JSX", () => {
    // The rowSpec array is the single source of truth. Each row
    // carries label + metricKey together so they can't drift.
    expect(body).toMatch(/const\s+rowSpec\s*:/)
    // The spec must include both `label` and `metricKey` fields so
    // the label/key pairing is co-located, not split across
    // sibling JSX props.
    expect(body).toMatch(/label:\s*["']ROE["']/)
    expect(body).toMatch(/metricKey:\s*["']roe_pct["']/)
    expect(body).toMatch(/label:\s*["']D\/E["']/)
    expect(body).toMatch(/metricKey:\s*["']debt_to_equity["']/)
    expect(body).toMatch(/label:\s*["']Net margin["']/)
    expect(body).toMatch(/metricKey:\s*["']net_margin_pct["']/)
  })

  it("renders every label declared in the row spec", () => {
    for (const label of EXPECTED_LABELS) {
      // Escape forward slashes for the regex.
      const escaped = label.replace(/\//g, "\\/")
      expect(body, `row label "${label}" missing from rowSpec`).toMatch(
        new RegExp(`label:\\s*["']${escaped}["']`),
      )
    }
  })

  it("never wires label + metricKey as separate inline JSX props per row", () => {
    // Reject the legacy pattern: <MetricWithContext label="ROE" ... peerMedian={...} />
    // where the label literal is wired SEPARATELY from data.peer_context.X.
    // We allow the new shape (label={row.label} ...) because it
    // reads from the row spec, not from a literal next to peer_context.
    //
    // The guard: if a literal label="ROE" / label="PE" / label="D/E"
    // is bound AS A JSX PROP (with leading whitespace + `label="`)
    // adjacent to `data.peer_context`, the legacy inline layout is
    // back. Anything inside an object spec like `label: "ROE"` is
    // fine.
    const inlineJsxLabel =
      /<MetricWithContext[\s\S]{0,400}?\blabel=["'](ROE|PE|D\/E|Net margin|NIM|CASA|GNPA)["'][\s\S]{0,400}?\bdata\.peer_context\b/
    expect(body).not.toMatch(inlineJsxLabel)
  })

  it("maps each rendered row through MetricWithContext with label= bound to row.label", () => {
    // The new render path threads row.label through the JSX prop,
    // proving the label travels with the row spec.
    expect(body).toMatch(/label=\{row\.label\}/)
    expect(body).toMatch(/format=\{row\.format\}/)
    expect(body).toMatch(/direction=\{row\.direction\}/)
  })

  it("self-hides the panel when no rows pass the visibility gate", () => {
    // Empty cohorts shouldn't render an empty card with just a
    // heading — the rowSpec.filter(...).length === 0 path returns
    // null.
    expect(body).toMatch(/renderedRows\.length\s*===\s*0[\s\S]{0,40}return null/)
  })
})
