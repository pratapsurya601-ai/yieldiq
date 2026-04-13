"use client"

import { useEffect, useRef } from "react"
import { cn } from "@/lib/utils"
import { SCORE_COLOR, SCORE_GRADE } from "@/lib/constants"

interface ConvictionRingProps {
  score: number
  confidence: number
  size?: number
}

export default function ConvictionRing({ score, confidence, size = 140 }: ConvictionRingProps) {
  const outerRef = useRef<SVGCircleElement>(null)
  const innerRef = useRef<SVGCircleElement>(null)

  const outerRadius = size / 2 - 8
  const innerRadius = size / 2 - 22
  const outerCircumference = 2 * Math.PI * outerRadius
  const innerCircumference = 2 * Math.PI * innerRadius

  const scoreColor = SCORE_COLOR(score)
  const confidenceColor = confidence >= 70 ? "#185FA5" : confidence >= 40 ? "#B45309" : "#DC2626"
  const grade = SCORE_GRADE(score)

  // Gradient end color: lighten the score color
  const gradientEndColor = score >= 70 ? "#3B82F6" : score >= 50 ? "#F59E0B" : "#F87171"

  useEffect(() => {
    const outerEl = outerRef.current
    const innerEl = innerRef.current
    if (!outerEl || !innerEl) return

    outerEl.style.strokeDasharray = `${outerCircumference}`
    outerEl.style.strokeDashoffset = `${outerCircumference}`
    innerEl.style.strokeDasharray = `${innerCircumference}`
    innerEl.style.strokeDashoffset = `${innerCircumference}`

    requestAnimationFrame(() => {
      outerEl.style.transition = "stroke-dashoffset 1s ease-out"
      outerEl.style.strokeDashoffset = `${outerCircumference - (score / 100) * outerCircumference}`
      innerEl.style.transition = "stroke-dashoffset 1s ease-out 0.3s"
      innerEl.style.strokeDashoffset = `${innerCircumference - (confidence / 100) * innerCircumference}`
    })
  }, [score, confidence, outerCircumference, innerCircumference])

  return (
    <div
      className={cn("relative inline-flex items-center justify-center")}
      style={{
        width: size,
        height: size,
        filter: `drop-shadow(0 0 8px ${scoreColor}33)`,
      }}
    >
      <svg width={size} height={size} className="-rotate-90" role="img" aria-label={`YieldIQ Score: ${score} out of 100, confidence ${confidence}%`}>
        <title>YieldIQ Score: {score}/100</title>
        <defs>
          <linearGradient id={`scoreGrad-${score}`} x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor={scoreColor} />
            <stop offset="100%" stopColor={gradientEndColor} />
          </linearGradient>
        </defs>
        {/* Outer track */}
        <circle
          cx={size / 2}
          cy={size / 2}
          r={outerRadius}
          fill="none"
          stroke="#e5e7eb"
          strokeWidth={6}
        />
        {/* Outer score ring */}
        <circle
          ref={outerRef}
          cx={size / 2}
          cy={size / 2}
          r={outerRadius}
          fill="none"
          stroke={`url(#scoreGrad-${score})`}
          strokeWidth={6}
          strokeLinecap="round"
        />
        {/* Inner track */}
        <circle
          cx={size / 2}
          cy={size / 2}
          r={innerRadius}
          fill="none"
          stroke="#e5e7eb"
          strokeWidth={4}
        />
        {/* Inner confidence ring */}
        <circle
          ref={innerRef}
          cx={size / 2}
          cy={size / 2}
          r={innerRadius}
          fill="none"
          stroke={confidenceColor}
          strokeWidth={4}
          strokeLinecap="round"
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-3xl font-black text-gray-900" style={{ fontSize: size * 0.24 }}>
          {score}
        </span>
        <span className="text-xs font-bold mt-0.5" style={{ fontSize: size * 0.11, color: scoreColor }}>
          {grade}
        </span>
        <span className="text-xs text-gray-400" style={{ fontSize: size * 0.08 }}>
          Score
        </span>
      </div>
    </div>
  )
}
