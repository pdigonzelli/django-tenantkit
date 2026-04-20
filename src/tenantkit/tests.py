import json
from typing import Any, cast
from unittest.mock import MagicMock, patch

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser, Group
from django.contrib.sessions.backends.db import SessionStore
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.db import connection, connections, models
from django.test import (
    Client,
    RequestFactory,
    TestCase,
    TransactionTestCase,
    override_settings,
)
from rest_framework.exceptions import AuthenticationFailed

from tenantkit.admin import (
    BothScopeGroupAdmin,
    BothScopeUserAdmin,
    TenantAdmin,
    TenantAdminForm,
)
from tenantkit.admin_base import TenantSharedModelAdmin
from tenantkit.admin_site import (
    AUTH_SCOPE_GLOBAL,
    AUTH_SCOPE_TENANT,
    SESSION_ACTIVE_TENANT_ID,
    SESSION_AUTH_SCOPE,
    TenantAdminAuthenticationForm,
    tenantkit_admin_site,
)
from tenantkit.auth import (
    TenantClaimsMixin,
    TenantJWTAuthentication,
    TenantTokenValidator,
)
from tenantkit.bootstrap import (
    register_database_tenant_connection,
    unregister_database_tenant_connection,
)
from tenantkit.classification import (
    MODEL_TYPE_BOTH,
    clear_classification_caches,
    get_app_scope,
    get_both_app_labels,
    get_model_scope,
)
from tenantkit.connections import parse_connection_url
from tenantkit.core.context import (
    clear_current_strategy,
    clear_current_tenant,
    get_current_strategy,
    get_current_tenant,
    set_current_strategy,
    set_current_tenant,
)
from tenantkit.crypto import decrypt_text, encrypt_text
from tenantkit.middleware.tenant import TenantMiddleware
from tenantkit.model_config import (
    MODEL_TYPE_SHARED,
    MODEL_TYPE_TENANT,
    ModelRegistry,
    get_models_for_migration,
    shared_model,
    tenant_model,
)
from tenantkit.models import Tenant, TenantInvitation, TenantSetting, TenantSharedModel
from tenantkit.provisioning import (
    ensure_database_exists,
    ensure_database_tenant_ready,
)
from tenantkit.routers.tenant import TenantRouter, _resolve_model_for_migration
from tenantkit.strategies.database.strategy import DatabaseStrategy
from tenantkit.strategies.schema.strategy import SchemaStrategy

User = get_user_model()


@tenant_model
class DummyTenantRecord(models.Model):
    name = models.CharField(max_length=64)

    class Meta:
        app_label = "tenantkit"
        managed = False

    def __str__(self) -> str:
        return str(self.name)


@tenant_model(auto_migrate=False, allow_global_queries=True)
class DummyGlobalTenantRecord(models.Model):
    name = models.CharField(max_length=64)

    class Meta:
        app_label = "tenantkit"
        managed = False

    def __str__(self) -> str:
        return str(self.name)


@shared_model
class DummySharedInTenantApp(models.Model):
    name = models.CharField(max_length=64)

    class Meta:
        app_label = "tenantkit"
        managed = False

    def __str__(self) -> str:
        return str(self.name)


@tenant_model
class DummyTenantInSharedApp(models.Model):
    name = models.CharField(max_length=64)

    class Meta:
        app_label = "auth"
        managed = False

    def __str__(self) -> str:
        return str(self.name)


class ContextTests(TestCase):
    def tearDown(self):
        clear_current_tenant()
        clear_current_strategy()

    def test_set_get_and_clear_current_tenant(self):
        tenant = object()
        set_current_tenant(tenant)

        self.assertIs(get_current_tenant(), tenant)

        clear_current_tenant()
        self.assertIsNone(get_current_tenant())

    def test_set_get_and_clear_current_strategy(self):
        strategy = object()
        set_current_strategy(strategy)

        self.assertIs(get_current_strategy(), strategy)

        clear_current_strategy()
        self.assertIsNone(get_current_strategy())


class TenantModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="owner", password="secret")

    def test_schema_tenant_auto_generates_schema_name(self):
        tenant = Tenant.objects.create(
            slug="acme",
            name="Acme",
            isolation_mode=Tenant.IsolationMode.SCHEMA,
        )

        self.assertTrue(tenant.schema_name)
        self.assertIsNone(tenant.connection_alias)
        self.assertIsNone(tenant.connection_string)

    def test_database_tenant_auto_generates_alias_and_connection_string(self):
        tenant = Tenant.objects.create(
            slug="acme-db",
            name="Acme DB",
            isolation_mode=Tenant.IsolationMode.DATABASE,
        )

        self.assertTrue(tenant.connection_alias)
        self.assertTrue(tenant.connection_string)
        self.assertIsNone(tenant.schema_name)
        self.assertTrue(tenant.get_connection_string().startswith("sqlite:///"))

    @override_settings(TENANT_ENCRYPTION_KEY="unit-test-key")
    def test_database_tenant_roundtrips_provisioning_connection_string(self):
        tenant = Tenant(
            slug="acme-db",
            name="Acme DB",
            isolation_mode=Tenant.IsolationMode.DATABASE,
            provisioning_mode=Tenant.ProvisioningMode.MANUAL,
            connection_alias="tenant_acme_db",
        )

        plain = "postgresql://admin:secret@localhost:5432/postgres"
        tenant.set_provisioning_connection_string(plain)

        self.assertNotEqual(tenant.provisioning_connection_string, plain)
        self.assertEqual(tenant.get_provisioning_connection_string(), plain)

    def test_database_tenant_rejects_explicit_schema_name(self):
        tenant = Tenant(
            slug="acme",
            name="Acme",
            isolation_mode=Tenant.IsolationMode.DATABASE,
            provisioning_mode=Tenant.ProvisioningMode.MANUAL,
            schema_name="acme_schema",
        )

        with self.assertRaises(ValidationError):
            tenant.save()

    def test_schema_tenant_rejects_explicit_connection_alias(self):
        tenant = Tenant(
            slug="acme",
            name="Acme",
            isolation_mode=Tenant.IsolationMode.SCHEMA,
            provisioning_mode=Tenant.ProvisioningMode.MANUAL,
            connection_alias="tenant_acme",
        )

        with self.assertRaises(ValidationError):
            tenant.save()

    # Note: Auto provisioning restriction for non-SQLite backends is tested
    # manually. The validation exists in ensure_isolation_fields() and raises
    # ValidationError when get_default_db_engine() returns non-sqlite.

    def test_schema_tenant_rejects_provisioning_connection_string(self):
        tenant = Tenant(
            slug="acme",
            name="Acme",
            isolation_mode=Tenant.IsolationMode.SCHEMA,
            provisioning_mode=Tenant.ProvisioningMode.MANUAL,
            schema_name="acme_schema",
            provisioning_connection_string="postgresql://admin:secret@localhost:5432/postgres",
        )

        with self.assertRaises(ValidationError):
            tenant.save()

    def test_soft_delete_and_restore(self):
        tenant = Tenant.objects.create(
            slug="acme",
            name="Acme",
            isolation_mode=Tenant.IsolationMode.SCHEMA,
        )

        self.assertFalse(tenant.deleted)
        self.assertTrue(tenant.is_active)

        tenant.soft_delete()
        tenant.refresh_from_db()

        self.assertTrue(tenant.deleted)
        self.assertFalse(tenant.is_active)

        tenant.restore()
        tenant.refresh_from_db()

        self.assertFalse(tenant.deleted)
        self.assertTrue(tenant.is_active)

    def test_audit_manager_filters_deleted_rows(self):
        alive = Tenant.objects.create(
            slug="alive",
            name="Alive",
            isolation_mode=Tenant.IsolationMode.SCHEMA,
        )
        deleted = Tenant.objects.create(
            slug="deleted",
            name="Deleted",
            isolation_mode=Tenant.IsolationMode.SCHEMA,
        )
        deleted.soft_delete()

        self.assertEqual(
            list(Tenant.objects.values_list("slug", flat=True)), [alive.slug]
        )
        self.assertCountEqual(
            Tenant.all_objects.values_list("slug", flat=True),
            [alive.slug, deleted.slug],
        )
        self.assertCountEqual(
            Tenant.all_objects.deleted().values_list("slug", flat=True),
            [deleted.slug],
        )

    @override_settings(TENANT_ENCRYPTION_KEY="unit-test-key")
    def test_connection_string_roundtrip(self):
        tenant = Tenant(
            slug="dbtenant",
            name="DB Tenant",
            isolation_mode=Tenant.IsolationMode.DATABASE,
            provisioning_mode=Tenant.ProvisioningMode.MANUAL,
            connection_alias="tenant_dbtenant",
        )

        plain = "postgresql://user:pass@localhost:5432/dbtenant"
        tenant.set_connection_string(plain)

        self.assertNotEqual(tenant.connection_string, plain)
        self.assertEqual(tenant.get_connection_string(), plain)

    def test_parse_plain_sqlite_path_as_sqlite_backend(self):
        config = parse_connection_url("test.db")

        self.assertEqual(config["ENGINE"], "django.db.backends.sqlite3")
        self.assertEqual(config["NAME"], "test.db")


