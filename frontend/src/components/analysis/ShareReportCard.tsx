"use client"

/**
 * ShareReportCard — the "Share Report Card" entry point on analysis /
 * public-stock pages. Opens a bottom-sheet preview of the 1080x1920
 * Prism share card (served by /api/og/analysis/[ticker]) and offers:
 *
 *   1. Download — forces a browser download of the PNG blob, named
 *      `YieldIQ_{TICKER}_prism.png` so the user's Photos app groups
 *      them together.
 *
 *   2. Share — uses navigator.share with the image file when the
 *      browser supports file-share (most mobile browsers do). Falls
 *      back to copying the share URL to the clipboard when it doesn't
 *      (desktop Chrome, Firefox, etc.).
 *
 * The image is 1080x1920 — the exact portrait size Instagram Story
 * and Twitter vertical both accept without cropping. WhatsApp Status
 * will letterbox slightly but preserves the frame.
 *
 * The share image URL intentionally uses the raw ticker (as supplied
 * in the URL) so the OG endpoint can normalise it (.NS suffix etc.)
 * the same way the analysis page does — no risk of two cached image
 * variants for the same stock.
 */

import { useCallback, useEffect, useMemo, useState } from "react"
import { trackExportUsed } from "@/lib/analytics"

interface ShareReportCardProps {
  ticker: string
  /** Optional visual variant — defaults to the full primary-button style
   *  matching analysis page CTAs. `compact` produces a smaller pill for
   *  dense layouts (e.g. public stocks page). */
  variant?: "primary" | "compact"
  /** Optional className override for positioning. */
  className?: string
}

function displayTicker(t: string): string {
  return (t || "").replace(/\.(NS|BO)$/i, "").toUpperCase()
}

// Phase 4.2 (2026-05-25): the modal now supports two share artefacts.
//   • prism        — the original 1080x1920 Prism portrait
//   • money_story  — Money Camera 1080x1920 story format
//   • money_horiz  — Money Camera 1200x630 horizontal OG card
// The Prism option is preserved verbatim; Money Camera is added as a
// new selectable format. Default is `money_story` since Phase 4.2 sets
// Money Camera as the canonical share image on the analysis page.
type ShareFormat = "prism" | "money_story" | "money_horiz"

interface FormatDef {
  key: ShareFormat
  label: string
  src: (ticker: string) => string
  width: number
  height: number
  aspect: string
  downloadSuffix: string
}

const FORMATS: FormatDef[] = [
  {
    key: "money_story",
    label: "Money Camera · Story",
    src: (t) =>
      `/api/og/money-camera/${encodeURIComponent(t)}?format=story`,
    width: 1080,
    height: 1920,
    aspect: "9 / 16",
    downloadSuffix: "moneycamera_story",
  },
  {
    key: "money_horiz",
    label: "Money Camera · Wide",
    src: (t) =>
      `/api/og/money-camera/${encodeURIComponent(t)}?format=horizontal`,
    width: 1200,
    height: 630,
    aspect: "1200 / 630",
    downloadSuffix: "moneycamera_wide",
  },
  {
    key: "prism",
    label: "Prism Card",
    src: (t) => `/api/og/analysis/${encodeURIComponent(t)}`,
    width: 1080,
    height: 1920,
    aspect: "9 / 16",
    downloadSuffix: "prism",
  },
]

