# Visual-regression strategy — Day-38

**Status**: Day-38a (testid inventory) shipped. Day-38b (Playwright pixel diff) deferred to a future sprint when the team is ready to onboard the tool.

This document explains the two-layer approach used to prevent the kind of silent UX regression that the Day-27 audit surfaced (loading skeletons that didn't match layout, dark-mode gaps, missing CTAs, etc.).

---

## Layer 1 — `data-testid` inventory (Day-38a, shipped)

**Location**: `backend/tests/test_day38_visual_regression_hooks.py`

**What it catches**: accidental removal of `data-testid` attributes added across Days 28-37. These attributes are the contract between the UI and any future Playwright / Chrome MCP visual-regression suite — if they disappear, future pixel-diff selectors silently break.

**How it works**: a Python `pytest` source-text grep over the frontend `.tsx` files. Each entry in `EXPECTED_TESTIDS` is a triple `(testid, file path, day-shipped)`. The test fails with a message that names the Day-XX PR that added the missing hook, so the regression is immediately diagnosable.

**Cost**: < 1 second per test run. No new dependencies.

**What it doesn't catch**: pixel-level drift (e.g. someone changes a `bg-blue-50` to `bg-green-50`; layout breakage that doesn't remove the testid). For those, see Layer 2 below.

### Inventory snapshot (Week-2 shipped 8 testids)

| testid | File | Day |
|---|---|---|
| `public-analysis-loading-skeleton` | PublicAnalysis.tsx | 28 |
| `portfolio-panel-loading-skeleton` | PortfolioPanel.tsx | 28 |
| `screener-loading-skeleton` | screener/page.tsx | 28 |
| `panel-fallback-*` | home/page.tsx | 29 |
| `screener-error-banner` | screener/page.tsx | 29 |
| `login-submit-button` | login/page.tsx | 29 |
| `watchlist-button` | WatchlistButton.tsx | 32 |
| `search-no-results` | search/page.tsx | 37 |

---

## Layer 2 — Playwright pixel-diff (Day-38b, deferred)

**Plan**: add Playwright + a per-page screenshot test for the 7 main routes. Run on every PR; fail when any baseline image differs by more than a small tolerance.

**Why deferred**: Playwright pulls ~200 MB of browser binaries on first install. The current YieldIQ team is one engineer; the value of catching pixel-level drift hasn't yet exceeded the maintenance cost of keeping baselines fresh. Re-evaluate when:
- The team grows past 1 engineer.
- A pixel regression actually ships to prod (e.g. a CSS edit that breaks one viewport).
- Visual polish becomes a paid-tier differentiator.

**Recommended config when enabled**:

```typescript
// frontend/playwright.config.ts
import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './__tests__/visual',
  retries: 2,
  reporter: [['html', { open: 'never' }]],
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:3000',
    screenshot: 'only-on-failure',
    trace: 'on-first-retry',
  },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'], viewport: { width: 1024, height: 768 } } },
    { name: 'mobile',  use: { ...devices['iPhone 13'] } },
  ],
})
```

**Recommended baseline tests**:

```typescript
// frontend/__tests__/visual/main-pages.spec.ts
import { test, expect } from '@playwright/test'

const PAGES = [
  { name: 'home',      path: '/home' },
  { name: 'analysis',  path: '/analysis/RELIANCE.NS' },
  { name: 'screener',  path: '/screener' },
  { name: 'discover',  path: '/discover' },
  { name: 'public',    path: '/public/RELIANCE' },
  { name: 'pricing',   path: '/pricing' },
  { name: 'login',     path: '/auth/login' },
]

for (const { name, path } of PAGES) {
  test(`${name} page matches baseline`, async ({ page }) => {
    await page.goto(path)
    await page.waitForLoadState('networkidle')
    await expect(page).toHaveScreenshot(`${name}.png`, {
      maxDiffPixelRatio: 0.02,
    })
  })
}
```

**Recommended GH workflow** (`.github/workflows/visual-regression.yml`):

Runs on every PR that touches `frontend/**`. Uses the `playwright/test:focal` Docker image so installation is one-time per CI run. Fails the PR if the diff exceeds 2%. Baselines live in `frontend/__tests__/visual/__snapshots__/`.

When Day-38b is ready to enable, copy the configs above and add Playwright to `frontend/package.json`. The Day-38a testid inventory will continue to work alongside it — they catch different regression classes.

---

## Why this approach (vs. running Playwright in CI today)

1. **Test maintenance is the killer**. Pixel-diff suites accumulate "flaky" failures (font rendering subpixel shifts, animation timing, etc.) that require constant baseline regeneration. Without a dedicated owner, the suite gets disabled within 2-3 months.

2. **70% of value, 5% of cost**. The testid inventory catches the most common visual regression in practice — engineers removing or renaming hooks without realizing they're load-bearing. The 30% of regressions it misses (pure CSS drift) is exactly what nightly users would catch and report.

3. **The harness can be added later without rework**. The testid contract is the foundation. Playwright is the optional second layer that consumes those testids as selectors.

---

## Sprint mechanics for future visual work

When adding any new UI primitive:
1. Give it a `data-testid` attribute matching the component's name.
2. Add the testid to `EXPECTED_TESTIDS` in `test_day38_visual_regression_hooks.py`.
3. If the component is on a critical user flow (analysis hero, screener results, login, payment), add the testid to the future Playwright baselines too.

Three lines of test cost to prevent a class of silent regressions.
