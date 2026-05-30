"""
Shared Django settings — environment-agnostic.

Both `dev.py` and `prod.py` import * from this module, then override
the few things that genuinely differ (DEBUG, email backend, security
headers, logging). Keep environment-specific defaults OUT of here —
the goal is that this file reads the same way prod or dev.

Sensitive values come from the env (Secrets Manager → ECS env in prod,
`.env` file in dev). Never bake secrets into source.
"""

import os
from datetime import timedelta
from pathlib import Path

import environ

# BASE_DIR is the `backend/` directory (two levels up from this file:
# `backend/lume_crm/settings/base.py` → `backend/`).
BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, []),
)
# Read .env when present. Production containers don't ship a .env (env
# vars are injected by ECS / Secrets Manager), so the `read_env` is a
# no-op there.
environ.Env.read_env(BASE_DIR / '.env')

# Read SECRET_KEY via raw os.environ -- django-environ's env() has a
# "proxied env" feature that recursively substitutes values starting
# with `$`. Random secrets routinely start with `$`, which breaks
# unpredictably. Same rationale applies to DB_PASSWORD below.
SECRET_KEY = os.environ['SECRET_KEY']
DEBUG = env('DEBUG')
ALLOWED_HOSTS = env('ALLOWED_HOSTS')


INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # Third-party
    'rest_framework',
    'rest_framework_simplejwt.token_blacklist',
    'corsheaders',
    'drf_spectacular',

    # Lumè apps
    'apps.users',
    'apps.tenants',
    'apps.audit',
    'apps.customers',
    'apps.services',
    'apps.appointments',
    'apps.invoices',
    'apps.forms',
    'apps.reports',
    'apps.platform',
    'apps.integrations',
    'apps.booking',
    'apps.waitlist',
    'apps.charts',
    'apps.marketing',
    'apps.products',
    'apps.packages',
    'apps.memberships',
    'apps.giftcards',
    'apps.timetracking',
    'apps.commissions',
    'apps.messaging',
    'apps.portal',
    'apps.imports',
    'apps.billing',
    'apps.payments',
    'apps.ai_inbox',
]

AUTH_USER_MODEL = 'users.User'

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'apps.tenants.middleware.TenantMiddleware',
    'apps.tenants.middleware.LocationMiddleware',
    'apps.portal.middleware.PortalSessionMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

# Default CORS — dev permits localhost; prod overrides with the real
# tenant subdomains. CORS_ALLOWED_ORIGINS lives in dev.py / prod.py.
CORS_ALLOW_CREDENTIALS = True

# Extend the default CORS allow-headers so the browser preflight accepts
# our custom tenant-slug header in dev (where subdomains aren't
# available). Prod resolves tenants from the request subdomain.
from corsheaders.defaults import default_headers as _default_cors_headers
CORS_ALLOW_HEADERS = (*_default_cors_headers, 'x-tenant-slug')


# Auth: the web CRM uses session cookies; the staff mobile app uses JWT
# bearer tokens (see ADR 0031). Both classes are active — DRF tries them
# in order and takes the first that resolves a user.
#
# SessionAuthentication is kept FIRST deliberately: DRF derives the
# 401-vs-403 status for an unauthenticated request from
# `authenticators[0].authenticate_header()`. SessionAuthentication
# returns none there, so browser requests keep their existing 403
# behaviour exactly — the JWT class advertises a `Bearer` challenge and
# would otherwise flip every unauthenticated response to 401.
# MobileJWTAuthentication runs second and picks up Bearer-token requests
# (it returns None when there's no Bearer header). Public endpoints opt
# into AllowAny.
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.SessionAuthentication',
        'apps.users.authentication.MobileJWTAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',

    # Throttle rates for the public booking surface (apps.booking).
    # Counts live in Django's default cache (local-memory in dev,
    # Redis in prod via Phase 0c.2). Tests use settings overrides to
    # disable throttling per-class so retry-heavy specs aren't fragile.
    'DEFAULT_THROTTLE_RATES': {
        'booking_submit': '10/hour',
        'booking_reschedule': '20/hour',
        # Self-serve signup is tight (5/hr per IP) because each
        # attempt creates a User + Tenant + Stripe Customer. Real
        # owners sign up once; attackers burn through dozens.
        'signup': '5/hour',
    },
}

