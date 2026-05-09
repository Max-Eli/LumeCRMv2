"""
Settings package — environments split into siblings.

Pick the right one with `DJANGO_SETTINGS_MODULE`:

    lume_crm.settings.dev   — local development (DEBUG, file-based email)
    lume_crm.settings.prod  — production (gunicorn, AWS, hardened)

Importing this package directly is intentionally a no-op so a stale
`DJANGO_SETTINGS_MODULE=lume_crm.settings` from before the split fails
loudly with "no Django settings configured" instead of silently picking
the wrong environment. Update such references to `.dev` or `.prod`.
"""
