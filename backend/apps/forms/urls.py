from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import FormSubmissionViewSet, FormTemplateViewSet, PublicFormSignView

router = DefaultRouter()
router.register('form-templates', FormTemplateViewSet, basename='form-template')
router.register('form-submissions', FormSubmissionViewSet, basename='form-submission')

urlpatterns = [
    # Public unauthenticated fill flow. Token in path (NOT query
    # string) — see ADR 0011 for the rationale (audit, log hygiene).
    path('forms/sign/<str:token>/', PublicFormSignView.as_view(), name='public-form-sign'),
    *router.urls,
]