# JWT settings for the staff mobile app (apps/users/mobile.py + ADR 0031).
# Short-lived access tokens; refresh tokens rotate on every use and the
# spent token is blacklisted, so a stolen refresh token is single-use.
# A 7-day refresh window means a lost device's session lapses within a
# week even without an explicit remote logout — the on-device app-lock
# is the primary control, this is defence in depth.
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=60),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'UPDATE_LAST_LOGIN': True,
    'AUTH_HEADER_TYPES': ('Bearer',),
}

# OpenAPI schema generation. Swagger UI: /api/docs/, ReDoc: /api/redoc/
SPECTACULAR_SETTINGS = {
    'TITLE': 'Lumè CRM API',
    'DESCRIPTION': 'Internal API for the Lumè CRM frontend. Multi-tenant; session-cookie auth.',
    'VERSION': '0.1.0',
    'SERVE_INCLUDE_SCHEMA': False,
    'COMPONENT_SPLIT_REQUEST': True,
}

ROOT_URLCONF = 'lume_crm.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'lume_crm.wsgi.application'


# Database connection. Two paths supported:
#
#   1. `DATABASE_URL` env var set directly -- used in dev (loaded
#      from .env) and any environment where the URL is hand-crafted.
#
#   2. Individual `DB_USER`/`DB_PASSWORD`/`DB_HOST`/`DB_PORT`/`DB_NAME`
#      env vars -- used in prod where ECS injects them separately
#      (DB_PASSWORD comes from Secrets Manager). We URL-encode the
#      password before assembling the URL because RDS-managed
#      passwords routinely include `@`, `$`, `/`, `&`, and other
#      characters that break URL parsing or shell expansion.
#
# CRITICAL: read DB_PASSWORD via `os.environ` directly, NOT via
# django-environ's `env()`. django-environ has a "proxied env"
# feature where any value starting with `$` gets recursively looked
# up as an env-var name -- which is exactly what RDS-generated
# passwords do when they happen to start with `$`. Bypassing env()
# avoids that footgun. Same reason for the other DB_* lookups in
# this block: any of them MIGHT start with `$` in some future
# rotation, and we don't want a deploy to silently break.
import os as _os
import urllib.parse as _urlparse

if not _os.environ.get('DATABASE_URL'):
    _db_password = _urlparse.quote(_os.environ['DB_PASSWORD'], safe='')
    _os.environ['DATABASE_URL'] = (
        f"postgres://{_os.environ['DB_USER']}"
        f":{_db_password}"
        f"@{_os.environ['DB_HOST']}:{_os.environ.get('DB_PORT', '5432')}"
        f"/{_os.environ['DB_NAME']}"
    )

DATABASES = {
    'default': env.db('DATABASE_URL'),
}


AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]


LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# Static-files configuration. WhiteNoise (prod.py) serves the
# collectstatic output via gunicorn so the admin/DRF browsable API
# work without an extra nginx layer. CloudFront caches in front.
STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

# Media-files configuration. Prod overrides STORAGES['default'] to
# S3-with-KMS (see settings/prod.py); these defaults serve dev uploads
# from the local filesystem so ImageField works without AWS creds.
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# ── Email ────────────────────────────────────────────────────────────
#
# Backend choice is per-environment (dev → filebased, prod → SES via
# django-ses). Defaults below are overridable so each environment can
# tighten them. See ADR 0012.

EMAIL_BACKEND = env(
    'EMAIL_BACKEND',
    default='django.core.mail.backends.filebased.EmailBackend',
)
EMAIL_FILE_PATH = env(
    'EMAIL_FILE_PATH',
    default=str(BASE_DIR / 'tmp' / 'emails'),
)
DEFAULT_FROM_EMAIL = env(
    'DEFAULT_FROM_EMAIL',
    default='Lumè CRM <noreply@dev.lumecrm.local>',
)

