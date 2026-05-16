# `apps.integrations` — tenant-connected external integrations

## What lives here

- **`Connection`** — one row per (tenant, provider). Holds the OAuth
  grant payload (encrypted Fernet blob), connection status, and the
  external account identifier.
- **`SocialThread` + `SocialMessage`** — inbox storage for Meta DMs
  (Instagram in Session 1; Facebook Messenger + WhatsApp in future
  sessions). Separate from `apps.messaging.Message` (SMS) per
  ADR 0027 §6.
- **OAuth + webhook handling** for Meta (`meta.py`).
- **Token encryption helpers** (`security.py`).
- **Provider registry** (`providers.py`) — single source of truth for
  display copy, scopes, and env-driven `oauth_ready` flag.

## URL surface

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET  | `/api/integrations/` | `MANAGE_INTEGRATIONS` | List providers + tenant's connection state |
| POST | `/api/integrations/<provider>/connect/begin/` | `MANAGE_INTEGRATIONS` | Start OAuth flow → returns `authorize_url` |
| POST | `/api/integrations/<id>/disconnect/` | `MANAGE_INTEGRATIONS` | Disconnect a connected provider |
| GET  | `/api/integrations/meta/oauth/callback/` | session-bound state token | Meta redirect target after consent |
| GET  | `/api/integrations/webhooks/meta/` | `hub.verify_token` echo | Meta webhook subscription handshake |
| POST | `/api/integrations/webhooks/meta/` | `X-Hub-Signature-256` HMAC | Meta event delivery |

## Configuration

All four env vars must be set for the Instagram integration to be
clickable in the UI. With any one missing, the provider registry
flips `oauth_ready=False` and the Connect button returns 501 with
`code='oauth_not_ready'` instead of attempting OAuth — safe to deploy
without credentials.

| Env var | Source |
|---|---|
| `META_APP_ID` | Meta App Dashboard top bar |
| `META_APP_SECRET` | Meta App Dashboard → App settings → Basic |
| `META_WEBHOOK_VERIFY_TOKEN` | Random string YOU pick (see runbook) |
| `INTEGRATIONS_FERNET_KEY` | `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |

Optional override: `META_OAUTH_REDIRECT_URI` (defaults to
`http://localhost:8000/api/integrations/meta/oauth/callback/` in dev,
overridden to the prod URL in `prod.py`).

For dev / tests: `dev.py` ships with a deterministic Fernet key and
`META_TEST_MODE=True` so the signature gate is off during tests.

For operator setup walkthrough see
[`docs/runbooks/06-meta-instagram-app-setup.md`](../../../docs/runbooks/06-meta-instagram-app-setup.md).

## Customer acquisition tracking (ADR 0027 §8a)

Every customer row carries `acquisition_source` — set at create,
immutable thereafter. Set-on-create paths:

| Origin | `acquisition_source` |
|---|---|
| `apps.booking.services.find_or_create_customer` | `online_booking` |
| Staff `/clients/new` POST | `manual` (model default) |
| `apps.imports.zenoti` (when CSV importer lands) | `zenoti_import` |
| Inbound IG DM | `instagram` |

Plus `is_social_guest=True` on auto-created customers from inbound
DMs so the directory hides them by default until an operator merges
or promotes them. The merge endpoint is at
`POST /api/customers/<source>/merge-into/<target>/` (ADR 0027 §8b).

## Audit posture

- Every OAuth state change (`connect_begin_attempted`,
  `connection_established`, `oauth_failed`, `connection_disconnected`)
  writes an `AuditLog` row with `resource_type='integration_connection'`.
- Every inbound webhook ingestion writes one aggregate row with
  `resource_type='social_message'` and metadata = count summary
  (messages_created, threads_touched, duplicates, unmatched).
- **No PHI in audit metadata.** Message bodies are NEVER logged in
  the audit trail — only counts. The bodies themselves live in the
  `SocialMessage.body` column with the standard tenant-scoped read
  controls.

## PHI policy (Meta DMs)

Meta's API terms prohibit PHI in DMs. Our outbound send path (Session
2) will carry an operator-facing banner reminding staff to keep
replies non-clinical. We do NOT auto-redact — the operator is
responsible. Mirrors the marketing-template token allowlist (no PHI
tokens permitted).

## Testing

Comprehensive coverage in `tests.py`:

- Token encryption round-trip + corrupt-ciphertext rejection
- Connection model accessors (`auth_data_dict`, `set_auth_data`,
  `clear_auth_data`)
- OAuth state generation + binding + one-time-use + expiry
- `connect/begin/` returns 501 cleanly when credentials missing
- `connect/begin/` returns authorize URL when ready + persists
  CONNECTING row
- OAuth callback success → tokens encrypted + status flipped to
  CONNECTED
- OAuth callback rejects invalid state + Meta-side errors (redirects
  with `integration_error=` query param)
- Webhook GET handshake (valid token echoes challenge, wrong token
  returns 403)
- Webhook POST signature verification (valid → 200/received,
  invalid → 200/received:false, NEVER 4xx)
- Webhook ingestion creates social-guest customer + thread + message
- Webhook ingestion is idempotent on `mid` (duplicate → no second row)
- Second message in existing thread reuses customer
- Unknown page_id swallowed (logged, doesn't crash)
- Echo messages (`is_echo: True`) skipped
- Cross-tenant isolation (page subscribed to tenant A never delivers
  to tenant B)
- Merge endpoint: moves threads + preserves acquisition, rejects
  real-into-real, rejects merge-into-self, rejects merge-into-guest,
  preserves existing non-MANUAL acquisition on target

Run: `python manage.py test apps.integrations.tests --keepdb`

## ADRs

- [ADR 0027 — Meta Instagram DM integration](../../../docs/decisions/0027-meta-instagram-dm-integration.md) (canonical spec)
- [ADR 0022 — Customer messaging inbox (SMS)](../../../docs/decisions/0022-customer-messaging-inbox.md) (explains why social DMs are a separate model)
