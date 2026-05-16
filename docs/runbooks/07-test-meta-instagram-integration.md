# 07 — Testing the Meta Instagram integration

Three paths, in order of complexity. Use the one that matches what
you're trying to verify.

| Path | Verifies | Prerequisites |
|---|---|---|
| **1. Mock data** | The `/social` UI renders | None |
| **2. Diagnostics endpoint** | Env vars + URLs are configured | Backend running |
| **3. Real OAuth + webhook** | The actual integration works | Meta App + ngrok (or prod) |

---

## Path 1 — Mock data (sanity check the UI in ~30 seconds)

Seed fake threads + customers into your dev DB so the inbox page has
something to render. No Meta calls, no OAuth, no webhooks.

```bash
cd backend
.venv/bin/python manage.py seed_test_social_thread --count=5
```

Output:

```
Tenant: acmespa (Acme Med Spa)
Created 5 test thread(s) for acmespa.

Open /social to see them. Examples:
  · @emma.glows → Emma Garcia
  · @marcus.aesthetics → Marcus Lee
  · @jenny.pdx → Jenny Chen
  ...

To remove these seeded rows later:
  python manage.py seed_test_social_thread --tenant=acmespa --purge
```

Open `/social` in the dashboard — you should see the threads listed.
Click one to view the conversation. The reply box is intentionally a
placeholder until outbound send ships (Session 2B).

**Cleanup when done:**

```bash
.venv/bin/python manage.py seed_test_social_thread --tenant=acmespa --purge
```

---

## Path 2 — Diagnostics (verify the backend is configured)

Hit the diagnostics endpoint to confirm every env var is loaded into
the *running process* (not just sitting in `.env`):

```bash
curl -s http://localhost:8000/api/integrations/diagnostics/ \
  -b cookies.txt \
  -H 'X-Tenant-Slug: <your-tenant-slug>' | jq
```

(You need a valid session cookie. Easiest: log into the dashboard,
copy the `sessionid` cookie out of dev tools, save to `cookies.txt`.)

The response tells you:

- **`env_vars_configured`** — which secrets are set (booleans only;
  the actual values are never returned)
- **`all_credentials_present`** — single boolean: is the integration
  even theoretically connectable?
- **`urls_meta_should_hit`** — the exact OAuth callback, webhook,
  and data-deletion URLs the running process is expecting Meta to
  call. **If these don't match what's configured in the Meta App
  dashboard, OAuth and webhooks will silently fail.**
- **`connections`** — per-tenant connection state, with a `has_token`
  boolean (true if we have an OAuth token on file, never the token
  itself)

Common red flags:

| Symptom | Likely cause |
|---|---|
| `all_credentials_present: false` | Missing env vars — set them in `.env` (dev) or Secrets Manager (prod) and restart the process |
| `oauth_redirect_uri: "(unset — using default)"` | `META_OAUTH_REDIRECT_URI` not set; falls back to localhost which Meta will reject |
| `webhook_callback` is `localhost` but you're testing real Meta | You need ngrok (Path 3) — Meta can't reach localhost |
| `connections[].last_error_message` populated | OAuth or webhook delivery failed; the message tells you why |

---

## Path 3 — Real OAuth + webhook (end-to-end)

You have two sub-options here. Pick based on your goal:

### 3a. Local + ngrok tunnel (development iteration)

Best for iterating on the OAuth flow or webhook handler. Meta hits
your laptop via a public tunnel.

1. **Install ngrok** if you haven't: `brew install ngrok && ngrok config add-authtoken <token>`
2. **Start the backend** in one terminal: `cd backend && .venv/bin/python manage.py runserver 8000`
3. **Start the tunnel** in another: `ngrok http 8000`
   - You'll get a forwarding URL like `https://1a2b-203-0-113-4.ngrok-free.app`
4. **Update your local `.env`**:
   ```
   META_OAUTH_REDIRECT_URI=https://1a2b-203-0-113-4.ngrok-free.app/api/integrations/meta/oauth/callback/
   PUBLIC_BASE_URL=https://1a2b-203-0-113-4.ngrok-free.app
   ```
   Restart the backend so it picks them up.
