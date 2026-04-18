import { redirect } from "next/navigation"

// Watchlist lives inside the Portfolio page as a tab; /watchlist is kept
// around so old bookmarks and shared URLs still resolve.
export default function WatchlistRedirect() {
  redirect("/portfolio?tab=watchlist")
}
