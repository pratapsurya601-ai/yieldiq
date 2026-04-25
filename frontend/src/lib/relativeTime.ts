// frontend/src/lib/relativeTime.ts
// Tiny zero-dependency relative-time formatter for the notifications
// drawer ("just now", "2h ago", etc.). Used instead of Intl.RelativeTimeFormat
// because the bell-drawer renders this on every poll and the Intl path
// allocates a fresh formatter object per call.
//
// Output beyond 7d falls back to a localized en-IN short date so a
// 3-month-old notification renders as "12 Jan" instead of "92d ago".
export function relativeTime(iso: string): string {
  const seconds = Math.floor((Date.now() - new Date(iso).getTime()) / 1000)
  if (seconds < 60) return "just now"
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`
  if (seconds < 604800) return `${Math.floor(seconds / 86400)}d ago`
  return new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short" })
}
