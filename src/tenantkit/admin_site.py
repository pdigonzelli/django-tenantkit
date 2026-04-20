from __future__ import annotations

from types import MethodType
from typing import Any, cast

from django import forms
from django.conf import settings
from django.contrib import admin
from django.contrib.admin import AdminSite
from django.contrib.admin.forms import AdminAuthenticationForm
from django.contrib.auth import REDIRECT_FIELD_NAME, get_user_model
from django.contrib.auth.decorators import login_not_required
from django.contrib.auth.views import LoginView
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import redirect, render
from django.urls import path, reverse
from django.utils.decorators import method_decorator
from django.utils.translation import gettext_lazy as _
from django.views.decorators.cache import never_cache

from tenantkit.bootstrap import register_database_tenant_connection
from tenantkit.core.context import (
    clear_current_strategy,
    clear_current_tenant,
    get_current_tenant,
    set_current_strategy,
    set_current_tenant,
)
from tenantkit.models import Tenant
from tenantkit.strategies.database.strategy import DatabaseStrategy
from tenantkit.strategies.schema.strategy import SchemaStrategy

SESSION_ACTIVE_TENANT_ID = "active_tenant_id"
SESSION_AUTH_SCOPE = "auth_scope"
AUTH_SCOPE_GLOBAL = "global"
AUTH_SCOPE_TENANT = "tenant"


def ensure_runtime_tenant_connection(tenant: Tenant) -> None:
    if tenant.isolation_mode == Tenant.IsolationMode.DATABASE:
        register_database_tenant_connection(tenant)


class TenantAdminAuthenticationForm(AdminAuthenticationForm):
    tenant = forms.ModelChoiceField(
        queryset=Tenant.objects.none(),
        required=False,
        label=_("Tenant"),
        empty_label=str(_("Default / Global")),
        help_text=str(_("Optional tenant selection for tenant-scoped admin login.")),
    )

    tenant_obj: Tenant | None = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].widget.attrs.update(
            {
                "autocomplete": "off",
                "autocapitalize": "none",
                "spellcheck": "false",
                "data-lpignore": "true",
                "data-1p-ignore": "true",
            }
        )
        self.fields["password"].widget.attrs.update(
            {
                "autocomplete": "current-password",
                "data-lpignore": "true",
                "data-1p-ignore": "true",
            }
        )
        self.fields["tenant"].queryset = Tenant.objects.filter(
            is_active=True,
            deleted_at__isnull=True,
        ).order_by("name")

    def clean(self):
        tenant = self.cleaned_data.get("tenant")
        if tenant is None:
            self.tenant_obj = None
            return super().clean()

        username = self.cleaned_data.get("username")
        password = self.cleaned_data.get("password")
        if username is None or not password:
            return self.cleaned_data

        user_model = get_user_model()
        
        # For SCHEMA tenants: temporarily set search_path to tenant schema
        # to find the user in the correct location
        from django.db import connection
        
        if tenant.isolation_mode == Tenant.IsolationMode.SCHEMA:
            schema_name = tenant.schema_name

            with connection.cursor() as cursor:
                # Capturar search_path actual de forma segura
                cursor.execute("SELECT pg_catalog.current_setting('search_path')")
                old_search_path = cursor.fetchone()[0]

                try:
                    # Setear search_path al tenant schema usando quote_ident para seguridad
                    cursor.execute(
                        """
                        SELECT pg_catalog.set_config(
                            'search_path',
                            pg_catalog.quote_ident(%s) || ', public',
                            false
                        )
                        """,
                        [schema_name],
                    )

                    # Lookup user en el tenant schema
                    try:
                        user = user_model._default_manager.get_by_natural_key(username)
                    except user_model.DoesNotExist:
                        raise self.get_invalid_login_error() from None

                    if not user.check_password(password):
                        raise self.get_invalid_login_error()

                    self.confirm_login_allowed(user)
                    user.backend = settings.AUTHENTICATION_BACKENDS[0]
                    self.user_cache = user

                finally:
                    # Restaurar search_path original de forma segura
                    cursor.execute(
                        "SELECT pg_catalog.set_config('search_path', %s, false)",
                        [old_search_path],
                    )
        
        elif tenant.isolation_mode == Tenant.IsolationMode.DATABASE:
            ensure_runtime_tenant_connection(tenant)
            strategy = DatabaseStrategy()
            database_alias = strategy.db_for_read(user_model, tenant=tenant) or "default"
            
            try:
                user = user_model._default_manager.db_manager(
                    database_alias
                ).get_by_natural_key(username)
            except user_model.DoesNotExist:
                raise self.get_invalid_login_error() from None

            if not user.check_password(password):
                raise self.get_invalid_login_error()

            self.confirm_login_allowed(user)
            user.backend = settings.AUTHENTICATION_BACKENDS[0]
            self.user_cache = user

        self.tenant_obj = tenant
        return self.cleaned_data


class TenantAdminLoginView(LoginView):
    def form_valid(self, form):
        response = super().form_valid(form)
        tenant = getattr(form, "tenant_obj", None)

        if tenant is None:
            self.request.session.pop(SESSION_ACTIVE_TENANT_ID, None)
            self.request.session[SESSION_AUTH_SCOPE] = AUTH_SCOPE_GLOBAL
        else:
            self.request.session[SESSION_ACTIVE_TENANT_ID] = str(tenant.pk)
            self.request.session[SESSION_AUTH_SCOPE] = AUTH_SCOPE_TENANT

        self.request.session.modified = True
        return response


