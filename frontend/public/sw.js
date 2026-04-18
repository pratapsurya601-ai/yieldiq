// YieldIQ service worker — stale-while-revalidate for read-mostly PUBLIC API routes.
//
// Contract: this SW only caches GET requests to PUBLIC endpoints (no Authorization
// header). Authed routes are passed straight through to the network — this avoids
// cross-user cache leakage on shared devices.
//
// Skip SW-caching for:
//   - Non-GET methods (mutations)
//   - Any request carrying an Authorization header (user-specific)
//   - /api/v1/admin/*, /api/v1/auth/*, /api/v1/watchlist, /api/v1/portfolio
//
// Cache version: bump the suffix (v1 -> v2) to force-invalidate all cached entries.
const CACHE_NAME = 'yieldiq-api-v1'

// Cacheable path patterns. Applied to (pathname + search). These are all public,
// read-mostly endpoints that don't require auth and benefit from repeat-visit warmth.
const CACHEABLE_PATTERNS = [
  /\/api\/v1\/analysis\/[^/?#]+(?:\?.*)?$/, // GET analysis root only (not /history, etc.)
  /\/api\/v1\/prism\//,
  /\/api\/v1\/public\//,
  /\/api\/v1\/hex\//,
  /\/api\/v1\/yieldiq50/,
]

// Path prefixes we always skip even if they match — belt-and-suspenders.
const NEVER_CACHE_PREFIXES = [
  '/api/v1/admin/',
  '/api/v1/auth/',
  '/api/v1/watchlist',
  '/api/v1/portfolio',
]

self.addEventListener('install', () => {
  // Activate immediately on first install so the page benefits on next load.
  self.skipWaiting()
})

self.addEventListener('activate', (event) => {
  // Nuke caches whose name doesn't match the current version.
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)),
      ),
    ),
  )
  self.clients.claim()
})

self.addEventListener('fetch', (event) => {
  const { request } = event

  // Fast bail-outs — never interfere with:
  //   - non-GET (mutations)
  //   - authed requests (bearer token present)
  //   - anything on a different origin (let browser handle)
  if (request.method !== 'GET') return
  if (request.headers.get('authorization')) return

  let url
  try {
    url = new URL(request.url)
  } catch {
    return
  }

  // Only handle same-origin-style API calls — allow any origin, but the
  // pathname has to look like our API surface.
  const pathAndSearch = url.pathname + url.search

  if (NEVER_CACHE_PREFIXES.some((p) => url.pathname.startsWith(p))) return
  if (!CACHEABLE_PATTERNS.some((p) => p.test(pathAndSearch))) return

  event.respondWith(
    caches.open(CACHE_NAME).then(async (cache) => {
      const cached = await cache.match(request)

      const networkPromise = fetch(request)
        .then((res) => {
          // Only cache successful responses — never 4xx/5xx/opaqueredirect.
          // Also require a basic/cors response we can actually replay.
          if (
            res &&
            res.ok &&
            (res.type === 'basic' || res.type === 'cors' || res.type === 'default')
          ) {
            // Clone before cache.put; original Response stream is single-use.
            cache.put(request, res.clone()).catch(() => {
              // Quota / opaque errors are non-fatal.
            })
          }
          return res
        })
        .catch(() => cached || Response.error())

      // SWR: serve cached instantly if we have it; let the network refresh in
      // the background. If no cache, we have to wait on the network.
      return cached || networkPromise
    }),
  )
})
