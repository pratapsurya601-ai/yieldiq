import { redirect } from "next/navigation"

// /screener was promised by some entry points but the canonical screener
// lives under /discover/screener (where filter chips, presets, and
// counts live). Redirect rather than 404 so any stale link, bookmark, or
// nav typo lands on the real page.
export default function ScreenerRedirect() {
  redirect("/discover/screener")
}