class CryptoTests(TestCase):
    @override_settings(TENANT_ENCRYPTION_KEY="unit-test-key")
    def test_encrypt_decrypt_roundtrip(self):
        plain = "postgresql://user:pass@localhost:5432/dbtenant"
        cipher = encrypt_text(plain)

        self.assertNotEqual(cipher, plain)
        self.assertEqual(decrypt_text(cipher), plain)


class TenantAdminFormTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="owner", password="secret")
        self.tenant = Tenant.objects.create(
            slug="schema-tenant",
            name="Schema Tenant",
            isolation_mode=Tenant.IsolationMode.SCHEMA,
            provisioning_mode=Tenant.ProvisioningMode.MANUAL,
            schema_name="schema_tenant",
        )

    def test_switching_to_database_manual_validates_connection_fields(self):
        form = TenantAdminForm(
            data={
                "slug": self.tenant.slug,
                "name": self.tenant.name,
                "isolation_mode": Tenant.IsolationMode.DATABASE,
                "provisioning_mode": Tenant.ProvisioningMode.MANUAL,
                "connection_alias": "tenant_schema_tenant",
                "connection_string_plain": "postgresql://user:pass@localhost:5432/schema_tenant",
                "provisioning_connection_string_plain": "postgresql://admin:secret@localhost:5432/postgres",
                "is_active": True,
            },
            instance=self.tenant,
        )

        self.assertTrue(form.is_valid(), form.errors)
        tenant = form.save()
        self.assertEqual(tenant.isolation_mode, Tenant.IsolationMode.DATABASE)
        self.assertEqual(tenant.connection_alias, "tenant_schema_tenant")
        self.assertTrue(tenant.get_connection_string())


class TenantSharedModelTests(TransactionTestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="owner", password="secret")
        self.tenant_one = Tenant.objects.create(
            slug="tenant-one",
            name="Tenant One",
            isolation_mode=Tenant.IsolationMode.SCHEMA,
        )
        self.tenant_two = Tenant.objects.create(
            slug="tenant-two",
            name="Tenant Two",
            isolation_mode=Tenant.IsolationMode.SCHEMA,
        )

    def test_allowed_tenants_empty_means_shared_for_all(self):
        class TenantSharedThingA(TenantSharedModel):
            name = models.CharField(max_length=50)

            class Meta:  # type: ignore[valid-type]
                app_label = "tenantkit"
                db_table = "multitenant_tenantsharedthing_a"

        with connection.schema_editor() as editor:
            editor.create_model(TenantSharedThingA)

        TenantSharedThingA.objects.create(name="shared")
        restricted_one = TenantSharedThingA.all_objects.create(name="restricted-one")
        restricted_one.allowed_tenants.add(self.tenant_one)
        restricted_two = TenantSharedThingA.all_objects.create(name="restricted-two")
        restricted_two.allowed_tenants.add(self.tenant_two)

        set_current_tenant(self.tenant_one)
        tenant_one_names = list(
            TenantSharedThingA.objects.values_list("name", flat=True).order_by("name")
        )
        clear_current_tenant()

        self.assertCountEqual(tenant_one_names, ["restricted-one", "shared"])

        all_names = list(
            TenantSharedThingA.all_objects.values_list("name", flat=True).order_by(
                "name"
            )
        )
        self.assertCountEqual(all_names, ["restricted-one", "restricted-two", "shared"])