# ── Twilio (SMS) ────────────────────────────────────────────────────
#
# Set via env in prod. When TWILIO_ACCOUNT_SID + TWILIO_AUTH_TOKEN
# are both present, the marketing sender (apps.marketing.sender) hits
# the real Twilio API. Otherwise SMS routes to stub mode — SendLog
# rows still written but no API call.
#
# TWILIO_FROM_NUMBER is the originating phone (E.164 format, e.g.
# +18885551234 for a toll-free). Required when sending — Twilio
# rejects with 21603 if it's missing on a Messages.create call.
#
# TWILIO_STATUS_CALLBACK_URL is the absolute URL Twilio POSTs
# delivery / failure updates to. Lives under /api/marketing/twilio/
# status-callback/. Empty in dev to skip status callbacks.
#
# TWILIO_TEST_MODE flips to True for unit tests; the SDK uses the
# documented test SID/token pair that accepts requests but does NOT
# actually send (Twilio docs).
TWILIO_ACCOUNT_SID = env('TWILIO_ACCOUNT_SID', default='')
TWILIO_AUTH_TOKEN = env('TWILIO_AUTH_TOKEN', default='')
TWILIO_FROM_NUMBER = env('TWILIO_FROM_NUMBER', default='')
TWILIO_STATUS_CALLBACK_URL = env('TWILIO_STATUS_CALLBACK_URL', default='')
TWILIO_TEST_MODE = env.bool('TWILIO_TEST_MODE', default=False)

# ── AI SMS inbox (apps/ai_inbox) ─────────────────────────────────────
# Picks the LLM provider; valid values: 'bedrock' (default — AWS BAA
# covered, prod path) or 'anthropic' (direct API; cheaper + faster
# onboarding, NOT BAA-covered unless a separate Anthropic BAA is
# signed). See ADR 0032 + apps/ai_inbox/README.md.
AI_LLM_PROVIDER = env('AI_LLM_PROVIDER', default='bedrock')

# Bedrock provider settings.
BEDROCK_REGION = env('BEDROCK_REGION', default='us-east-1')
BEDROCK_CLAUDE_MODEL_ID = env(
    'BEDROCK_CLAUDE_MODEL_ID',
    default='us.anthropic.claude-sonnet-4-6',
)

# Direct-Anthropic provider settings. ANTHROPIC_API_KEY is empty in
# dev (the bedrock provider doesn't need it); in prod it's injected
# from AWS Secrets Manager via the ECS task def's `secrets` block.
ANTHROPIC_API_KEY = env('ANTHROPIC_API_KEY', default='')
ANTHROPIC_CLAUDE_MODEL_ID = env(
    'ANTHROPIC_CLAUDE_MODEL_ID',
    default='claude-sonnet-4-6',
)

# Public host the tokenized fill URLs resolve under. Used to build
# the absolute /sign/<token> link in emails. Dev: localhost:3000;
# prod: per-tenant subdomain (set via env).
PUBLIC_BASE_URL = env(
    'PUBLIC_BASE_URL',
    default='http://localhost:3000',
)

# ── Meta (Instagram + Facebook + WhatsApp) ─────────────────────────
#
# ADR 0027 wires Instagram Business DM ingestion. When all three of
# META_APP_ID / META_APP_SECRET / META_WEBHOOK_VERIFY_TOKEN are set,
# the integrations app flips the Instagram provider's `oauth_ready`
# flag to True and the OAuth flow lights up. Absent any of them, the
# Connect button surfaces the "awaiting approval" copy instead of
# attempting OAuth — safe to deploy without credentials.
#
# META_APP_ID / META_APP_SECRET come from the Meta App dashboard at
# developers.facebook.com once the App is created (see runbook).
#
# META_WEBHOOK_VERIFY_TOKEN is a random string WE choose — Meta echoes
# it back on the GET handshake so we know the subscription was
# configured through our dashboard, not via probing.
#
# META_OAUTH_REDIRECT_URI is the absolute URL Meta sends users back to
# after consent. MUST match what's registered in the Meta App's
# Facebook Login settings. Dev: localhost via the Next.js proxy; prod:
# `https://api.xn--lumcrm-5ua.com/api/integrations/meta/oauth/callback/`
# (xn--lumcrm-5ua.com is the IDN punycode form of lumècrm.com — the
# canonical ASCII representation Meta's dashboard expects).
#
# META_TEST_MODE flips signature verification off for unit tests
# (mirrors TWILIO_TEST_MODE).
META_APP_ID = env('META_APP_ID', default='')
META_APP_SECRET = env('META_APP_SECRET', default='')
META_WEBHOOK_VERIFY_TOKEN = env('META_WEBHOOK_VERIFY_TOKEN', default='')
META_OAUTH_REDIRECT_URI = env(
    'META_OAUTH_REDIRECT_URI',
    default='http://localhost:8000/api/integrations/meta/oauth/callback/',
)
META_TEST_MODE = env.bool('META_TEST_MODE', default=False)

