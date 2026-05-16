# 08 — Deploy Meta Instagram integration to production

End-to-end checklist for getting the Instagram OAuth + webhook flow
live on `api.xn--lumcrm-5ua.com`. Run these in order.

> **Pre-flight:** Runbook 06 must already be complete — the Meta App
> exists, products are added, App Domains + Privacy / Terms /
> Data-Deletion URLs + webhook callback URL + verify token are all
> filled in via the Meta dashboard. This runbook handles the code +
> AWS side.

---

## Step 1 — Apply Terraform (creates secret slots + wires task def)

This adds 4 empty Secrets Manager entries + updates the ECS task
definition to inject them as env vars + grants the task role
permission to decrypt them.

```bash
cd infra
terraform plan
```

Review the plan. You should see:

- `+ aws_secretsmanager_secret.meta_app_id`
- `+ aws_secretsmanager_secret.meta_app_secret`
- `+ aws_secretsmanager_secret.meta_webhook_verify_token`
- `+ aws_secretsmanager_secret.integrations_fernet_key`
- `~ aws_ecs_task_definition.backend` (new env var + 4 new secrets entries)
- `~ aws_iam_role_policy.ecs_execution_secrets` (4 new ARNs added to the read list)

If plan looks correct:

```bash
terraform apply
```

After apply, the 4 secret slots exist but are empty. The next step
populates them.

---

## Step 2 — Populate the 4 secret values

Run these four `aws secretsmanager put-secret-value` commands with
the actual values. Each is idempotent — re-running with a new value
rotates that secret. Replace `<...>` placeholders with your real values.

```bash
# 1. Meta App ID — from developers.facebook.com → your app → top bar
aws secretsmanager put-secret-value \
  --secret-id lume-prod/meta-app-id \
  --secret-string '<META_APP_ID>'

# 2. Meta App Secret — from Meta App Settings → Basic → click "Show"
aws secretsmanager put-secret-value \
  --secret-id lume-prod/meta-app-secret \
  --secret-string '<META_APP_SECRET>'

# 3. Webhook verify token — the random string you set in the Meta
#    App webhook config. MUST match exactly.
aws secretsmanager put-secret-value \
  --secret-id lume-prod/meta-webhook-verify-token \
  --secret-string '<META_WEBHOOK_VERIFY_TOKEN>'

# 4. Fernet key for encrypting OAuth tokens at rest. Generate fresh:
#    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
aws secretsmanager put-secret-value \
  --secret-id lume-prod/integrations-fernet-key \
  --secret-string '<INTEGRATIONS_FERNET_KEY>'
```

> **Critical for the Fernet key:** Once tokens are encrypted under it,
> rotating it without a multi-key transition will leave every existing
> connection's `auth_data_dict` raising `EncryptionError`. Treat it
> like a database encryption key — write it down somewhere safe in
> addition to Secrets Manager. Rotation procedure: pass both keys as
> a list via `INTEGRATIONS_FERNET_KEYS` until the old key's
> connections refresh.

Verify the secrets resolved:

```bash
aws secretsmanager describe-secret --secret-id lume-prod/meta-app-id --query 'Name'
aws secretsmanager describe-secret --secret-id lume-prod/meta-app-secret --query 'Name'
aws secretsmanager describe-secret --secret-id lume-prod/meta-webhook-verify-token --query 'Name'
aws secretsmanager describe-secret --secret-id lume-prod/integrations-fernet-key --query 'Name'
```

---

## Step 3 — Deploy the new code

The Session 1 + 2A code is sitting in your working directory; it
needs to ship to `main` so the GitHub Actions deploy picks it up.

```bash
cd ..  # back to repo root
git status   # confirm the changes look right
git add backend/ infra/ docs/ frontend/ PROJECT_PLAN.md
git commit -m "$(cat <<'EOF'
feat(integrations): Meta Instagram DM ingestion (Session 1 + 2A)

- ADR 0027 — OAuth, webhook, encryption, data deletion, acquisition source
- Token encryption (Fernet) + Customer.acquisition_source + Customer.instagram_handle
- SocialThread + SocialMessage models + REST API (/api/social/threads/*)
- Real Meta OAuth flow + webhook receiver + signature verification
- Data deletion callback + public status endpoint (Meta Platform Terms)
- /social inbox UI (read-only; reply box ships in Session 2B)
- Diagnostics endpoint + seed_test_social_thread management command
- Terraform: 4 new Meta secrets + ECS task wiring + IAM read perm
- 62 tests passing
EOF
)"
git push origin main
```

GitHub Actions kicks in (~5-10 min):

1. Build Docker image (ARM64 native)
2. Push to ECR
3. Run `python manage.py migrate` (applies the 4 new migrations:
   `integrations.0002`, `0003`, `0004` + `customers.0004`)
4. Update ECS task definition + force new deployment
5. New tasks come up with all 4 Meta secrets injected as env vars

Watch the deploy at `https://github.com/<your-org>/lume-crm/actions`.

---

## Step 4 — Verify env vars actually landed

After the deploy completes, hit the diagnostics endpoint to confirm
the new tasks loaded all 4 Meta secrets. You need a logged-in
session as an owner/manager:

