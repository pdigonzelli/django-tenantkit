from __future__ import annotations

from typing import cast

from django.db import connections
from django.db.utils import OperationalError, ProgrammingError

from multitenant.connections import parse_connection_url
from multitenant.models import Tenant


def register_database_tenant_connection(tenant: Tenant) -> bool:
    """Register a single database-tenant connection in Django's registry."""

    if tenant.isolation_mode != Tenant.IsolationMode.DATABASE:
        return False

    alias = str(tenant.connection_alias or "")
    connection_string = tenant.get_connection_string()
    if not alias or not connection_string:
        return False

    databases = cast(dict[str, dict[str, object]], connections.databases)
    if alias in databases:
        try:
            connections[alias].close()
        except Exception:  # pragma: no cover - best effort cleanup
            pass
    databases[alias] = parse_connection_url(connection_string)
    return True


def unregister_database_tenant_connection(alias: str | None) -> bool:
    """Remove a database-tenant connection from Django's registry."""

    if not alias:
        return False

    databases = cast(dict[str, dict[str, object]], connections.databases)
    if alias in databases:
        try:
            connections[alias].close()
        except Exception:  # pragma: no cover - best effort cleanup
            pass
    return databases.pop(alias, None) is not None


def register_database_tenant_connections() -> int:
    """Register all database-tenant connections in Django's connection registry."""

    try:
        tenants = Tenant.all_objects.filter(
            isolation_mode=Tenant.IsolationMode.DATABASE,
            is_active=True,
            deleted_at__isnull=True,
        )
    except (OperationalError, ProgrammingError):
        return 0

    registered = 0
    for tenant in tenants:
        if register_database_tenant_connection(tenant):
            registered += 1

    return registered
