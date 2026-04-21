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

export default function ShareReportCard({
  ticker,
  variant = "primary",
  className,
}: ShareReportCardProps) {
  const [open, setOpen] = useState(false)
  const [imgLoaded, setImgLoaded] = useState(false)
  const [imgError, setImgError] = useState(false)
  const [toast, setToast] = useState<string | null>(null)

  // The image path is stable across renders — memoise so the preview
  // <img> doesn't re-request every time this component re-renders due
  // to the toast timer.
  const imgSrc = useMemo(
    () => `/api/og/analysis/${encodeURIComponent(ticker)}`,
    [ticker]
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

  const handleOpen = useCallback(() => {
    trackExportUsed("prism_card_open", ticker)
    setImgLoaded(false)
    setImgError(false)
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
      a.download = `YieldIQ_${displayTicker(ticker)}_prism.png`
      document.body.appendChild(a)
      a.click()
      a.remove()
      // Revoke on next tick so Safari has time to start the download.
      setTimeout(() => URL.revokeObjectURL(url), 1000)
      setToast("Card downloaded.")
    } catch {
      setToast("Download failed — try again.")
    }
  }, [fetchBlob, ticker])

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
        `YieldIQ_${displayTicker(ticker)}_prism.png`,
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
  }, [fetchBlob, ticker])

  const buttonClass =
    variant === "compact"
      ? "inline-flex items-center gap-1.5 px-3 py-1.5 min-h-[36px] text-xs font-semibold text-brand bg-brand-50 hover:bg-brand/10 rounded-lg transition"
      : "inline-flex items-center gap-2 px-4 py-2 min-h-[40px] text-sm font-semibold text-white bg-brand hover:opacity-90 active:scale-[0.97] rounded-lg transition"

  return (
    <>
      <button
        type="button"
        onClick={handleOpen}
        className={[buttonClass, className].filter(Boolean).join(" ")}
        aria-label="Share report card"
      >
        <ShareIcon />
        <span>Share Report Card</span>
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
                  {displayTicker(ticker)} Prism Card
                </h3>
                <p className="text-xs text-caption mt-1">
                  1080 &times; 1920 &mdash; Instagram Story / Twitter vertical
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

            {/* Preview frame — 9:16 aspect box so the image area is
                stable while the PNG streams in. */}
            <div className="mt-4 rounded-xl overflow-hidden border border-border bg-bg">
              <div
                className="relative w-full"
                style={{ aspectRatio: "9 / 16" }}
              >
                {!imgLoaded && !imgError && (
                  <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 text-caption">
                    <div className="h-7 w-7 animate-spin rounded-full border-2 border-brand border-t-transparent" />
                    <span className="text-xs">Generating card&hellip;</span>
                  </div>
                )}
                {imgError && (
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
                  src={imgSrc}
                  alt={`YieldIQ Prism report card for ${displayTicker(ticker)}`}
                  width={1080}
                  height={1920}
                  className="w-full h-full object-contain"
                  onLoad={() => setImgLoaded(true)}
                  onError={() => setImgError(true)}
                />
              </div>
            </div>

            <div className="mt-4 grid grid-cols-2 gap-3">
              <button
                type="button"
                onClick={handleDownload}
                disabled={imgError}
                className="inline-flex items-center justify-center gap-2 px-4 py-2.5 min-h-[44px] text-sm font-semibold text-ink bg-bg hover:bg-border rounded-lg border border-border transition disabled:opacity-50"
              >
                <DownloadIcon />
                Download
              </button>
              <button
                type="button"
                onClick={handleShare}
                disabled={imgError}
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
