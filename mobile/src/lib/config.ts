/**
 * Runtime configuration for the staff app.
 *
 * The API host is resolved from `EXPO_PUBLIC_API_URL` when set (Expo
 * inlines `EXPO_PUBLIC_*` vars at build time). Otherwise it defaults by
 * build type: a dev build talks to the local Django server, a release
 * build talks to production. EAS release builds set the var explicitly
 * (see Phase 9), so the production default is only a backstop.
 *
 * For local dev on a simulator, `http://localhost:8000` works as-is.
 * On a physical device, set `EXPO_PUBLIC_API_URL` in `mobile/.env` to
 * your machine's LAN address (the device can't reach `localhost`).
 */

const DEFAULT_API_URL = __DEV__
  ? 'http://localhost:8000'
  : 'https://api.xn--lumcrm-5ua.com';

/** Base URL for the Lumè API, never with a trailing slash. */
export const API_BASE_URL = (
  process.env.EXPO_PUBLIC_API_URL ?? DEFAULT_API_URL
).replace(/\/+$/, '');
