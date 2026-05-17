# ADR 0027 — Meta Instagram Business DMs: OAuth, webhook, and social inbox

## Status

Accepted (2026-05-16). Session 1 — foundation (OAuth + webhook
ingestion). Outbound send + inbox UI ship in Session 2.

## Context

ADR 0022 shipped two-way SMS / MMS through Twilio and explicitly
deferred social DMs (Instagram, Facebook Messenger, WhatsApp) to a
separate surface: *"a **separate** menu surface for social DMs ...
different channels have different consent semantics, different rate
limits, different opt-out vocabularies (`STOP` for SMS, 'block'
for Meta DMs), and different PHI postures (Meta's terms forbid
sending PHI through their APIs even though carriers will accept it
via SMS under our BAA)."*

Manhattan Laser Spa and the second launch tenant both live on
Instagram — the majority of "can I book?" inquiries arrive as IG
DMs. Without an inbox surface those messages compete with the rest
of the spa owner's personal IG notifications, get missed for hours,
and turn into lost bookings.

Phase 1K (the original "Meta channels" entry in PROJECT_PLAN.md)
was paused on Meta App approval because the OAuth callback URL has
to be a real HTTPS endpoint Meta can reach. The production backend
at `https://api.xn--lumcrm-5ua.com` (deployed in Phase 0c) closes that
gap — we can now resume.

Scope for this ADR: **Instagram Business DMs only.** Facebook Page
Messenger is enabled at the Meta App level because IG Business DMs
ride on Page Messenger's webhook plumbing and share scopes — but
the Lumè UI exposes only the Instagram surface in Session 1. WhatsApp
adds later under a separate ADR (different review process, different
billing model).

## Decision

### 1. Token storage — field-level encryption on `Connection.auth_data`

The `Connection` model has carried a JSONField `auth_data` since v1
with a comment promising encryption when real tokens land. Session 1
delivers on that promise via a new `apps.integrations.security`
module wrapping `cryptography.fernet`:

```
encrypted_str = encrypt_auth_data({'access_token': '...', 'page_id': '...'})
plaintext_dict = decrypt_auth_data(encrypted_str)
```

The key comes from `settings.INTEGRATIONS_FERNET_KEY` (a 32-byte
url-safe base64 string), loaded from Secrets Manager in prod and
from `.env` in dev. Key rotation is supported by passing a list
`Fernet([new_key, old_key])` — tokens encrypted under the old key
keep decrypting until the next OAuth refresh.

We do NOT add a Django custom field class. The model continues to
read/write `auth_data` as a dict via a property on `Connection` that
calls the helpers transparently:

```
@property
def auth_data_dict(self) -> dict:
    return decrypt_auth_data(self.auth_data) if self.auth_data else {}

def set_auth_data(self, value: dict) -> None:
    self.auth_data = encrypt_auth_data(value)
```

Reasoning: keeping `auth_data` as a string field (encrypted blob)
means migrations / admin / tests / DRF all see opaque ciphertext
unless they go through the property. That's the SOC 2 posture we
want — accidental serialisation of a Connection row produces an
unreadable string, not a leaked token. A custom field class would
silently decrypt in admin and serializers, defeating that property.

### 2. OAuth flow — Facebook Login with IG scopes

