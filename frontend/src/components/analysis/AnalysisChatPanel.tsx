// frontend/src/components/analysis/AnalysisChatPanel.tsx
//
// T6.2 Phase A (2026-06-10) — multi-turn streaming chat panel.
//
// The R4 prompt-presets feature is single-shot: one click, one
// answer, no follow-up turn. Users wanted to dig in — "okay but
// what if WACC drops 100bps", "compare that to ITC", etc. This
// panel adds CONVERSATIONAL exploration.
//
// Layout: a fixed bottom-right launcher button + a slide-in side
// drawer with the chat thread. The drawer is intentionally a
// portal-less inline drawer so it inherits the design tokens of
// the surrounding analysis page (matches the AIPromptPresetsPanel
// register). No modal scrim — the user can still scroll the page
// behind the drawer, which keeps the "ask while you read" flow
// working.
//
// Wire: POST /api/v1/analysis/{ticker}/chat with an SSE stream of
// {delta, done} JSON events. Assembled deltas land in the current
// assistant bubble in real time.
//
// Suggested prompts: a four-chip row above the textarea that
// prepopulates the input on click. Same SEBI-safe register as the
// preset cards (and authored hand-in-hand with the system-prompt
// constraint, so they always land cleanly in the LLM output).
//
// Keyboard: Cmd/Ctrl+Enter submits. Plain Enter inserts a newline
// (the input is a textarea so power users can compose multi-line
// follow-ups). Escape closes the drawer.

"use client"

import React, {
  type KeyboardEvent,
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
} from "react"

import {
  postChatStream,
  type ChatMessage,
  type ChatStreamEvent,
} from "@/lib/api"

interface Props {
  ticker: string
}

interface ThreadMessage extends ChatMessage {
  // Local-only fields. ``streaming`` is true while the assistant
  // bubble is still being assembled from deltas; ``error`` and
  // ``errorKind`` surface the most recent failure for the retry
  // affordance.
  streaming?: boolean
  error?: string | null
  errorKind?: "limit" | "generic" | null
}


// SEBI-safe prompt chips. Every line is observational and uses the
// vocabulary the system prompt encourages ("MoS", "scenario range",
// etc) so the LLM lands naturally in the right register.
const SUGGESTED_PROMPTS: string[] = [
  "Walk me through the composite IV gap and what closed it last quarter.",
  "Which DCF input is the most material driver of the MoS today?",
  "How does this name rank on score and MoS within its sector cohort?",
  "What scenario range does the model assign to bear / base / bull?",
]


