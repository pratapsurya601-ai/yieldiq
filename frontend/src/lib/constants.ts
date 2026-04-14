// Single source of truth for colors — matches verdict_colors.py

export const VERDICT_COLORS = {
  undervalued: { bg: "bg-blue-50", text: "text-blue-800", border: "border-blue-200", hex: "#185FA5" },
  fairly_valued: { bg: "bg-gray-100", text: "text-gray-700", border: "border-gray-200", hex: "#475569" },
  overvalued: { bg: "bg-amber-50", text: "text-amber-800", border: "border-amber-200", hex: "#B45309" },
  avoid: { bg: "bg-red-50", text: "text-red-800", border: "border-red-200", hex: "#DC2626" },
  data_limited: { bg: "bg-gray-100", text: "text-gray-600", border: "border-gray-300", hex: "#6B7280" },
} as const

export const TIER_LIMITS = { free: 5, starter: 50, pro: Infinity } as const

export const SCORE_COLOR = (score: number): string => {
  if (score >= 75) return "#185FA5"
  if (score >= 55) return "#B45309"
  return "#DC2626"
}

export const SCORE_GRADE = (score: number): string => {
  if (score >= 75) return "A"
  if (score >= 55) return "B"
  if (score >= 35) return "C"
  if (score >= 20) return "D"
  return "F"
}
