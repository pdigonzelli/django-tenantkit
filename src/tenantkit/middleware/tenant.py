from __future__ import annotations

from typing import Any, cast

from django.http import HttpRequest, HttpResponse
from django.utils.deprecation import MiddlewareMixin

from tenantkit.admin_site import (
    AUTH_SCOPE_TENANT,
    SESSION_ACTIVE_TENANT_ID,
    SESSION_AUTH_SCOPE,
)
from tenantkit.bootstrap import register_database_tenant_connection
from tenantkit.core.context import (
    clear_current_strategy,
    clear_current_tenant,
    set_current_strategy,
    set_current_tenant,
)
from tenantkit.models import Tenant
from tenantkit.strategies.database.strategy import DatabaseStrategy
from tenantkit.strategies.schema.strategy import SchemaStrategy


class TenantMiddleware(MiddlewareMixin):
    """Resolves the tenant from the request and activates its strategy."""

    header_name = "HTTP_X_TENANT"

    def __init__(self, get_response):
        super().__init__(get_response)
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        tenant = self.resolve_tenant(request)
        strategy = self.resolve_strategy(tenant)

        try:
            if tenant is not None and strategy is not None:
                set_current_tenant(tenant)
                set_current_strategy(strategy)
                strategy.activate(tenant)

            cast_request = cast(Any, request)
            cast_request.tenant = tenant
            cast_request.tenant_strategy = strategy

            return self.get_response(request)
        finally:
            if strategy is not None:
                strategy.deactivate()

            clear_current_strategy()
            clear_current_tenant()

    def resolve_tenant(self, request: HttpRequest) -> Tenant | None:
        # First, try to resolve from session (for web UI with tenant login)
        tenant = self.resolve_tenant_from_session(request)
        if tenant:
            return tenant

        # If no tenant in session, try X-Tenant header (for API calls)
        slug = request.META.get(self.header_name)
        if slug:
            try:
                return Tenant.objects.get(slug=slug)
            except Tenant.DoesNotExist:  # type: ignore[attr-defined]
                return None

        return None

    def resolve_tenant_from_session(self, request: HttpRequest) -> Tenant | None:
        session = getattr(request, "session", None)
        if session is None or session.get(SESSION_AUTH_SCOPE) != AUTH_SCOPE_TENANT:
            return None

        tenant_id = session.get(SESSION_ACTIVE_TENANT_ID)
        if not tenant_id:
            return None

        try:
            return Tenant.objects.get(
                pk=tenant_id, is_active=True, deleted_at__isnull=True
            )
        except Tenant.DoesNotExist:  # type: ignore[attr-defined]
            return None

    def resolve_strategy(self, tenant: Tenant | None) -> Any | None:
        if tenant is None:
            return None

        if tenant.isolation_mode == Tenant.IsolationMode.SCHEMA:
            return SchemaStrategy()

        if tenant.isolation_mode == Tenant.IsolationMode.DATABASE:
            register_database_tenant_connection(tenant)
            return DatabaseStrategy()

        return None
