from django.apps import AppConfig


class ImportsConfig(AppConfig):
    """Data-migration tooling — currently houses the Zenoti importer.

    The app is deliberately generic ("imports") rather than vendor-
    specific because we expect to add Vagaro / Mindbody / Boulevard
    importers as we onboard tenants migrating from other systems.
    Each vendor lives in its own submodule (`apps.imports.zenoti`,
    etc.); shared pieces (the `ImportRun` audit row, the dry-run
    framework) live at the app level.
    """

    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.imports'
    label = 'imports'
