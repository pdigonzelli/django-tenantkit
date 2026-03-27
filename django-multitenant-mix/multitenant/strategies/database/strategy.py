from __future__ import annotations

from typing import Any

from multitenant.core.context import get_current_tenant
from multitenant.core.strategy import TenantStrategy


class DatabaseStrategy(TenantStrategy):
    """Database isolation strategy based on a tenant connection alias."""

    def activate(self, tenant: Any) -> None:
        return None

    def deactivate(self) -> None:
        return None

    def _resolve_tenant(self, hints: dict[str, Any]) -> Any | None:
        if "tenant" in hints:
            return hints["tenant"]
        return get_current_tenant()

    def _resolve_database_alias(self, tenant: Any | None) -> str:
        alias = (
            getattr(tenant, "connection_alias", None) if tenant is not None else None
        )
        if not alias:
            metadata = getattr(tenant, "metadata", {}) if tenant is not None else {}
            database_config = (
                metadata.get("database", {}) if isinstance(metadata, dict) else {}
            )
            alias = database_config.get("alias")
        return alias or "default"

    def db_for_read(self, model: Any, **hints: Any) -> str | None:
        tenant = self._resolve_tenant(hints)
        return self._resolve_database_alias(tenant)

    def db_for_write(self, model: Any, **hints: Any) -> str | None:
        tenant = self._resolve_tenant(hints)
        return self._resolve_database_alias(tenant)

    def allow_migrate(
        self, db: str, app_label: str, model_name: str | None = None, **hints: Any
    ) -> bool | None:
        return None