```bash
# Get a session by logging in via the dashboard first, then copy
# the `sessionid` cookie out of dev tools.
curl -s https://api.xn--lumcrm-5ua.com/api/integrations/diagnostics/ \
  -b "sessionid=<your-session-cookie>" \
  -H 'X-Tenant-Slug: <your-tenant-slug>' | jq
```

Expected:

```json
{
  "tenant": "<your-tenant>",
  "env_vars_configured": {
    "META_APP_ID": true,
    "META_APP_SECRET": true,
    "META_WEBHOOK_VERIFY_TOKEN": true,
    "INTEGRATIONS_FERNET_KEY": true,
    "META_TEST_MODE": false
  },
  "all_credentials_present": true,
  "ready_to_connect": {
    "meta_instagram": true,
    ...
  },
  "urls_meta_should_hit": {
    "oauth_redirect_uri": "https://api.xn--lumcrm-5ua.com/api/integrations/meta/oauth/callback/",
    "webhook_callback": "https://api.xn--lumcrm-5ua.com/api/integrations/webhooks/meta/",
    "data_deletion_callback": "https://api.xn--lumcrm-5ua.com/api/integrations/meta/data-deletion/"
  },
  ...
}
```

If `all_credentials_present` is `false` or any env var shows `false`,
the secret didn't resolve. Check ECS task logs:

```bash
aws logs tail /ecs/lume-prod-backend --since 10m --follow
```

---

## Step 5 — Verify the webhook is reachable

Meta will hit the webhook GET endpoint to confirm the subscription
before delivering events. Test it the same way Meta does:

```bash
curl "https://api.xn--lumcrm-5ua.com/api/integrations/webhooks/meta/?hub.mode=subscribe&hub.verify_token=<YOUR_VERIFY_TOKEN>&hub.challenge=hello"
```

Should respond `hello` as plain text. If you get 403, the verify
token doesn't match between Secrets Manager and the Meta dashboard.

---

## Step 6 — OAuth your Instagram

In the production CRM (`https://<tenant>.xn--lumcrm-5ua.com`):

1. Sign in as a tenant owner.
2. Navigate to **Organization → Integrations**.
3. Find the **Instagram Business DMs** card. The "Connect" button
   should now be active (not greyed out / "awaiting approval").
4. Click **Connect**. You'll be redirected to facebook.com:
   - You'll see Lumè CRM in the consent screen.
   - **Pick the Facebook Page** linked to your IG Business Account.
   - Approve the requested scopes (`instagram_business_basic`,
     `instagram_business_manage_messages`, `pages_show_list`,
     `pages_manage_metadata`).
5. Meta redirects you back to `https://api.xn--lumcrm-5ua.com/api/integrations/meta/oauth/callback/?code=...&state=...`
   which exchanges the code, subscribes the Page to messaging
   webhooks, and bounces you back to `/org/integrations?connected=instagram`.
6. The Instagram card flips to green **"Connected"** with the
   IG account name displayed.

---

## Step 7 — Smoke-test inbound DMs

1. From your personal Instagram, send a DM to the connected
   Business account.
2. Within a few seconds (Meta's webhook delivery is usually <2s),
   the message should land in `/social`.
3. The customer record is auto-created as a "social guest" with
   `acquisition_source='instagram'` and `is_social_guest=True`.

If nothing arrives:

- Check `aws logs tail /ecs/lume-prod-backend --since 5m --follow`
  for any `integrations.meta.webhook_*` log lines.
- Re-check the webhook is subscribed in the Meta App dashboard
  (Webhooks → Instagram → check `messages` is subscribed against
  the Page you just connected).
- Hit `/api/integrations/diagnostics/` again — the connection should
  now show `has_token: true` and `instagram_username` populated.

---

## Troubleshooting reference

| Symptom | Where to look |
|---|---|
| "Connect" button still 501s | Diagnostics: `all_credentials_present` |
| OAuth fails with "App not active" in Facebook | Meta App is in Dev Mode; you must be a Meta App admin to OAuth |
| OAuth fails with redirect URI mismatch | Meta App dashboard → Facebook Login → Valid OAuth Redirect URIs MUST exactly match what diagnostics reports |
| Webhook subscribed but no DMs arrive | Make sure the Page is subscribed (Meta dashboard → Webhooks → Instagram → click into the row); check ECS logs for delivery attempts |
| Decrypt errors after rotating Fernet key | Use `INTEGRATIONS_FERNET_KEYS=new,old` until existing connections refresh; never drop the old key without re-encrypting |

---

## Post-launch checklist (within 7 days)

- [ ] Rotate the Meta App Secret in the Meta dashboard, then
  `aws secretsmanager put-secret-value --secret-id lume-prod/meta-app-secret`
  with the new value, then force ECS redeploy. (The current value was
  exposed in chat history during initial setup.)
- [ ] Submit Meta App for review to graduate from Dev Mode. Until
  then, only Meta App admins (you) can OAuth — production tenants
  will see "App not active" errors if they try.
- [ ] Add `integrations.meta.webhook_bad_signature` log line to the
  CloudWatch alarm pipeline (signal for "someone's probing the
  webhook endpoint with bogus payloads").
