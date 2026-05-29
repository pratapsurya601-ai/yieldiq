"use client"

// MemoryLane — Phase 4 manifesto (Paradigm 11): per-user, per-ticker
// personal history layer. Shows on every analysis page for logged-in
// users with a prior visit. Calls three additive endpoints under
// /api/v1/me/ (router: backend/routers/me.py):
//
//   POST /me/ticker-visit/{ticker}        — fire-and-forget visit beacon
//   GET  /me/memory-lane/{ticker}         — 204 = render nothing
//   PUT  /me/memory-lane/{ticker}/note    — debounced auto-save (1s)
//
// SEBI safety: descriptive copy only ("you first analyzed this 47 days
// ago"), no advisory language. Verdict labels reuse the established
// verdictDisplayLabel() helper so they match the page hero verbatim.
//
// Renders null for:
//   - anon users (no token)
//   - logged-in users with no prior visit (GET returned 204)
// Visit-tracking POST is fired by AnalysisBody, not by this component,
// so the GET below sees a fresh row on the very first interaction.

import { useCallback, useEffect, useRef, useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { useAuthStore } from "@/store/authStore"
import { CountUp, RevealOnScroll } from "@/components/anim"
import { verdictDisplayLabel, formatCompanyName } from "@/lib/utils"

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

interface MemoryLanePayload {
  ticker: string
  ticker_bare: string
  first_visited_at: string | null
  last_visited_at: string | null
  days_ago: number
  visit_count: number
  price_at_first_visit: number | null
  fair_value_at_first_visit: number | null
  verdict_at_first_visit: string | null
  current_price: number | null
  current_fair_value: number | null
  current_verdict: string | null
  price_delta_pct: number | null
  fv_delta_pct: number | null
  hypothetical_10k_value: number | null
  user_note: string | null
}

function cleanTicker(ticker: string): string {
  return ticker
    .toUpperCase()
    .replace(".NS", "")
    .replace(".BO", "")
    .replace(".BSE", "")
    .replace(".NSE", "")
}

async function fetchMemoryLane(
  ticker: string,
  token: string,
): Promise<MemoryLanePayload | null> {
  const clean = cleanTicker(ticker)
  const res = await fetch(`${API_BASE}/api/v1/me/memory-lane/${clean}`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  // 204 = no prior visit; render nothing.
  if (res.status === 204) return null
  if (!res.ok) throw new Error(`memory-lane fetch failed: ${res.status}`)
  return res.json()
}

async function saveNote(
  ticker: string,
  note: string,
  token: string,
): Promise<void> {
  const clean = cleanTicker(ticker)
  const res = await fetch(
    `${API_BASE}/api/v1/me/memory-lane/${clean}/note`,
    {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({ note }),
    },
  )
  if (!res.ok) {
    const txt = await res.text().catch(() => "")
    throw new Error(`note save failed: ${res.status} ${txt}`)
  }
}

// Format ₹ with Indian-style grouping (lakh/crore commas). Matches the
// rest of the app's rupee formatting; no separate i18n lib for one widget.
function fmtRupee(n: number, decimals: number = 0): string {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: decimals,
    minimumFractionDigits: decimals,
  }).format(n)
}

function fmtDaysAgo(days: number): string {
  if (days === 0) return "today"
  if (days === 1) return "1 day ago"
  return `${days} days ago`
}

function deltaColor(pct: number | null): string {
  if (pct === null) return "text-caption"
  if (pct > 0) return "text-emerald-600 dark:text-emerald-400"
  if (pct < 0) return "text-rose-600 dark:text-rose-400"
  return "text-caption"
}

interface Props {
  ticker: string
  companyName?: string
}

