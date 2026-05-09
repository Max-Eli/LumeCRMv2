"""
Production settings — AWS Fargate behind ALB + CloudFront, RDS Postgres,
SES email, structured JSON logging to CloudWatch.

Every override here is justified by either a HIPAA technical safeguard
or operational reality at the deployment shape. Don't add things to
this file because they "feel safer" — every line is auditable in a SOC
2 review and unexplained options are work for our future selves.

Required environment variables (set by ECS task def from Secrets
Manager — see PROJECT_PLAN.md §4 Phase 0c.5 runbook):

    SECRET_KEY              Django secret. 50+ random bytes.
    ALLOWED_HOSTS           Comma-separated (e.g. 'api.lumecrm.com').
    DATABASE_URL            postgres://user:pw@host:5432/dbname
    PUBLIC_BASE_URL         https://app.lumecrm.com (no trailing slash)
    DEFAULT_FROM_EMAIL      'Lumè CRM <noreply@mail.lumecrm.com>'
    AWS_REGION              us-east-1 (for SES, S3, Secrets Manager)
    AWS_STORAGE_BUCKET_NAME PHI / media bucket name
    AWS_S3_KMS_KEY_ID       Customer-managed KMS key alias for SSE-KMS

Optional:

    CSRF_TRUSTED_ORIGINS    Comma-separated (defaults to ALLOWED_HOSTS
                            with https:// prefix; override only for
                            the multi-domain case).
    SESSION_COOKIE_DOMAIN   `.lumecrm.com` if cookies need to span
                            subdomains (the wildcard tenant pattern).
"""

import os

from .base import *  # noqa: F401, F403
from .base import env

# Prod requires DEBUG off — the env var must be `0` (or unset, which
# defaults to False in base.py). Surface a misconfiguration loudly so
# we don't leak stack traces to the world.
if env('DEBUG'):
    raise RuntimeError(
        'lume_crm.settings.prod loaded with DEBUG=1. Refusing to start.'
    )

DEBUG = False

# ── Trusted origins / hosts ─────────────────────────────────────────
#
# ALLOWED_HOSTS comes from env (no defaults — explicit allowlist).
# CSRF needs `https://` URLs for the trusted origins; we let the env
# control this so multi-domain rollouts (api.lumecrm.com plus the
# wildcard *.lumecrm.com tenant pattern) are configurable without
# code changes.

CSRF_TRUSTED_ORIGINS = env.list(
    'CSRF_TRUSTED_ORIGINS',
    default=[f'https://{h}' for h in ALLOWED_HOSTS],  # noqa: F405
)

# CORS for the production frontend. Same rationale as CSRF_TRUSTED_ORIGINS.
CORS_ALLOWED_ORIGINS = env.list(
    'CORS_ALLOWED_ORIGINS',
    default=[f'https://{h}' for h in ALLOWED_HOSTS],  # noqa: F405
)
# Wildcard subdomain match for the per-tenant URLs. CORS by regex so
# every spa subdomain works without a redeploy when we onboard one.
# Pattern intentionally matches *.lumecrm.com only (production apex).
CORS_ALLOWED_ORIGIN_REGEXES = env.list(
    'CORS_ALLOWED_ORIGIN_REGEXES',
    default=[r'^https://[a-z0-9-]+\.lumecrm\.com$'],
)

# ── ALB / proxy hardening ───────────────────────────────────────────
#
# Fargate sits behind ALB which terminates TLS. Django needs to be
# told to trust the X-Forwarded-Proto header so `request.is_secure()`
# returns True for HTTPS-via-ALB requests — without this, redirects
# from HTTP→HTTPS loop forever.

SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# USE_X_FORWARDED_HOST: ALB rewrites Host; Django must respect that.
USE_X_FORWARDED_HOST = True
USE_X_FORWARDED_PORT = True

# ── HTTPS / cookies — HIPAA technical safeguards ────────────────────
#
# Every cookie that isn't already HttpOnly + Secure is a phishing /
# session-hijack vector. The session-cookie age caps at 8 hours so a
# stolen laptop can't authenticate indefinitely; an idle gap of 15
# minutes also kills it (configured in middleware — see
# apps.users.middleware.IdleSessionTimeoutMiddleware, Phase 0c).

SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
# CSRF_COOKIE_HTTPONLY MUST be False -- the SPA reads the CSRF token
# value from `document.cookie` and echoes it in `X-CSRFToken` header
# on every state-changing request. That round-trip IS the CSRF
# protection. The token itself isn't a secret (it's a per-session
# random nonce); the SECURITY comes from a forged cross-origin POST
# being unable to read the token without same-origin DOM access.
# Setting this to True silently breaks every login + form submission.
CSRF_COOKIE_HTTPONLY = False
# 8-hour max session lifetime; the idle-timeout middleware applies a
# 15-minute idle cap independently.
SESSION_COOKIE_AGE = 8 * 60 * 60
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
# SameSite=Lax is the standard default. Strict breaks legitimate
# cross-subdomain navigation (tenant subdomain → API subdomain).
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SAMESITE = 'Lax'

# Cross-subdomain cookies (the tenant wildcard pattern). Must be a
# leading-dot domain; the env injects the actual zone so non-prod
# environments can stay on a different apex.
SESSION_COOKIE_DOMAIN = env('SESSION_COOKIE_DOMAIN', default=None)
CSRF_COOKIE_DOMAIN = env('CSRF_COOKIE_DOMAIN', default=SESSION_COOKIE_DOMAIN)

# HSTS: tell browsers to refuse HTTP for our zone for a year. Include
# subdomains so the per-tenant URLs can't be downgraded. Only enable
# `preload` if/when we explicitly submit to hstspreload.org.
SECURE_HSTS_SECONDS = 60 * 60 * 24 * 365
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = False

# Browser-level hardening. Content-type sniffing, referrer policy,
# clickjacking are pre-set by Django's SecurityMiddleware once these
# are on. CSP is custom — see SecurityHeadersMiddleware (Phase 0c).
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'same-origin'
X_FRAME_OPTIONS = 'DENY'

# Force HTTPS at the app layer too -- ALB usually does this, but the
# defense-in-depth posture says don't trust a single layer. With
# SECURE_PROXY_SSL_HEADER set, this redirects HTTP requests that
# somehow bypass ALB.
SECURE_SSL_REDIRECT = True

# Exempt healthcheck paths from the HTTPS redirect. ALB sends health
# check requests over HTTP directly to the task IP (no X-Forwarded-Proto
# header), and Django would return 301 for HTTP to HTTPS, which the
# ALB target group reads as "unhealthy" (response code mismatch). Since
# these endpoints don't expose any sensitive data, an HTTP 200 response
# is fine.
SECURE_REDIRECT_EXEMPT = [
    r'^healthz/?$',
    r'^healthz/live/?$',
]

# ── Static files (WhiteNoise) ───────────────────────────────────────
#
# WhiteNoise serves collectstatic output from inside gunicorn. We
# *also* push these files to CloudFront via the deploy pipeline; the
# WhiteNoise layer is the fallback + admin/DRF-browsable safety net.

# Insert WhiteNoise immediately after SecurityMiddleware, then
# SecurityHeadersMiddleware right after WhiteNoise. The middleware
# order matters for response headers: WhiteNoise short-circuits some
# responses (static assets) and we need security headers on those
# too, so SecurityHeaders sits AFTER WhiteNoise in the request order
# (= BEFORE in response order, because middleware runs in reverse on
# the way out — Django wraps responses inside-out).
#
# `list(...)` first so we don't mutate the shared list defined in
# base.py — that would silently leak prod middleware into other
# settings modules in the same Python process (tests, dev shell).
_middleware_with_security = list(MIDDLEWARE)  # noqa: F405
_security_idx = _middleware_with_security.index('django.middleware.security.SecurityMiddleware')
_middleware_with_security.insert(_security_idx + 1, 'whitenoise.middleware.WhiteNoiseMiddleware')
_middleware_with_security.insert(_security_idx + 2, 'lume_crm.security_headers.SecurityHeadersMiddleware')
MIDDLEWARE = _middleware_with_security
STORAGES = {
    'default': {
        # Media (PHI uploads) → S3 with SSE-KMS.
        'BACKEND': 'storages.backends.s3.S3Storage',
        'OPTIONS': {
            'bucket_name': env('AWS_STORAGE_BUCKET_NAME'),
            'region_name': env('AWS_REGION', default='us-east-1'),
            'default_acl': None,                            # block ACLs
            'querystring_auth': True,                       # signed URLs
            'querystring_expire': 600,                      # 10 minutes
            'object_parameters': {
                'ServerSideEncryption': 'aws:kms',
                'SSEKMSKeyId': env('AWS_S3_KMS_KEY_ID'),
            },
        },
    },
    'staticfiles': {
        'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage',
    },
}