export default function AnalysisChatPanel({ ticker }: Props) {
  const [open, setOpen] = useState(false)
  const [input, setInput] = useState("")
  const [messages, setMessages] = useState<ThreadMessage[]>([])
  const [sending, setSending] = useState(false)
  const [latestError, setLatestError] = useState<{
    kind: "limit" | "generic"
    message: string
  } | null>(null)

  const abortRef = useRef<AbortController | null>(null)
  const transcriptRef = useRef<HTMLDivElement | null>(null)
  const textareaRef = useRef<HTMLTextAreaElement | null>(null)
  const drawerId = useId()

  // Scroll the transcript to the bottom on every message tick so the
  // streaming response is always visible. We watch messages.length
  // AND the trailing message's content length so deltas trigger
  // scroll too.
  const trailingLen = messages[messages.length - 1]?.content.length ?? 0
  useEffect(() => {
    if (!transcriptRef.current) return
    transcriptRef.current.scrollTop = transcriptRef.current.scrollHeight
  }, [messages.length, trailingLen])

  // Esc closes the drawer (only while it is open).
  useEffect(() => {
    if (!open) return
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false)
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [open])

  // Focus the textarea when the drawer opens.
  useEffect(() => {
    if (open) {
      // Defer so the slide-in transition has started rendering.
      const t = setTimeout(() => textareaRef.current?.focus(), 80)
      return () => clearTimeout(t)
    }
  }, [open])

  // Abort any in-flight stream on unmount.
  useEffect(() => {
    return () => {
      abortRef.current?.abort()
    }
  }, [])


  const sendMessage = useCallback(
    async (content: string) => {
      const trimmed = content.trim()
      if (!trimmed || sending) return

      setLatestError(null)
      const userTurn: ThreadMessage = { role: "user", content: trimmed }
      const assistantTurn: ThreadMessage = {
        role: "assistant",
        content: "",
        streaming: true,
      }

      // Optimistic append — both turns visible immediately. The
      // assistant turn fills as deltas arrive.
      const baseHistory = messages
      const nextMessages: ThreadMessage[] = [
        ...baseHistory,
        userTurn,
        assistantTurn,
      ]
      setMessages(nextMessages)
      setInput("")
      setSending(true)

      const controller = new AbortController()
      abortRef.current = controller

      // Wire-history: drop the streaming placeholder before sending.
      const wireHistory: ChatMessage[] = [
        ...baseHistory.map((m) => ({ role: m.role, content: m.content })),
        { role: "user", content: trimmed },
      ]

      try {
        await postChatStream({
          ticker,
          messages: wireHistory,
          signal: controller.signal,
          onEvent: (ev: ChatStreamEvent) => {
            if (ev.error) {
              setMessages((prev) => {
                const copy = [...prev]
                const last = copy[copy.length - 1]
                if (last && last.role === "assistant") {
                  copy[copy.length - 1] = {
                    ...last,
                    streaming: false,
                    error: "Stream interrupted.",
                    errorKind: "generic",
                  }
                }
                return copy
              })
              return
            }
            if (ev.delta) {
              setMessages((prev) => {
                const copy = [...prev]
                const last = copy[copy.length - 1]
                if (last && last.role === "assistant") {
                  copy[copy.length - 1] = {
                    ...last,
                    content: last.content + ev.delta,
                  }
                }
                return copy
              })
            }
            if (ev.done) {
              setMessages((prev) => {
                const copy = [...prev]
                const last = copy[copy.length - 1]
                if (last && last.role === "assistant") {
                  copy[copy.length - 1] = { ...last, streaming: false }
                }
                return copy
              })
            }
          },
        })
      } catch (err) {
        const status = (err as { status?: number })?.status
        const kind: "limit" | "generic" = status === 429 ? "limit" : "generic"
        const message =
          kind === "limit"
            ? "Daily AI limit reached. Upgrade for unlimited chat turns."
            : "Could not reach the AI backend. Try again."
        setMessages((prev) => {
          const copy = [...prev]
          const last = copy[copy.length - 1]
          if (last && last.role === "assistant") {
            copy[copy.length - 1] = {
              ...last,
              streaming: false,
              error: message,
              errorKind: kind,
            }
          }
          return copy
        })
        setLatestError({ kind, message })
      } finally {
        setSending(false)
        abortRef.current = null
      }
    },
    [messages, sending, ticker],
  )


  const onTextareaKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
      e.preventDefault()
      void sendMessage(input)
    }
  }


  const retryLast = () => {
    // The most-recent user turn is always second-from-last after a
    // failure (assistant placeholder is last). Pop the failed assistant
    // turn AND the user turn, then re-send the user content so the
    // optimistic-append path runs again cleanly.
    setMessages((prev) => {
      if (prev.length < 2) return prev
      const lastUser = prev[prev.length - 2]
      const trimmed = prev.slice(0, -2)
      // Schedule the resend AFTER state settles to keep the wire
      // history consistent with the on-screen history.
      setTimeout(() => void sendMessage(lastUser.content), 0)
      return trimmed
    })
  }


  return (
    <>
      {/* Launcher — fixed bottom-right floating button. */}
      <button
        type="button"
        aria-label={open ? "Close AI chat" : "Open AI chat"}
        aria-expanded={open}
        aria-controls={drawerId}
        data-testid="analysis-chat-launcher"
        onClick={() => setOpen((v) => !v)}
        className={
          "fixed bottom-5 right-5 z-40 inline-flex items-center gap-2 " +
          "px-4 py-3 min-h-[48px] rounded-full shadow-lg " +
          "bg-brand text-white text-sm font-semibold " +
          "hover:opacity-90 active:scale-[0.98] transition"
        }
      >
        <span
          aria-hidden
          className="inline-flex w-6 h-6 items-center justify-center rounded-full bg-white/20 text-xs font-mono"
        >
          AI
        </span>
        <span>{open ? "Close chat" : "Chat with the model"}</span>
      </button>

      {/* Slide-in side drawer. */}
      <aside
        id={drawerId}
        data-testid="analysis-chat-panel"
        aria-hidden={!open}
        aria-label="Ask the model"
        className={
          "fixed top-0 right-0 z-30 h-full w-full sm:w-[420px] " +
          "bg-bg dark:bg-surface border-l border-border " +
          "shadow-2xl transition-transform duration-200 ease-out " +
          (open ? "translate-x-0" : "translate-x-full")
        }
        // Note: not using inert here because of legacy-browser fallout;
        // aria-hidden + tab-trap-via-launcher is the chosen compromise.
      >
        <div className="flex h-full flex-col">
          {/* Header */}
          <header className="flex items-center justify-between gap-3 border-b border-border px-4 py-3">
            <div className="flex items-center gap-2">
              <span
                aria-hidden
                className="inline-flex items-center justify-center w-7 h-7 rounded-full bg-brand-50 text-brand text-xs font-semibold"
              >
                AI
              </span>
              <div>
                <h2 className="text-sm font-semibold text-ink leading-tight">
                  Ask the model
                </h2>
                <p className="text-[11px] text-caption leading-tight">
                  Multi-turn chat about {ticker}
                </p>
              </div>
            </div>
            <button
              type="button"
              onClick={() => setOpen(false)}
              data-testid="analysis-chat-close"
              aria-label="Close chat"
              className="rounded-md p-1.5 text-caption hover:bg-border/30 transition"
            >
              <span aria-hidden className="text-base leading-none">×</span>
            </button>
          </header>

          {/* Transcript */}
          <div
            ref={transcriptRef}
            data-testid="analysis-chat-transcript"
            className="flex-1 overflow-y-auto px-4 py-3 space-y-3"
          >
            {messages.length === 0 && (
              <div
                data-testid="analysis-chat-empty"
                className="text-xs text-caption leading-relaxed"
              >
                Start a thread about <span className="font-mono">{ticker}</span>.
                The model answers using the current YieldIQ analysis — fair
                value, scenario range, DCF inputs. Replies are descriptive,
                not advice.
              </div>
            )}

            {messages.map((m, i) => (
              <MessageBubble key={i} message={m} index={i} onRetry={retryLast} />
            ))}
          </div>

          {/* Suggested prompts */}
          {messages.length === 0 && (
            <div
              data-testid="analysis-chat-suggestions"
              className="px-4 pb-2 flex flex-wrap gap-2"
            >
              {SUGGESTED_PROMPTS.map((p, i) => (
                <button
                  key={i}
                  type="button"
                  onClick={() => setInput(p)}
                  data-testid={`analysis-chat-suggestion-${i}`}
                  className="text-[11px] px-2.5 py-1 rounded-full border border-border text-ink hover:border-brand/40 hover:bg-brand-50 transition"
                >
                  {p}
                </button>
              ))}
            </div>
          )}

          {/* Composer */}
          <form
            data-testid="analysis-chat-composer"
            onSubmit={(e) => {
              e.preventDefault()
              void sendMessage(input)
            }}
            className="border-t border-border px-4 py-3 space-y-2"
          >
            <textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={onTextareaKey}
              placeholder={
                "Ask about MoS, scenario range, sector cohort percentile…"
              }
              rows={2}
              data-testid="analysis-chat-input"
              aria-label="Chat message"
              disabled={sending}
              className="w-full resize-none rounded-lg border border-border bg-bg dark:bg-surface px-3 py-2 text-sm text-ink placeholder:text-caption focus:outline-none focus:ring-2 focus:ring-brand/40"
            />
            <div className="flex items-center justify-between gap-3">
              <p className="text-[10px] text-caption">
                Cmd/Ctrl+Enter to send. Descriptive replies only.
              </p>
              <button
                type="submit"
                disabled={sending || !input.trim()}
                data-testid="analysis-chat-send"
                className="inline-flex items-center px-3 py-1.5 min-h-[36px] rounded-lg bg-brand text-white text-xs font-semibold hover:opacity-90 active:scale-[0.98] disabled:opacity-60 transition"
              >
                {sending ? "Streaming…" : "Send"}
              </button>
            </div>
            {latestError && latestError.kind === "limit" && (
              <p
                role="alert"
                data-testid="analysis-chat-limit-banner"
                className="text-[11px] text-caption"
              >
                {latestError.message}
              </p>
            )}
          </form>
        </div>
      </aside>
    </>
  )
}


