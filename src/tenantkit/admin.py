from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from django import forms
from django.contrib import admin, messages
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import GroupAdmin as DjangoGroupAdmin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.models import Group
from django.http import HttpRequest, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import path, reverse
from django.utils.translation import gettext_lazy as _

from tenantkit.admin_base import (
    ScopedModelAdminMixin,
    SharedScopeModelAdmin,
    SoftDeleteAdminMixin,
    SoftDeleteStatusFilter,
)
from tenantkit.admin_site import tenantkit_admin_site
from tenantkit.bootstrap import register_database_tenant_connection
from tenantkit.core.context import (
    clear_current_strategy,
    clear_current_tenant,
    set_current_strategy,
    set_current_tenant,
)
from tenantkit.crypto import encrypt_text
from tenantkit.errors import MultitenantError
from tenantkit.models import Tenant, TenantInvitation, TenantSetting
from tenantkit.provisioning import (
    migrate_tenant,
    provision_and_migrate_tenant,
    provision_tenant,
)
from tenantkit.strategies.database.strategy import DatabaseStrategy
from tenantkit.strategies.schema.strategy import SchemaStrategy


class TenantAdminForm(forms.ModelForm):
    connection_string_plain = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="Plaintext connection string; stored encrypted.",
    )
    provisioning_connection_string_plain = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="Plaintext admin connection string; stored encrypted.",
    )
    # Read-only fields to show encrypted values
    connection_string_encrypted = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 2, "readonly": "readonly"}),
        help_text="Encrypted value stored in database (read-only).",
    )
    provisioning_connection_string_encrypted = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 2, "readonly": "readonly"}),
        help_text="Encrypted provisioning value stored in database (read-only).",
    )

    class Meta:
        model = Tenant
        fields = [
            "slug",
            "name",
            "isolation_mode",
            "provisioning_mode",
            "schema_name",
            "connection_alias",
            "metadata",
            "is_active",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Initialize plain fields with decrypted values when editing existing tenant
        if self.instance and self.instance.pk:
            connection_string = self.instance.get_connection_string()
            if connection_string:
                self.initial["connection_string_plain"] = connection_string
                self.initial["connection_string_encrypted"] = (
                    self.instance.connection_string
                )
            provisioning_string = self.instance.get_provisioning_connection_string()
            if provisioning_string:
                self.initial["provisioning_connection_string_plain"] = (
                    provisioning_string
                )
                self.initial["provisioning_connection_string_encrypted"] = (
                    self.instance.provisioning_connection_string
                )

    def clean(self):
        cleaned_data = super().clean()
        isolation_mode = cleaned_data.get("isolation_mode") or getattr(
            self.instance, "isolation_mode", None
        )
        provisioning_mode = cleaned_data.get("provisioning_mode") or getattr(
            self.instance, "provisioning_mode", None
        )

        if isolation_mode == Tenant.IsolationMode.SCHEMA:
            if provisioning_mode == Tenant.ProvisioningMode.AUTO:
                cleaned_data["schema_name"] = None
                self.instance.schema_name = None
            else:
                cleaned_data["schema_name"] = (
                    cleaned_data.get("schema_name") or self.instance.schema_name
                )
            cleaned_data["connection_alias"] = None
            self.instance.connection_alias = None
            self.instance.connection_string = None
            self.instance.provisioning_connection_string = None
            cleaned_data["connection_string_plain"] = ""
            cleaned_data["provisioning_connection_string_plain"] = ""
        elif isolation_mode == Tenant.IsolationMode.DATABASE:
            cleaned_data["schema_name"] = None
            self.instance.schema_name = None

            if provisioning_mode == Tenant.ProvisioningMode.AUTO:
                cleaned_data["connection_alias"] = None
                self.instance.connection_alias = None
                cleaned_data["connection_string_plain"] = ""
            else:
                connection_alias = (
                    cleaned_data.get("connection_alias")
                    or self.instance.connection_alias
                )
                connection_string_plain = cleaned_data.get("connection_string_plain")
                provisioning_connection_string_plain = cleaned_data.get(
                    "provisioning_connection_string_plain"
                )
                if not connection_alias:
                    self.add_error(
                        "connection_alias",
                        "This field is required for manual database tenants.",
                    )
                if not connection_string_plain and not getattr(
                    self.instance, "connection_string", None
                ):
                    self.add_error(
                        "connection_string_plain",
                        "This field is required for manual database tenants.",
                    )
                self.instance.connection_alias = connection_alias
                self.instance.connection_string = (
                    connection_string_plain or self.instance.connection_string
                )
                self.instance.provisioning_connection_string = (
                    provisioning_connection_string_plain
                    or self.instance.provisioning_connection_string
                )

        return cleaned_data

    def save(self, commit: bool = True):
        instance = super().save(commit=False)
        connection_string = self.cleaned_data.get("connection_string_plain")
        provisioning_connection_string = self.cleaned_data.get(
            "provisioning_connection_string_plain"
        )
        if "connection_string_plain" in self.cleaned_data:
            if connection_string:
                instance.connection_string = encrypt_text(connection_string)
            else:
                instance.connection_string = None
        if "provisioning_connection_string_plain" in self.cleaned_data:
            if provisioning_connection_string:
                instance.provisioning_connection_string = encrypt_text(
                    provisioning_connection_string
                )
            else:
                instance.provisioning_connection_string = None
        if commit:
            instance.save()
            self.save_m2m()
        return instance


class BootstrapTenantAdminForm(forms.Form):
    username = forms.CharField(max_length=150)
    email = forms.EmailField()
    password1 = forms.CharField(widget=forms.PasswordInput)
    password2 = forms.CharField(widget=forms.PasswordInput)

    def __init__(self, *args, tenant: Tenant, **kwargs):
        self.tenant = tenant
        super().__init__(*args, **kwargs)
        self.fields["username"].initial = self._suggest_username()

    def _suggest_username(self) -> str:
        if self.tenant.isolation_mode == Tenant.IsolationMode.DATABASE:
            connection_string = self.tenant.get_connection_string() or ""
            parsed = urlparse(connection_string)
            if parsed.username:
                return parsed.username
        return "admin"

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get("password1") != cleaned_data.get("password2"):
            raise forms.ValidationError(_("Passwords do not match."))
        return cleaned_data


class TenantAdmin(SoftDeleteAdminMixin, SharedScopeModelAdmin):
    form = TenantAdminForm
    change_form_template = "admin/tenantkit_tenant_change_form.html"
    list_display = (
        "deleted_status",
        "slug",
        "name",
        "isolation_mode",
        "provisioning_mode",
        "is_active",
        "deleted_at",
    )
    list_filter = (
        SoftDeleteStatusFilter,
        "isolation_mode",
        "provisioning_mode",
        "is_active",
    )
    search_fields = ("slug", "name")
    readonly_fields = (
        "created_at",
        "updated_at",
        "deleted_at",
        "created_by",
        "updated_by",
        "deleted_by",
        "has_connection_string",
        "has_provisioning_connection_string",
    )
    fieldsets = [
        (
            None,
            {
                "fields": [
                    "slug",
                    "name",
                    "isolation_mode",
                    "provisioning_mode",
                    "is_active",
                ]
            },
        ),
        (
            "Schema",
            {
                "classes": ["tenant-section", "tenant-section-schema-manual"],
                "fields": ["schema_name", "metadata"],
            },
        ),
        (
            "Database runtime",
            {
                "classes": ["tenant-section", "tenant-section-database-manual"],
                "fields": [
                    "connection_alias",
                    "connection_string_plain",
                    "connection_string_encrypted",
                    "has_connection_string",
                ],
            },
        ),
        (
            "Database provisioning",
            {
                "classes": ["tenant-section", "tenant-section-database"],
                "fields": [
                    "provisioning_connection_string_plain",
                    "provisioning_connection_string_encrypted",
                    "has_provisioning_connection_string",
                ],
            },
        ),
        (
            "Audit",
            {
                "classes": ["collapse"],
                "fields": [
                    "created_at",
                    "created_by",
                    "updated_at",
                    "updated_by",
                    "deleted_at",
                    "deleted_by",
                ],
            },
        ),
    ]

    class Media:
        js = ("tenantkit/admin/tenant_form.js",)

    # Combine custom delete action with soft delete actions
    actions = [
        "delete_selected_tenants_with_databases",
        "restore_selected",
        "hard_delete_selected",
    ]

    @admin.action(
        description="Delete selected tenants with their databases",
        permissions=["delete"],
    )
    def delete_selected_tenants_with_databases(self, request, queryset):
        """Custom delete action that also drops physical databases."""
        # Filter only database tenants with connection strings
        database_tenants = [
            t
            for t in queryset
            if t.isolation_mode == Tenant.IsolationMode.DATABASE
            and t.get_connection_string()
        ]

        if not database_tenants:
            # No database tenants, use standard soft delete
            count = queryset.count()
            for tenant in queryset:
                tenant.soft_delete()
            self.message_user(
                request, f"{count} tenant(s) deleted successfully.", messages.SUCCESS
            )
            return

        if request.method == "POST" and "confirm_bulk_delete" in request.POST:
            # Process the deletion
            confirm_text = request.POST.get("confirm_bulk_delete", "").strip()
            expected_text = f"DELETE {len(database_tenants)} TENANTS"

            if confirm_text != expected_text:
                self.message_user(
                    request,
                    "Confirmation text did not match. Deletion cancelled.",
                    messages.ERROR,
                )
                return

            # Delete databases and soft delete tenants
            deleted_count = 0
            error_count = 0

            for tenant in database_tenants:
                try:
                    tenant.soft_delete(delete_database=True)
                    deleted_count += 1
                except Exception as exc:
                    self.message_user(
                        request,
                        f"Error deleting tenant {tenant.slug}: {exc}",
                        messages.ERROR,
                    )
                    error_count += 1

            # Soft delete any non-database tenants
            other_tenants = queryset.exclude(id__in=[t.id for t in database_tenants])
            for tenant in other_tenants:
                tenant.soft_delete()
                deleted_count += 1

            if deleted_count > 0:
                self.message_user(
                    request,
                    f"{deleted_count} tenant(s) and their databases deleted successfully.",
                    messages.SUCCESS,
                )

            return

        # Show confirmation page
        context = {
            **self.admin_site.each_context(request),
            "title": _("Warning: Multiple Databases Will Be Deleted"),
            "tenants": database_tenants,
            "total_count": len(database_tenants),
            "expected_confirmation": f"DELETE {len(database_tenants)} TENANTS",
            "opts": self.opts,
            "action_checkbox_name": ACTION_CHECKBOX_NAME,
        }
        return render(request, "admin/tenantkit_tenant_bulk_delete.html", context)

    def get_actions(self, request):
        actions = super().get_actions(request)
        # Remove default delete action
        if "delete_selected" in actions:
            del actions["delete_selected"]
        return actions

    @admin.display(boolean=True, description="Has connection string")
    def has_connection_string(self, obj: Tenant) -> bool:
        return bool(obj.connection_string)

    @admin.display(boolean=True, description="Has provisioning string")
    def has_provisioning_connection_string(self, obj: Tenant) -> bool:
        return bool(getattr(obj, "provisioning_connection_string", None))

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "<path:object_id>/ops/bootstrap_admin/",
                self.admin_site.admin_view(self.bootstrap_tenant_admin_view),
                name="tenant_bootstrap_admin",
            ),
            path(
                "<path:object_id>/ops/<str:operation>/",
                self.admin_site.admin_view(self.tenant_operation_view),
                name="tenant_operation",
            ),
        ]
        return custom_urls + urls

    def get_operation_url(self, obj: Tenant, operation: str) -> str:
        return reverse(
            "admin:tenant_operation",
            args=[obj.pk, operation],
        )

    def render_change_form(
        self, request, context, add=False, change=False, form_url="", obj=None
    ):
        context = dict(context)
        context["tenant_operation_urls"] = {}
        if obj is not None:
            context["tenant_operation_urls"] = {
                "bootstrap_admin": reverse(
                    "admin:tenant_bootstrap_admin", args=[obj.pk]
                ),
                "provision_and_migrate": self.get_operation_url(
                    obj, "provision_migrate"
                ),
                "provision_only": self.get_operation_url(obj, "provision_only"),
                "migrate_only": self.get_operation_url(obj, "migrate_only"),
            }
        return super().render_change_form(request, context, add, change, form_url, obj)

    def bootstrap_tenant_admin_view(self, request, object_id: str):
        tenant = get_object_or_404(Tenant, pk=object_id)

        if request.method == "POST":
            form = BootstrapTenantAdminForm(request.POST, tenant=tenant)
            if form.is_valid():
                try:
                    self._create_tenant_admin(tenant, form.cleaned_data)
                    messages.success(
                        request,
                        f"Tenant admin '{form.cleaned_data['username']}' created successfully.",
                        fail_silently=True,
                    )
                    return redirect(
                        reverse(
                            f"admin:{self.opts.app_label}_{self.opts.model_name}_change",
                            args=[tenant.pk],
                        )
                    )
                except Exception as exc:
                    messages.error(
                        request,
                        f"Bootstrap tenant admin failed: {exc}",
                        fail_silently=True,
                    )
        else:
            form = BootstrapTenantAdminForm(tenant=tenant)

        return render(
            request,
            "admin/tenantkit_bootstrap_admin.html",
            {
                **self.admin_site.each_context(request),
                "title": f"Bootstrap tenant admin - {tenant.name}",
                "tenant": tenant,
                "form": form,
                "opts": self.opts,
            },
        )

    def _create_tenant_admin(
        self, tenant: Tenant, cleaned_data: dict[str, Any]
    ) -> None:
        strategy = None
        if tenant.isolation_mode == Tenant.IsolationMode.SCHEMA:
            strategy = SchemaStrategy()
        elif tenant.isolation_mode == Tenant.IsolationMode.DATABASE:
            register_database_tenant_connection(tenant)
            strategy = DatabaseStrategy()

        if strategy is None:
            raise ValueError("Unsupported tenant isolation mode.")

        try:
            set_current_tenant(tenant)
            set_current_strategy(strategy)
            strategy.activate(tenant)

            user_model = get_user_model()
            user, _ = user_model.objects.get_or_create(
                username=str(cleaned_data["username"])
            )
            user.email = str(cleaned_data["email"])
            user.is_staff = True
            user.is_superuser = True
            user.is_active = True
            user.set_password(str(cleaned_data["password1"]))
            user.save()
        finally:
            strategy.deactivate()
            clear_current_strategy()
            clear_current_tenant()

    def tenant_operation_view(self, request, object_id: str, operation: str):
        tenant = get_object_or_404(Tenant, pk=object_id)
        if request.method == "POST":
            try:
                result = self.execute_tenant_operation(tenant, operation)
                if result:
                    messages.success(
                        request,
                        f"Operation '{operation}' completed successfully.",
                        fail_silently=True,
                    )
                else:
                    messages.warning(
                        request,
                        f"Operation '{operation}' completed with no changes.",
                        fail_silently=True,
                    )
            except MultitenantError as exc:
                messages.error(request, exc.message, fail_silently=True)
            except Exception as exc:  # pragma: no cover - defensive for admin UX
                messages.error(request, f"Operation failed: {exc}", fail_silently=True)
            return redirect(
                reverse(
                    f"admin:{self.opts.app_label}_{self.opts.model_name}_change",
                    args=[tenant.pk],
                )
            )

        return render(
            request,
            "admin/tenantkit_tenant_operation.html",
            {
                **self.admin_site.each_context(request),
                "title": f"{tenant.name} - {operation.replace('_', ' ').title()}",
                "tenant": tenant,
                "operation": operation,
                "operation_label": self.operation_label(operation),
            },
        )

    def operation_label(self, operation: str) -> str:
        return {
            "provision_migrate": "Provision & Migrate",
            "provision_only": "Provision only",
            "migrate_only": "Migrate only",
        }.get(operation, operation)

    def execute_tenant_operation(self, tenant: Tenant, operation: str) -> bool:
        if operation == "provision_migrate":
            return provision_and_migrate_tenant(tenant)
        if operation == "provision_only":
            return provision_tenant(tenant)
        if operation == "migrate_only":
            return migrate_tenant(tenant)
        raise ValueError(f"Unknown operation: {operation}")

    def delete_view(self, request: HttpRequest, object_id, extra_context=None) -> Any:
        """Override delete view to add double confirmation for database tenants."""
        tenant = self.get_object(request, object_id)

        if tenant is None:
            return self._get_obj_does_not_exist_redirect(request, self.opts, object_id)

        # Only intercept for database tenants with connection string
        is_database_tenant = (
            tenant.isolation_mode == Tenant.IsolationMode.DATABASE
            and tenant.get_connection_string()
        )

        if not is_database_tenant:
            # For non-database tenants, use default delete flow
            return super().delete_view(request, object_id, extra_context)

        # For database tenants, show custom double confirmation
        if request.method == "POST":
            # Check for double confirmation
            confirm_text = str(request.POST.get("confirm_delete_database", "")).strip()
            expected_text = f"DELETE {tenant.slug}"

            if confirm_text != expected_text:
                # First confirmation - show warning page
                context = {
                    **self.admin_site.each_context(request),
                    "title": _("Warning: Database Will Be Deleted"),
                    "object": tenant,
                    "object_name": str(tenant),
                    "opts": self.opts,
                    "expected_confirmation": expected_text,
                    "database_name": tenant.get_connection_string().split("/")[-1]
                    if tenant.get_connection_string()
                    else "unknown",
                    "media": self.media,
                }
                return render(
                    request,
                    "admin/tenantkit_tenant_delete_confirmation.html",
                    context,
                )

            # Second confirmation passed - proceed with delete including database
            try:
                tenant.soft_delete(delete_database=True)
                messages.success(
                    request, _("Tenant and database deleted successfully.")
                )
                return HttpResponseRedirect(
                    reverse(
                        f"admin:{self.opts.app_label}_{self.opts.model_name}_changelist"
                    )
                )
            except Exception as exc:
                messages.error(request, f"Error deleting tenant: {exc}")
                return redirect(
                    reverse(
                        f"admin:{self.opts.app_label}_{self.opts.model_name}_change",
                        args=[tenant.pk],
                    )
                )

        # GET request - show first confirmation page
        expected_text = f"DELETE {tenant.slug}"
        context = {
            **self.admin_site.each_context(request),
            "title": _("Warning: Database Will Be Deleted"),
            "object": tenant,
            "object_name": str(tenant),
            "opts": self.opts,
            "expected_confirmation": expected_text,
            "database_name": tenant.get_connection_string().split("/")[-1]
            if tenant.get_connection_string()
            else "unknown",
            "media": self.media,
        }
        return render(
            request, "admin/tenantkit_tenant_delete_confirmation.html", context
        )


