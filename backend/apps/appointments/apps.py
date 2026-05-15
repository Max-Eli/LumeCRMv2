from django.apps import AppConfig


class AppointmentsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.appointments'
    label = 'appointments'

    def ready(self):
        # Wire the post_save handler that fires transactional
        # SMS confirmation on appointment create. Import-on-ready
        # is the Django-recommended way to register signals — keeps
        # them out of the import graph until app loading is complete.
        from . import signals  # noqa: F401
