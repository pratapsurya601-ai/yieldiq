# YieldIQ Mobile — Design & Roadmap

Phase 0 scaffolding lives at `mobile/`. The app is React Native via
Expo's managed workflow with file-based routing (`expo-router`).

## Why React Native + Expo

- The web product (`frontend/`) is Next.js + React + Zustand. Sharing
  React mental model and Zustand state across web + native cuts
  duplication.
- Expo handles iOS + Android signing, OTA updates (`expo-updates`), and
  build (`eas build`) without the user having to set up Xcode-only or
  Android-Studio-only toolchains.
- The FastAPI backend already serves `https://api.yieldiq.in/api/v1/*`
  to the webapp; the mobile client is purely a new consumer with no
  backend changes required.

## Architecture

```
                  +-------------------+
                  |  Expo (React N.)  |
                  |  expo-router      |
                  +---------+---------+
                            |
                  +---------v---------+        +-------------------+
                  |  src/lib/api.ts   |  HTTPS |  FastAPI          |
                  |  apiFetch()       +-------->  api.yieldiq.in   |
                  |  Bearer token     |        |  /api/v1/*        |
                  +---------+---------+        +-------------------+
                            |
                  +---------v---------+
                  |  expo-secure-store|  (Keychain / Keystore)
                  |  yieldiq_token    |
                  +-------------------+
                            ^
                            |
                  +---------+---------+
                  | src/store/        |
                  | authStore.ts      |  (zustand + persist)
                  +-------------------+
```

### Screens

| Route                              | Purpose                                | Endpoints |
|------------------------------------|----------------------------------------|-----------|
| `/`                                | redirect (login or home)               | —         |
| `/(auth)/login`                    | email + password                       | `POST /api/v1/auth/login` |
| `/(app)/home`                      | greeting + quota + previews            | (read auth store) |
| `/(app)/watchlist`                 | FlatList of saved tickers              | `GET /api/v1/watchlist` |
| `/(app)/search`                    | ticker / company name search           | `GET /api/v1/public/all-tickers` |
| `/(app)/account`                   | plan + sign-out                        | (logout: clear secure store) |
| `/(app)/analysis/[ticker]`         | hero card: FV/MoS/Score/Grade + Hex    | `GET /api/v1/analyze/:ticker` |

### State

- **Auth store** (`src/store/authStore.ts`): zustand persist with
  `expo-secure-store` adapter. Token is mirrored into SecureStore by
  `src/lib/api.ts` so non-React callers can read it without a hook.
- **No global market / analysis cache** in Phase 0. Each screen does
  its own fetch on mount. Phase 2 adds React Query.

### Theme

`src/theme/tokens.ts` mirrors the CSS variables in
`frontend/src/app/globals.css` (`--color-bg`, `--color-brand`, etc.).
Light + dark via `useColorScheme()`. When the web tokens change, sync
this file in the same PR — there's no automated drift detector yet
(Phase 2: a generator script).

## Local dev runbook

```bash
cd mobile
npm install
npm run dev          # = expo start
# press i / a / w, or scan QR with Expo Go
```

Backend selection is via `app.json` -> `extra.apiBaseUrl`. To point at
a local FastAPI:

```bash
# Edit mobile/app.json: "apiBaseUrl": "http://10.0.2.2:8000"  (Android emu)
# or "http://localhost:8000" for iOS simulator
```

## Build runbook (Phase 2)

```bash
npm install -g eas-cli
eas login
# preview build for TestFlight / Play internal track
eas build --profile preview --platform all
eas submit --platform ios
eas submit --platform android
```

## CORS

Backend `allow_origins` (see `backend/main.py`) currently includes the
production webapp origins. React Native fetch from a native binary is
**not** subject to CORS (only browsers enforce it), so no backend change
is needed for native iOS/Android. The Expo web target *is* CORS-bound;
Phase 2 should either add `https://*.expo.dev` for live preview tunnels
or accept that web target only works against local dev.

## Phase 0 (this PR) — done

- [x] App skeleton + tab nav
- [x] Login -> token in SecureStore -> auth store
- [x] Watchlist (FlatList) reading `/api/v1/watchlist`
- [x] Analysis hero card with FV/MoS/Score/Grade + Hex SVG
- [x] Search + Account
- [x] One render smoke test
- [x] CI workflow: typecheck, lint, test, expo prebuild dry-run

## Phase 1 (next)

- Pull-to-refresh on Watchlist + Home
- Add to / remove from watchlist
- Compare (2-3 tickers)
- React Query for caching + retry
- Inter font via `expo-font` to match web typography
- App icons + splash (replace placeholders)
- EAS preview build to TestFlight / Play internal

## Phase 2 (later)

- Push notifications (`expo-notifications`) for alert hits
- Biometric auth on the token (FaceID / Touch ID via
  `expo-local-authentication`)
- Reverse-DCF / sensitivity sliders
- Promoter pledge / governance signals card
- Multilingual (i18n)
- Deep linking (`yieldiq://analysis/RELIANCE`) → already half-wired via
  `expo-router` + `scheme: yieldiq` in `app.json`
- Detox E2E (login → watchlist → analysis)
- Accessibility audit

## Known gaps

- Placeholder app icons (`mobile/assets/`) — drop real PNGs before
  submitting to stores.
- No offline mode.
- No retry / network-error toast — errors render inline only.
- Token refresh: backend issues a long-lived JWT; if it expires the user
  is silently 401'd. Phase 1 should add a refresh endpoint or
  re-prompt-on-401.
- `/api/v1/analyze/:ticker` and `/api/v1/watchlist` response shapes are
  best-guess; if the actual schema differs, update `src/lib/api.ts`
  types in the first follow-up PR.