export default function ShareReportCard({
  ticker,
  variant = "primary",
  className,
}: ShareReportCardProps) {
  const [open, setOpen] = useState(false)
  // We track which src has loaded (or errored) instead of a bare bool
  // so switching format resets the spinner without a setState-in-effect
  // pattern. `loadedSrc === imgSrc` means the current preview is ready;
  // `errorSrc === imgSrc` means it failed.
  const [loadedSrc, setLoadedSrc] = useState<string | null>(null)
  const [errorSrc, setErrorSrc] = useState<string | null>(null)
  const [toast, setToast] = useState<string | null>(null)
  const [format, setFormat] = useState<ShareFormat>("money_story")

  const activeFormat = useMemo(
    () => FORMATS.find((f) => f.key === format) ?? FORMATS[0],
    [format]
  )

  // The image path is stable per (ticker, format) — memoise so the
  // preview <img> doesn't re-request every time the toast timer fires
  // a re-render. Changing format intentionally swaps the src, which is
  // what triggers the preview to reload.
  const imgSrc = useMemo(
    () => activeFormat.src(ticker),
    [activeFormat, ticker]
  )

  // ESC closes the modal — mirrors the Prism PillarExplainer pattern.
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false)
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [open])

  // Auto-dismiss the inline toast after 3s.
  useEffect(() => {
    if (!toast) return
    const t = setTimeout(() => setToast(null), 3000)
    return () => clearTimeout(t)
  }, [toast])

  // Note: when the user switches format we reset the loading state by
  // remounting the <img> via React's `key` prop (set to `format` below)
  // rather than calling setState in an effect — the latter is flagged
  // by react-hooks/set-state-in-effect under the React 19 ruleset.

  const handleOpen = useCallback(() => {
    trackExportUsed("prism_card_open", ticker)
    setLoadedSrc(null)
    setErrorSrc(null)
    setOpen(true)
  }, [ticker])

  const fetchBlob = useCallback(async (): Promise<Blob> => {
    // Request the same URL the preview is showing. The browser will
    // usually hit the cached copy, so this is nearly instant after the
    // modal has opened.
    const res = await fetch(imgSrc, { cache: "force-cache" })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    return res.blob()
  }, [imgSrc])

  const handleDownload = useCallback(async () => {
    trackExportUsed("prism_card_download", ticker)
    try {
      const blob = await fetchBlob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement("a")
      a.href = url
      a.download = `YieldIQ_${displayTicker(ticker)}_${activeFormat.downloadSuffix}.png`
      document.body.appendChild(a)
      a.click()
      a.remove()
      // Revoke on next tick so Safari has time to start the download.
      setTimeout(() => URL.revokeObjectURL(url), 1000)
      setToast("Card downloaded.")
    } catch {
      setToast("Download failed — try again.")
    }
  }, [fetchBlob, ticker, activeFormat.downloadSuffix])

  const handleShare = useCallback(async () => {
    trackExportUsed("prism_card_share", ticker)
    const shareUrl = `https://yieldiq.in/analysis/${encodeURIComponent(ticker)}`
    const shareTitle = `${displayTicker(ticker)} on YieldIQ`
    const shareText = `${displayTicker(ticker)} analysis — fair value, Prism score & verdict on YieldIQ`

    // Prefer the "share the actual image" flow on browsers that support
    // it (most mobile). This is what makes the card actually reach a
    // friend's inbox vs. just a link.
    try {
      const blob = await fetchBlob()
      const file = new File(
        [blob],
        `YieldIQ_${displayTicker(ticker)}_${activeFormat.downloadSuffix}.png`,
        { type: "image/png" }
      )
      const nav = navigator as Navigator & {
        canShare?: (d: ShareData) => boolean
      }
      if (
        typeof nav.share === "function" &&
        typeof nav.canShare === "function" &&
        nav.canShare({ files: [file] })
      ) {
        await nav.share({
          files: [file],
          title: shareTitle,
          text: shareText,
          url: shareUrl,
        })
        return
      }
      // Native share without file support (older iOS) — share the link.
      if (typeof nav.share === "function") {
        await nav.share({ title: shareTitle, text: shareText, url: shareUrl })
        return
      }
    } catch {
      // User dismissed, file-share refused, or fetch failed — fall through.
    }

    // Desktop fallback: copy the share URL.
    try {
      await navigator.clipboard.writeText(shareUrl)
      setToast("Link copied to clipboard.")
    } catch {
      setToast("Share unavailable on this device.")
    }
  }, [fetchBlob, ticker, activeFormat.downloadSuffix])

  // Mobile: enlarge tap target and bump min-height to 44px (a11y baseline).
  const buttonClass =
    variant === "compact"
      ? "inline-flex items-center gap-1.5 px-3 py-2 min-h-[44px] text-xs font-semibold text-brand bg-brand-50 hover:bg-brand/10 rounded-lg transition"
      : "inline-flex items-center gap-2 px-4 py-2 min-h-[44px] text-sm font-semibold text-white bg-brand hover:opacity-90 active:scale-[0.97] rounded-lg transition"

  return (
    <>
      <button
        type="button"
        onClick={handleOpen}
        className={[buttonClass, className].filter(Boolean).join(" ")}
        aria-label="Share report card"
      >
        <ShareIcon />
        {/* Hide long label on mobile — icon + aria-label still convey
            intent and tap target stays >= 44px. Show full text from sm. */}
        <span className="hidden sm:inline">Share Report Card</span>
        <span className="sm:hidden">Share</span>
      </button>

      {open && (
        <div
          className="fixed inset-0 z-50"
          role="dialog"
          aria-modal="true"
          aria-labelledby="share-report-card-title"
        >
          <button
            type="button"
            aria-label="Close"
            onClick={() => setOpen(false)}
            className="absolute inset-0 bg-black/60"
          />
          <div
            className="
              absolute left-0 right-0 bottom-0 max-h-[92vh] overflow-y-auto
              bg-surface border-t border-border rounded-t-2xl p-5
              md:left-1/2 md:right-auto md:top-1/2 md:bottom-auto md:-translate-x-1/2 md:-translate-y-1/2
              md:max-h-[92vh] md:w-[520px] md:rounded-2xl md:border
            "
          >
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="text-[10px] uppercase tracking-[0.15em] font-semibold text-brand">
                  Share
                </p>
                <h3
                  id="share-report-card-title"
                  className="text-xl font-semibold text-ink mt-0.5"
                >
                  {displayTicker(ticker)} &mdash; Share
                </h3>
                <p className="text-xs text-caption mt-1">
                  {activeFormat.width} &times; {activeFormat.height} &mdash;{" "}
                  {activeFormat.key === "money_horiz"
                    ? "Open Graph / Twitter / LinkedIn"
                    : "Instagram Story / Twitter vertical"}
                </p>
              </div>
              <button
                type="button"
                aria-label="Close"
                onClick={() => setOpen(false)}
                className="shrink-0 w-8 h-8 rounded-full hover:bg-bg flex items-center justify-center text-caption text-xl leading-none"
              >
                &times;
              </button>
            </div>

            {/* Format selector — Money Camera (story + wide) and the
                legacy Prism card. Pill-style tabs so the tap targets
                stay finger-friendly on mobile. */}
            <div
              className="mt-4 flex gap-2 overflow-x-auto"
              role="tablist"
              aria-label="Share format"
            >
              {FORMATS.map((f) => {
                const active = f.key === format
                return (
                  <button
                    key={f.key}
                    type="button"
                    role="tab"
                    aria-selected={active}
                    onClick={() => setFormat(f.key)}
                    className={[
                      "shrink-0 px-3 py-1.5 min-h-[36px] text-xs font-semibold rounded-full border transition",
                      active
                        ? "bg-brand text-white border-brand"
                        : "bg-transparent text-ink border-border hover:bg-bg",
                    ].join(" ")}
                  >
                    {f.label}
                  </button>
                )
              })}
            </div>

            {/* Preview frame — aspect ratio tracks the active format so
                the image area stays stable while the PNG streams in.
                Switching to Money Camera Wide reshapes the box to 1200:630. */}
            <div className="mt-4 rounded-xl overflow-hidden border border-border bg-bg">
              <div
                className="relative w-full"
                style={{ aspectRatio: activeFormat.aspect }}
              >
                {loadedSrc !== imgSrc && errorSrc !== imgSrc && (
                  <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 text-caption">
                    <div className="h-7 w-7 animate-spin rounded-full border-2 border-brand border-t-transparent" />
                    <span className="text-xs">Generating card&hellip;</span>
                  </div>
                )}
                {errorSrc === imgSrc && (
                  <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-caption px-6 text-center">
                    <p className="text-sm text-ink font-semibold">
                      Preview unavailable
                    </p>
                    <p className="text-xs">
                      We couldn&rsquo;t render the card right now. Try the
                      download button &mdash; the image endpoint may still
                      work.
                    </p>
                  </div>
                )}
                {/* We use plain <img> (not next/image) on purpose —
                    the OG endpoint already serves a pre-sized PNG with
                    long-lived cache headers, and next/image would
                    double-fetch through the optimiser. */}
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  key={format}
                  src={imgSrc}
                  alt={`YieldIQ ${activeFormat.label} for ${displayTicker(ticker)}`}
                  width={activeFormat.width}
                  height={activeFormat.height}
                  className="w-full h-full object-contain"
                  onLoad={() => setLoadedSrc(imgSrc)}
                  onError={() => setErrorSrc(imgSrc)}
                />
              </div>
            </div>

            <div className="mt-4 grid grid-cols-2 gap-3">
              <button
                type="button"
                onClick={handleDownload}
                disabled={errorSrc === imgSrc}
                className="inline-flex items-center justify-center gap-2 px-4 py-2.5 min-h-[44px] text-sm font-semibold text-ink bg-bg hover:bg-border rounded-lg border border-border transition disabled:opacity-50"
              >
                <DownloadIcon />
                Download
              </button>
              <button
                type="button"
                onClick={handleShare}
                disabled={errorSrc === imgSrc}
                className="inline-flex items-center justify-center gap-2 px-4 py-2.5 min-h-[44px] text-sm font-semibold text-white bg-brand hover:opacity-90 active:scale-[0.98] rounded-lg transition disabled:opacity-50"
              >
                <ShareIcon />
                Share
              </button>
            </div>

            <p className="text-[11px] text-caption leading-relaxed mt-4 text-center">
              Model estimate only. Not investment advice.
            </p>

            {toast && (
              <div
                className="fixed bottom-6 left-1/2 -translate-x-1/2 bg-gray-900 text-white text-xs font-medium px-4 py-2 rounded-lg shadow-lg z-50 whitespace-nowrap"
                role="status"
              >
                {toast}
              </div>
            )}
          </div>
        </div>
      )}
    </>
  )
}

function ShareIcon() {
  return (
    <svg
      className="w-4 h-4"
      fill="none"
      viewBox="0 0 24 24"
      stroke="currentColor"
      strokeWidth={1.8}
      aria-hidden="true"
    >
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M7.217 10.907a2.25 2.25 0 100 2.186m0-2.186c.18.324.283.696.283 1.093s-.103.77-.283 1.093m0-2.186l9.566-5.314m-9.566 7.5l9.566 5.314m0 0a2.25 2.25 0 103.935 2.186 2.25 2.25 0 00-3.935-2.186zm0-12.814a2.25 2.25 0 103.933-2.185 2.25 2.25 0 00-3.933 2.185z"
      />
    </svg>
  )
}

function DownloadIcon() {
  return (
    <svg
      className="w-4 h-4"
      fill="none"
      viewBox="0 0 24 24"
      stroke="currentColor"
      strokeWidth={1.8}
      aria-hidden="true"
    >
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12m4.5 4.5V3"
      />
    </svg>
  )
}
