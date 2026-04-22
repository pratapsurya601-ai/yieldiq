# YieldIQ PWA Audit — 2026-04-22

Scope: installable PWA compliance + offline fallback. Branch
`pwa/installable-v2`. Full native mobile is **out of scope**.

All findings are against files on `origin/main` at the time of this audit.

---

## 1. `frontend/public/manifest.json`

Current state is **mostly good** — most W3C-recommended fields are already
present. Gaps below.

| Field                 | Present? | Value                                 | Notes                                                                                               |
| --------------------- | -------- | ------------------------------------- | --------------------------------------------------------------------------------------------------- |
| `name`                | yes      | `YieldIQ — Stock Valuation`           | good                                                                                                |
| `short_name`          | yes      | `YieldIQ`                             | good                                                                                                |
| `description`         | yes      | good DCF copy                         | good                                                                                                |
| `scope`               | yes      | `/`                                   | good                                                                                                |
| `start_url`           | yes      | `/home`                               | **FIX** — should be `/` to match scope and route the SW offline-fallback correctly. `/home` is a marketing redirect that behaves poorly when offline. |
| `display`             | yes      | `standalone`                          | good                                                                                                |
| `orientation`         | yes      | `portrait`                            | good                                                                                                |
| `background_color`    | yes      | `#FFFFFF`                             | **FIX** — should be `#0F172A` to match the Tailwind dark hero so the iOS/Android splash doesn't flash white before first paint. |
| `theme_color`         | yes      | `#2563EB`                             | good, matches Viewport                                                                              |
| `categories`          | yes      | `["finance", "business"]`             | good                                                                                                |
| `id`                  | **no**   | —                                     | **ADD** — W3C recommends a stable `id` (`"yieldiq"`) so install promotion de-dupes correctly when URLs change.              |
| `lang`                | yes      | `en-IN`                               | good                                                                                                |
| `prefer_related_applications` | yes | `false`                          | good                                                                                                |
| `icons[].purpose=any`  | yes     | 192, 512, 180 (apple)                 | good                                                                                                |
| `icons[].purpose=maskable` | yes | re-uses `icon-512.png`                | **CAVEAT** — reuses the non-maskable asset. Acceptable as a stopgap; note as follow-up for a real maskable PNG with proper safe-zone padding (see Out-of-scope). |
| `screenshots`         | **no**   | —                                     | Optional per spec; Chrome uses them for richer install UI on Android. **Out of scope** — needs design assets. |
| `shortcuts`           | yes      | 4 entries                             | good — covers Search, Nifty 50, RELIANCE, Earnings calendar                                         |

**Lighthouse PWA-install check**: currently passes the "installable" gate
(manifest present, `display: standalone`, 192+512 icons, SW registered,
HTTPS). The `start_url` fetches `/home` which is a live route, so the
install prompt itself succeeds — but the lack of a real offline
navigation fallback fails "Current page does not respond with a 200 when
offline" in Lighthouse.

## 2. `frontend/public/sw.js`

Current SW is a **stale-while-revalidate API cache** — it caches
authless GET responses from `/api/v1/analysis/:ticker`, `/api/v1/prism/`,
`/api/v1/public/`, `/api/v1/hex/`, `/api/v1/yieldiq50`.

Findings:

- **Does NOT serve an offline fallback page.** Nav requests that fail
  while offline just error out — user sees the browser's default offline
  screen. This is the single biggest gap.
- **Does NOT cache static assets.** `_next/static/*`, icons, and the
  logo are not pre-cached or runtime-cached, so even a return visitor
  with the SW active sees nothing when offline.
- **Caches API responses.** The task spec says "pass-through, do NOT
  cache" for API calls. The existing SWR cache does improve repeat-visit
  latency but risks showing stale prices on shared devices (the current
  code does already skip authed requests and a list of private routes,
  which is the right shape — but the task brief is unambiguous about
  the new design: navigation-first offline fallback, no API caching).
  Removing the API cache is the conservative choice given the "broken
  SW bricks returning visitors" hard constraint.
- **`CACHE_NAME` is `yieldiq-api-v1`.** Must bump to `yieldiq-v2` so
  existing clients drop the old SWR cache on activate.
- `skipWaiting` + `clients.claim`: present and correct.

## 3. Install prompts

Two components, both registered in the app tree: `InstallPrompt.tsx` and
`PWAInstallBanner.tsx`. There is overlap, but each handles a different
surface and they don't fight each other — `InstallPrompt` is the more
thorough one (handles iOS helper, 30-day dismissal, `display-mode:
standalone` and `navigator.standalone` detection).

Findings:

- `beforeinstallprompt` handling in both files is correct:
  `e.preventDefault()` before showing, `prompt()` + `userChoice` on the
  deferred event.
- **`PWAInstallBanner` gates on `MIN_VIEWS = 3`** and mobile-only, with
  permanent dismissal on click. Not aggressive.
- **`InstallPrompt` gates on** (a) not in standalone, (b) not dismissed
  in last 30 days. For iOS, it shows the helper after 10 seconds of
  engagement. This is fine — **LEAVE ALONE** per task brief.
- No redundant auto-prompting, no nagging. The "once per session,
  >30s" throttle in the task spec is already effectively enforced
  (InstallPrompt listens for the event; browsers themselves throttle
  `beforeinstallprompt`; dismissal sticks for 30 days).

**No changes needed to either install component.**

## 4. iOS splash screens (apple-touch-startup-image)

- **Not present.** Only `apple-touch-icon.png` (180x180) is wired in
  `layout.tsx` via `icons.apple`.
- Generating a full set of iOS splash images requires 20+ exact-pixel
  PNGs (iPhone SE, 13, 14 Pro, 15 Pro Max, iPad mini, iPad Pro 11/12.9,
  etc.) at both orientations and 1x/2x/3x DPRs. This needs a design tool.
- **Out of scope** per the "Do NOT generate new icon images" constraint.
  Follow-up noted below.

## 5. Offline behavior (current, pre-fix)

- If a user loses connection mid-page on a client-interactive route
  (`/analysis/:ticker`, `/prism/:ticker`, `/portfolio`), the current
  page stays mounted. Any `fetch` the page makes to the backend fails —
  the existing React Query/SWR-shaped call sites surface their error
  UI (already handled by page code). Fine.
- If a user navigates to a new route while offline, the browser's
  default "no internet" error page renders. **This is the single
  user-visible gap.**
- After this PR: navigation while offline renders `/offline` — a small
  server-rendered component with the message "You're offline. YieldIQ
  needs an internet connection for live prices. Go back to home when
  you're online."

---

## Follow-ups (not in this PR)

- **Real maskable icon asset.** Replace the `purpose: "maskable"` entry
  (currently re-uses `icon-512.png`) with a proper maskable PNG that
  has the W3C-spec 10% safe-zone padding. Needs design.
- **iOS splash images.** Generate `apple-touch-startup-image` set
  (20+ PNGs) and wire via `<link rel="apple-touch-startup-image">`.
- **`screenshots` field in manifest.** 2-3 PNGs at 540x720 (narrow) and
  1024x593 (wide) unlock richer install UI on Android.
- **Push notifications.** Separate project — needs backend push server
  with VAPID keys, subscription table, worker for delivery. Explicitly
  out of scope here.
- **Could re-add conservative API SWR cache in a later PR** if repeat-
  visit latency becomes a priority — but route-scope it narrowly
  (`/api/v1/yieldiq50` only, say) and add a short TTL so prices can't
  go stale for days.
