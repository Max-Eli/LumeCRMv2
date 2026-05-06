from django.apps import AppConfig


class WaitlistConfig(AppConfig):
    """Waitlist for the public booking surface.

    When a customer hits a fully-booked day on the booking page, they
    can opt in to a waitlist instead of bouncing. The entry captures
    what they wanted (service, location, optional provider, date) so
    the operator can manually reach out when something opens up.

    v1 is intentionally manual: no auto-notify when slots free up,
    no SMS scheduling, no Celery. The operator sees the list in the
    calendar's Waitlist tool panel and calls / texts the customer
    directly. Auto-notify lands when 1F (SMS reminders) ships.

    HIPAA framing: a waitlist entry is PHI-adjacent — it ties identity
    to a treatment intent. Same posture as `apps.booking`: audit-log
    every public action, no PHI in audit metadata, tenant-scoped at
    every layer.
    """

    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.waitlist'
    label = 'waitlist'