// ── Sub-components ──────────────────────────────────────────────

interface MessageBubbleProps {
  message: ThreadMessage
  index: number
  onRetry: () => void
}

function MessageBubble({ message, index, onRetry }: MessageBubbleProps) {
  const isUser = message.role === "user"
  return (
    <div
      data-testid={`analysis-chat-message-${index}`}
      data-role={message.role}
      className={
        "flex " + (isUser ? "justify-end" : "justify-start")
      }
    >
      <div
        className={
          "max-w-[88%] rounded-2xl px-3 py-2 text-sm leading-relaxed whitespace-pre-wrap " +
          (isUser
            ? "bg-brand text-white"
            : "bg-surface dark:bg-bg border border-border text-ink")
        }
      >
        {message.content || (message.streaming ? (
          <StreamingPulse />
        ) : null)}

        {message.streaming && message.content && (
          <span
            aria-hidden
            className="inline-block w-1.5 h-3 align-baseline ml-0.5 bg-current animate-pulse"
            data-testid={`analysis-chat-cursor-${index}`}
          />
        )}

        {message.error && (
          <div
            role="alert"
            data-testid={`analysis-chat-error-${index}`}
            className="mt-2 text-[11px] text-caption space-y-1"
          >
            <p>{message.error}</p>
            {message.errorKind !== "limit" && (
              <button
                type="button"
                onClick={onRetry}
                data-testid={`analysis-chat-retry-${index}`}
                className="inline-flex items-center px-2 py-0.5 text-[10px] font-semibold text-brand bg-brand-50 rounded-md hover:opacity-90 transition"
              >
                Retry
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  )
}


function StreamingPulse() {
  // Three-dot pre-first-delta indicator. Once the first delta lands,
  // the bubble switches to rendering content + a trailing cursor.
  return (
    <span
      data-testid="analysis-chat-streaming-pulse"
      aria-label="Thinking"
      className="inline-flex items-center gap-1"
    >
      <span className="w-1.5 h-1.5 rounded-full bg-current opacity-60 animate-pulse" />
      <span
        className="w-1.5 h-1.5 rounded-full bg-current opacity-60 animate-pulse"
        style={{ animationDelay: "120ms" }}
      />
      <span
        className="w-1.5 h-1.5 rounded-full bg-current opacity-60 animate-pulse"
        style={{ animationDelay: "240ms" }}
      />
    </span>
  )
}
