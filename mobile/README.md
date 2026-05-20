# Lumè CRM — staff mobile app

The native staff app for Lumè CRM, built with Expo (managed workflow)
and React Native. It is the phone-first companion to the web CRM —
operators run their day from it: calendar, clients, check-in, charting.

One binary serves every tenant. Sign-in is slug-first: the operator
enters their workspace slug, then signs in with email + password
scoped to it (see [ADR 0031](../docs/decisions/0031-staff-mobile-app.md)).

## Stack

- **Expo SDK 54** / React Native 0.81 / React 19, TypeScript
- **Expo Router** — file-based routing under `src/app/`
- **JWT auth** against the `/api/auth/mobile/` backend surface
- **expo-secure-store** — tokens at rest in the Keychain / Keystore

## Project layout

```
src/
  app/                  file-based routes
    _layout.tsx         root — AuthProvider + auth-guarded navigator
    login.tsx           email + password sign-in
    select-workspace.tsx workspace picker (multi-spa staff)
    (app)/              authenticated route group
  components/ui/        shared primitives (Button, TextField)
  constants/theme.ts    design tokens (mirrors the web palette)
  lib/
    config.ts           API host resolution
    api.ts              HTTP primitive + unauthenticated auth calls
    auth.tsx            AuthProvider — session, tokens, authedFetch
    secure-store.ts     encrypted token persistence
    types.ts            shared API types
```

## Running it

```bash
npm install
npx expo start
```

Then press `i` (iOS simulator) or `a` (Android emulator), or scan the
QR code with Expo Go.

### Pointing at a backend

The API host is read from `EXPO_PUBLIC_API_URL`. Defaults: a dev build
uses `http://localhost:8000`, a release build uses the production API.

- **iOS simulator** → `localhost:8000` works with no setup.
- **Physical device** → create `mobile/.env` with your machine's LAN
  address so the device can reach the dev server:

  ```
  EXPO_PUBLIC_API_URL=http://192.168.1.x:8000
  ```

EAS release builds set `EXPO_PUBLIC_API_URL` explicitly.

## Checks

```bash
npx tsc --noEmit          # type check
npx expo-doctor           # project health
npx expo export -p ios    # verify the bundle compiles
```

## Conventions

This app is **locked to light mode** — the web CRM ships no dark mode,
so a dark variant would only create brand drift. PHI is **never**
written to device storage; only auth tokens and the active-workspace
slug are persisted, and those go to the encrypted Keychain / Keystore.
