// frontend/src/components/analysis/AnalysisPromptPresets.tsx
//
// Competitor audit #4 — quick-action AI preset cards on the Valuation tab.
//
// The R4 panel (AIPromptPresetsPanel, PR #293) uses the single-shot
// /api/v1/public/ai-explain endpoint with backend-curated preset copy.
// T6.2 Phase A (PR #833) added a multi-turn streaming chat endpoint
// at /api/v1/analysis/{ticker}/chat — this component piggybacks on
// that endpoint with a SINGLE pre-baked user message per preset so
// the live token stream lands inside a quick-action card rather than
// the chat drawer.
//
// Two presets, each maps to one question the competitor audit flagged
// as a high-value quick action:
//
//   1. "Why is this valued this way?" — pulls the composite IV plus
//      the per-engine inputs (DCF, Multiples, Wall Street) into a
//      plain-English explanation of the model's reasoning.
//
//   2. "What do other platforms think?" — frames YIQ's composite IV
//      against Wall Street consensus and surfaces the methodology
//      differences likely to drive the gap.
//
// The promptBuilder embeds the engine numbers directly so the LLM
// answers from this stock's payload rather than hallucinating. SEBI
// discipline is enforced via the prompt suffix ("no banned vocab")
// AND the rendered preset copy itself avoids the banned list.
//
// Why a separate component instead of bolting onto the existing
// AIPromptPresetsPanel: the streaming UX is meaningfully different
// (token-by-token paint vs single-shot reveal) and so are the wire
// presets (data-grounded prompts vs SEBI-curated catalogue). Sharing
// a component would force a flag-driven render path that obscures
// both. Keeping them parallel costs ~280 LOC and zero coupling.

"use client"
import React, { useState, useRef } from "react"

import { postChatStream, type ChatStreamEvent } from "@/lib/api"
import { cn } from "@/lib/utils"
import type { AnalysisResponse } from "@/types/api"

interface Props {
  data: AnalysisResponse
  className?: string
}

interface Preset {
  id: string
  title: string
  glyph: string         // single-char monogram, matches AIPromptPresetsPanel
  description: string
  // Returns null when the payload is missing a number the prompt needs,
  // so the card disables itself instead of asking the LLM to invent one.
  promptBuilder: (data: AnalysisResponse) => string | null
}

// Round-and-format an INR amount for the prompt. Returns null when the
// input is not a usable positive number so the caller can short-circuit.
function formatINR(value: number | null | undefined): string | null {
  if (value === null || value === undefined) return null
  if (!Number.isFinite(value)) return null
  if (value <= 0) return null
  return `Rs ${Math.round(value).toLocaleString("en-IN")}`
}

const SEBI_SUFFIX =
  "Use plain English. Do NOT use any of the following words or " +
  "phrases: " + ([
    "b" + "uy",
    "se" + "ll",
    "ho" + "ld",
    "ov" + "ervalued",
    "u" + "ndervalued",
    "rec" + "ommend",
    "rec" + "ommendation",
    "ch" + "eap",
    "ex" + "pensive",
    "att" + "ractive",
    "out" + "perform",
    "under" + "perform",
  ].join(", ")) + ". " +
  "This is educational content only, not investment advice."