# ── Stripe Billing (SaaS subscriptions) ────────────────────────────
#
# Self-serve pricing tiers + trial signup land in Phase 1. Two Stripe
# integrations are intentionally separate environments (different keys,
# different webhook secrets):
#
#   - Billing (this block) — how Lumè charges spas for the SaaS
#     subscription. Account is registered to **Voxtro LLC** (the legal
#     entity behind the Lumè product). Receipt + statement-descriptor
#     branding identify Voxtro LLC.
#
#   - Connect (separate `STRIPE_CONNECT_*` block, lands in Phase 2) —
#     how spas charge THEIR customers for treatments. Different account,
#     different secret, different webhook.
#
# When `STRIPE_SECRET_KEY` is empty (dev without Stripe access),
# `apps.billing.services.is_configured()` returns False and every
# billing endpoint returns a clear 503 instead of crashing. Tests
# mock the stripe SDK directly; they don't need real keys.
#
# Stripe Price IDs are created in the dashboard (one Product per tier,
# two Prices per Product — monthly + annual). The IDs land in env vars
# so different deploy targets (staging vs prod) can point at different
# Stripe accounts without code changes.
STRIPE_SECRET_KEY = env('STRIPE_SECRET_KEY', default='')
STRIPE_PUBLISHABLE_KEY = env('STRIPE_PUBLISHABLE_KEY', default='')
STRIPE_WEBHOOK_SECRET = env('STRIPE_WEBHOOK_SECRET', default='')

# Per-tier Price IDs (see Stripe dashboard → Products). Format:
# STRIPE_PRICE_<plan>_<cycle>. Starter + Pro have public prices;
# Enterprise pricing is custom + manual so no STRIPE_PRICE_ENTERPRISE_*.
STRIPE_PRICE_STARTER_MONTHLY = env('STRIPE_PRICE_STARTER_MONTHLY', default='')
STRIPE_PRICE_STARTER_ANNUAL = env('STRIPE_PRICE_STARTER_ANNUAL', default='')
STRIPE_PRICE_PRO_MONTHLY = env('STRIPE_PRICE_PRO_MONTHLY', default='')
STRIPE_PRICE_PRO_ANNUAL = env('STRIPE_PRICE_PRO_ANNUAL', default='')

# Add-on Price IDs (quantity-based SubscriptionItems). Each is keyed
# by the canonical add-on identifier matching `Tenant.addon_quantities`.
STRIPE_PRICE_ADDON_STAFF = env('STRIPE_PRICE_ADDON_STAFF', default='')
STRIPE_PRICE_ADDON_LOCATION = env('STRIPE_PRICE_ADDON_LOCATION', default='')
STRIPE_PRICE_ADDON_EMAIL_5K = env('STRIPE_PRICE_ADDON_EMAIL_5K', default='')
STRIPE_PRICE_ADDON_EMAIL_10K = env('STRIPE_PRICE_ADDON_EMAIL_10K', default='')
STRIPE_PRICE_SMS_OVERAGE = env('STRIPE_PRICE_SMS_OVERAGE', default='')

