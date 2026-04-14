import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function formatCurrency(value: number, currency: string = "INR"): string {
  const abs = Math.abs(value)
  if (currency === "INR") {
    if (abs >= 1e7) return `\u20b9${(value / 1e7).toFixed(1)}Cr`
    if (abs >= 1e5) return `\u20b9${(value / 1e5).toFixed(1)}L`
    return `\u20b9${value.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`
  }
  if (abs >= 1e9) return `$${(value / 1e9).toFixed(1)}B`
  if (abs >= 1e6) return `$${(value / 1e6).toFixed(1)}M`
  return `$${value.toLocaleString("en-US", { maximumFractionDigits: 2 })}`
}

export function formatMoS(mos: number): string {
  return `${mos >= 0 ? "+" : ""}${mos.toFixed(1)}%`
}

export function formatPct(value: number): string {
  return `${value >= 0 ? "+" : ""}${value.toFixed(1)}%`
}

const COMPANY_ABBREVIATIONS: Record<string, string> = {
  LT: "Ltd",
  LTD: "Ltd",
  SERV: "Services",
  IND: "Industries",
  CORP: "Corporation",
  TECH: "Technologies",
  PHARMA: "Pharma",
  FIN: "Finance",
  INF: "Infrastructure",
  CONS: "Consultancy",
  ENT: "Enterprises",
  INTL: "International",
  MFG: "Manufacturing",
  GRP: "Group",
  HLD: "Holdings",
  HLDG: "Holdings",
  CHEM: "Chemicals",
  ENGG: "Engineering",
  ELEC: "Electricals",
  AUTO: "Automobiles",
  RLWY: "Railway",
  PETRO: "Petroleum",
}

export function formatCompanyName(name: string): string {
  if (!name) return name
  // Already looks properly formatted (has lowercase letters)
  if (/[a-z]/.test(name)) return name
  return name
    .split(/\s+/)
    .map((word) => {
      const upper = word.toUpperCase()
      if (COMPANY_ABBREVIATIONS[upper]) return COMPANY_ABBREVIATIONS[upper]
      if (upper.length <= 2 && /^[A-Z&]+$/.test(upper)) return upper // keep short abbrevs like "IT", "&"
      return word.charAt(0).toUpperCase() + word.slice(1).toLowerCase()
    })
    .join(" ")
}