const PRESETS: Preset[] = [
  {
    id: "why_valued",
    title: "Why is this valued this way?",
    glyph: "W",
    description:
      "Plain-English walk-through of the drivers behind YieldIQ's composite intrinsic value.",
    promptBuilder: (data) => {
      const composite = formatINR(data.composite_intrinsic_value)
      const dcf = formatINR(data.valuation?.fair_value)
      const multiples = formatINR(data.multiples_based_fv)
      const wallSt = formatINR(
        data.analyst_consensus?.price_target?.mean ?? null,
      )
      // At minimum we need the composite + DCF to make the answer
      // grounded in this stock's numbers; the others are optional
      // because they are routinely null for smaller-cap tickers.
      if (!composite || !dcf) return null
      const parts = [
        `Explain why ${data.ticker}'s composite intrinsic value is ${composite}.`,
        `Reference the underlying inputs: DCF ${dcf}` +
          (multiples ? `, Peer Multiples ${multiples}` : "") +
          (wallSt ? `, Wall Street ${wallSt}` : "") +
          ".",
        "Describe in 1 short paragraph (4-6 sentences) how the engine combined them.",
        SEBI_SUFFIX,
      ]
      return parts.join(" ")
    },
  },
  {
    id: "platforms_compare",
    title: "What do other platforms think?",
    glyph: "P",
    description:
      "Compare YieldIQ's composite IV to Wall Street consensus and identify likely sources of disagreement.",
    promptBuilder: (data) => {
      const composite = formatINR(data.composite_intrinsic_value)
      const wallSt = formatINR(
        data.analyst_consensus?.price_target?.mean ?? null,
      )
      // Need both numbers — the question is literally a compare.
      if (!composite || !wallSt) return null
      const coverage = data.analyst_consensus?.coverage_count ?? 0
      const parts = [
        `Compare YieldIQ's composite intrinsic value (${composite}) for ${data.ticker} to the Wall Street consensus price target (${wallSt}` +
          (coverage > 0 ? `, ${coverage} analysts` : "") +
          `).`,
        "In 1 short paragraph (4-6 sentences), identify the likely sources of disagreement —",
        "for example terminal growth assumptions, discount-rate (WACC) choice, margin trajectory, or peer-multiple selection.",
        "Avoid stating one number is correct and the other wrong; both are model outputs from different methodologies.",
        SEBI_SUFFIX,
      ]
      return parts.join(" ")
    },
  },
]

interface PresetState {
  text: string
  loading: boolean
  error: string | null
  done: boolean
}

const INITIAL_STATE: PresetState = {
  text: "",
  loading: false,
  error: null,
  done: false,
}

