from __future__ import annotations

from typing import Any

from django.contrib import admin, messages
from django.db.models import Q
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from tenantkit.admin_site import (
    AUTH_SCOPE_TENANT,
    SESSION_ACTIVE_TENANT_ID,
    SESSION_AUTH_SCOPE,
)
from tenantkit.core.context import get_current_tenant
from tenantkit.models import Tenant


class SoftDeleteStatusFilter(admin.SimpleListFilter):
    """Filter to show active, deleted, or all records for soft-delete models."""

    title = _("status")
    parameter_name = "soft_delete_status"

    def lookups(self, request, model_admin):
        return (
            ("active", _("Active")),
            ("deleted", _("Deleted (Soft)")),
            ("all", _("All")),
        )

    def queryset(self, request, queryset):
        if self.value() == "active":
            return queryset.filter(deleted_at__isnull=True)
        elif self.value() == "deleted":
            return queryset.filter(deleted_at__isnull=False)
        # 'all' or default - return full queryset including deleted
        return queryset

    def choices(self, changelist):
        for lookup, title in self.lookup_choices:
            yield {
                "selected": self.value() == str(lookup),
                "query_string": changelist.get_query_string(
                    {self.parameter_name: lookup}
                ),
                "display": title,
            }


class TenantAwareAdminMixin:
    """Reusable tenant-aware admin behavior.

    This mixin is intentionally generic so it can be reused by future
    tenant-local ModelAdmin classes without coupling them to a specific model.
    """

    tenant_field_name = "tenant"

    def get_current_tenant(self, request):
        return get_current_tenant()

    def get_tenant_field_name(self) -> str:
        return str(getattr(self, "tenant_field_name", "tenant"))

    def get_tenant_filter_kwargs(self, request) -> dict[str, Any]:
        tenant = self.get_current_tenant(request)
        if tenant is None:
            return {}
        return {self.get_tenant_field_name(): tenant}

    def scope_queryset(self, request, queryset):
        tenant_filter = self.get_tenant_filter_kwargs(request)
        if not tenant_filter:
            return queryset
        return queryset.filter(**tenant_filter)

    def assign_tenant_to_object(self, request, obj) -> None:
        tenant = self.get_current_tenant(request)
        if tenant is None:
            return

        tenant_field_name = self.get_tenant_field_name()
        if getattr(obj, tenant_field_name, None) is None:
            setattr(obj, tenant_field_name, tenant)


class ScopedModelAdminMixin:
    """Scope-aware admin behavior for shared vs tenant-local models."""

    multitenant_scope = "shared"  # shared | tenant | both

    def get_active_multitenant_scope(self, request) -> str:
        session = getattr(request, "session", None)
        if session is not None:
            if session.get(SESSION_AUTH_SCOPE) == AUTH_SCOPE_TENANT and session.get(
                SESSION_ACTIVE_TENANT_ID
            ):
                return "tenant"
            return "shared"

        return "tenant" if get_current_tenant() is not None else "shared"

    def scope_matches(self, request) -> bool:
        active_scope = self.get_active_multitenant_scope(request)
        return self.multitenant_scope in {"both", active_scope}

    def _scoped_super(self, method_name: str, request, *args, **kwargs):
        method = getattr(super(), method_name)
        return method(request, *args, **kwargs)

    def get_model_perms(self, request):
        if not self.scope_matches(request):
            return {}
        return super().get_model_perms(request)  # type: ignore[attr-defined]

    def has_module_permission(self, request):
        if not self.scope_matches(request):
            return False
        return super().has_module_permission(request)  # type: ignore[attr-defined]

    def has_view_permission(self, request, obj=None):
        if not self.scope_matches(request):
            return False
        return super().has_view_permission(request, obj=obj)  # type: ignore[attr-defined]

    def has_add_permission(self, request):
        if not self.scope_matches(request):
            return False
        return super().has_add_permission(request)  # type: ignore[attr-defined]

    def has_change_permission(self, request, obj=None):
        if not self.scope_matches(request):
            return False
        return super().has_change_permission(request, obj=obj)  # type: ignore[attr-defined]

    def has_delete_permission(self, request, obj=None):
        if not self.scope_matches(request):
            return False
        return super().has_delete_permission(request, obj=obj)  # type: ignore[attr-defined]

    def has_view_or_change_permission(self, request, obj=None):
        if not self.scope_matches(request):
            return False
        return super().has_view_or_change_permission(request, obj=obj)  # type: ignore[attr-defined]


class TenantAwareModelAdmin(TenantAwareAdminMixin, admin.ModelAdmin):
    """ModelAdmin base class for tenant-local models."""

    multitenant_scope = "tenant"

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        return self.scope_queryset(request, queryset)

    def save_model(self, request, obj, form, change):
        self.assign_tenant_to_object(request, obj)
        super().save_model(request, obj, form, change)


