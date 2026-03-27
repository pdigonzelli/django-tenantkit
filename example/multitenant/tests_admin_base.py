from __future__ import annotations

from types import SimpleNamespace

from django.test import SimpleTestCase

from multitenant.admin_base import TenantAwareAdminMixin
from multitenant.core.context import clear_current_tenant, set_current_tenant


class FakeQuerySet:
    def __init__(self):
        self.filters: list[dict[str, object]] = []

    def filter(self, **kwargs):
        self.filters.append(kwargs)
        return self


class DummyAdmin(TenantAwareAdminMixin):
    pass


class DummyTenant:
    pass


class TenantAwareAdminBaseTests(SimpleTestCase):
    def tearDown(self):
        clear_current_tenant()

    def test_scope_queryset_without_tenant_returns_queryset(self):
        admin_base = DummyAdmin()
        queryset = FakeQuerySet()

        scoped = admin_base.scope_queryset(request=object(), queryset=queryset)

        self.assertIs(scoped, queryset)
        self.assertEqual(queryset.filters, [])

    def test_scope_queryset_with_request_tenant_filters_queryset(self):
        admin_base = DummyAdmin()
        queryset = FakeQuerySet()
        tenant = DummyTenant()
        set_current_tenant(tenant)

        scoped = admin_base.scope_queryset(request=object(), queryset=queryset)

        self.assertIs(scoped, queryset)
        self.assertEqual(queryset.filters, [{"tenant": tenant}])

    def test_assign_tenant_to_object_sets_missing_tenant(self):
        admin_base = DummyAdmin()
        tenant = DummyTenant()
        set_current_tenant(tenant)
        request = SimpleNamespace()
        obj = SimpleNamespace(tenant=None)

        admin_base.assign_tenant_to_object(request=request, obj=obj)

        self.assertIs(obj.tenant, tenant)

    def test_assign_tenant_to_object_does_not_overwrite_existing_tenant(self):
        admin_base = DummyAdmin()
        current_tenant = DummyTenant()
        existing_tenant = DummyTenant()
        set_current_tenant(current_tenant)
        request = SimpleNamespace()
        obj = SimpleNamespace(tenant=existing_tenant)

        admin_base.assign_tenant_to_object(request=request, obj=obj)

        self.assertIs(obj.tenant, existing_tenant)

    def test_get_current_tenant_falls_back_to_contextvars(self):
        admin_base = DummyAdmin()
        tenant = DummyTenant()
        set_current_tenant(tenant)

        self.assertIs(admin_base.get_current_tenant(request=object()), tenant)
