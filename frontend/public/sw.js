// YieldIQ service worker — installable-PWA build (v2).
//
// Design goals (deliberately minimal):
//   1. Navigation requests: network-first, fall back to /offline on failure.
//      This is what makes the PWA feel like a real app when the network
//      goes away mid-session. No stale HTML served to logged-in users.
//   2. Static app shell (/_next/static/*, /favicon*, /icon-*, /logo*):
//      cache-first. Content-hashed under /_next/static, so cache-first is
//      safe forever — old hashes simply never get requested again.
//   3. API calls (api.yieldiq.in/*, /api/*): PASS-THROUGH. We do not cache
//      backend responses at the SW layer. Prices, valuations, and user
//      data must come from origin. React Query handles in-memory caching
//      at the app layer.
//   4. Activate: nuke any cache not named CACHE_NAME so bumping the version
//      invalidates the previous SW's caches atomically.
//
// Bumping: change CACHE_NAME's suffix (v2 -> v3) to force every client to
// drop its caches on next activation. This is the escape hatch if a stale
// asset gets baked in.

const CACHE_NAME = 'yieldiq-v2'

// URL that the SW falls back to when a navigation request fails. Must be
// a real app route rendered by /app/offline/page.tsx so that the document
// shell is self-contained (no external fetches).
const OFFLINE_URL = '/offline'

// Static asset path prefixes we runtime-cache on first request.
// /_next/static/* is content-hashed by Next.js so the URL itself changes
// with every deploy — cache-first is safe.
const STATIC_PREFIXES = [
  '/_next/static/',
  '/favicon',
  '/icon-',
  '/logo',
  '/apple-touch-icon',
]

self.addEventListener('install', (event) => {
  event.waitUntil(
    (async () => {
      // Pre-cache the offline shell so it's guaranteed available even on
      // the very first network failure after install.
      const cache = await caches.open(CACHE_NAME)
      try {
        await cache.add(new Request(OFFLINE_URL, { cache: 'reload' }))
      } catch {
        // If pre-cache fails (e.g. route not yet deployed), proceed anyway;
        // runtime nav handler will attempt to cache it on first successful
        // fetch.
      }
    })(),
  )
  // Activate new SW immediately on first install.
  self.skipWaiting()
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    (async () => {
      // Drop any cache whose name doesn't match the current version.
      const keys = await caches.keys()
      await Promise.all(
        keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)),
      )
      await self.clients.claim()
    })(),
  )
})

function isStaticAsset(url) {
  return STATIC_PREFIXES.some((p) => url.pathname.startsWith(p))
}

function isApiRequest(url) {
  // Same-origin /api/* OR any request to the api.yieldiq.in host.
  if (url.hostname === 'api.yieldiq.in') return true
  if (url.pathname.startsWith('/api/')) return true
  return false
}

self.addEventListener('fetch', (event) => {
  const { request } = event

  // Only handle GET. Mutations must always hit the network.
  if (request.method !== 'GET') return

  let url
  try {
    url = new URL(request.url)
  } catch {
    return
  }

  // API requests: pass-through. We never cache backend responses —
  // stale prices on a shared device are worse than a network round-trip.
  if (isApiRequest(url)) return

  // Navigation requests (HTML documents): network-first, fall back to
  // the pre-cached /offline shell. `request.mode === 'navigate'` is the
  // canonical signal for a top-level document fetch.
  if (request.mode === 'navigate') {
    event.respondWith(
      (async () => {
        try {
          const fresh = await fetch(request)
          return fresh
        } catch {
          const cache = await caches.open(CACHE_NAME)
          const cached = await cache.match(OFFLINE_URL)
          if (cached) return cached
          // Absolute last-resort inline shell if /offline isn't cached
          // for some reason. Keep it tiny and self-contained.
          return new Response(
            '<!doctype html><meta charset=utf-8><title>Offline</title>' +
              '<body style="font:16px system-ui;padding:2rem;text-align:center">' +
              "<h1>You're offline</h1>" +
              '<p>YieldIQ needs an internet connection for live prices.</p>' +
              '</body>',
            { headers: { 'Content-Type': 'text/html; charset=utf-8' } },
          )
        }
      })(),
    )
    return
  }

  // Static app shell: cache-first. Content-hashed under /_next/static.
  if (isStaticAsset(url)) {
    event.respondWith(
      (async () => {
        const cache = await caches.open(CACHE_NAME)
        const cached = await cache.match(request)
        if (cached) return cached
        try {
          const fresh = await fetch(request)
          // Only cache successful, non-opaque responses.
          if (
            fresh &&
            fresh.ok &&
            (fresh.type === 'basic' || fresh.type === 'default')
          ) {
            cache.put(request, fresh.clone()).catch(() => {
              // Quota errors non-fatal.
            })
          }
          return fresh
        } catch (err) {
          // No cached copy and network is down — let the browser
          // render its native error for this sub-resource.
          throw err
        }
      })(),
    )
    return
  }

  // Everything else: let the browser handle it (no SW intervention).
})
