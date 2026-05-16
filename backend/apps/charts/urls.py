"""URL routing for chart notes + treatment records.

Mounted at `/api/`. Routes:

    GET    /api/chart-notes/?customer=<id>            List
    POST   /api/chart-notes/                          Sign a new note
    GET    /api/chart-notes/<id>/                     Retrieve one
    PATCH  /api/chart-notes/<id>/                     Edit (within window)
    POST   /api/chart-notes/<id>/addendum/            New addendum
    POST   /api/chart-notes/<id>/void/                Void

    GET    /api/treatment-record-templates/           List templates
    POST   /api/treatment-record-templates/           Create template
    GET    /api/treatment-record-templates/<id>/      Retrieve
    PATCH  /api/treatment-record-templates/<id>/      Update (auto-bumps version)
    DELETE /api/treatment-record-templates/<id>/      Delete (only when no records reference)

    GET    /api/treatment-records/?customer=<id>      List records
    POST   /api/treatment-records/                    Sign a new record
    GET    /api/treatment-records/<id>/               Retrieve one
    PATCH  /api/treatment-records/<id>/               Edit answers (within window)
    POST   /api/treatment-records/<id>/addendum/      New addendum
    POST   /api/treatment-records/<id>/void/          Void
"""

from rest_framework.routers import DefaultRouter

from .views import (
    ChartNoteViewSet,
    TreatmentRecordTemplateViewSet,
    TreatmentRecordViewSet,
)

router = DefaultRouter()
router.register(r'chart-notes', ChartNoteViewSet, basename='chart-note')
router.register(
    r'treatment-record-templates',
    TreatmentRecordTemplateViewSet,
    basename='treatment-record-template',
)
router.register(
    r'treatment-records',
    TreatmentRecordViewSet,
    basename='treatment-record',
)

urlpatterns = router.urls