class TenantSharedModelAdminTests(TransactionTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(username="owner", password="secret")
        self.superuser = User.objects.create_superuser(
            username="root", password="secret", email="root@example.com"
        )
        self.tenant_one = Tenant.objects.create(
            slug="tenant-one",
            name="Tenant One",
            isolation_mode=Tenant.IsolationMode.SCHEMA,
        )
        self.tenant_two = Tenant.objects.create(
            slug="tenant-two",
            name="Tenant Two",
            isolation_mode=Tenant.IsolationMode.SCHEMA,
        )

    def test_tenant_shared_admin_filters_by_allowed_tenants(self):
        class TenantSharedThingB(TenantSharedModel):
            name = models.CharField(max_length=50)

            class Meta:  # type: ignore[valid-type]
                app_label = "tenantkit"
                db_table = "multitenant_tenantsharedthing_b"

        class TenantSharedThingAdmin(TenantSharedModelAdmin):
            pass

        with connection.schema_editor() as editor:
            editor.create_model(TenantSharedThingB)

        admin = TenantSharedThingAdmin(TenantSharedThingB, tenantkit_admin_site)

        TenantSharedThingB.objects.create(name="shared")
        restricted_one = TenantSharedThingB.all_objects.create(name="restricted-one")
        restricted_one.allowed_tenants.add(self.tenant_one)
        restricted_two = TenantSharedThingB.all_objects.create(name="restricted-two")
        restricted_two.allowed_tenants.add(self.tenant_two)

        request = self.factory.get("/admin/")
        request = cast(Any, request)
        request.user = self.superuser
        request.session = SessionStore()
        request.session[SESSION_AUTH_SCOPE] = AUTH_SCOPE_TENANT
        request.session[SESSION_ACTIVE_TENANT_ID] = str(self.tenant_one.pk)

        names = list(admin.get_queryset(request).values_list("name", flat=True))
        self.assertCountEqual(names, ["shared", "restricted-one"])


class ConnectionConfigTests(TestCase):
    def test_parse_connection_url_includes_django_defaults(self):
        config = parse_connection_url("postgresql://user:pass@localhost:5432/demo")

        self.assertIn("ATOMIC_REQUESTS", config)
        self.assertFalse(config["ATOMIC_REQUESTS"])
        self.assertEqual(config["NAME"], "demo")


class TenantRouterTests(TestCase):
    class DummyStrategy:
        def __init__(self):
            self.read_calls = []
            self.write_calls = []
            self.migrate_calls = []

        def db_for_read(self, model, **hints):
            self.read_calls.append((model, hints))
            return "tenant_db"

        def db_for_write(self, model, **hints):
            self.write_calls.append((model, hints))
            return "tenant_db"

        def allow_migrate(self, db, app_label, model_name=None, **hints):
            self.migrate_calls.append((db, app_label, model_name, hints))
            return True

    def tearDown(self):
        clear_current_tenant()
        clear_current_strategy()
        clear_classification_caches()

    def test_router_returns_none_without_tenant(self):
        router = TenantRouter()
        self.assertEqual(router.db_for_read(Tenant), "default")
        self.assertEqual(router.db_for_write(Tenant), "default")
        self.assertIsNone(router.db_for_read(DummyTenantRecord))
        self.assertIsNone(router.db_for_write(DummyTenantRecord))

    def test_router_delegates_to_strategy(self):
        tenant = Tenant(
            slug="acme",
            name="Acme",
            isolation_mode=Tenant.IsolationMode.DATABASE,
        )
        strategy = self.DummyStrategy()
        set_current_tenant(tenant)
        set_current_strategy(strategy)

        router = TenantRouter()
        self.assertEqual(router.db_for_read(DummyTenantRecord), "tenant_db")
        self.assertEqual(router.db_for_write(DummyTenantRecord), "tenant_db")
        self.assertFalse(router.allow_migrate("tenant_db", "tenantkit", "tenant"))

        self.assertEqual(len(strategy.read_calls), 1)
        self.assertEqual(strategy.read_calls[0][0], DummyTenantRecord)
        self.assertEqual(len(strategy.write_calls), 1)
        self.assertEqual(strategy.write_calls[0][0], DummyTenantRecord)
        self.assertEqual(len(strategy.migrate_calls), 0)

    def test_router_allows_global_queries_for_configured_tenant_model(self):
        router = TenantRouter()

        self.assertEqual(router.db_for_read(DummyGlobalTenantRecord), "default")

    def test_router_routes_dual_app_models_to_default_without_tenant(self):
        router = TenantRouter()

        self.assertEqual(router.db_for_read(User), "default")
        self.assertEqual(router.db_for_write(User), "default")

    def test_router_routes_dual_app_models_via_strategy_with_tenant(self):
        tenant = Tenant(
            slug="acme",
            name="Acme",
            isolation_mode=Tenant.IsolationMode.DATABASE,
        )
        strategy = self.DummyStrategy()
        set_current_tenant(tenant)
        set_current_strategy(strategy)

        router = TenantRouter()

        self.assertEqual(router.db_for_read(User), "tenant_db")
        self.assertEqual(router.db_for_write(User), "tenant_db")

        self.assertEqual(len(strategy.read_calls), 1)
        self.assertEqual(strategy.read_calls[0][0], User)
        self.assertEqual(len(strategy.write_calls), 1)
        self.assertEqual(strategy.write_calls[0][0], User)

    def test_router_defers_unclassified_models_without_warning(self):
        class UnclassifiedModel(models.Model):
            name = models.CharField(max_length=32)

            class Meta:
                app_label = "tenantkit"
                managed = False

            def __str__(self) -> str:
                return str(self.name)

        router = TenantRouter()

        with self.assertNoLogs("tenantkit.routers.tenant", level="WARNING"):
            self.assertIsNone(router.db_for_read(UnclassifiedModel))
            self.assertIsNone(router.db_for_write(UnclassifiedModel))

    @override_settings(
        TENANTKIT_BOTH_APPS=["django.contrib.auth", "django.contrib.contenttypes"]
    )
    def test_classification_recognizes_both_apps(self):
        clear_classification_caches()

        self.assertIn("auth", get_both_app_labels())
        self.assertEqual(get_model_scope(User), MODEL_TYPE_BOTH)

    @override_settings(TENANTKIT_DUAL_APPS=["django.contrib.auth"])
    def test_classification_supports_legacy_dual_apps(self):
        clear_classification_caches()

        with self.assertWarns(DeprecationWarning):
            labels = get_both_app_labels()

        self.assertIn("auth", labels)

    @override_settings(TENANTKIT_TENANT_APPS=["tenantkit"])
    def test_allow_migrate_uses_tenant_app_scope_without_model_name(self):
        clear_classification_caches()
        router = TenantRouter()

        self.assertFalse(router.allow_migrate("default", "tenantkit"))
        self.assertTrue(router.allow_migrate("tenant_db", "tenantkit"))

    @override_settings(TENANTKIT_SHARED_APPS=["tenantkit"])
    def test_allow_migrate_uses_shared_app_scope_without_model_name(self):
        clear_classification_caches()
        router = TenantRouter()

        self.assertTrue(router.allow_migrate("default", "tenantkit"))
        self.assertFalse(router.allow_migrate("tenant_db", "tenantkit"))

    @override_settings(TENANTKIT_BOTH_APPS=["django.contrib.auth"])
    def test_get_app_scope_recognizes_both_app(self):
        clear_classification_caches()

        self.assertEqual(get_app_scope("auth"), MODEL_TYPE_BOTH)

    @override_settings(TENANTKIT_TENANT_APPS=["tenantkit"])
    def test_model_scope_shared_overrides_tenant_app_scope_for_migrations(self):
        clear_classification_caches()
        router = TenantRouter()

        self.assertEqual(get_model_scope(DummySharedInTenantApp), MODEL_TYPE_SHARED)
        self.assertTrue(
            router.allow_migrate("default", "tenantkit", "dummysharedintenantapp")
        )
        self.assertFalse(
            router.allow_migrate("tenant_db", "tenantkit", "dummysharedintenantapp")
        )

    @override_settings(TENANTKIT_SHARED_APPS=["django.contrib.auth"])
    def test_model_scope_tenant_overrides_shared_app_scope_for_migrations(self):
        clear_classification_caches()
        router = TenantRouter()

        self.assertEqual(get_model_scope(DummyTenantInSharedApp), MODEL_TYPE_TENANT)
        self.assertFalse(
            router.allow_migrate("default", "auth", "dummytenantinsharedapp")
        )
        self.assertIsNone(
            router.allow_migrate("tenant_db", "auth", "dummytenantinsharedapp")
        )

    @override_settings(TENANTKIT_TENANT_APPS=["tenantkit"])
    def test_migration_resolution_prefers_live_model_over_unclassified_historical_model(
        self,
    ):
        clear_classification_caches()

        class HistoricalDummySharedInTenantApp:
            class _meta:
                app_label = "tenantkit"

        resolved = _resolve_model_for_migration(
            "tenantkit", "dummysharedintenantapp", HistoricalDummySharedInTenantApp
        )

        self.assertIs(resolved, DummySharedInTenantApp)
        self.assertEqual(get_model_scope(resolved), MODEL_TYPE_SHARED)
        router = TenantRouter()
        self.assertTrue(
            router.allow_migrate(
                "default",
                "tenantkit",
                "dummysharedintenantapp",
                model=HistoricalDummySharedInTenantApp,
            )
        )

    def test_registry_tracks_concrete_tenant_model_configuration(self):
        self.assertTrue(ModelRegistry.is_tenant_model(DummyTenantRecord))
        self.assertTrue(ModelRegistry.is_tenant_model(DummyGlobalTenantRecord))

        config = ModelRegistry.get_model_config(DummyGlobalTenantRecord)
        self.assertIsNotNone(config)
        config = cast(dict[str, Any], config)
        self.assertTrue(config["allow_global_queries"])
        self.assertFalse(config["auto_migrate"])

    def test_get_models_for_migration_excludes_opted_out_tenant_models(self):
        tenant_models = get_models_for_migration(MODEL_TYPE_TENANT)

        self.assertIn(DummyTenantRecord, tenant_models)
        self.assertNotIn(DummyGlobalTenantRecord, tenant_models)


class SchemaStrategyTests(TestCase):
    @patch("tenantkit.strategies.schema.strategy.activate_schema")
    @patch("tenantkit.strategies.schema.strategy.deactivate_schema")
    def test_activate_sets_context_and_calls_backend(
        self, deactivate_schema, activate_schema
    ):
        tenant = Tenant(
            slug="acme",
            name="Acme",
            isolation_mode=Tenant.IsolationMode.SCHEMA,
            provisioning_mode=Tenant.ProvisioningMode.MANUAL,
            schema_name="acme_schema",
        )

        strategy = SchemaStrategy()
        strategy.activate(tenant)

        activate_schema.assert_called_once_with("acme_schema")
        deactivate_schema.assert_not_called()

    @patch("tenantkit.strategies.schema.strategy.activate_schema")
    @patch("tenantkit.strategies.schema.strategy.deactivate_schema")
    def test_deactivate_clears_context_and_resets_backend(
        self, deactivate_schema, activate_schema
    ):
        tenant = Tenant(
            slug="acme",
            name="Acme",
            isolation_mode=Tenant.IsolationMode.SCHEMA,
            provisioning_mode=Tenant.ProvisioningMode.MANUAL,
            schema_name="acme_schema",
        )

        strategy = SchemaStrategy()
        strategy.activate(tenant)
        strategy.deactivate()

        activate_schema.assert_called_once_with("acme_schema")
        deactivate_schema.assert_called_once()


class DatabaseStrategyTests(TestCase):
    def test_db_for_read_uses_metadata_alias_when_present(self):
        tenant = Tenant(
            slug="acme",
            name="Acme",
            isolation_mode=Tenant.IsolationMode.DATABASE,
            provisioning_mode=Tenant.ProvisioningMode.MANUAL,
            connection_alias="tenant_acme",
        )

        strategy = DatabaseStrategy()

        self.assertEqual(strategy.db_for_read(Tenant, tenant=tenant), "tenant_acme")
        self.assertEqual(strategy.db_for_write(Tenant, tenant=tenant), "tenant_acme")

    def test_db_for_read_defaults_to_default_without_alias(self):
        tenant = Tenant(
            slug="acme",
            name="Acme",
            isolation_mode=Tenant.IsolationMode.DATABASE,
            provisioning_mode=Tenant.ProvisioningMode.MANUAL,
            connection_alias="",
            metadata={},
        )

        strategy = DatabaseStrategy()

        self.assertEqual(strategy.db_for_read(Tenant, tenant=tenant), "default")
        self.assertEqual(strategy.db_for_write(Tenant, tenant=tenant), "default")


class BootstrapTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="owner", password="secret")

    @override_settings(TENANT_ENCRYPTION_KEY="unit-test-key")
    def test_register_and_unregister_database_tenant_connection(self):
        tenant = Tenant.objects.create(
            slug="acme-db",
            name="Acme DB",
            isolation_mode=Tenant.IsolationMode.DATABASE,
        )

        databases = cast(dict[str, dict[str, object]], connections.databases)

        self.assertTrue(register_database_tenant_connection(tenant))
        self.assertIn(str(tenant.connection_alias), databases)

        self.assertTrue(
            unregister_database_tenant_connection(str(tenant.connection_alias))
        )
        self.assertNotIn(str(tenant.connection_alias), databases)


class ProvisioningTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="owner", password="secret")

    @override_settings(TENANT_ENCRYPTION_KEY="unit-test-key")
    @patch("psycopg.connect")
    def test_ensure_database_exists_creates_missing_database(self, connect_mock):
        # Mock connection and cursor for database existence check (returns None = doesn't exist)
        conn_mock = MagicMock()
        cur_mock = MagicMock()
        cur_mock.fetchone.return_value = None  # Database doesn't exist
        conn_mock.cursor.return_value.__enter__ = MagicMock(return_value=cur_mock)
        conn_mock.cursor.return_value.__exit__ = MagicMock(return_value=False)

        # Mock connection for CREATE DATABASE
        conn_mock2 = MagicMock()
        cur_mock2 = MagicMock()
        conn_mock2.cursor.return_value.__enter__ = MagicMock(return_value=cur_mock2)
        conn_mock2.cursor.return_value.__exit__ = MagicMock(return_value=False)

        connect_mock.side_effect = [conn_mock, conn_mock2]

        self.assertTrue(
            ensure_database_exists(
                "postgresql://tenant:pass@localhost:5432/tenant_acme_db",
                "postgresql://admin:secret@localhost:5432/postgres",
            )
        )
        self.assertEqual(connect_mock.call_count, 2)

    @override_settings(TENANT_ENCRYPTION_KEY="unit-test-key")
    @patch("psycopg.connect")
    def test_ensure_database_exists_is_idempotent_when_database_already_exists(
        self, connect_mock
    ):
        # Mock connection and cursor that shows database already exists
        conn_mock = MagicMock()
        cur_mock = MagicMock()
        cur_mock.fetchone.return_value = (1,)  # Database exists
        conn_mock.cursor.return_value.__enter__ = MagicMock(return_value=cur_mock)
        conn_mock.cursor.return_value.__exit__ = MagicMock(return_value=False)

        connect_mock.return_value = conn_mock

        self.assertFalse(
            ensure_database_exists(
                "postgresql://tenant:pass@localhost:5432/tenant_acme_db",
                "postgresql://admin:secret@localhost:5432/postgres",
            )
        )
        connect_mock.assert_called_once()

    @patch("tenantkit.bootstrap.register_database_tenant_connection")
    @patch("tenantkit.models.Tenant.get_provisioning_connection_string")
    @patch("tenantkit.models.Tenant.get_connection_string")
    def test_ensure_database_tenant_ready_registers_tenant_after_create(
        self,
        get_connection_string_mock,
        get_provisioning_connection_string_mock,
        register_mock,
    ):
        """Test that ensure_database_tenant_ready orchestrates provisioning and registers connection."""
        get_connection_string_mock.return_value = (
            "postgresql://tenant:pass@localhost:5432/tenant_acme_db"
        )
        get_provisioning_connection_string_mock.return_value = (
            "postgresql://admin:secret@localhost:5432/postgres"
        )
        register_mock.return_value = True  # Connection registered

        tenant = Tenant.objects.create(
            slug="acme-db",
            name="Acme DB",
            isolation_mode=Tenant.IsolationMode.DATABASE,
        )
        tenant.set_provisioning_connection_string(
            "postgresql://admin:secret@localhost:5432/postgres"
        )

        # Mock the provisioning strategy to avoid DB calls
        mock_strategy = MagicMock()
        mock_strategy.ensure_database_exists.return_value = True
        mock_strategy.ensure_user_exists.return_value = True
        mock_strategy.grant_permissions.return_value = True

        with patch(
            "tenantkit.provisioning.ProvisioningStrategyFactory.get_strategy",
            return_value=mock_strategy,
        ):
            result = ensure_database_tenant_ready(tenant)

            self.assertTrue(result)
            register_mock.assert_called_once()
            mock_strategy.ensure_database_exists.assert_called_once()


