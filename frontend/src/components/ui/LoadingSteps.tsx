"use client"

import { useEffect, useState } from "react"
import { cn } from "@/lib/utils"

const STEPS = [
  "Fetching data...",
  "Running DCF model...",
  "Checking quality signals...",
  "Preparing analysis...",
]

const STEP_DURATIONS = [1200, 1800, 1500, 1000]

export default function LoadingSteps() {
  const [currentStep, setCurrentStep] = useState(0)

  useEffect(() => {
    if (currentStep >= STEPS.length) return

    const timer = setTimeout(() => {
      setCurrentStep((prev) => prev + 1)
    }, STEP_DURATIONS[currentStep])

    return () => clearTimeout(timer)
  }, [currentStep])

  const progress = Math.min(((currentStep + 1) / STEPS.length) * 100, 100)

  return (
    <div className="flex flex-col items-center gap-6 py-12 px-4">
      {/* Progress bar */}
      <div className="w-full max-w-xs h-1.5 bg-gray-200 rounded-full overflow-hidden">
        <div
          className="h-full bg-blue-600 rounded-full transition-all duration-700 ease-out"
          style={{ width: `${progress}%` }}
        />
      </div>

      {/* Steps */}
      <div className="flex flex-col gap-3 w-full max-w-xs">
        {STEPS.map((step, i) => {
          const isActive = i === currentStep
          const isDone = i < currentStep

          return (
            <div key={step} className="flex items-center gap-3">
              {isDone ? (
                <svg className="h-4 w-4 text-blue-600 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
                </svg>
              ) : isActive ? (
                <div className="h-4 w-4 shrink-0 flex items-center justify-center">
                  <div className="h-2.5 w-2.5 rounded-full bg-blue-600 animate-pulse" />
                </div>
              ) : (
                <div className="h-4 w-4 shrink-0 flex items-center justify-center">
                  <div className="h-2 w-2 rounded-full bg-gray-300" />
                </div>
              )}
              <span
                className={cn(
                  "text-sm transition-colors",
                  isDone && "text-gray-500",
                  isActive && "text-gray-900 font-medium",
                  !isDone && !isActive && "text-gray-400"
                )}
              >
                {step}
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}
