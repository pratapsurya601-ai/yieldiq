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
