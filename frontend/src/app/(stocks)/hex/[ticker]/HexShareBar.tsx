"use client"

import { useState } from "react"

interface HexShareBarProps {
  ticker: string
  url: string
}

export default function HexShareBar({ ticker, url }: HexShareBarProps) {
  const [copied, setCopied] = useState(false)

  const text = `${ticker} Hex on YieldIQ — a 6-axis profile of value, quality, growth, moat, safety, and pulse. Model estimate.`
  const twitter = `https://twitter.com/intent/tweet?text=${encodeURIComponent(text)}&url=${encodeURIComponent(url)}`
  const whatsapp = `https://api.whatsapp.com/send?text=${encodeURIComponent(`${text} ${url}`)}`

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(url)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // ignore
    }
  }

  return (
    <div className="flex flex-wrap gap-3">
      <a
        href={twitter}
        target="_blank"
        rel="noopener noreferrer"
        className="inline-flex items-center gap-2 bg-gray-900 text-white text-sm font-semibold px-4 py-2 rounded-xl hover:bg-gray-700 transition"
      >
        Share on X
      </a>
      <a
        href={whatsapp}
        target="_blank"
        rel="noopener noreferrer"
        className="inline-flex items-center gap-2 bg-green-600 text-white text-sm font-semibold px-4 py-2 rounded-xl hover:bg-green-500 transition"
      >
        WhatsApp
      </a>
      <button
        type="button"
        onClick={copy}
        className="inline-flex items-center gap-2 bg-blue-600 text-white text-sm font-semibold px-4 py-2 rounded-xl hover:bg-blue-500 transition"
      >
        {copied ? "Copied!" : "Copy link"}
      </button>
    </div>
  )
}