class TenantSharedModelAdmin(ScopedModelAdminMixin, admin.ModelAdmin):
    """ModelAdmin base for models that are shared by default or restricted to tenants."""

    multitenant_scope = "both"

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        session_tenant = self._get_session_tenant(request)
        if session_tenant is None:
            return queryset

        return queryset.filter(
            Q(allowed_tenants__isnull=True) | Q(allowed_tenants=session_tenant)
        ).distinct()

    def _get_session_tenant(self, request):
        session = getattr(request, "session", None)
        if session is None:
            return get_current_tenant()

        if session.get(SESSION_AUTH_SCOPE) != AUTH_SCOPE_TENANT:
            return None

        tenant_id = session.get(SESSION_ACTIVE_TENANT_ID)
        if not tenant_id:
            return None

        return Tenant.objects.filter(
            pk=tenant_id, is_active=True, deleted_at__isnull=True
        ).first()


class SharedScopeModelAdmin(ScopedModelAdminMixin, admin.ModelAdmin):
    """ModelAdmin base for shared/default models."""

    multitenant_scope = "shared"


class SoftDeleteAdminMixin:
    """Mixin to add soft-delete support to ModelAdmin classes.

    Features:
    - Filter by status (Active/Deleted/All)
    - Action to restore soft-deleted records
    - Action to permanently delete records
    - Visual indicator for deleted records in list view
    """

    list_filter = (SoftDeleteStatusFilter,)
    actions = ["restore_selected", "hard_delete_selected"]

    def get_queryset(self, request):
        """Override to use all_objects manager for soft-delete support."""
        # Use all_objects to include soft-deleted records
        if hasattr(self.model, "all_objects"):
            qs = self.model.all_objects.get_queryset()
        else:
            qs = super().get_queryset(request)

        # Apply ordering
        ordering = self.get_ordering(request)
        if ordering:
            qs = qs.order_by(*ordering)

        return qs

    def get_list_display(self, request):
        """Add status indicator to list display."""
        list_display = list(super().get_list_display(request))
        if "deleted_status" not in list_display:
            list_display.insert(0, "deleted_status")
        return tuple(list_display)

    @admin.display(description=_("Status"), ordering="deleted_at")
    def deleted_status(self, obj):
        """Visual indicator for deleted records."""
        if obj.deleted_at:
            return _("🗑️ Deleted")
        return _("✅ Active")

    @admin.action(description=_("Restore selected records"))
    def restore_selected(self, request, queryset):
        """Restore soft-deleted records."""
        restored_count = 0
        for obj in queryset.filter(deleted_at__isnull=False):
            obj.restore(user=request.user)
            restored_count += 1

        if restored_count:
            self.message_user(
                request,
                _("%(count)d record(s) restored successfully.")
                % {"count": restored_count},
                messages.SUCCESS,
            )
        else:
            self.message_user(
                request, _("No deleted records selected."), messages.WARNING
            )

    @admin.action(description=_("Permanently delete selected records"))
    def hard_delete_selected(self, request, queryset):
        """Permanently delete records (bypass soft delete)."""
        # This requires a confirmation step
        if request.method == "POST" and "confirm_hard_delete" in request.POST:
            confirm_text = request.POST.get("confirm_hard_delete", "").strip()
            expected_text = _("HARD DELETE")

            if confirm_text != expected_text:
                self.message_user(
                    request,
                    _("Confirmation text did not match. Deletion cancelled."),
                    messages.ERROR,
                )
                return

            deleted_count = queryset.count()
            queryset.delete()  # This is the real delete
            self.message_user(
                request,
                _("%(count)d record(s) permanently deleted.")
                % {"count": deleted_count},
                messages.SUCCESS,
            )
            return HttpResponseRedirect(
                reverse(
                    "admin:%s_%s_changelist"
                    % (self.opts.app_label, self.opts.model_name)
                )
            )

        # Show confirmation page
        context = {
            **self.admin_site.each_context(request),
            "title": _("Confirm Permanent Deletion"),
            "queryset": queryset,
            "count": queryset.count(),
            "opts": self.opts,
            "action_checkbox_name": admin.helpers.ACTION_CHECKBOX_NAME,
            "expected_confirmation": _("HARD DELETE"),
        }
        return render(
            request, "admin/soft_delete_hard_delete_confirmation.html", context
        )

    def delete_model(self, request, obj):
        """Override delete to use soft delete by default."""
        # Check if this is a hard delete request
        if request.method == "POST" and "hard_delete" in request.POST:
            # Permanent deletion
            obj.delete()
        else:
            # Soft delete
            obj.soft_delete(user=request.user)

    def delete_queryset(self, request, queryset):
        """Override bulk delete to use soft delete."""
        for obj in queryset:
            obj.soft_delete(user=request.user)