def _available_tenants(self: AdminSite):
    return Tenant.objects.filter(is_active=True, deleted_at__isnull=True).order_by(
        "name"
    )


def _current_tenant_from_session(self: AdminSite, request: HttpRequest):
    session = getattr(request, "session", None)
    if session is None:
        return None

    tenant_id = session.get(SESSION_ACTIVE_TENANT_ID)
    if not tenant_id:
        return None
    return Tenant.objects.filter(
        pk=tenant_id, is_active=True, deleted_at__isnull=True
    ).first()


def _switch_context(
    self: AdminSite, request: HttpRequest, error: str | None = None
) -> dict[str, object]:
    any_self = cast(Any, self)
    current_tenant = any_self._current_tenant_from_session(request)
    return {
        **self.each_context(request),
        "current_tenant": current_tenant,
        "available_tenants": any_self._available_tenants(),
        "error": error,
        "auth_scope_global": AUTH_SCOPE_GLOBAL,
        "auth_scope_tenant": AUTH_SCOPE_TENANT,
    }


def tenant_switch_view(self: AdminSite, request: HttpRequest) -> HttpResponse:
    any_self = cast(Any, self)
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
                context = any_self._switch_context(request, error="Tenant not found")
                return render(request, "admin/tenant_switch.html", context)
            session[SESSION_ACTIVE_TENANT_ID] = str(tenant.pk)
            session[SESSION_AUTH_SCOPE] = AUTH_SCOPE_TENANT

        session.modified = True
        return redirect(reverse("admin:index"))

    return render(
        request, "admin/tenant_switch.html", any_self._switch_context(request)
    )


def tenantkit_each_context(self: AdminSite, request: HttpRequest) -> dict[str, object]:
    any_self = cast(Any, self)
    context = AdminSite.each_context(self, request)
    current_tenant = get_current_tenant() or any_self._current_tenant_from_session(
        request
    )
    available_tenants = any_self._available_tenants()
    context.update(
        {
            "current_tenant": current_tenant,
            "current_tenant_label": current_tenant.name if current_tenant else None,
            "tenant_switch_url": reverse("admin:tenant-switch"),
            "tenant_scope_label": "Tenant" if current_tenant else "Default / Global",
            "available_tenants": available_tenants,
        }
    )
    return context


def tenantkit_get_urls(self: AdminSite):
    any_self = cast(Any, self)
    urls = AdminSite.get_urls(self)
    custom_urls = [
        path(
            "tenant-switch/",
            self.admin_view(any_self.tenant_switch_view),
            name="tenant-switch",
        ),
    ]
    return custom_urls + urls


@method_decorator(never_cache)
@login_not_required
def tenantkit_login(self: AdminSite, request: HttpRequest, extra_context=None):
    any_request = cast(Any, request)
    if request.method == "GET" and self.has_permission(request):
        index_path = reverse("admin:index", current_app=self.name)
        return HttpResponseRedirect(index_path)

    context = {
        **self.each_context(request),
        "title": _("Log in"),
        "subtitle": None,
        "app_path": request.get_full_path(),
        "username": any_request.user.get_username(),
    }
    if (
        REDIRECT_FIELD_NAME not in request.GET
        and REDIRECT_FIELD_NAME not in request.POST
    ):
        context[REDIRECT_FIELD_NAME] = reverse("admin:index", current_app=self.name)
    context.update(extra_context or {})

    defaults = {
        "extra_context": context,
        "authentication_form": TenantAdminAuthenticationForm,
        "template_name": self.login_template or "tenantkit/admin/login.html",
    }
    any_request.current_app = self.name
    return TenantAdminLoginView.as_view(**defaults)(request)


def install_tenantkit_admin_extensions(site: Any) -> AdminSite:
    any_site = cast(Any, site)
    if getattr(any_site, "_tenantkit_extensions_installed", False):
        return cast(AdminSite, site)

    any_site._available_tenants = MethodType(_available_tenants, site)
    any_site._current_tenant_from_session = MethodType(
        _current_tenant_from_session, site
    )
    any_site._switch_context = MethodType(_switch_context, site)
    any_site.tenant_switch_view = MethodType(tenant_switch_view, site)
    any_site.each_context = MethodType(tenantkit_each_context, site)
    any_site.get_urls = MethodType(tenantkit_get_urls, site)
    any_site.login = MethodType(tenantkit_login, site)
    any_site._tenantkit_extensions_installed = True
    return cast(AdminSite, site)


class TenantkitAdminSite(AdminSite):
    site_header = "django-tenantkit"
    site_title = "django-tenantkit admin"
    index_title = "Administration"

    def get_urls(self):
        return tenantkit_get_urls(self)

    def _available_tenants(self):
        return _available_tenants(self)

    def _current_tenant_from_session(self, request: HttpRequest):
        return _current_tenant_from_session(self, request)

    def tenant_switch_view(self, request: HttpRequest) -> HttpResponse:
        return tenant_switch_view(self, request)

    def _switch_context(
        self, request: HttpRequest, error: str | None = None
    ) -> dict[str, object]:
        return _switch_context(self, request, error)

    def each_context(self, request: HttpRequest) -> dict[str, object]:
        return tenantkit_each_context(self, request)


tenantkit_admin_site = install_tenantkit_admin_extensions(admin.site)
