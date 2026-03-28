from __future__ import annotations

from django.db import models

from tenantkit.core.context import get_current_tenant


class AuditQuerySet(models.QuerySet):
    def alive(self):
        return self.filter(deleted_at__isnull=True)

    def deleted(self):
        return self.filter(deleted_at__isnull=False)


class AuditManager(models.Manager.from_queryset(AuditQuerySet)):
    def get_queryset(self):
        return super().get_queryset().alive()


class AllObjectsManager(models.Manager.from_queryset(AuditQuerySet)):
    pass


class TenantSharedQuerySet(models.QuerySet):
    def visible_to(self, tenant):
        if tenant is None:
            return self

        return self.filter(
            models.Q(allowed_tenants__isnull=True) | models.Q(allowed_tenants=tenant)
        ).distinct()

    def for_current_tenant(self):
        return self.visible_to(get_current_tenant())


class TenantSharedManager(models.Manager.from_queryset(TenantSharedQuerySet)):
    def get_queryset(self):
        return super().get_queryset().for_current_tenant()
