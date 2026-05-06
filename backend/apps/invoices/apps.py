from django.apps import AppConfig


class InvoicesConfig(AppConfig):
    """Invoices — billing records that gate appointment completion.

    Wires the `apps.invoices.signals` module on ready so the
    appointment-created → invoice-created hook is registered exactly once
    per process. See ADR 0007 for the rationale.
    """

    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.invoices'
    label = 'invoices'

    def ready(self):
        # Import for signal-handler side effects only.
        from . import signals  # noqa: F401