export default function MemoryLane({ ticker, companyName }: Props) {
  const token = useAuthStore((s) => s.token)
  const userId = useAuthStore((s) => s.userId)

  const enabled = !!ticker && !!token && !!userId

  const query = useQuery({
    queryKey: ["memory-lane", cleanTicker(ticker)],
    queryFn: () => fetchMemoryLane(ticker, token as string),
    enabled,
    staleTime: 5 * 60 * 1000,
    retry: 1,
  })

  // Note auto-save state. Debounce 1s after typing stops.
  //
  // React 19 forbids both effect-based setState seeding and ref mutation
  // during render. The blessed pattern for "reset state when an upstream
  // identity changes" is to derive the prior-key via state and call
  // setState during render — React commits without an extra paint.
  // We also gate the in-flight debounce against `lastSaved` (state, not
  // ref) so optimistic-save bookkeeping plays by the same rules.
  const [noteDraft, setNoteDraft] = useState<string>("")
  const [lastSaved, setLastSaved] = useState<string>("")
  const [seededFor, setSeededFor] = useState<string | null>(null)
  const [noteStatus, setNoteStatus] = useState<"idle" | "saving" | "saved" | "error">(
    "idle",
  )
  const noteDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  if (query.data && seededFor !== query.data.ticker_bare) {
    const initial = query.data.user_note ?? ""
    setSeededFor(query.data.ticker_bare)
    setNoteDraft(initial)
    setLastSaved(initial)
  }

  const flushNote = useCallback(
    async (value: string) => {
      if (!token) return
      if (value === lastSaved) return
      setNoteStatus("saving")
      try {
        await saveNote(ticker, value, token)
        setLastSaved(value)
        setNoteStatus("saved")
        // Fade "Saved" back to idle after 2s.
        setTimeout(() => setNoteStatus((s) => (s === "saved" ? "idle" : s)), 2000)
      } catch {
        setNoteStatus("error")
      }
    },
    [token, ticker, lastSaved],
  )

  const onNoteChange = useCallback(
    (e: React.ChangeEvent<HTMLTextAreaElement>) => {
      const v = e.target.value
      setNoteDraft(v)
      if (noteDebounceRef.current) clearTimeout(noteDebounceRef.current)
      noteDebounceRef.current = setTimeout(() => flushNote(v), 1000)
    },
    [flushNote],
  )

  // Cleanup pending debounce on unmount.
  useEffect(() => {
    return () => {
      if (noteDebounceRef.current) clearTimeout(noteDebounceRef.current)
    }
  }, [])

  // Render nothing for anon, first-time visitors, or before data lands.
  // (No skeleton — Memory Lane is additive; an empty slot is fine.)
  if (!enabled) return null
  const data = query.data
  if (!data || !data.first_visited_at) return null

  const target = companyName ? formatCompanyName(companyName) : cleanTicker(ticker)
  const firstPrice = data.price_at_first_visit
  const firstFv = data.fair_value_at_first_visit
  const curPrice = data.current_price
  const curFv = data.current_fair_value
  const priceDelta = data.price_delta_pct
  const fvDelta = data.fv_delta_pct
  const hypo10k = data.hypothetical_10k_value

  // Verdict copy. If the verdict hasn't changed, render "still X". If it
  // changed, render "now X (was Y)". If we never had a verdict on first
  // visit (cache miss), skip the line entirely.
  const verdictThen = data.verdict_at_first_visit
  const verdictNow = data.current_verdict
  let verdictLine: string | null = null
  if (verdictThen && verdictNow) {
    const labelNow = verdictDisplayLabel(verdictNow)
    if (verdictThen === verdictNow) {
      verdictLine = `Verdict: still ${labelNow}.`
    } else {
      const labelThen = verdictDisplayLabel(verdictThen)
      verdictLine = `Verdict: now ${labelNow} (was ${labelThen}).`
    }
  }

  return (
    <RevealOnScroll>
      <section
        aria-labelledby="memory-lane-heading"
        className="bg-bg rounded-2xl border border-border p-4 sm:p-6 space-y-4"
      >
        <header>
          <h3
            id="memory-lane-heading"
            className="text-xs sm:text-sm font-semibold tracking-[0.18em] uppercase text-caption"
          >
            Your Memory Lane
          </h3>
        </header>

        <p className="text-sm sm:text-base text-ink leading-relaxed max-w-prose">
          You first analyzed{" "}
          <span className="font-semibold">{target}</span>{" "}
          <span className="font-semibold">{fmtDaysAgo(data.days_ago)}</span>
          {firstPrice !== null ? (
            <>
              {" "}
              at <span className="font-semibold tabular-nums">{fmtRupee(firstPrice, 0)}</span>.
            </>
          ) : (
            "."
          )}
        </p>

        {(firstFv !== null && curFv !== null) ||
        (firstPrice !== null && curPrice !== null) ||
        verdictLine ? (
          <ul className="text-sm text-ink space-y-1.5 list-none pl-0">
            {firstFv !== null && curFv !== null ? (
              <li className="flex items-baseline gap-2 flex-wrap">
                <span className="text-caption">Fair value moved</span>
                <span className="tabular-nums font-medium">
                  {fmtRupee(firstFv, 0)} → {fmtRupee(curFv, 0)}
                </span>
                {fvDelta !== null ? (
                  <span className={`tabular-nums font-semibold ${deltaColor(fvDelta)}`}>
                    (<CountUp to={fvDelta} duration={1.0} decimals={1} />%)
                  </span>
                ) : null}
              </li>
            ) : null}

            {firstPrice !== null && curPrice !== null ? (
              <li className="flex items-baseline gap-2 flex-wrap">
                <span className="text-caption">Price moved</span>
                <span className="tabular-nums font-medium">
                  {fmtRupee(firstPrice, 0)} → {fmtRupee(curPrice, 0)}
                </span>
                {priceDelta !== null ? (
                  <span className={`tabular-nums font-semibold ${deltaColor(priceDelta)}`}>
                    (<CountUp to={priceDelta} duration={1.0} decimals={1} />%)
                  </span>
                ) : null}
              </li>
            ) : null}

            {verdictLine ? (
              <li className="text-caption italic">{verdictLine}</li>
            ) : null}
          </ul>
        ) : null}

        {hypo10k !== null && firstPrice !== null ? (
          <p className="text-sm text-ink leading-relaxed max-w-prose">
            If you had bought{" "}
            <span className="font-semibold tabular-nums">₹10,000</span> worth
            that day, it would be worth{" "}
            <span className="font-semibold tabular-nums text-ink">
              <CountUp
                to={hypo10k}
                duration={1.4}
                decimals={0}
                format={(n) => fmtRupee(n, 0)}
              />
            </span>{" "}
            today.
          </p>
        ) : null}

        <div className="space-y-1">
          <label
            htmlFor="memory-lane-note"
            className="flex items-center justify-between text-xs uppercase tracking-wide text-caption font-semibold"
          >
            <span>Note for future-you</span>
            <span
              aria-live="polite"
              className={[
                "text-[10px] normal-case tracking-normal italic font-normal transition-opacity",
                noteStatus === "idle" ? "opacity-0" : "opacity-100",
                noteStatus === "error" ? "text-rose-600 dark:text-rose-400" : "text-caption",
              ].join(" ")}
            >
              {noteStatus === "saving"
                ? "Saving…"
                : noteStatus === "saved"
                  ? "Saved"
                  : noteStatus === "error"
                    ? "Couldn’t save — retrying on next edit"
                    : " "}
            </span>
          </label>
          <textarea
            id="memory-lane-note"
            value={noteDraft}
            onChange={onNoteChange}
            rows={2}
            maxLength={2000}
            placeholder="Why are you looking at this name? Auto-saves as you type."
            className="w-full rounded-lg border border-border bg-surface text-sm text-ink p-2 focus:outline-none focus:ring-2 focus:ring-brand/50 resize-y min-h-[60px]"
          />
        </div>

        <p className="text-xs text-caption">
          Visited{" "}
          <span className="font-semibold tabular-nums text-ink">
            <CountUp to={data.visit_count} duration={0.8} decimals={0} />
          </span>{" "}
          {data.visit_count === 1 ? "time" : "times"}.
        </p>
      </section>
    </RevealOnScroll>
  )
}
