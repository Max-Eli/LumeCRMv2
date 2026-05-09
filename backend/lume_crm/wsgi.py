"""
WSGI config for lume_crm project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.1/howto/deployment/wsgi/
"""

import os

from django.core.wsgi import get_wsgi_application

# Default to prod for `gunicorn lume_crm.wsgi`; manage.py defaults to
# dev. Set DJANGO_SETTINGS_MODULE explicitly to override (tests do this).
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'lume_crm.settings.prod')

application = get_wsgi_application()
