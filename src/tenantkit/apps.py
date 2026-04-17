from django.apps import AppConfig
from django.conf import settings


class TenantkitConfig(AppConfig):
    name = "tenantkit"
    label = "tenantkit"

    def ready(self):
        from . import checks  # noqa: F401

        if (
            settings.DATABASES.get("default", {}).get("ENGINE")
            == "django.db.backends.sqlite3"
        ):
            return

        # Intentionally avoid querying the database during app initialization.
        # Database-tenant connections are registered lazily during provisioning
        # and explicit tenant operations.
        return None
