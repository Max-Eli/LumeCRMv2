"""
URL configuration for lume_crm project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView

from apps.tenants.public_views import public_signup
from lume_crm.health import liveness, readiness

urlpatterns = [
    # Liveness + readiness — ECS uses /healthz/live, ALB uses /healthz.
    # Order: registered before any catch-all so they always resolve.
    path('healthz', readiness, name='healthz-readiness'),
    path('healthz/live', liveness, name='healthz-liveness'),

    path('admin/', admin.site.urls),
    path('api/auth/', include('apps.users.urls')),
    path('api/', include('apps.tenants.urls')),
    path('api/', include('apps.customers.urls')),
    path('api/', include('apps.services.urls')),
    path('api/', include('apps.appointments.urls')),
    path('api/', include('apps.invoices.urls')),
    path('api/', include('apps.forms.urls')),
    path('api/', include('apps.reports.urls')),
    path('api/', include('apps.platform.urls')),
    path('api/', include('apps.integrations.urls')),
    path('api/', include('apps.booking.urls')),
    path('api/', include('apps.waitlist.urls')),
    path('api/', include('apps.charts.urls')),
    path('api/', include('apps.marketing.urls')),
    path('api/', include('apps.products.urls')),
    path('api/', include('apps.packages.urls')),
    path('api/', include('apps.memberships.urls')),
    path('api/', include('apps.giftcards.urls')),
    path('api/', include('apps.timetracking.urls')),
    path('api/', include('apps.commissions.urls')),
    path('api/', include('apps.messaging.urls')),
    path('api/', include('apps.portal.urls')),
    path('api/billing/', include('apps.billing.urls')),
    path('api/payments/', include('apps.payments.urls')),
    path('api/', include('apps.ai_inbox.urls')),

    # Public (unauthenticated) endpoints: self-serve signup, lead-
    # capture, etc. Throttled aggressively per-IP — see SignupThrottle.
    path('api/public/signup/', public_signup, name='public-signup'),

    # OpenAPI schema + Swagger UI
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
]

# Dev-only: serve user uploads (Service hero photos, etc.) from
# MEDIA_ROOT. In prod, STORAGES['default'] points at S3 and signed
# URLs bypass Django entirely — this line is a no-op there.
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
