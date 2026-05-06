from django.apps import AppConfig


class BookingConfig(AppConfig):
    """Public-facing online booking surface — no auth required.

    Endpoints under `/api/booking/<tenant_slug>/` let unauthenticated
    customers browse the spa's services, see real-time availability,
    and book an appointment. Each booking auto-creates a Customer (or
    matches an existing one), an Appointment with `source='online'`,
    a one-time `booking_token` for the confirmation email's manage
    link, an Invoice (via the existing post_save signal), and any
    forms required by the service (via apps.forms.services).

    No models of its own — operates against the existing
    Service / Provider / Customer / Appointment models. The
    availability calculator is the only meaningful new logic.
    """

    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.booking'
    label = 'booking'
