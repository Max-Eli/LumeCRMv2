from rest_framework.routers import DefaultRouter

from django.urls import path

from .views import ServiceCategoryViewSet, ServiceProtocolView, ServiceViewSet

router = DefaultRouter()
router.register('services', ServiceViewSet, basename='service')
router.register('service-categories', ServiceCategoryViewSet, basename='service-category')

urlpatterns = [
    *router.urls,
    # Singleton clinical-protocol resource per service. GET returns
    # an empty-shaped payload when no protocol has been authored yet;
    # PUT / PATCH upsert.
    path(
        'services/<int:service_id>/protocol/',
        ServiceProtocolView.as_view(),
        name='service-protocol',
    ),
]
