# Runbook — Meta App setup for Instagram Business DMs

> Reading time: ~30 min. Total wall-clock to complete (excluding Meta
> App Review wait time): ~1–2 hours.

This runbook walks through everything you need to do on Meta's side
to enable Instagram Business DM ingestion in Lumè. The code is already
shipped (ADR 0027); this is the external configuration that flips the
flow on.

**You'll know it's working when:** A tenant in `/org/integrations`
clicks "Connect" on Instagram, Meta's consent screen appears, they
pick their Facebook Page, and after consent they land back on
`/org/integrations?connected=instagram`. From that point any DM sent
to the connected Instagram Business account auto-creates a customer
record in Lumè marked `acquisition_source=instagram`.

---

## Step 0 — Pre-requisites

You must have:

- [ ] A **Facebook Page** for the spa (every IG Business account is
      linked to one — Meta requires it).
- [ ] An **Instagram Business or Creator account** linked to that Page.
      (In Instagram app → Settings → Account → Switch to Professional
      Account → Business → "Yes, connect a Facebook Page".)
- [ ] **Admin access to that Facebook Page** under the Facebook account
      you'll use as the Meta App admin.
- [ ] A **Facebook Business account** (free; create at
      [business.facebook.com](https://business.facebook.com/)).
- [ ] The production backend deployed at `https://api.xn--lumcrm-5ua.com`
      (already true as of 2026-05-16).
- [ ] **Privacy Policy** and **Terms of Service** pages live at public
      HTTPS URLs (Meta requires both for App Review).

---

## Step 1 — Create the Meta App

1. Go to [developers.facebook.com/apps](https://developers.facebook.com/apps).
2. Click **Create app** → pick **Business** as the use case → **Next**.
3. App details:
   - **App name:** `Lumè CRM` (or whatever you want it called in the
     consent screen).
   - **App contact email:** the email you check.
   - **Business account:** pick your Facebook Business account from
     Step 0.
4. Click **Create app**. You'll land in the App Dashboard.

Note the **App ID** at the top of the dashboard. You'll use it as
`META_APP_ID` later.

---

## Step 2 — Add products to the App

In the left sidebar of the App Dashboard click **Add product**.

Add (in this exact order):

1. **Facebook Login for Business**
   - In its settings → **Client OAuth Settings**:
     - **Valid OAuth Redirect URIs:** add
       `https://api.xn--lumcrm-5ua.com/api/integrations/meta/oauth/callback/`
     - **Login with the JavaScript SDK:** No (we use server-side flow)
     - Click **Save changes**.
2. **Instagram** → pick **Instagram Business**
   - This is the product that exposes `instagram_basic` and
     `instagram_manage_messages` scopes.
3. **Messenger** (yes, even though we only want IG)
   - IG Business DMs ride on Messenger's webhook plumbing. You don't
     have to configure anything here; just enabling it is enough.
4. **Webhooks**
   - More on this in Step 4.

---

## Step 3 — App Settings → Basic

Left sidebar → **App settings → Basic**.

### App Domains

This field is the most common stumbling block. Meta requires every
domain your app communicates with to be listed here. The form accepts
**root domains only** — adding `xn--lumcrm-5ua.com` automatically
covers every subdomain (`api.`, `app.`, `www.`, etc.) so you don't
need to list them individually.

Add (one per line in the field):

```
xn--lumcrm-5ua.com
```

That's the **punycode** (IDN ASCII-compatible) form of our actual
brand domain `lumècrm.com`. They're functionally identical — DNS
resolves both to the same servers — but Meta's dashboard expects the
punycode form because it's the canonical ASCII representation. If
you type `lumècrm.com` literally, Meta will either silently convert
it or reject it depending on the day.

To remember: **punycode form = `xn--lumcrm-5ua.com` (this is the
one Meta wants).**

### Other Settings → Basic fields

- **Privacy Policy URL:** `https://xn--lumcrm-5ua.com/legal/privacy`
  (must be a real, live page — Meta clicks it during App Review)
- **Terms of Service URL:** `https://xn--lumcrm-5ua.com/legal/terms`
- **User Data Deletion Callback URL:** `https://api.xn--lumcrm-5ua.com/api/integrations/meta/data-deletion/`
  (we built this endpoint — when a Meta user removes the app, Meta
  POSTs here, we revoke their tokens automatically and return a
  confirmation URL the user can visit to verify deletion)
- **Category:** Productivity → Business Tools
- **App icon:** upload the Lumè logo (square, ≥1024×1024)
- **Business use case:** add a short description
  ("Receive Instagram Business DMs in the Lumè CRM so spa staff can
  respond to client inquiries in one inbox.")

Note the **App Secret** (click "Show"). You'll use it as
`META_APP_SECRET` later. Treat it like a password.

Click **Save changes**.

---

## Step 4 — Configure the Webhook

In the App Dashboard left sidebar → **Webhooks**.

1. Pick **Instagram** from the dropdown (NOT Page — IG webhooks ride
   on Instagram's own subscription, even though they use the Messenger
   payload shape).
2. Click **Subscribe to this object**.
3. **Callback URL:** `https://api.xn--lumcrm-5ua.com/api/integrations/webhooks/meta/`
4. **Verify Token:** pick a random string and write it down. Meta will
   POST this back to you during the handshake to prove the
   subscription was set up through you. You'll use it as
   `META_WEBHOOK_VERIFY_TOKEN` later.

   Easy generator:
   ```
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```

5. Click **Verify and save**. Meta will:
   - GET `https://api.xn--lumcrm-5ua.com/api/integrations/webhooks/meta/?hub.mode=subscribe&hub.verify_token=<yours>&hub.challenge=<random>`
   - Our endpoint will echo the challenge back as plain-text 200 if
     `META_WEBHOOK_VERIFY_TOKEN` matches.
   - **If this step fails:** check that the env var is set on the
     production backend (Step 6) and that the verify token matches
     exactly. Both leading and trailing whitespace count.

6. After successful verification, in the **Subscription fields**
   section, click **Subscribe** on:
   - `messages` (inbound DM bodies)
   - `messaging_postbacks` (button-tap events for future Quick Replies)
   - `message_reads` (delivery-receipt read state)

You should now see all three fields checked under the Instagram
subscription.

---

## Step 5 — Generate a Fernet key for token encryption

OAuth tokens are stored encrypted (ADR 0027 §1). Generate a fresh
Fernet key:

```
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Copy the output. You'll use it as `INTEGRATIONS_FERNET_KEY` next.

**Important:** Once tokens are stored encrypted under this key, you
cannot decrypt them with a different one. Treat it like a database
backup encryption key — write it down somewhere safe in addition to
Secrets Manager. Rotation works via `INTEGRATIONS_FERNET_KEYS` (list)
when the time comes.

---

## Step 6 — Set the four env vars in production

In AWS Secrets Manager, edit (or create) the secret used by the
backend ECS task. Add these four entries:

| Key | Value |
|---|---|
| `META_APP_ID` | from Step 1 (the App Dashboard top bar) |
| `META_APP_SECRET` | from Step 3 (App Settings → Basic, click Show) |
| `META_WEBHOOK_VERIFY_TOKEN` | from Step 4 (the random string you generated) |
| `INTEGRATIONS_FERNET_KEY` | from Step 5 (the Fernet key) |

Optional (already defaulted in `base.py` but you can override):

| Key | Value |
|---|---|
| `META_OAUTH_REDIRECT_URI` | `https://api.xn--lumcrm-5ua.com/api/integrations/meta/oauth/callback/` |

After saving, **restart the ECS service** so the new env values are
picked up by all running tasks:

```
aws ecs update-service \
  --cluster lume-prod \
  --service lume-backend \
  --force-new-deployment
```

Wait ~3 min for the rolling deploy to finish, then verify by hitting:

```
curl https://api.xn--lumcrm-5ua.com/api/integrations/webhooks/meta/?hub.mode=subscribe\&hub.verify_token=<yours>\&hub.challenge=test123
```

You should get back `test123` as plain text. If you get 403, the env
var didn't take — check the ECS service logs.

---

## Step 7 — Submit for Business Verification

Meta requires Business Verification before granting access to the
`instagram_manage_messages` scope.

1. App Dashboard → left sidebar → **App Review** → **Business
   Verification**.
2. Click **Start Verification**.
3. Fill in the business details — legal name, address, tax ID
   (EIN for US LLCs), DUNS number (free at
   [dnb.com](https://www.dnb.com/duns-number.html), takes ~30 days the
   first time).
4. Upload documents Meta asks for — typically Articles of
   Incorporation or a recent tax return showing the business name.
5. Submit.

Wait time: 2–10 business days for first-time verification. Renewals
are faster.

---

## Step 8 — Submit for App Review

Once Business Verification is approved, request the scopes.

1. App Dashboard → **App Review** → **Permissions and Features**.
2. Search for each of these and click **Request** next to it:
   - `instagram_basic`
   - `instagram_manage_messages`
   - `pages_show_list`
   - `pages_manage_metadata`
3. For each scope, Meta will ask:
   - **How will your app use this permission?**
     Example: "Lumè is a CRM for medical spas. We use this permission
     to receive direct messages sent to the spa's Instagram Business
     account so the spa's staff can respond to customer inquiries in
     a unified inbox alongside their other communication channels."
   - **Test instructions (screencast or video URL):** Record a 2-3
     minute screencast showing:
     - Tenant logs into Lumè
     - Navigates to `/org/integrations`
     - Clicks Connect on Instagram
     - Goes through the Meta consent screen
     - Lands on `/org/integrations?connected=instagram`
     - Sends a test DM to the connected IG account
     - Shows the DM appearing in the Lumè inbox / customer record
   - **Platform:** Web

4. Submit.

Wait time: 1–4 weeks per scope. Meta usually reviews them as a batch.

If they reject anything, the rejection email explains what to change
and you can resubmit immediately.

---

## Step 9 — Switch the App to Live mode

After all scopes are approved:

1. App Dashboard → top of page → **App Mode** toggle → flip to **Live**.

That's it. The integration is now usable by any tenant, not just App
Admins/Testers.

---

## Step 10 — Test end-to-end

1. As a tenant owner in production, navigate to `/org/integrations`.
2. Click **Connect** on Instagram.
3. Meta consent screen appears → pick your linked FB Page → grant the
   requested permissions.
4. You should land on `/org/integrations?connected=instagram` with a
   toast confirming success.
5. From a separate Instagram account (or the IG app on your phone),
   send a DM to the connected Business account.
6. Within ~5 seconds, the message should appear:
   - In the Lumè database (`SocialMessage` table)
   - As a new social-guest customer (`Customer.is_social_guest=True`,
     `acquisition_source=instagram`)
   - On the customer detail page (Session 2 ships the `/social` inbox
     UI for triage)

If a DM doesn't appear, check the backend logs for
`integrations.meta.webhook_*` entries.

---

## Common failure modes

| Symptom | Likely cause | Fix |
|---|---|---|
| "App is not active" on the consent screen | App is in Development mode | Step 9 |
| Webhook subscription "Verify and save" fails | Env var not set / not picked up | Step 6 — restart ECS |
| OAuth callback shows `integration_error=invalid_state` | User took >10 min on the consent screen | Click Connect again |
| OAuth callback shows `integration_error=oauth_failed` | App Secret wrong, or scopes not yet approved | Check logs; if scopes pending, only App Admins can connect |
| Webhook 200s but no DMs appear in Lumè | Page not subscribed to `messages` field | Step 4.6 — confirm checkbox is set |
| Webhook fires but `pages_unmatched: 1` in audit | Connection row was disconnected between subscribe and delivery | Re-Connect from `/org/integrations` |

---

## Rotation + maintenance

- **App Secret rotation:** App Dashboard → App Settings → Basic →
  click **Reset** next to App Secret. Update `META_APP_SECRET` in
  Secrets Manager and redeploy. Old webhooks will fail signature
  validation; tenants need to Disconnect + Reconnect.
- **Verify Token rotation:** generate a new random string, update
  `META_WEBHOOK_VERIFY_TOKEN` in Secrets Manager, redeploy, then
  click **Resubscribe** in the Meta App Webhooks page.
- **Fernet key rotation:** out of scope here; see `apps/integrations/security.py`
  `INTEGRATIONS_FERNET_KEYS` (plural) for the rotation flow.
- **Long-lived tokens:** Page access tokens last 60 days. Session 2
  ships a background job that refreshes them automatically; until
  then, a tenant who connects must Reconnect every 60 days or the
  webhook signature validation will fail on outbound calls.

---

## What's NOT in scope for this runbook

- Facebook Page Messenger DMs (separate scope set; different ADR)
- WhatsApp Business (separate App Review process)
- Google Business Messages (not Meta; different platform)
- Story replies / mentions (additional webhook fields + scope)