Instagram Business DMs require a Facebook Login OAuth grant against
the IG-linked Facebook Page (Meta does not offer a "log in with
Instagram" path for Business APIs; this is the documented pattern).
The flow:

```
1. Operator clicks Connect in /org/integrations
2. POST /api/integrations/meta_instagram/connect/begin/
   → server generates a state token (256-bit random, stored on the
     user's session under `meta_oauth_state`)
   → server returns:
       {
         "authorize_url": "https://www.facebook.com/v18.0/dialog/oauth?
                           client_id={META_APP_ID}
                           &redirect_uri={CALLBACK_URL}
                           &state={STATE}
                           &scope=instagram_basic,
                                  instagram_manage_messages,
                                  pages_show_list,
                                  pages_manage_metadata"
       }
3. Frontend window.location = authorize_url
4. User picks the Page linked to their IG Business account, consents
5. Meta redirects: GET /api/integrations/meta/oauth/callback/
                       ?code=<short-lived-code>&state=<state>
6. Server validates `state` against session, exchanges code for a
   short-lived (1h) user token via /oauth/access_token
7. Server exchanges that for a long-lived (60d) user token
8. Server calls /me/accounts to list Pages the user manages, picks
   the one whose `instagram_business_account` field is non-null
9. Server stores the Page access token + Page ID + IG Business
   Account ID + IG username + granted scopes in Connection.auth_data
   (encrypted)
10. Server calls POST /{page-id}/subscribed_apps?subscribed_fields=
    messages,messaging_postbacks to enable webhook delivery for this
    page
11. Connection.status = CONNECTED
12. Redirect back to /org/integrations with ?connected=instagram
```

If the user has multiple Pages with an IG Business Account linked,
Session 1 picks the FIRST one. Multi-page selection UI is Session 3
polish — most spas have exactly one Page.

State validation rejects:
- Missing state in session (expired / different browser tab)
- Mismatched state (CSRF defence)
- State older than 10 minutes (replay defence)

All steps audit-logged with `event` keys:
`oauth_started`, `oauth_callback_received`, `oauth_token_exchanged`,
`oauth_page_selected`, `oauth_webhook_subscribed`, `oauth_failed`.

### 3. Webhook receiver — single endpoint, signature-verified

`POST /api/integrations/webhooks/meta/` mirrors the Twilio-webhook
posture from ADR 0022:

- `AllowAny` permission (Meta doesn't carry a session cookie).
- `X-Hub-Signature-256` header verified as HMAC-SHA256 of the raw
  request body using `settings.META_APP_SECRET`. Mismatch returns
  200 with `{"received": false}` — never 4xx, because Meta retries
  4xx aggressively (worse than Twilio's behaviour). The mismatch
  is logged with severity WARNING for alerting.
- `META_TEST_MODE=True` bypasses signature verification for unit
  tests, same convention as `TWILIO_TEST_MODE`.

`GET /api/integrations/webhooks/meta/` handles the subscription
verification handshake:

- Reads `hub.mode`, `hub.verify_token`, `hub.challenge`
- If mode=`subscribe` AND verify_token matches
  `settings.META_WEBHOOK_VERIFY_TOKEN`, echo back `hub.challenge`
  as plain text 200
- Otherwise 403

`META_WEBHOOK_VERIFY_TOKEN` is a random string we pick (not a
Meta-supplied secret) — it goes in the Meta App dashboard webhook
config so we can prove the GET is coming from a configured Meta
subscription, not a random scanner.

### 4. Payload routing — page ID → tenant lookup

Meta webhook payloads contain a Page ID at `entry[].id`. Lookup
flow:

```
1. For each entry in payload['entry']:
2.   page_id = entry['id']
3.   connection = Connection.objects.filter(
         provider='meta_instagram',
         status='connected',
         external_id=page_id,
     ).first()
4.   if not connection: log + continue (was probably disconnected
                       between subscribe and delivery)
5.   tenant = connection.tenant
6.   for change in entry.get('changes', []):
7.       process_change(tenant, connection, change)
```

The `external_id` field on Connection holds the Page ID (NOT the
IG Business Account ID) because that's what Meta sends in webhook
payloads. The IG Business Account ID lives in `auth_data` for
outbound sends, which need it in the URL.

### 5. Customer matching — IG handle → existing customer → social guest

Inbound message payload includes the sender's IG-scoped User ID
(`sender.id`) and, on first message, can be supplemented with the
sender's IG username via `GET /{ig-scoped-user-id}?fields=username`
(scoped IDs don't expose usernames by default; the username lookup
is gated by scope `instagram_basic`).

Matching priority:

1. **Existing `Customer.instagram_handle` match** — if any customer
   in the tenant has this IG handle stored, use them.
2. **New "social guest" Customer** — create a fresh Customer row
   with:
   - `first_name = ig_username` (e.g. "@maria.beauty" → "maria.beauty")
   - `last_name = ''`
   - `external_id = ig_scoped_user_id`
   - `external_source = 'instagram'`
   - `instagram_handle = ig_username`
   - `marketing_email_opt_in = False`, `marketing_sms_opt_in = False`
     (social DM consent is not the same as marketing consent —
     belt-and-braces opt-out by default)
   - A new `is_social_guest = True` flag distinguishes these from
     "real" customers in the directory until the operator merges
     them into an existing client (Session 3 merge UI).

This is the same provenance pattern the Zenoti importer uses. The
`is_social_guest` flag lets the customer-list UI hide these rows
by default so the spa's directory doesn't fill with random IG
handles asking "what's your $200 facial?"

A new `Customer.instagram_handle` field + the `is_social_guest`
boolean ship in this migration. Frontend updates for visibility +
merge are Session 3.

### 6. Message storage — new `SocialThread` + `SocialMessage` in `apps.integrations.social`

Per ADR 0022's anticipated split, social messages live in their
own models — NOT mixed into `apps.messaging.Message`. Reasoning:

- Different identifier shape (IG scoped user IDs vs phone numbers).
- Different status enum (Meta: `received`, `delivered`, `read` via
  webhooks; Twilio: `queued/sent/delivered/failed/received`).
- Different opt-out semantics (Meta blocks at the user level; SMS
  is opt-out via STOP keyword).
- Different rate limits (Meta: per-page-per-day; Twilio: per-number-per-second).
- Different PHI policy (Meta forbids PHI in DMs; SMS we treat as
  PHI under our BAA).

Models:

```python
class SocialThread(TenantedModel):
    provider = CharField(choices=Provider.choices)  # 'instagram', ...
    connection = FK(Connection, PROTECT)
    customer = FK(Customer, PROTECT)
    external_thread_id = CharField(max_length=128)  # IG-scoped user ID
    external_username = CharField(max_length=128, blank=True)
    last_message_at = DateTimeField(db_index=True)
    last_inbound_at = DateTimeField(null=True)
    read_at = DateTimeField(null=True)  # "marked read" by operator
    created_at = ...
    class Meta:
        unique_together = [('tenant', 'provider', 'external_thread_id')]

class SocialMessage(TenantedModel):
    thread = FK(SocialThread, CASCADE, related_name='messages')
    direction = CharField(choices=Direction.choices)  # 'outbound', 'inbound'
    body = TextField(blank=True)  # text content; empty for media-only
    media_urls = TextField(blank=True)  # newline-separated
    external_message_id = CharField(max_length=128, db_index=True)  # Meta `mid`
    status = CharField(choices=Status.choices, default='received')
    sent_by = FK(User, SET_NULL, null=True)  # outbound only
    created_at = DateTimeField(db_index=True)
    delivered_at = DateTimeField(null=True)
    read_at = DateTimeField(null=True)  # delivery-receipt read, NOT operator read
    class Meta:
        unique_together = [('tenant', 'external_message_id')]
```

The `unique_together` on `external_message_id` is the idempotency
fence: Meta retries the same `mid` if our 200 doesn't reach them
in time. The unique constraint turns a duplicate into a no-op via
`IntegrityError` → swallowed → still 200.

### 7. Outbound rate limits + PHI policy

Outbound send lands in Session 2 but the architecture decisions
are made now:

- **PHI never in social DMs.** Operator replies are sent as-is, but
  the `/social` inbox UI will (Session 2) carry a banner reminding
  operators that "Meta's API terms prohibit PHI in DMs — keep
  replies non-clinical." We do NOT auto-redact; the operator is
  responsible. The reasoning matches our marketing-template token
  allowlist (no PHI tokens permitted).
- **24-hour reply window.** Meta's Messenger Platform restricts
  outbound DMs to 24 hours after the user's last inbound message
  unless a Message Tag is used. Session 2 enforces this server-side
  by checking `SocialThread.last_inbound_at` before allowing send.
  No tag use in v1 — appointment-related tags (`CONFIRMED_EVENT_UPDATE`)
  are tempting but require extra App Review.
- **Per-page rate limits.** Documented as 200 calls / hour / page
  in Meta's docs. Session 2 will add a simple per-page sliding
  window in Redis (since we already have it from Phase 0c).

### 8a. Acquisition source — first-touch attribution per customer

Operators don't want "an inbox" — they want to know whether IG is
worth the ad spend. That answer requires per-customer first-touch
provenance that survives the eventual booking:

- New `Customer.acquisition_source` enum field with choices:
  `instagram`, `facebook`, `whatsapp`, `online_booking`,
  `walk_in`, `referral`, `zenoti_import`, `manual`, `other`.
- Set at customer creation; immutable thereafter. Sources of truth:
  - Social-guest creation (this ADR) — `instagram` / `facebook` / `whatsapp`
  - Public booking page (`apps.booking`) — `online_booking`
  - Staff-created in `/clients/new` — `manual`
  - Zenoti / vendor import (`apps.imports`) — `zenoti_import`
  - Future: phone-call walk-in form, in-spa kiosk — `walk_in`
- A backfill migration sets existing customers to `manual` by
  default; the Zenoti importer is updated to set `zenoti_import`
  on new rows it creates.
- **Appointments inherit attribution via the customer FK.** No new
  field on `Appointment`. The existing `Appointment.source` enum
  (`online` / `manual`) stays — it answers "which booking surface
  was used?" — while `Customer.acquisition_source` answers "where
  did this customer originally come from?" Both are useful and
  orthogonal:
    - A walk-in customer booking online later → `source='online'`,
      `acquisition_source='walk_in'`
    - An IG-DM customer the operator manually booked → `source='manual'`,
      `acquisition_source='instagram'`

### 8b. Social-guest → real-customer merge

When an IG conversation produces a real booking, the operator should
be able to confirm the social guest IS the real customer. The merge:

- New `POST /api/customers/{social_guest_id}/merge-into/{real_id}/`
  endpoint, owner + manager only via `MANAGE_CLIENT_RECORDS`.
- Moves all `SocialThread` + `SocialMessage` rows to the real
  customer (`SocialThread.customer_id` swap).
- Copies `instagram_handle` + `acquisition_source` from guest to
  real customer ONLY IF the real customer doesn't already have
  them. Never overwrites — preserves the earlier first-touch.
- Soft-deletes the social guest (`is_active=False`) and audit-logs
  the merge with `event='social_guest_merged'`, both customer IDs.
- This is Session 2 UI work but the endpoint ships in Session 1
  so the architecture is testable end-to-end.

### 8c. Reporting — acquisition source as a first-class dimension

Two new reports in `apps.reports` (Session 2 — schemas + tests, no
new infrastructure):

- **Operations · Bookings by acquisition source** (`bookings_by_acquisition_source`)
  Per source: appointment count, completed count, cancelled count,
  no-show count, cancellation rate. Window = date range.
  PHI tier: `none`. Permission: `VIEW_OPERATIONS_REPORTS`.
- **Financial · Revenue by acquisition source** (`revenue_by_acquisition_source`)
  Per source: gross revenue (PAID invoices), average ticket, customer
  count, repeat-customer count. PHI tier: `aggregated`. Permission:
  `VIEW_FINANCIAL_REPORTS`.

The "is my Meta ad budget paying off?" question is answered by
filtering the Financial report to `acquisition_source='instagram'`
over the window of the ad campaign. This is the report the spa
owner will actually look at — explicit business reason for the
feature.

### 9. Audit log — every connect, disconnect, inbound, send

All Connection state changes audit-logged with
`resource_type='integration_connection'`. All SocialMessage rows
get an audit entry on insert (inbound) and on send (outbound,
Session 2) with `resource_type='social_message'`. PHI is NEVER in
the audit metadata — `body` is summarised as a length + media
count (`{"body_length": 47, "media_count": 0}`), not the content.
Customer ID + message direction + status are logged.

This mirrors the SMS audit posture (ADR 0022) — same SOC 2
boundary, same HIPAA defensibility.

## Consequences

### Good

- IG DMs land in Lumè within seconds of being sent. Operators stop
  missing inquiries that compete with the owner's personal IG
  notifications.
- The OAuth + webhook plumbing is reusable for Facebook Page
  Messenger and WhatsApp (next ADR each) with mostly the same
  scaffolding — separate provider entries in the registry, separate
  Connection rows, same webhook endpoint, same signature scheme.
- Encryption-at-rest for OAuth tokens closes a long-standing v1
  shortcut. Helper module is reusable for any future integration.
- PHI posture is explicit and enforceable: PHI never crosses Meta's
  API surface, audit logs never include message bodies.

### Bad / Deferred

- **Session 2 dependency:** Operators can't reply through Lumè in
  Session 1 — they see inbound DMs in the audit log + database but
  the UI to reply lands in Session 2. Workable but not shippable to
  end users yet.
- **Multi-page selection:** If a tenant manages multiple FB Pages
  with IG-linked accounts, Session 1 picks the first one returned
  by `/me/accounts`. Most tenants have one Page; multi-page picker
  is Session 3 polish.
- **No story replies / mentions:** Webhook subscription is for
  `messages` + `messaging_postbacks` only in Session 1. Story
  replies + @mentions ride on different webhook fields and require
  additional App Review; deferred to Session 3.
- **Token expiry:** Long-lived (60d) tokens need refresh; the
  refresh job lands in Session 2. If Session 1 ships with a 60d
  expiry, no production tenant should connect until Session 2 is
  also live or they'll silently lose connection on day 60.

### Acknowledged

- Meta App Review for `instagram_manage_messages` typically
  takes 1-3 weeks. Until approved, only the Meta App admins (us)
  can authenticate against the integration — production tenants
  see "connect" but the OAuth flow fails with Meta's "this app
  hasn't been approved" message. We'll mark `oauth_ready=True` in
  the provider registry only after review passes.
- The `is_social_guest` Customer flag opens a small attack surface:
  someone could spam-DM a tenant's IG account to bloat the Customer
  table. Session 3 adds a duplicate-detection + rate-limit on
  guest creation (max N guests per page per hour). For Session 1
  we rely on Meta's own anti-spam at the IG layer.

## Alternatives considered

### Mix social DMs into `apps.messaging.Message` with a `channel` enum

Tempting (single inbox query) but rejected because the SMS and
social-DM domains diverge enough (identifier shapes, status enums,
PHI posture, opt-out semantics) that the polymorphic table grew
sufficient nullable columns to be confusing. ADR 0022 already
anticipated the split. Keeping them separate keeps each model's
invariants legible — `Message.from_number` is always populated for
SMS rows; `SocialMessage.external_username` is always populated for
social rows.

The unified-inbox UX still lives at the frontend layer (Session 2 +
Session 3) — `/messages` and `/social` will share a "unread by
customer" composite query.

### Server-Sent Events / WebSocket push to the frontend on inbound

Considered for instant inbox-badge updates. Rejected for v1 in
favour of poll-on-tab-focus (the existing pattern in `/messages`).
Pub/sub infra lands later if support volume demands it; until then
a 30-second poll on the active inbox tab is sufficient.

### Long-lived Meta tokens via "System User" tokens (no expiry)

Available for Business Manager accounts but requires the tenant to
have a Business Manager + add Lumè as a partner app. Higher
configuration burden on the tenant for negligible benefit (the
60d refresh is automatic background work for us). Standard Page
tokens with refresh stay.

### Encrypt only specific JSON fields, not the whole blob

`access_token` is the only truly sensitive field; `page_id` and
`granted_scopes` are not. Encrypting only the sensitive fields would
let the rest be queryable. Rejected: encrypting the whole blob is
simpler, faster to audit, and the "queryable scopes" need is
hypothetical. If a future feature needs to filter Connections by
granted scope, that's a separate column-projection migration.

## Implementation checklist (Session 1)

- [ ] `apps/integrations/security.py` — Fernet encrypt/decrypt helpers
- [ ] `Connection` model — `auth_data` swapped to `TextField`,
      `auth_data_dict` property + `set_auth_data()` method
- [ ] Migration 0002 — `auth_data` TextField + encrypt existing rows
      (no-op, they're all empty `{}`)
- [ ] Settings — `META_APP_ID`, `META_APP_SECRET`, `META_WEBHOOK_VERIFY_TOKEN`,
      `META_OAUTH_REDIRECT_URI`, `META_TEST_MODE`, `INTEGRATIONS_FERNET_KEY`
- [ ] `Customer` — `instagram_handle` + `is_social_guest` +
      `acquisition_source` enum (with backfill migration setting
      existing rows to `manual` and Zenoti-imported rows to
      `zenoti_import`)
- [ ] `apps.booking` views set `acquisition_source='online_booking'`
      on customer create; `apps.customers` `/clients/new` view sets
      `manual`; `apps.imports.zenoti` sets `zenoti_import`
- [ ] `apps/integrations/social/` — new module
- [ ] `SocialThread` + `SocialMessage` models + migration
- [ ] `apps/integrations/oauth/meta.py` — flow logic (state token,
      authorize URL, code exchange, page selection, webhook subscribe)
- [ ] `IntegrationConnectBeginView` — replace 501 stub with real flow
      (gated on `oauth_ready` in provider registry)
- [ ] `MetaOAuthCallbackView` — new endpoint at
      `/api/integrations/meta/oauth/callback/`
- [ ] `MetaWebhookView` — GET (hub-challenge) + POST (signature +
      ingestion). Public, `AllowAny`, CSRF-exempt.
- [ ] `apps/integrations/webhooks/meta_handler.py` — payload parsing,
      tenant lookup, customer matching, message insertion
- [ ] Update `providers.py` — flip `meta_instagram.oauth_ready=True`
      once `META_APP_ID` is set (env-driven, not hardcoded)
- [ ] Tests:
  - OAuth state generated, stored on session, validated
  - State expiry (older than 10 min rejected)
  - Cross-session state rejected
  - Code exchange mocked end-to-end → Connection row created
  - Page selection picks IG-linked Page
  - Webhook subscribe call made on connect
  - Webhook GET: valid token → echoes challenge; invalid → 403
  - Webhook POST: valid signature → 200; invalid → 200 with
    `{"received": false}` (no 4xx to Meta)
  - Inbound message → SocialMessage created
  - Inbound message → SocialThread upserted
  - Duplicate `mid` → idempotent (no second row)
  - Unknown page_id → 200, no crash, log entry
  - Customer matching: existing handle → reused; new → social guest
  - Cross-tenant: a Page subscribed to tenant A never delivers to B
  - Audit log written on connect/disconnect/inbound (no PHI in
    metadata)
- [ ] `apps/integrations/README.md` — operator docs + dev-setup notes
- [ ] Update `PROJECT_PLAN.md` Phase 1K to "Session 1 shipped"

## Session 2C — outbound send + token refresh + disconnect hardening

Shipped 2026-05-17.

### Outbound DM send

- `POST /api/social/threads/<id>/reply/` (`SocialThreadReplyView`)
- Validates in order: connection still CONNECTED, body non-empty,
  body ≤ 1000 chars, 24-hour Meta reply window via
  `thread.last_inbound_at`. Each failure returns a stable `code`
  field so the frontend renders the right inline message.
- Creates `SocialMessage` row in `QUEUED` state up-front for a
  stable ID, then calls `meta.send_instagram_dm()`. On success:
  `external_message_id` updated to Meta's `mid`, status flipped to
  `SENT`, thread `last_message_at` bumped, `read_at` set.
- On Meta rejection: status flipped to `FAILED` (NOT deleted —
  failed messages stay visible in the thread so operator can retry
  with edits), 502 returned with Meta's error message.
- Permission gate: `SocialPermission` (owner + manager only).

### HIPAA reinforcement

- Audit log records `body_length` and `meta_message_id` only —
  never the body text itself, even on failure. Regression test
  asserts a sentinel substring from a sample body does NOT appear
  in `entry.metadata`.
- Reply UI shows a persistent (non-dismissible) banner: "Meta's
  platform terms prohibit sending PHI through DMs — keep replies
  non-clinical." Operators are the responsible party; we do not
  auto-redact.
- The body still stores in our DB encrypted-at-rest via the RDS
  KMS key (same posture as every other PHI surface). Access to the
  detail endpoint is already audit-logged via the existing
  `social_thread.read` event.

### Token refresh (60-day cycle)

- `meta.refresh_long_lived_token()` — `GET graph.instagram.com/refresh_access_token`
  per Meta docs. Returns new token + extended expiry.
- `python manage.py refresh_meta_tokens` — daily cron-friendly
  management command. Selects connections expiring within a 14-day
  window. On permanent errors (token expired, session revoked)
  flips the connection to `ERROR` so the operator sees "reconnect
  required" in the integrations UI. Transient errors are logged
  and retried on the next sweep.
- `--dry-run` + `--tenant=<slug>` + `--window-days=N` for
  ops control.
- Will be wired to EventBridge → ECS RunTask in the Terraform
  follow-up (currently must be invoked manually or by a developer's
  cron).

### Disconnect hardening

- `IntegrationDisconnectView` now calls
  `meta.unsubscribe_ig_user_from_webhooks()` BEFORE wiping local
  tokens. Without this, Meta keeps delivering webhook events forever
  (or until the user revokes via Instagram); each delivery 200s but
  logs "no matching connection."
- Best-effort: if the unsubscribe call fails (token expired, network
  blip), proceed with local disconnect anyway — better to leave a
  dangling Meta subscription than block an operator from
  disconnecting.
- Audit log records `webhook_unsubscribe_status` (`success` /
  `failed` / `skipped`) so the audit trail captures whether Meta's
  side actually got cleaned up.

### Tests

13 new tests (75 total in `apps.integrations.tests`):

- `SocialThreadReplyTests` — happy path, empty body, oversized
  body, 24h window violation, no-inbound-anchor, disconnected
  connection, Meta rejection → failed status, audit log omits body
  text, front-desk forbidden.
- `RefreshMetaTokensCommandTests` — in-window refresh updates token
  + expires_at, out-of-window skipped (no Meta call), permanent
  error flags connection ERROR, dry-run makes no Meta calls.

## Session 2E — DM history backfill (`apps.integrations.backfill`)

Shipped 2026-05-17.

### Problem

Meta's webhook system only forwards messages received AFTER a
subscription is registered. A spa connecting their existing
Instagram presence sees an empty `/social` inbox even though they
have years of DM history in the IG app. This was both bad UX (the
inbox felt broken on day-one) and a Meta-App-Review concern (a
reviewer connecting a real test account sees no data).

### Decision

On every successful OAuth connect, we now call Meta's
`/{ig-user-id}/conversations` + `/{conversation-id}?fields=messages{…}`
endpoints to seed the inbox with recent history. Implementation
lives in `apps.integrations.backfill` to keep `meta.py`
narrowly-focused on the live OAuth + send path.

### Caveats (documented in operator-facing copy)

- Meta only returns **recent activity** — typically the last ~30
  conversations and ~20 messages per conversation. Older threads
  are NOT retrievable.
- Counts against Meta's rate limit (~200 calls/hour/account).
  Backfilling one connection = 1 + N API calls (N = number of
  recent conversations).
- Messages older than Meta's retention window or that have been
  deleted by either party are not returned at all.

### Idempotency + safety

- The SocialMessage `(tenant, external_message_id)` unique constraint
  + SocialThread `(tenant, provider, external_thread_id)` constraint
  make re-running the backfill a no-op for already-imported rows.
- Backfill in the OAuth callback is **best-effort + try-wrapped**: a
  failure does NOT block the connect-success redirect, the operator
  just sees an empty inbox that fills as new messages arrive (and
  they can run the management command later).
- Audit log records counts only: `conversations_examined`,
  `messages_created`, `messages_duplicate`, `api_errors`. No PHI.

### Operator entry points

- **Automatic** — fires inside `MetaOAuthCallbackView` immediately
  after the per-account subscription succeeds, before the redirect.
- **Manual** — `python manage.py backfill_meta_conversations` for
  already-connected tenants. Supports `--tenant=<slug>`,
  `--connection-id=N`, `--dry-run`.

### Customer-matching reuse

Backfilled messages use the same `_resolve_thread_and_customer` helper
that live-ingestion uses, so customer-matching semantics stay
consistent between the two paths. PSIDs returned by `/conversations`
have the same format as the ones webhook deliveries carry.

## References

- [Meta Messenger Platform Webhooks](https://developers.facebook.com/docs/messenger-platform/webhooks)
- [Instagram Business Messaging API](https://developers.facebook.com/docs/messenger-platform/instagram)
- [Page Subscribed Apps](https://developers.facebook.com/docs/graph-api/reference/page/subscribed_apps/)
- [Long-Lived Page Access Tokens](https://developers.facebook.com/docs/facebook-login/guides/access-tokens/get-long-lived/)
- ADR 0022 — Customer messaging inbox (SMS / MMS)
- ADR 0021 — Per-tenant TFN provisioning + SMS opt-in posture
- ADR 0017 — PHI redaction (template for the audit-no-PHI rule)
