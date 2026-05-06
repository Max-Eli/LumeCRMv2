from django.apps import AppConfig


class ReportsConfig(AppConfig):
    """Reports — categorized aggregations over OLTP tables (ADR 0013).

    No models of its own. Each report is an `APIView` subclass under
    `apps.reports.views` and registers itself with the catalog by
    being added to `urls.py` + `catalog.REPORT_REGISTRY`.
    """

    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.reports'
    label = 'reports'
