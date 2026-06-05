/**
 * SectionIcon — typed mapping from section-name → Lucide icon.
 *
 * Replaces emoji-as-UI-semantics across analysis-page section
 * headers. Callers pick a name from a closed union; the mapping
 * picks the Lucide component. Size/color stay at currentColor so
 * callers control them via className (no hardcoded sizing here).
 *
 * Non-goals:
 *   - Theme wrapper or per-name color overrides — render plain.
 *   - Hardcoded sizes — let className win.
 */
import {
  BarChart3,
  Landmark,
  LineChart,
  ShieldCheck,
  Sparkles,
  Target,
  TrendingUp,
  Users,
  Wallet,
  AlertTriangle,
  type LucideIcon,
} from "lucide-react"

export type SectionIconName =
  | "moat"
  | "valuation"
  | "risk-flag"
  | "strengths"
  | "dividends"
  | "analyst"
  | "insider"
  | "promoter"
  | "quality"
  | "growth"

const ICON_MAP: Record<SectionIconName, LucideIcon> = {
  moat: ShieldCheck,
  valuation: LineChart,
  "risk-flag": AlertTriangle,
  strengths: Sparkles,
  dividends: Wallet,
  analyst: Target,
  insider: Users,
  promoter: Landmark,
  quality: BarChart3,
  growth: TrendingUp,
}

export interface SectionIconProps {
  name: SectionIconName
  /** Tailwind size + color classes; defaults to h-4 w-4 if absent. */
  className?: string
}

export default function SectionIcon({ name, className }: SectionIconProps) {
  const Icon = ICON_MAP[name]
  // Default to h-4 w-4 currentColor so it composes cleanly inside
  // headers; callers override via className.
  return (
    <Icon
      aria-hidden="true"
      data-testid={`section-icon-${name}`}
      className={className ?? "h-4 w-4"}
    />
  )
}
