# YieldIQ Mobile (React Native + Expo)

Phase 0 scaffolding for the native YieldIQ mobile app. Consumes the
existing FastAPI backend at `https://api.yieldiq.in/api/v1/*`.

## Local development

```bash
cd mobile
npm install
npm run dev   # alias for `expo start`
```

Then either:
- press `i` for iOS simulator (macOS only)
- press `a` for Android emulator
- scan the QR code with Expo Go on a physical device

## Build (when ready, Phase 2)

```bash
npm install -g eas-cli
eas login
eas build --profile preview --platform ios
eas build --profile preview --platform android
```

## Layout

```
mobile/
  app/                       # expo-router file-based routes
    _layout.tsx              # root stack
    index.tsx                # entry redirect (login or app)
    (auth)/login.tsx         # email + password
    (app)/_layout.tsx        # bottom tab nav (home/watchlist/search/account)
    (app)/home.tsx
    (app)/watchlist.tsx
    (app)/search.tsx
    (app)/account.tsx
    (app)/analysis/[ticker].tsx
  src/
    lib/api.ts               # apiFetch + typed endpoints
    store/authStore.ts       # zustand + expo-secure-store persistence
    theme/tokens.ts          # mirrors frontend/src/app/globals.css palette
    components/HexAxes.tsx   # SVG radar (subset of frontend/src/components/hex/)
  __tests__/login.test.tsx   # smoke render test
```

See `docs/mobile_app_design.md` (repo root) for architecture and roadmap.
