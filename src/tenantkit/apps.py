from django.apps import AppConfig
from django.conf import settings


class TenantkitConfig(AppConfig):
    name = "tenantkit"
    label = "tenantkit"

    def ready(self):
        if (
            settings.DATABASES.get("default", {}).get("ENGINE")
            == "django.db.backends.sqlite3"
        ):
            return

        from .bootstrap import register_database_tenant_connections

        register_database_tenant_connections()
