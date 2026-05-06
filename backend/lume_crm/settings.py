"""
Django settings for lume_crm project.

Local-dev settings. Do not deploy this configuration to production as-is.
Sensitive values are loaded from a `.env` file in the backend/ directory.
"""

from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, []),
)
environ.Env.read_env(BASE_DIR / '.env')

SECRET_KEY = env('SECRET_KEY')
DEBUG = env('DEBUG')
ALLOWED_HOSTS = env('ALLOWED_HOSTS')


INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    'rest_framework',
    'corsheaders',
    'drf_spectacular',

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
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

# CORS — allow the Next.js dev server to call our API with credentials
CORS_ALLOWED_ORIGINS = [
    'http://localhost:3000',
    'http://127.0.0.1:3000',
]
CORS_ALLOW_CREDENTIALS = True

# Extend the default CORS allow-headers so the browser preflight accepts our
# custom tenant-slug header in dev (where subdomains aren't available).
from corsheaders.defaults import default_headers as _default_cors_headers
CORS_ALLOW_HEADERS = (*_default_cors_headers, 'x-tenant-slug')

# CSRF — trust the Next.js dev origin so DRF SessionAuthentication accepts CSRF tokens from it
CSRF_TRUSTED_ORIGINS = [
    'http://localhost:3000',
    'http://127.0.0.1:3000',
]

# DRF defaults: session-cookie auth, require auth by default. Endpoints that should
# be public (login, csrf) opt into AllowAny explicitly.
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.SessionAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',

    # Throttle rates for the public booking surface (apps.booking).
    # Counts live in Django's default cache (local-memory) — accurate
    # at single-instance scale. When we move to multi-process /
    # multi-instance hosting in Phase 0c, swap CACHES to Redis so
    # the counts are shared. Tests use settings overrides to disable
    # throttling per-class so retry-heavy specs aren't fragile.
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

STATIC_URL = 'static/'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# ── Email ────────────────────────────────────────────────────────────
#
# Dev: filebased backend writes each email to `backend/tmp/emails/`
# as a `.log` file. Way more reliable than the console backend —
# discoverable (just `ls` the directory), survives restarts, and
# doesn't depend on which terminal is open. View the latest with
# `cat $(ls -t backend/tmp/emails/*.log | head -1)`.
#
# Production: AWS SES via `django-ses` — see ADR 0012. Phase 0c
# wiring will set EMAIL_BACKEND=django_ses.SESBackend + the SES
# credentials via env. The choice of backend is the only thing that
# changes; templates + send code are identical.

EMAIL_BACKEND = env(
    'EMAIL_BACKEND',
    default='django.core.mail.backends.filebased.EmailBackend',
)
# Only relevant when EMAIL_BACKEND is filebased. Created on first
# send if it doesn't exist.
EMAIL_FILE_PATH = env(
    'EMAIL_FILE_PATH',
    default=str(BASE_DIR / 'tmp' / 'emails'),
)
DEFAULT_FROM_EMAIL = env(
    'DEFAULT_FROM_EMAIL',
    default='Lumè CRM <noreply@dev.lumecrm.local>',
)

# Public host the tokenized fill URLs resolve under. Used to build
# the absolute /sign/<token> link in emails. In dev: localhost:3000;
# in prod: per-tenant subdomain (set via env, Phase 0c).
PUBLIC_BASE_URL = env(
    'PUBLIC_BASE_URL',
    default='http://localhost:3000',
)
