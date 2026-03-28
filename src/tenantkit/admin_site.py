from __future__ import annotations

from django.contrib.admin import AdminSite
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import path, reverse

from tenantkit.core.context import get_current_tenant
from tenantkit.models import Tenant


SESSION_ACTIVE_TENANT_ID = "active_tenant_id"
SESSION_AUTH_SCOPE = "auth_scope"
AUTH_SCOPE_GLOBAL = "global"
AUTH_SCOPE_TENANT = "tenant"


class TenantkitAdminSite(AdminSite):
    site_header = "django-tenantkit"
    site_title = "django-tenantkit admin"
    index_title = "Administration"

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "tenant-switch/",
                self.admin_view(self.tenant_switch_view),
                name="tenant-switch",
            ),
        ]
        return custom_urls + urls

    def _available_tenants(self):
        return Tenant.objects.filter(is_active=True, deleted_at__isnull=True).order_by(
            "name"
        )

    def _current_tenant_from_session(self, request: HttpRequest):
        session = getattr(request, "session", None)
        if session is None:
            return None

        tenant_id = session.get(SESSION_ACTIVE_TENANT_ID)
        if not tenant_id:
            return None
        return Tenant.objects.filter(
            pk=tenant_id, is_active=True, deleted_at__isnull=True
        ).first()

    def tenant_switch_view(self, request: HttpRequest) -> HttpResponse:
        if request.method == "POST":
            session = getattr(request, "session", None)
            if session is None:
                return redirect(reverse("admin:index"))

            target = request.POST.get("tenant", "")
            if target in {"", AUTH_SCOPE_GLOBAL}:
                session.pop(SESSION_ACTIVE_TENANT_ID, None)
                session[SESSION_AUTH_SCOPE] = AUTH_SCOPE_GLOBAL
            else:
                tenant = Tenant.objects.filter(
                    pk=target, is_active=True, deleted_at__isnull=True
                ).first()
                if tenant is None:
                    context = self._switch_context(request, error="Tenant not found")
                    return render(request, "admin/tenant_switch.html", context)
                session[SESSION_ACTIVE_TENANT_ID] = str(tenant.pk)
                session[SESSION_AUTH_SCOPE] = AUTH_SCOPE_TENANT

            session.modified = True
            return redirect(reverse("admin:index"))

        return render(
            request, "admin/tenant_switch.html", self._switch_context(request)
        )

    def _switch_context(
        self, request: HttpRequest, error: str | None = None
    ) -> dict[str, object]:
        current_tenant = self._current_tenant_from_session(request)
        return {
            **self.each_context(request),
            "current_tenant": current_tenant,
            "available_tenants": self._available_tenants(),
            "error": error,
            "auth_scope_global": AUTH_SCOPE_GLOBAL,
            "auth_scope_tenant": AUTH_SCOPE_TENANT,
        }

    def each_context(self, request: HttpRequest) -> dict[str, object]:
        context = super().each_context(request)
        current_tenant = get_current_tenant() or self._current_tenant_from_session(
            request
        )
        available_tenants = self._available_tenants()
        context.update(
            {
                "current_tenant": current_tenant,
                "current_tenant_label": current_tenant.name if current_tenant else None,
                "tenant_switch_url": reverse("admin:tenant-switch"),
                "tenant_scope_label": "Tenant"
                if current_tenant
                else "Default / Global",
                "available_tenants": available_tenants,
            }
        )
        return context


tenantkit_admin_site = TenantkitAdminSite(name="tenantkit_admin")