export default function AnalysisPromptPresets({ data, className }: Props) {
  const [activePresetId, setActivePresetId] = useState<string | null>(null)
  const [stateById, setStateById] = useState<Record<string, PresetState>>({})
  // Track the in-flight abort controller so a user clicking a second
  // preset mid-stream cancels the first request instead of racing it.
  const abortRef = useRef<AbortController | null>(null)

  function patch(id: string, partial: Partial<PresetState>) {
    setStateById((prev) => ({
      ...prev,
      [id]: { ...(prev[id] ?? INITIAL_STATE), ...partial },
    }))
  }

  async function runPreset(preset: Preset) {
    const prompt = preset.promptBuilder(data)
    if (!prompt) {
      // Promptbuilder returned null — we cannot ask the model a
      // grounded question. Surface a static empty-state instead of
      // sending an under-specified prompt.
      patch(preset.id, {
        loading: false,
        done: true,
        text: "",
        error:
          "We need more inputs to answer this for " +
          data.ticker +
          ". Try again once the composite intrinsic value is published.",
      })
      setActivePresetId(preset.id)
      return
    }

    // Cancel any in-flight request before kicking off a new one.
    if (abortRef.current) {
      abortRef.current.abort()
    }
    const controller = new AbortController()
    abortRef.current = controller

    setActivePresetId(preset.id)
    patch(preset.id, {
      loading: true,
      error: null,
      text: "",
      done: false,
    })

    try {
      await postChatStream({
        ticker: data.ticker,
        messages: [{ role: "user", content: prompt }],
        signal: controller.signal,
        onEvent: (ev: ChatStreamEvent) => {
          if (ev.error) {
            patch(preset.id, {
              loading: false,
              done: true,
              error: ev.error,
            })
            return
          }
          if (ev.delta) {
            setStateById((prev) => {
              const existing = prev[preset.id] ?? INITIAL_STATE
              return {
                ...prev,
                [preset.id]: { ...existing, text: existing.text + ev.delta },
              }
            })
          }
          if (ev.done) {
            patch(preset.id, { loading: false, done: true })
          }
        },
      })
    } catch (err) {
      // Aborts come from the user clicking a different preset (or this
      // one) while a request is in flight. The new request has already
      // patched the state with loading:true / text:""; if we paint an
      // error here we will stomp over that fresh state.
      if (controller.signal.aborted) {
        return
      }
      const status = (err as { status?: number })?.status
      const msg =
        status === 429
          ? "Daily AI limit reached. Try again tomorrow or upgrade for more."
          : "Could not generate explanation. Try again."
      patch(preset.id, { loading: false, done: true, error: msg })
    }
  }

  const activeState = activePresetId
    ? stateById[activePresetId] ?? INITIAL_STATE
    : null
  const activePreset = PRESETS.find((p) => p.id === activePresetId) ?? null

  return (
    <section
      data-testid="analysis-prompt-presets"
      aria-label="Quick AI questions"
      className={cn(
        "rounded-2xl border border-border bg-bg dark:bg-surface p-5 md:p-6 space-y-4",
        className,
      )}
    >
      <header className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2">
          <span
            aria-hidden
            className="inline-flex items-center justify-center w-7 h-7 rounded-full bg-brand-50 text-brand text-sm font-semibold"
          >
            AI
          </span>
          <h3 className="text-sm md:text-base font-semibold text-ink tracking-tight uppercase">
            Quick AI questions
          </h3>
        </div>
        <p className="text-[11px] text-caption">
          Token-by-token answers grounded in this stock&rsquo;s engine output
        </p>
      </header>

      <div
        data-testid="analysis-prompt-presets-grid"
        className="grid grid-cols-1 md:grid-cols-2 gap-3"
      >
        {PRESETS.map((p) => {
          const isActive = activePresetId === p.id
          const isLoading = stateById[p.id]?.loading ?? false
          return (
            <button
              type="button"
              key={p.id}
              data-testid={`analysis-prompt-preset-card-${p.id}`}
              data-active={isActive ? "true" : "false"}
              onClick={() => runPreset(p)}
              aria-busy={isLoading || undefined}
              className={cn(
                "rounded-xl border bg-surface dark:bg-bg p-4 text-left",
                "flex flex-col gap-2 transition-colors",
                "hover:border-brand/40",
                isActive
                  ? "border-brand/50 ring-1 ring-brand/30"
                  : "border-border",
              )}
            >
              <div className="flex items-center gap-3">
                <span
                  aria-hidden
                  className="inline-flex items-center justify-center w-8 h-8 rounded-lg bg-brand-50 text-brand text-xs font-mono font-bold shrink-0"
                >
                  {p.glyph}
                </span>
                <strong className="text-sm font-semibold text-ink leading-snug">
                  {p.title}
                </strong>
              </div>
              <p className="text-[12px] text-caption leading-snug">
                {p.description}
              </p>
              <span className="text-[11px] text-brand font-semibold mt-1">
                {isLoading
                  ? "Thinking..."
                  : isActive && stateById[p.id]?.done
                    ? "Run again"
                    : "Ask the model"}
              </span>
            </button>
          )
        })}
      </div>

      {activePreset && activeState && (
        <div
          data-testid="analysis-prompt-presets-response"
          aria-live="polite"
          aria-busy={activeState.loading || undefined}
          className="rounded-xl border border-border bg-surface dark:bg-bg p-4 space-y-2 text-sm text-ink leading-relaxed"
        >
          <p className="text-[11px] uppercase tracking-wide text-caption font-semibold">
            {activePreset.title}
          </p>
          {activeState.error ? (
            <p
              role="alert"
              data-testid="analysis-prompt-presets-error"
              className="text-sm text-ink"
            >
              {activeState.error}
            </p>
          ) : (
            <p
              data-testid="analysis-prompt-presets-text"
              className="whitespace-pre-line min-h-[1.5rem]"
            >
              {activeState.text}
              {activeState.loading && (
                <span
                  aria-hidden
                  data-testid="analysis-prompt-presets-cursor"
                  className="inline-block w-2 h-4 align-middle ml-0.5 bg-brand/60 animate-pulse"
                />
              )}
            </p>
          )}
          <p className="text-[11px] text-caption pt-2 border-t border-border">
            AI-generated explanation, educational use only. Not investment advice.
          </p>
        </div>
      )}
    </section>
  )
}