class TenantAPITests(TestCase):
    def setUp(self):
        self.client = Client()
        self.owner = User.objects.create_user(username="owner", password="secret")

    @override_settings(TENANT_ENCRYPTION_KEY="unit-test-key")
    def test_post_auto_tenant(self):
        response = self.client.post(
            "/api/tenants/",
            data=json.dumps(
                {
                    "slug": "auto-acme",
                    "name": "Auto Acme",
                    "isolation_mode": "database",
                    "provisioning_mode": "auto",
                }
            ),
            content_type="application/json",
        )

        response = cast(Any, response)
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["slug"], "auto-acme")
        self.assertEqual(body["provisioning_mode"], "auto")
        self.assertTrue(body["connection_alias"])
        self.assertTrue(body["has_connection_string"])
        self.assertIsNone(body["connection_string"])

    @override_settings(TENANT_ENCRYPTION_KEY="unit-test-key")
    def test_post_manual_tenant(self):
        response = self.client.post(
            "/api/tenants/",
            data=json.dumps(
                {
                    "slug": "manual-acme",
                    "name": "Manual Acme",
                    "isolation_mode": "database",
                    "provisioning_mode": "manual",
                    "connection_alias": "tenant_manual_acme",
                    "connection_string": "postgresql://user:pass@localhost:5432/manual_acme",
                    "provisioning_connection_string": "postgresql://admin:secret@localhost:5432/postgres",
                }
            ),
            content_type="application/json",
        )

        response = cast(Any, response)
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["slug"], "manual-acme")
        self.assertEqual(body["provisioning_mode"], "manual")
        self.assertEqual(body["connection_alias"], "tenant_manual_acme")
        self.assertTrue(body["has_connection_string"])
        self.assertTrue(body["has_provisioning_connection_string"])
        self.assertIsNone(body["connection_string"])

    def test_delete_tenant(self):
        tenant = Tenant.objects.create(
            slug="delete-me",
            name="Delete Me",
            isolation_mode=Tenant.IsolationMode.SCHEMA,
        )

        response = self.client.delete(f"/api/tenants/{tenant.slug}/")
        response = cast(Any, response)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["deleted"])

    def test_tenant_operation_api_returns_structured_error_for_schema_on_sqlite(self):
        tenant = Tenant.objects.create(
            slug="schema-test",
            name="Schema Test",
            isolation_mode=Tenant.IsolationMode.SCHEMA,
        )

        response = self.client.post(
            f"/api/tenants/{tenant.slug}/operations/",
            data=json.dumps({"operation": "provision_migrate"}),
            content_type="application/json",
        )

        response = cast(Any, response)
        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertEqual(body["error"]["code"], "SCHEMA_PROVISIONING_UNSUPPORTED")
        self.assertIn("PostgreSQL", body["error"]["message"])


class TenantMiddlewareTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(username="owner", password="secret")
        self.tenant = Tenant.objects.create(
            slug="acme",
            name="Acme",
            isolation_mode=Tenant.IsolationMode.SCHEMA,
        )

    def tearDown(self):
        clear_current_tenant()
        clear_current_strategy()

    def test_middleware_resolves_tenant_from_header_and_clears_context(self):
        request = self.factory.get("/", **{"HTTP_X_TENANT": self.tenant.slug})

        seen = {}

        def get_response(req):
            seen["tenant"] = get_current_tenant()
            seen["strategy"] = get_current_strategy()
            return "ok"

        middleware = TenantMiddleware(get_response)
        response = middleware(request)

        request = cast(Any, request)
        self.assertEqual(response, "ok")
        self.assertEqual(request.tenant.pk, self.tenant.pk)
        self.assertIsInstance(request.tenant_strategy, SchemaStrategy)
        self.assertEqual(seen["tenant"].pk, self.tenant.pk)
        self.assertIsInstance(seen["strategy"], SchemaStrategy)
        self.assertIsNone(get_current_tenant())
        self.assertIsNone(get_current_strategy())

    def test_middleware_ignores_missing_tenant_header(self):
        request = self.factory.get("/")

        def get_response(req):
            self.assertIsNone(get_current_tenant())
            self.assertIsNone(get_current_strategy())
            return "ok"

        middleware = TenantMiddleware(get_response)
        response = middleware(request)

        request = cast(Any, request)
        self.assertEqual(response, "ok")
        self.assertIsNone(request.tenant)
        self.assertIsNone(request.tenant_strategy)

    def test_middleware_uses_session_tenant_inside_admin(self):
        request = self.factory.get("/admin/")
        request = cast(Any, request)
        request.session = SessionStore()
        request.session[SESSION_AUTH_SCOPE] = AUTH_SCOPE_TENANT
        request.session[SESSION_ACTIVE_TENANT_ID] = str(self.tenant.pk)

        def get_response(req):
            return "ok"

        middleware = TenantMiddleware(get_response)
        response = middleware(request)

        self.assertEqual(response, "ok")
        self.assertEqual(request.tenant.pk, self.tenant.pk)
        self.assertIsInstance(request.tenant_strategy, SchemaStrategy)


class TenantAdminSiteTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(username="owner", password="secret")
        self.superuser = User.objects.create_superuser(
            username="root", password="secret", email="root@example.com"
        )
        self.tenant = Tenant.objects.create(
            slug="acme",
            name="Acme",
            isolation_mode=Tenant.IsolationMode.SCHEMA,
        )

    def _request(self, method: str = "get", path: str = "/admin/tenant-switch/"):
        request = getattr(self.factory, method)(path)
        request = cast(Any, request)
        request.user = self.user
        request.session = SessionStore()
        request.session[SESSION_AUTH_SCOPE] = AUTH_SCOPE_GLOBAL
        request._dont_enforce_csrf_checks = True
        return request

    def test_tenant_switch_view_sets_tenant_in_session(self):
        request = self.factory.post(
            "/admin/tenant-switch/",
            data={"tenant": str(self.tenant.pk)},
        )
        request = cast(Any, request)
        request.user = self.user
        request.session = SessionStore()
        request.session[SESSION_AUTH_SCOPE] = AUTH_SCOPE_GLOBAL

        response = cast(Any, tenantkit_admin_site).tenant_switch_view(request)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(request.session[SESSION_AUTH_SCOPE], AUTH_SCOPE_TENANT)
        self.assertEqual(request.session[SESSION_ACTIVE_TENANT_ID], str(self.tenant.pk))

    def test_tenant_switch_view_clears_tenant_for_default(self):
        request = self.factory.post(
            "/admin/tenant-switch/",
            data={"tenant": ""},
        )
        request = cast(Any, request)
        request.user = self.user
        request.session = SessionStore()
        request.session[SESSION_AUTH_SCOPE] = AUTH_SCOPE_TENANT
        request.session[SESSION_ACTIVE_TENANT_ID] = str(self.tenant.pk)

        response = cast(Any, tenantkit_admin_site).tenant_switch_view(request)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(request.session[SESSION_AUTH_SCOPE], AUTH_SCOPE_GLOBAL)
        self.assertNotIn(SESSION_ACTIVE_TENANT_ID, request.session)

    def test_each_context_exposes_tenant_ui_state(self):
        request = self._request()
        request.session[SESSION_AUTH_SCOPE] = AUTH_SCOPE_TENANT
        request.session[SESSION_ACTIVE_TENANT_ID] = str(self.tenant.pk)

        context = tenantkit_admin_site.each_context(request)

        self.assertEqual(context["tenant_scope_label"], "Tenant")
        self.assertEqual(context["current_tenant_label"], self.tenant.name)
        self.assertTrue(context["tenant_switch_url"])
        self.assertTrue(context["available_tenants"])

    def test_framework_shared_models_are_registered_on_default_admin_site(self):
        self.assertIn(Tenant, admin.site._registry)
        self.assertIn(TenantInvitation, admin.site._registry)
        self.assertIn(TenantSetting, admin.site._registry)

    def test_user_and_group_are_registered_as_both_scope_admins(self):
        self.assertIsInstance(admin.site._registry[User], BothScopeUserAdmin)
        self.assertIsInstance(admin.site._registry[Group], BothScopeGroupAdmin)

    def test_admin_app_list_shows_shared_models_in_shared_scope(self):
        request = self._request()
        request.user = self.superuser

        app_list = tenantkit_admin_site.get_app_list(request)
        model_names = [
            model["object_name"] for app in app_list for model in app["models"]
        ]

        self.assertIn("Tenant", model_names)

    def test_admin_app_list_hides_shared_models_in_tenant_scope(self):
        request = self._request()
        request.user = self.superuser
        request.session[SESSION_AUTH_SCOPE] = AUTH_SCOPE_TENANT
        request.session[SESSION_ACTIVE_TENANT_ID] = str(self.tenant.pk)

        app_list = tenantkit_admin_site.get_app_list(request)
        model_names = [
            model["object_name"] for app in app_list for model in app["models"]
        ]

        self.assertNotIn("Tenant", model_names)

    def test_tenant_admin_exposes_operation_urls(self):
        admin = tenantkit_admin_site._registry[Tenant]
        assert isinstance(admin, TenantAdmin)

        provision_url = admin.get_operation_url(self.tenant, "provision_migrate")
        self.assertIn("/ops/provision_migrate/", provision_url)
        self.assertIn(str(self.tenant.pk), provision_url)

    @patch("tenantkit.admin.provision_and_migrate_tenant")
    def test_tenant_operation_view_posts_and_redirects(self, op_mock):
        admin = tenantkit_admin_site._registry[Tenant]
        assert isinstance(admin, TenantAdmin)
        op_mock.return_value = True

        request = self.factory.post(
            f"/admin/tenantkit/tenant/{self.tenant.pk}/ops/provision_migrate/"
        )
        request = cast(Any, request)
        request.user = self.user
        request.session = SessionStore()

        response = admin.tenant_operation_view(
            request, object_id=str(self.tenant.pk), operation="provision_migrate"
        )

        self.assertEqual(response.status_code, 302)
        op_mock.assert_called_once()

    @patch("tenantkit.admin_site.get_user_model")
    def test_tenant_login_form_rejects_global_fallback_when_user_missing_in_tenant(
        self, mock_get_user_model
    ):
        request = self._request("post", "/admin/login/")
        request.user = AnonymousUser()

        mock_manager = MagicMock()
        mock_manager.db_manager.return_value.get_by_natural_key.side_effect = (
            User.DoesNotExist
        )
        mock_model = MagicMock()
        mock_model._default_manager = mock_manager
        mock_model.DoesNotExist = User.DoesNotExist
        mock_get_user_model.return_value = mock_model

        form = TenantAdminAuthenticationForm(
            request=request,
            data={
                "username": "admin",
                "password": "admin123",
                "tenant": self.tenant.pk,
            },
        )

        self.assertFalse(form.is_valid())
        self.assertIn(
            "Please enter the correct username and password for a staff account.",
            form.non_field_errors()[0],
        )

    @patch("tenantkit.admin_site.get_user_model")
    def test_tenant_login_form_authenticates_user_from_tenant_context(
        self, mock_get_user_model
    ):
        request = self._request("post", "/admin/login/")
        request.user = AnonymousUser()

        tenant_user = MagicMock()
        tenant_user.check_password.return_value = True
        tenant_user.is_active = True
        tenant_user.is_staff = True

        mock_manager = MagicMock()
        mock_manager.db_manager.return_value.get_by_natural_key.return_value = (
            tenant_user
        )
        mock_model = MagicMock()
        mock_model._default_manager = mock_manager
        mock_model.DoesNotExist = User.DoesNotExist
        mock_get_user_model.return_value = mock_model

        form = TenantAdminAuthenticationForm(
            request=request,
            data={
                "username": "tenant-admin",
                "password": "secret",
                "tenant": self.tenant.pk,
            },
        )

        self.assertTrue(form.is_valid())
        self.assertIs(form.get_user(), tenant_user)
        assert form.tenant_obj is not None
        self.assertEqual(form.tenant_obj.pk, self.tenant.pk)


