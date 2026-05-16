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


# DRF defaults: session-cookie auth, require auth by default. Endpoints
# that should be public (login, csrf) opt into AllowAny explicitly.
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.SessionAuthentication',
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
    },
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
