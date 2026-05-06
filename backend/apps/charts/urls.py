"""URL routing for chart notes.

Mounted at `/api/`. Routes:

    GET    /api/chart-notes/?customer=<id>     List
    POST   /api/chart-notes/                   Sign a new note
    GET    /api/chart-notes/<id>/              Retrieve one
    PATCH  /api/chart-notes/<id>/              Edit (within window)
"""

from rest_framework.routers import DefaultRouter

from .views import ChartNoteViewSet

router = DefaultRouter()
router.register(r'chart-notes', ChartNoteViewSet, basename='chart-note')

urlpatterns = router.urls
