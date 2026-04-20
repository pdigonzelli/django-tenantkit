from __future__ import annotations

from auditkit.managers import SoftDeleteManager
from auditkit.querysets import SoftDeleteQuerySet
from django.db import models

from tenantkit.core.context import get_current_tenant

# Backward compatibility aliases
AuditQuerySet = SoftDeleteQuerySet
AuditManager = SoftDeleteManager


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