class _DummyTokenSerializer:
    def get_token(self, user: Any) -> dict[str, Any]:
        return {"sub": str(user.pk)}


class _TenantAwareTokenSerializer(TenantClaimsMixin, _DummyTokenSerializer):
    pass


class _PayloadToken:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload


class _BackendWithoutHeader:
    def __init__(self, result: tuple[Any, Any] | None) -> None:
        self.result = result

    def authenticate(self, request: Any) -> tuple[Any, Any] | None:
        return self.result


class _BackendWithHeader(_BackendWithoutHeader):
    def authenticate_header(self, request: Any) -> str:
        return "Custom"


class _ConfigurableJWTBackend(_BackendWithHeader):
    def __init__(self) -> None:
        super().__init__((User(), {"tenant_slug": "config-tenant"}))


class TenantAdminAuthenticationFormCleanTests(TestCase):
    """Tests for TenantAdminAuthenticationForm.clean() with SCHEMA and DATABASE tenants."""

    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(username="testuser", password="testpass123")
        self.superuser = User.objects.create_superuser(
            username="admin", password="admin123", email="admin@example.com"
        )

        # Create SCHEMA tenant
        self.schema_tenant = Tenant.objects.create(
            slug="test-schema",
            name="Test Schema Tenant",
            isolation_mode=Tenant.IsolationMode.SCHEMA,
            provisioning_mode=Tenant.ProvisioningMode.MANUAL,
            schema_name="test_tenant_schema",
        )

        # Create DATABASE tenant
        self.database_tenant = Tenant.objects.create(
            slug="test-db",
            name="Test DB Tenant",
            isolation_mode=Tenant.IsolationMode.DATABASE,
            provisioning_mode=Tenant.ProvisioningMode.MANUAL,
            connection_alias="tenant_test_db",
        )

    def _create_mock_cursor(self, search_path='"$user", public'):
        """Create a mock cursor that simulates PostgreSQL behavior."""
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (search_path,)
        return mock_cursor

    def test_schema_tenant_search_path_restoration_with_complex_values(self):
        """
        Test that search_path is correctly restored even with complex values
        like '"$user", public' that would break with f-string interpolation.
        """
        # Complex search_path that would break with f-string interpolation
        complex_search_path = '"$user", public'

        mock_cursor = self._create_mock_cursor(complex_search_path)
        mock_connection = MagicMock()
        mock_connection.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_connection.cursor.return_value.__exit__ = MagicMock(return_value=False)

        with patch("tenantkit.admin_site.connection", mock_connection):
            with patch("tenantkit.admin_site.get_user_model") as mock_get_user_model:
                # Mock user lookup to succeed
                mock_user = MagicMock()
                mock_user.check_password.return_value = True
                mock_user.is_active = True
                mock_user.is_staff = True

                mock_manager = MagicMock()
                mock_manager.get_by_natural_key.return_value = mock_user
                mock_model = MagicMock()
                mock_model._default_manager = mock_manager
                mock_model.DoesNotExist = User.DoesNotExist
                mock_get_user_model.return_value = mock_model

                form = TenantAdminAuthenticationForm(
                    data={
                        "username": "admin",
                        "password": "admin123",
                        "tenant": self.schema_tenant.pk,
                    }
                )

                # Form should be valid
                self.assertTrue(form.is_valid())

                # Verify search_path was captured with current_setting
                execute_calls = [call[0][0] for call in mock_cursor.execute.call_args_list]
                self.assertTrue(
                    any("current_setting" in str(call) for call in execute_calls),
                    "current_setting should be used to capture search_path"
                )

                # Verify set_config was called to restore the original search_path
                set_config_calls = [
                    call for call in execute_calls
                    if "set_config" in str(call) and "search_path" in str(call)
                ]
                self.assertEqual(len(set_config_calls), 2, "set_config should be called twice (set and restore)")

                # Verify the restoration uses %s placeholder (not f-string)
                restore_call = set_config_calls[-1]
                self.assertIn("%s", str(restore_call), "Restoration should use %s placeholder")
                self.assertNotIn('"$user"', str(restore_call).split("%s")[0],
                    "Complex values should be passed as parameters, not interpolated")

    def test_schema_tenant_login_success(self):
        """
        Test successful login with SCHEMA tenant selected.
        Verifies that:
        - User is found in tenant schema
        - Password is checked correctly
        - User is authenticated
        - tenant_obj is set in form
        """
        mock_cursor = self._create_mock_cursor("public")
        mock_connection = MagicMock()
        mock_connection.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_connection.cursor.return_value.__exit__ = MagicMock(return_value=False)

        with patch("tenantkit.admin_site.connection", mock_connection):
            with patch("tenantkit.admin_site.get_user_model") as mock_get_user_model:
                # Create mock user that simulates a user in the tenant schema
                mock_user = MagicMock()
                mock_user.check_password.return_value = True
                mock_user.is_active = True
                mock_user.is_staff = True
                mock_user.pk = 123

                mock_manager = MagicMock()
                mock_manager.get_by_natural_key.return_value = mock_user
                mock_model = MagicMock()
                mock_model._default_manager = mock_manager
                mock_model.DoesNotExist = User.DoesNotExist
                mock_get_user_model.return_value = mock_model

                form = TenantAdminAuthenticationForm(
                    data={
                        "username": "tenantuser",
                        "password": "correctpass",
                        "tenant": self.schema_tenant.pk,
                    }
                )

                # Form should be valid
                is_valid = form.is_valid()
                self.assertTrue(is_valid, f"Form errors: {form.errors}")

                # Verify user was looked up
                mock_manager.get_by_natural_key.assert_called_once_with("tenantuser")

                # Verify password was checked
                mock_user.check_password.assert_called_once_with("correctpass")

                # Verify user is cached in form
                self.assertEqual(form.user_cache, mock_user)

                # Verify tenant_obj is set
                self.assertIsNotNone(form.tenant_obj)
                self.assertEqual(form.tenant_obj.pk, self.schema_tenant.pk)

                # Verify search_path was set to tenant schema
                execute_calls = [call[0][0] for call in mock_cursor.execute.call_args_list]
                set_tenant_path_call = None
                for call in execute_calls:
                    if "set_config" in str(call) and "test_tenant_schema" in str(call):
                        set_tenant_path_call = call
                        break
                self.assertIsNotNone(set_tenant_path_call, "Should set search_path to tenant schema")

    def test_schema_tenant_login_user_not_found(self):
        """
        Test that login fails correctly when user doesn't exist in tenant schema.
        Should NOT fallback to public schema user.
        """
        mock_cursor = self._create_mock_cursor("public")
        mock_connection = MagicMock()
        mock_connection.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_connection.cursor.return_value.__exit__ = MagicMock(return_value=False)

        with patch("tenantkit.admin_site.connection", mock_connection):
            with patch("tenantkit.admin_site.get_user_model") as mock_get_user_model:
                # Simulate user not found in tenant schema
                mock_manager = MagicMock()
                mock_manager.get_by_natural_key.side_effect = User.DoesNotExist
                mock_model = MagicMock()
                mock_model._default_manager = mock_manager
                mock_model.DoesNotExist = User.DoesNotExist
                mock_get_user_model.return_value = mock_model

                form = TenantAdminAuthenticationForm(
                    data={
                        "username": "nonexistentuser",
                        "password": "anypassword",
                        "tenant": self.schema_tenant.pk,
                    }
                )

                # Form should be invalid
                self.assertFalse(form.is_valid())

                # Verify error message
                self.assertIn(
                    "Please enter the correct username and password",
                    str(form.non_field_errors())
                )

                # Verify search_path was still restored in finally block
                execute_calls = [call[0][0] for call in mock_cursor.execute.call_args_list]
                set_config_calls = [call for call in execute_calls if "set_config" in str(call)]
                self.assertEqual(len(set_config_calls), 2, "Should set and restore search_path even on failure")

    def test_schema_tenant_login_wrong_password(self):
        """
        Test that login fails correctly with wrong password in tenant schema.
        """
        mock_cursor = self._create_mock_cursor("public")
        mock_connection = MagicMock()
        mock_connection.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_connection.cursor.return_value.__exit__ = MagicMock(return_value=False)

        with patch("tenantkit.admin_site.connection", mock_connection):
            with patch("tenantkit.admin_site.get_user_model") as mock_get_user_model:
                # Create mock user with wrong password
                mock_user = MagicMock()
                mock_user.check_password.return_value = False  # Wrong password

                mock_manager = MagicMock()
                mock_manager.get_by_natural_key.return_value = mock_user
                mock_model = MagicMock()
                mock_model._default_manager = mock_manager
                mock_model.DoesNotExist = User.DoesNotExist
                mock_get_user_model.return_value = mock_model

                form = TenantAdminAuthenticationForm(
                    data={
                        "username": "existinguser",
                        "password": "wrongpassword",
                        "tenant": self.schema_tenant.pk,
                    }
                )

                # Form should be invalid
                self.assertFalse(form.is_valid())

                # Verify error message
                self.assertIn(
                    "Please enter the correct username and password",
                    str(form.non_field_errors())
                )

                # Verify password was checked
                mock_user.check_password.assert_called_once_with("wrongpassword")

    def test_schema_tenant_uses_quote_ident(self):
        """
        Test that schema names are properly escaped using quote_ident.
        This prevents SQL injection via schema_name.
        """
        # Create a tenant with a malicious schema name
        malicious_tenant = Tenant.objects.create(
            slug="malicious-tenant",
            name="Malicious Tenant",
            isolation_mode=Tenant.IsolationMode.SCHEMA,
            provisioning_mode=Tenant.ProvisioningMode.MANUAL,
            schema_name="public'; DROP TABLE users; --",
        )

        mock_cursor = self._create_mock_cursor("public")
        mock_connection = MagicMock()
        mock_connection.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_connection.cursor.return_value.__exit__ = MagicMock(return_value=False)

        with patch("tenantkit.admin_site.connection", mock_connection):
            with patch("tenantkit.admin_site.get_user_model") as mock_get_user_model:
                mock_user = MagicMock()
                mock_user.check_password.return_value = True
                mock_user.is_active = True
                mock_user.is_staff = True

                mock_manager = MagicMock()
                mock_manager.get_by_natural_key.return_value = mock_user
                mock_model = MagicMock()
                mock_model._default_manager = mock_manager
                mock_model.DoesNotExist = User.DoesNotExist
                mock_get_user_model.return_value = mock_model

                form = TenantAdminAuthenticationForm(
                    data={
                        "username": "user",
                        "password": "pass",
                        "tenant": malicious_tenant.pk,
                    }
                )

                form.is_valid()

                # Verify that quote_ident is used in the SQL
                execute_calls = [call[0][0] for call in mock_cursor.execute.call_args_list]
                set_config_calls = [
                    call for call in execute_calls
                    if "set_config" in str(call) and "search_path" in str(call)
                ]

                # The first set_config should use quote_ident
                self.assertTrue(len(set_config_calls) >= 1, "Should have set_config calls")
                first_set_config = set_config_calls[0]
                self.assertIn("quote_ident", str(first_set_config).lower(),
                    "Schema name should be escaped using quote_ident")

                # Verify the malicious schema name is passed as a parameter (%s)
                # and not directly interpolated
                call_args = mock_cursor.execute.call_args_list
                for call in call_args:
                    sql, params = call[0]
                    if "set_config" in str(sql) and "search_path" in str(sql):
                        # Check that the schema name is in params, not in the SQL
                        if params and malicious_tenant.schema_name in params:
                            self.assertNotIn(malicious_tenant.schema_name, str(sql),
                                "Malicious schema name should be a parameter, not in SQL")

    def test_database_tenant_login_still_works(self):
        """
        Regression test: Ensure DATABASE tenant login wasn't broken by SCHEMA fix.
        """
        with patch("tenantkit.admin_site.ensure_runtime_tenant_connection") as mock_ensure:
            with patch("tenantkit.admin_site.DatabaseStrategy") as mock_strategy_class:
                with patch("tenantkit.admin_site.get_user_model") as mock_get_user_model:
                    # Mock the strategy
                    mock_strategy = MagicMock()
                    mock_strategy.db_for_read.return_value = "tenant_test_db"
                    mock_strategy_class.return_value = mock_strategy

                    # Mock user lookup
                    mock_user = MagicMock()
                    mock_user.check_password.return_value = True
                    mock_user.is_active = True
                    mock_user.is_staff = True

                    mock_manager = MagicMock()
                    mock_manager.db_manager.return_value.get_by_natural_key.return_value = mock_user
                    mock_model = MagicMock()
                    mock_model._default_manager = mock_manager
                    mock_model.DoesNotExist = User.DoesNotExist
                    mock_get_user_model.return_value = mock_model

                    form = TenantAdminAuthenticationForm(
                        data={
                            "username": "dbuser",
                            "password": "dbpass",
                            "tenant": self.database_tenant.pk,
                        }
                    )

                    # Form should be valid
                    is_valid = form.is_valid()
                    self.assertTrue(is_valid, f"Form errors: {form.errors}")

                    # Verify ensure_runtime_tenant_connection was called
                    mock_ensure.assert_called_once_with(self.database_tenant)

                    # Verify DatabaseStrategy was instantiated
                    mock_strategy_class.assert_called_once()

                    # Verify db_for_read was called
                    mock_strategy.db_for_read.assert_called_once()

                    # Verify user was looked up using the correct database alias
                    mock_manager.db_manager.assert_called_once_with("tenant_test_db")
                    mock_manager.db_manager.return_value.get_by_natural_key.assert_called_once_with("dbuser")

                    # Verify user is cached
                    self.assertEqual(form.user_cache, mock_user)

                    # Verify tenant_obj is set
                    self.assertIsNotNone(form.tenant_obj)
                    self.assertEqual(form.tenant_obj.pk, self.database_tenant.pk)


class AuthHelpersTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(
            username="authuser", email="auth@example.com", password="secret"
        )
        self.tenant = Tenant.objects.create(
            slug="auth-tenant",
            name="Auth Tenant",
            isolation_mode=Tenant.IsolationMode.SCHEMA,
        )

    def tearDown(self):
        clear_current_tenant()

    def test_claims_mixin_adds_tenant_slug_when_context_exists(self):
        set_current_tenant(self.tenant)

        token = _TenantAwareTokenSerializer().get_token(self.user)

        self.assertEqual(token["tenant_slug"], self.tenant.slug)
        self.assertEqual(token["sub"], str(self.user.pk))

    def test_claims_mixin_leaves_token_unchanged_without_tenant_context(self):
        token = _TenantAwareTokenSerializer().get_token(self.user)

        self.assertEqual(token, {"sub": str(self.user.pk)})

    def test_token_validator_passes_when_tenant_matches(self):
        validator = TenantTokenValidator()
        request = self.factory.get("/api/")
        set_current_tenant(self.tenant)

        validator.validate_tenant({"tenant_slug": self.tenant.slug}, request)

    def test_token_validator_fails_when_claim_is_missing(self):
        validator = TenantTokenValidator()
        request = self.factory.get("/api/")
        set_current_tenant(self.tenant)

        with self.assertRaises(AuthenticationFailed) as exc:
            validator.validate_tenant({}, request)

        self.assertIn("Token does not contain tenant information", str(exc.exception))

    def test_token_validator_fails_when_tenant_context_is_missing(self):
        validator = TenantTokenValidator()
        request = self.factory.get("/api/")

        with self.assertRaises(AuthenticationFailed) as exc:
            validator.validate_tenant({"tenant_slug": self.tenant.slug}, request)

        self.assertIn("No tenant context available", str(exc.exception))

    def test_token_validator_fails_when_tenant_mismatches(self):
        validator = TenantTokenValidator()
        request = self.factory.get("/api/")
        set_current_tenant(self.tenant)

        with self.assertRaises(AuthenticationFailed) as exc:
            validator.validate_tenant({"tenant_slug": "other-tenant"}, request)

        self.assertIn(self.tenant.slug, str(exc.exception))
        self.assertIn("other-tenant", str(exc.exception))

    def test_jwt_authentication_returns_none_when_backend_returns_none(self):
        authentication = TenantJWTAuthentication(backend=_BackendWithoutHeader(None))

        result = authentication.authenticate(self.factory.get("/api/"))

        self.assertIsNone(result)

    def test_jwt_authentication_validates_dict_tokens(self):
        backend = _BackendWithoutHeader((self.user, {"tenant_slug": self.tenant.slug}))
        authentication = TenantJWTAuthentication(backend=backend)
        request = self.factory.get("/api/")
        set_current_tenant(self.tenant)

        result = authentication.authenticate(request)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result[0], self.user)
        self.assertEqual(result[1]["tenant_slug"], self.tenant.slug)

    def test_jwt_authentication_validates_payload_attribute_tokens(self):
        token = _PayloadToken({"tenant_slug": self.tenant.slug})
        backend = _BackendWithoutHeader((self.user, token))
        authentication = TenantJWTAuthentication(backend=backend)
        request = self.factory.get("/api/")
        set_current_tenant(self.tenant)

        result = authentication.authenticate(request)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result[1], token)

    def test_jwt_authentication_skips_validation_for_anonymous_user(self):
        backend = _BackendWithoutHeader((AnonymousUser(), object()))
        authentication = TenantJWTAuthentication(backend=backend)

        result = authentication.authenticate(self.factory.get("/api/"))

        self.assertIsNotNone(result)
        assert result is not None
        self.assertIsInstance(result[0], AnonymousUser)

    def test_jwt_authentication_returns_bearer_without_backend_header(self):
        authentication = TenantJWTAuthentication(backend=_BackendWithoutHeader(None))

        header = authentication.authenticate_header(self.factory.get("/api/"))

        self.assertEqual(header, "Bearer")

    def test_jwt_authentication_delegates_authenticate_header_when_available(self):
        authentication = TenantJWTAuthentication(backend=_BackendWithHeader(None))

        header = authentication.authenticate_header(self.factory.get("/api/"))

        self.assertEqual(header, "Custom")

    def test_jwt_authentication_raises_clear_error_without_backend(self):
        authentication = TenantJWTAuthentication()

        with self.assertRaises(AuthenticationFailed) as exc:
            authentication.authenticate(self.factory.get("/api/"))

        self.assertIn("No JWT backend configured", str(exc.exception))
        self.assertIn("future phase", str(exc.exception))

    def test_jwt_authentication_raises_clear_error_for_unsupported_token(self):
        backend = _BackendWithoutHeader((self.user, object()))
        authentication = TenantJWTAuthentication(backend=backend)
        request = self.factory.get("/api/")
        set_current_tenant(self.tenant)

        with self.assertRaises(AuthenticationFailed) as exc:
            authentication.authenticate(request)

        self.assertIn("Unsupported token representation", str(exc.exception))
        self.assertIn("future phase", str(exc.exception))

    @override_settings(TENANTKIT_JWT_BACKEND="tenantkit.tests._ConfigurableJWTBackend")
    def test_jwt_authentication_loads_backend_from_settings(self):
        authentication = TenantJWTAuthentication()
        request = self.factory.get("/api/")
        config_tenant = Tenant.objects.create(
            slug="config-tenant",
            name="Configured Tenant",
            isolation_mode=Tenant.IsolationMode.SCHEMA,
        )
        set_current_tenant(config_tenant)

        result = authentication.authenticate(request)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result[1]["tenant_slug"], config_tenant.slug)

    @override_settings(TENANTKIT_JWT_BACKEND="tenantkit.missing.DoesNotExist")
    def test_jwt_authentication_raises_improperly_configured_for_invalid_backend(self):
        with self.assertRaises(ImproperlyConfigured) as exc:
            TenantJWTAuthentication()

        self.assertIn("Could not import JWT backend", str(exc.exception))
