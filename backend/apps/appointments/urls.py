from rest_framework.routers import DefaultRouter

from .views import AppointmentViewSet, TimeBlockViewSet

router = DefaultRouter()
router.register('appointments', AppointmentViewSet, basename='appointment')
router.register(
    'time-blocks', TimeBlockViewSet, basename='time-block',
)

urlpatterns = router.urls
