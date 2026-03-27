from __future__ import annotations

from typing import Any

from multitenant.backends.postgresql.base import activate_schema, deactivate_schema
from multitenant.core.strategy import TenantStrategy


class SchemaStrategy(TenantStrategy):
    """Schema isolation strategy for PostgreSQL-backed tenants."""

    def activate(self, tenant: Any) -> None:
        schema_name = getattr(tenant, "schema_name", None)
        activate_schema(schema_name)

    def deactivate(self) -> None:
        deactivate_schema()

    def db_for_read(self, model: Any, **hints: Any) -> str | None:
        return "default"

    def db_for_write(self, model: Any, **hints: Any) -> str | None:
        return "default"

    def allow_migrate(
        self, db: str, app_label: str, model_name: str | None = None, **hints: Any
    ) -> bool | None:
        return None
