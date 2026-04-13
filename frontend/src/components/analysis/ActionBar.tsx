"use client"

import { useState } from "react"
import { cn } from "@/lib/utils"

interface ActionBarProps {
  ticker: string
  currentPrice: number
}

function ActionButton({ icon, label, onClick }: { icon: React.ReactNode; label: string; onClick?: () => void }) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "flex flex-1 flex-col items-center gap-1 rounded-xl bg-gray-50 py-3 px-2",
        "text-gray-600 hover:bg-gray-100 active:bg-gray-200 transition-colors"
      )}
    >
      {icon}
      <span className="text-xs font-medium">{label}</span>
    </button>
  )
}

export default function ActionBar({ ticker, currentPrice }: ActionBarProps) {
  const handleWatchlist = () => {
    // TODO: add to watchlist
  }

  const handleAlert = () => {
    // TODO: set price alert
  }

  const handleExport = async () => {
    try {
      const token = document.cookie.split("yieldiq_token=")[1]?.split(";")[0]
      const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"
      const response = await fetch(`${API_BASE}/api/v1/analysis/${ticker}/report`, {
        headers: { Authorization: `Bearer ${token}` },
      })
      if (!response.ok) throw new Error("Export failed")
      const blob = await response.blob()
      const url = window.URL.createObjectURL(blob)
      const a = document.createElement("a")
      a.href = url
      a.download = `YieldIQ_${ticker}.txt`
      document.body.appendChild(a)
      a.click()
      a.remove()
      window.URL.revokeObjectURL(url)
    } catch {
      alert("Could not generate report. Please try again.")
    }
  }

  const [showCopied, setShowCopied] = useState(false)

  const handleShare = async () => {
    const shareUrl = `https://yieldiq.in/analysis/${ticker}`
    try {
      await navigator.clipboard.writeText(shareUrl)
      setShowCopied(true)
      setTimeout(() => setShowCopied(false), 2000)
    } catch {
      // Fallback for browsers that block clipboard API
      if (navigator.share) {
        navigator.share({
          title: `${ticker} Analysis — YieldIQ`,
          text: `Check out the YieldIQ analysis for ${ticker}`,
          url: shareUrl,
        }).catch(() => {})
      }
    }
  }

  return (
    <div className="relative flex flex-row gap-2">
      {/* Copied toast */}
      {showCopied && (
        <div className="absolute -top-10 left-1/2 -translate-x-1/2 bg-gray-900 text-white text-xs font-medium px-3 py-1.5 rounded-lg shadow-lg animate-fade-in whitespace-nowrap z-10">
          Link copied!
        </div>
      )}
      <ActionButton
        label="Watchlist"
        onClick={handleWatchlist}
        icon={
          <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M11.48 3.499a.562.562 0 011.04 0l2.125 5.111a.563.563 0 00.475.345l5.518.442c.499.04.701.663.321.988l-4.204 3.602a.563.563 0 00-.182.557l1.285 5.385a.562.562 0 01-.84.61l-4.725-2.885a.562.562 0 00-.586 0L6.982 20.54a.562.562 0 01-.84-.61l1.285-5.386a.562.562 0 00-.182-.557l-4.204-3.602a.562.562 0 01.321-.988l5.518-.442a.563.563 0 00.475-.345L11.48 3.5z" />
          </svg>
        }
      />
      <ActionButton
        label="Alert"
        onClick={handleAlert}
        icon={
          <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M14.857 17.082a23.848 23.848 0 005.454-1.31A8.967 8.967 0 0118 9.75V9A6 6 0 006 9v.75a8.967 8.967 0 01-2.312 6.022c1.733.64 3.56 1.085 5.455 1.31m5.714 0a24.255 24.255 0 01-5.714 0m5.714 0a3 3 0 11-5.714 0" />
          </svg>
        }
      />
      <ActionButton
        label="Export"
        onClick={handleExport}
        icon={
          <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12m4.5 4.5V3" />
          </svg>
        }
      />
      <ActionButton
        label="Share"
        onClick={handleShare}
        icon={
          <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M7.217 10.907a2.25 2.25 0 100 2.186m0-2.186c.18.324.283.696.283 1.093s-.103.77-.283 1.093m0-2.186l9.566-5.314m-9.566 7.5l9.566 5.314m0 0a2.25 2.25 0 103.935 2.186 2.25 2.25 0 00-3.935-2.186zm0-12.814a2.25 2.25 0 103.933-2.185 2.25 2.25 0 00-3.933 2.185z" />
          </svg>
        }
      />
    </div>
  )
}