# Legal / branding identity on Stripe Customer descriptions, BAA
# templates, and receipt footers. Voxtro LLC is the merchant of record
# for Lumè CRM; Lumè CRM is the product brand. Keep these distinct so
# we can rebrand the product without re-incorporating, and so receipt
# footers correctly identify the legal billing entity.
BILLING_LEGAL_NAME = env('BILLING_LEGAL_NAME', default='Voxtro LLC')
BILLING_PRODUCT_NAME = env('BILLING_PRODUCT_NAME', default='Lumè CRM')

# ── Stripe Connect (spa-customer card processing) ──────────────────
#
# Phase 2 — distinct integration from Stripe Billing above. Connect is
# how spas charge THEIR customers (treatments, products); Billing is
# how Lumè charges spas for the SaaS subscription. Same Stripe account
# (Voxtro LLC), different products, different webhook secrets.
#
# Architecture: Stripe Connect Platform with Express account type
# (see ADR queued at docs/decisions/). Each spa gets their own Express
# account on Lumè's platform. Onboarding is Stripe-hosted (KYC + bank
# verification); spas get an Express Dashboard for refunds + payouts.
#
# When STRIPE_SECRET_KEY is set, Connect calls reuse it — Connect uses
# the SAME platform secret key as Billing. The only Connect-specific
# secret is the WEBHOOK signing secret (different webhook endpoint,
# different signing secret). Same env-var hygiene as Billing: empty
# defaults so the system stays gracefully disabled until configured.
#
# STRIPE_CONNECT_RETURN_URL is where Stripe sends the spa after they
# complete (or skip) the hosted onboarding flow. Use a tenant-aware
# URL so each tenant lands back on their own /org/payments page.
STRIPE_CONNECT_WEBHOOK_SECRET = env(
    'STRIPE_CONNECT_WEBHOOK_SECRET', default='',
)
# Two URLs Stripe needs for the Express AccountLink flow:
#   - return_url: where to send the spa after they finish onboarding
#   - refresh_url: where to send them if the time-limited link expires
# We format them per-tenant at link-create time using these templates;
# `{tenant_slug}` gets substituted by `services.create_onboarding_link`.
STRIPE_CONNECT_RETURN_URL_TEMPLATE = env(
    'STRIPE_CONNECT_RETURN_URL_TEMPLATE',
    default='https://{tenant_slug}.xn--lumcrm-5ua.com/org/payments?onboarded=1',
)
STRIPE_CONNECT_REFRESH_URL_TEMPLATE = env(
    'STRIPE_CONNECT_REFRESH_URL_TEMPLATE',
    default='https://{tenant_slug}.xn--lumcrm-5ua.com/org/payments?refresh=1',
)

# ── Instagram Business Login ───────────────────────────────────────
#
# The Instagram product configured inside the Meta App has its OWN
# App ID + Secret, distinct from the parent Meta App credentials
# above. Used for the IG-only OAuth flow (ADR 0027 revision 2) that
# authenticates the spa directly via Instagram, no Facebook account
# or Page required. Meta App admins find these under:
#   Meta App dashboard → Instagram → Settings → 'Instagram App ID' / 'Instagram App Secret'
#
# The webhook secret (META_WEBHOOK_VERIFY_TOKEN) is shared across
# both Instagram + future Facebook Messenger paths because the Meta
# App has a single webhook configuration covering all subscribed
# products.
INSTAGRAM_APP_ID = env('INSTAGRAM_APP_ID', default='')
INSTAGRAM_APP_SECRET = env('INSTAGRAM_APP_SECRET', default='')

# ── Integration token encryption ────────────────────────────────────
#
# Field-level encryption for OAuth tokens stored on Connection rows.
# Generate with:
#   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
#
# Dev: a deterministic key in .env is fine (dev encrypts no real tokens).
# Prod: rotate from Secrets Manager. Multi-key rotation supported via
# INTEGRATIONS_FERNET_KEYS (a comma-separated list overrides the singular).
INTEGRATIONS_FERNET_KEY = env(
    'INTEGRATIONS_FERNET_KEY',
    default='',  # ImproperlyConfigured at first use if blank in prod
)
INTEGRATIONS_FERNET_KEYS = env.list(
    'INTEGRATIONS_FERNET_KEYS',
    default=[],
)