# ── Email (SES) ─────────────────────────────────────────────────────
#
# django-ses uses boto3, which picks up credentials from the ECS task
# IAM role automatically. No API keys in env.

EMAIL_BACKEND = 'django_ses.SESBackend'
AWS_SES_REGION_NAME = env('AWS_SES_REGION', default=env('AWS_REGION', default='us-east-1'))
AWS_SES_REGION_ENDPOINT = f'email.{AWS_SES_REGION_NAME}.amazonaws.com'
# Required by base.py — must be the verified-sender address in SES.
DEFAULT_FROM_EMAIL = env('DEFAULT_FROM_EMAIL')

# ── Logging — JSON to stdout, scrubbed of PHI ───────────────────────
#
# CloudWatch agent on Fargate ingests stdout/stderr verbatim. We emit
# JSON so CloudWatch Insights queries don't have to parse free-form
# text. PHIScrubFilter is in lume_crm/logging.py — masks email,
# phone, DOB-shaped values, and structured PHI keys.

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'filters': {
        'phi_scrub': {
            '()': 'lume_crm.logging.PHIScrubFilter',
        },
    },
    'formatters': {
        'json': {
            '()': 'pythonjsonlogger.jsonlogger.JsonFormatter',
            'fmt': '%(asctime)s %(levelname)s %(name)s %(message)s',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'filters': ['phi_scrub'],
            'formatter': 'json',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': env('LOG_LEVEL', default='INFO'),
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
        # Quiet the gunicorn access log down to WARN — ALB already
        # logs every request to S3 (Phase 0c.3), so duplicating each
        # line in CloudWatch is just storage cost.
        'gunicorn.access': {
            'handlers': ['console'],
            'level': 'WARNING',
            'propagate': False,
        },
        'gunicorn.error': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}

# ── Database — RDS Postgres ──────────────────────────────────────────
#
# DATABASE_URL from base.py is honored; we only annotate connection
# options here. SSL is enforced by RDS parameter group, but we set
# it client-side too as defense in depth. CONN_MAX_AGE keeps a small
# pool warm per worker — Fargate task = 1 process = 1 pool.

DATABASES['default']['CONN_MAX_AGE'] = 60  # noqa: F405
DATABASES['default']['CONN_HEALTH_CHECKS'] = True  # noqa: F405
DATABASES['default'].setdefault('OPTIONS', {})  # noqa: F405
DATABASES['default']['OPTIONS']['sslmode'] = 'require'  # noqa: F405

# ── django-otp (MFA) ─────────────────────────────────────────────────
#
# Phase 0c v1: TOTP-only (Google Authenticator / 1Password / Authy).
# SMS / Push are out of scope until Cognito migration. The MFA
# enrollment + verification UI lives in apps.users.

INSTALLED_APPS = list(INSTALLED_APPS) + [  # noqa: F405
    'django_otp',
    'django_otp.plugins.otp_totp',
    'django_otp.plugins.otp_static',  # one-time recovery codes
]

# OTPMiddleware decorates `request.user.is_verified()`; the actual
# enforcement happens in apps.users.middleware.RequireMFAMiddleware
# (which checks both that the user has a confirmed device AND that
# they're verified for the current session).
#
# IdleSessionTimeoutMiddleware enforces HIPAA §164.312(a)(2)(iii) —
# 15-min idle cap. Sits AFTER auth so it has a populated request.user.
_middleware_with_otp = list(MIDDLEWARE)
_auth_idx = _middleware_with_otp.index('django.contrib.auth.middleware.AuthenticationMiddleware')
_middleware_with_otp.insert(_auth_idx + 1, 'django_otp.middleware.OTPMiddleware')
_middleware_with_otp.insert(_auth_idx + 2, 'apps.users.middleware.IdleSessionTimeoutMiddleware')
MIDDLEWARE = _middleware_with_otp

IDLE_SESSION_TIMEOUT_SECONDS = env.int('IDLE_SESSION_TIMEOUT_SECONDS', default=15 * 60)
