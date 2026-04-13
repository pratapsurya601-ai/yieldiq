"use client"
import { useState, useEffect } from "react"

const STEPS = [
  "Fetching financial data...",
  "Running DCF model...",
  "Checking quality signals...",
  "Calculating YieldIQ Score...",
  "Preparing your analysis...",
]

export default function LoadingSteps() {
  const [step, setStep] = useState(0)

  useEffect(() => {
    const timers = STEPS.map((_, i) =>
      setTimeout(() => setStep(i), i * 800 + 500)
    )
    return () => timers.forEach(clearTimeout)
  }, [])

  return (
    <div className="max-w-2xl mx-auto px-4 py-8 space-y-6">
      {/* Skeleton header */}
      <div className="bg-white rounded-2xl border border-gray-100 p-5 space-y-4 animate-pulse">
        <div className="flex justify-between">
          <div>
            <div className="h-5 w-40 bg-gray-200 rounded mb-2" />
            <div className="h-3 w-24 bg-gray-100 rounded" />
          </div>
          <div className="h-6 w-28 bg-gray-200 rounded" />
        </div>
        <div className="flex items-center gap-5">
          {/* Skeleton conviction ring */}
          <div className="w-[120px] h-[120px] rounded-full bg-gray-100" />
          <div className="flex-1 space-y-3">
            <div className="h-6 w-28 bg-gray-200 rounded-full" />
            <div className="h-8 w-36 bg-gray-100 rounded" />
            <div className="h-4 w-48 bg-gray-100 rounded" />
          </div>
        </div>
      </div>

      {/* Progress steps */}
      <div className="bg-white rounded-2xl border border-gray-100 p-5">
        <div className="space-y-3">
          {STEPS.map((text, i) => (
            <div key={i} className="flex items-center gap-3">
              <div className={`w-5 h-5 rounded-full flex items-center justify-center text-xs
                ${i < step ? "bg-blue-600 text-white" : i === step ? "bg-blue-100 text-blue-600 animate-pulse" : "bg-gray-100 text-gray-400"}`}>
                {i < step ? "✓" : i + 1}
              </div>
              <span className={`text-sm ${i <= step ? "text-gray-900" : "text-gray-400"}`}>
                {text}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Skeleton insight cards */}
      <div className="grid grid-cols-2 gap-3">
        {[1,2,3,4].map(i => (
          <div key={i} className="bg-white rounded-xl border border-gray-100 p-3 animate-pulse">
            <div className="h-3 w-20 bg-gray-100 rounded mb-2" />
            <div className="h-5 w-12 bg-gray-200 rounded mb-1" />
            <div className="h-3 w-24 bg-gray-100 rounded" />
          </div>
        ))}
      </div>
    </div>
  )
}