5. **Update the Meta App dashboard** (developers.facebook.com):
   - **App Settings → Basic → App Domains**: add the ngrok host (`1a2b-203-0-113-4.ngrok-free.app`)
   - **Facebook Login → Valid OAuth Redirect URIs**: add `https://1a2b-203-0-113-4.ngrok-free.app/api/integrations/meta/oauth/callback/`
   - **Webhooks → Instagram callback URL**: `https://1a2b-203-0-113-4.ngrok-free.app/api/integrations/webhooks/meta/` + your `META_WEBHOOK_VERIFY_TOKEN`
   - **App Settings → Basic → User Data Deletion Callback**: `https://1a2b-203-0-113-4.ngrok-free.app/api/integrations/meta/data-deletion/`
6. **In Meta App dashboard, switch the app to Development Mode** (App Review → App Mode). In Dev Mode, only Meta App admins (you) can authenticate; perfect for testing.
7. **In your CRM**, go to `/org/integrations` → click **Connect Instagram**. You'll be redirected to Facebook, asked to grant access to your Page with the linked IG Business account, then bounced back. On success, the Connection card flips to green "Connected" and the `connections[]` array in `/api/integrations/diagnostics/` shows `has_token: true`.
8. **Test the inbound webhook**: open the IG app on your phone and DM your connected Business account. Within seconds you should see a new thread in `/social`.

**ngrok caveats:**
- The free-tier URL changes every restart. Re-update Meta + `.env` each time.
- ngrok rewrites the request origin — if you see CORS errors, add the ngrok host to `CORS_ALLOWED_ORIGINS` in `dev.py`.
- Keep the tunnel terminal open while testing.

### 3b. Test directly against production

Best when iteration on local OAuth is more painful than redeploying.
Especially good for the data-deletion flow which needs a stable URL.

1. **Add the env vars to AWS Secrets Manager** (see runbook 06):
   - `META_APP_ID`
   - `META_APP_SECRET`
   - `META_WEBHOOK_VERIFY_TOKEN`
   - `INTEGRATIONS_FERNET_KEY`
2. **Restart the ECS service**:
   ```bash
   aws ecs update-service \
     --cluster lume-prod \
     --service lume-backend \
     --force-new-deployment
   ```
   Wait ~3 min.
3. **Verify env loaded**: hit `https://api.xn--lumcrm-5ua.com/api/integrations/diagnostics/` (you need a session). `all_credentials_present` should be `true`.
4. **Verify webhook reachable**:
   ```bash
   curl "https://api.xn--lumcrm-5ua.com/api/integrations/webhooks/meta/?hub.mode=subscribe&hub.verify_token=<YOUR_TOKEN>&hub.challenge=hello"
   ```
   Should echo `hello`.
5. **In the production CRM**, go to `/org/integrations` → Connect Instagram → grant access → return to dashboard, status should flip to Connected.
6. **DM the connected IG account** from your personal IG. Within seconds it should land in production `/social`.

---

## What to test in each path

When you're done with whatever path you picked, run through this:

- [ ] **Inbox renders** — threads sorted newest first, unread badge visible, refresh button works
- [ ] **Filter** — toggle "Showing unread" ↔ "All threads"; counts and visibility change
- [ ] **Thread detail** — clicking a row opens the conversation; messages render in chronological order with correct bubble alignment (inbound left, outbound right when Session 2B ships)
- [ ] **Auto-mark-read** — opening an unread thread clears the unread dot in the list (might need to refresh once)
- [ ] **Deep link** — `/social?thread=<id>` opens that thread directly
- [ ] **PHI safety in audit log** — open the thread, then check `apps.audit.models.AuditLog` for a `resource_type='social_thread'` row. The `metadata` field must NOT contain message body content; only `event`, `message_count`, `customer_id`.
- [ ] **Tenant isolation** — log out, log in as a user on a different tenant, hit `/social`. You should see zero of the first tenant's threads.
- [ ] **Role gate** — log in as a front-desk-only user. The "Social inbox" entry should be HIDDEN from the sidebar (and `/social` should 403 if you visit directly).

If anything fails any of these, the diagnostics endpoint is the
first place to check. After that, look at the application logs
(`logger.info('integrations.meta.…')` entries trace every step of
the OAuth + webhook flow).
