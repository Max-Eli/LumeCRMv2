"""
Development-environment settings.

The defaults baked into `base.py` already match dev (file-based email,
loose static-file handling); this file just adds the localhost-specific
CORS / CSRF allowlists and a sanity check that DEBUG is on.

Do NOT deploy this configuration. The `prod.py` sibling enforces every
HIPAA technical safeguard (TLS-only cookies, HSTS, scrubbed logs,
secret rotation) that this file deliberately leaves off so iteration is
fast.
"""

from .base import *  # noqa: F401, F403

# Sanity: dev is for dev. If somehow this file is loaded with DEBUG off
# in env, surface that as an error rather than a silently-broken UX.
# (Override via `DEBUG=1` in `.env`.)
import os as _os
if _os.environ.get('DEBUG') == '0':
    raise RuntimeError(
        'lume_crm.settings.dev loaded with DEBUG=0. '
        'Use lume_crm.settings.prod for production-like environments.'
    )

DEBUG = True

# Local frontends — Next.js CRM (3000), marketing site (3001).
CORS_ALLOWED_ORIGINS = [
    'http://localhost:3000',
    'http://127.0.0.1:3000',
    'http://localhost:3001',
    'http://127.0.0.1:3001',
]

# CSRF — trust the Next.js dev origin so DRF SessionAuthentication
# accepts CSRF tokens from it.
CSRF_TRUSTED_ORIGINS = [
    'http://localhost:3000',
    'http://127.0.0.1:3000',
]