class TenantInvitationAdmin(SoftDeleteAdminMixin, SharedScopeModelAdmin):
    list_display = (
        "tenant",
        "email",
        "status",
        "expires_at",
        "created_at",
        "deleted_at",
    )
    list_filter = ("status",) + SoftDeleteAdminMixin.list_filter
    search_fields = ("tenant__slug", "tenant__name", "email")
    readonly_fields = (
        "created_at",
        "updated_at",
        "deleted_at",
        "created_by",
        "updated_by",
        "deleted_by",
    )
    fieldsets = [
        (
            None,
            {
                "fields": [
                    "tenant",
                    "email",
                    "token",
                    "status",
                    "expires_at",
                    "accepted_at",
                    "accepted_by",
                ]
            },
        ),
        (
            "Audit",
            {
                "classes": ["collapse"],
                "fields": [
                    "created_at",
                    "created_by",
                    "updated_at",
                    "updated_by",
                    "deleted_at",
                    "deleted_by",
                ],
            },
        ),
    ]
    actions = SoftDeleteAdminMixin.actions


class TenantSettingAdmin(SoftDeleteAdminMixin, SharedScopeModelAdmin):
    list_display = ("tenant", "key", "created_at", "updated_at", "deleted_at")
    search_fields = ("tenant__slug", "tenant__name", "key")
    list_filter = SoftDeleteAdminMixin.list_filter
    readonly_fields = (
        "created_at",
        "updated_at",
        "deleted_at",
        "created_by",
        "updated_by",
        "deleted_by",
    )
    fieldsets = [
        (
            None,
            {"fields": ["tenant", "key", "value"]},
        ),
        (
            "Audit",
            {
                "classes": ["collapse"],
                "fields": [
                    "created_at",
                    "created_by",
                    "updated_at",
                    "updated_by",
                    "deleted_at",
                    "deleted_by",
                ],
            },
        ),
    ]
    actions = SoftDeleteAdminMixin.actions


class BothScopeUserAdmin(ScopedModelAdminMixin, DjangoUserAdmin):
    multitenant_scope = "both"


class BothScopeGroupAdmin(ScopedModelAdminMixin, DjangoGroupAdmin):
    multitenant_scope = "both"


def _safe_register(admin_site, model, admin_class) -> None:
    if model not in admin_site._registry:
        admin_site.register(model, admin_class)


def _replace_registration(admin_site, model, admin_class) -> None:
    if model in admin_site._registry:
        admin_site.unregister(model)
    admin_site.register(model, admin_class)


sites = list({id(site): site for site in (admin.site, tenantkit_admin_site)}.values())
for site in sites:
    _safe_register(site, Tenant, TenantAdmin)
    _safe_register(site, TenantInvitation, TenantInvitationAdmin)
    _safe_register(site, TenantSetting, TenantSettingAdmin)
    _replace_registration(site, get_user_model(), BothScopeUserAdmin)
    _replace_registration(site, Group, BothScopeGroupAdmin)
