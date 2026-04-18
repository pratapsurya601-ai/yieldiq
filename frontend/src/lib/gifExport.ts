"use client"

/**
 * gifExport — despite the name, this module ships a single-frame PNG export
 * for v1 of the Time Machine. Full multi-frame WebM recording via
 * MediaRecorder + canvas.captureStream is plausible but requires either
 * html2canvas (not in our deps) or a much beefier SVG-rasterise-per-frame
 * loop than we want to take on right now. v1 captures the currently-visible
 * Prism frame so users can at least screenshot-share the "2021 vs today"
 * moment without a phone-OS screenshot.
 *
 * Approach: serialise the SVG node → blob → <img> → draw onto a 2x-DPI
 * <canvas> → PNG download. No deps, no window at module top-level. All
 * async to keep the UI responsive on low-end devices.
 */

export interface CapturePngOptions {
  /** Device-pixel scale — 2 gives retina-sharp output on most phones. */
  scale?: number
  /** Background colour; defaults to the page bg token. Transparent is
   *  discouraged because the gradient/Pulse glow reads as dirty without
   *  a backdrop. */
  background?: string
}

/**
 * Serialise an SVG node to a standalone data URL. We inline only the
 * styles that are already reflected in the SVG's own attributes (stroke,
 * fill, etc. are set explicitly in Signature/Spectrum), so we don't need to
 * walk computed styles — the Prism component paints every meaningful
 * property as an attribute, not via external CSS.
 */
function serializeSvg(svg: SVGSVGElement): string {
  const clone = svg.cloneNode(true) as SVGSVGElement
  if (!clone.getAttribute("xmlns")) {
    clone.setAttribute("xmlns", "http://www.w3.org/2000/svg")
  }
  const xml = new XMLSerializer().serializeToString(clone)
  // Use Blob URL instead of data: URL — Safari rejects large base64 SVG
  // images and the blob path is faster on every browser.
  return URL.createObjectURL(
    new Blob([xml], { type: "image/svg+xml;charset=utf-8" }),
  )
}

/**
 * Capture the first <svg> descendant of `root` as a PNG and trigger a
 * browser download. Resolves once the download has been dispatched;
 * rejects if no SVG is found or the browser can't rasterise it.
 */
export async function capturePngFromSvg(
  root: HTMLElement,
  filename: string,
  opts: CapturePngOptions = {},
): Promise<void> {
  if (typeof window === "undefined") {
    throw new Error("capturePngFromSvg called during SSR")
  }
  const svg = root.querySelector("svg") as SVGSVGElement | null
  if (!svg) throw new Error("No SVG found in target element")

  const scale = opts.scale ?? 2
  const rect = svg.getBoundingClientRect()
  const width = Math.max(1, Math.round(rect.width))
  const height = Math.max(1, Math.round(rect.height))

  const url = serializeSvg(svg)
  try {
    const img = new Image()
    img.crossOrigin = "anonymous"
    const loaded = new Promise<void>((resolve, reject) => {
      img.onload = () => resolve()
      img.onerror = () => reject(new Error("SVG image failed to load"))
    })
    img.src = url
    await loaded

    const canvas = document.createElement("canvas")
    canvas.width = width * scale
    canvas.height = height * scale
    const ctx = canvas.getContext("2d")
    if (!ctx) throw new Error("2D canvas context unavailable")
    ctx.scale(scale, scale)

    // Paint the background so the resulting PNG doesn't show checkerboard
    // transparency on Twitter/WhatsApp previews.
    const cssBg = getComputedStyle(document.documentElement)
      .getPropertyValue("--color-bg")
      .trim()
    const bg = opts.background ?? (cssBg || "#ffffff")
    ctx.fillStyle = bg
    ctx.fillRect(0, 0, width, height)
    ctx.drawImage(img, 0, 0, width, height)

    const blob: Blob | null = await new Promise((resolve) =>
      canvas.toBlob((b) => resolve(b), "image/png"),
    )
    if (!blob) throw new Error("Canvas toBlob returned null")

    const dl = URL.createObjectURL(blob)
    const a = document.createElement("a")
    a.href = dl
    a.download = filename
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    // Revoke asynchronously — some browsers fire the download AFTER a
    // microtask, so immediate revocation can abort it.
    setTimeout(() => URL.revokeObjectURL(dl), 5_000)
  } finally {
    URL.revokeObjectURL(url)
  }
}

/**
 * Feature-detect whether the browser can actually rasterise an SVG blob
 * onto a canvas. Safari < 15 and some WebKit forks silently fail. We check
 * up-front so the UI can hide the Record button cleanly instead of
 * surfacing a cryptic error mid-export.
 */
export function isPngCaptureSupported(): boolean {
  if (typeof window === "undefined") return false
  if (typeof document === "undefined") return false
  try {
    const c = document.createElement("canvas")
    return typeof c.toBlob === "function" && !!c.getContext("2d")
  } catch {
    return false
  }
}
