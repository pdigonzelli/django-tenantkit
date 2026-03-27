import json
import subprocess

from django.contrib.auth import get_user_model
from django.contrib.sessions.backends.db import SessionStore
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, connections, models
from django.test import (
    Client,
    RequestFactory,
    TestCase,
    TransactionTestCase,
    override_settings,
)
from unittest.mock import MagicMock, patch
from typing import Any, cast

from multitenant.admin_site import (
    AUTH_SCOPE_GLOBAL,
    AUTH_SCOPE_TENANT,
    SESSION_ACTIVE_TENANT_ID,
    SESSION_AUTH_SCOPE,
    multitenant_admin_site,
)
from multitenant.admin import TenantAdmin, TenantAdminForm
from multitenant.connections import parse_connection_url
from multitenant.admin_base import TenantSharedModelAdmin
from multitenant.core.context import (
    clear_current_strategy,
    clear_current_tenant,
    get_current_strategy,
    get_current_tenant,
    set_current_strategy,
    set_current_tenant,
)
from multitenant.bootstrap import (
    register_database_tenant_connection,
    unregister_database_tenant_connection,
)
from multitenant.crypto import decrypt_text, encrypt_text
from multitenant.middleware.tenant import TenantMiddleware
from multitenant.models import Tenant, TenantMembership
from multitenant.models import TenantSharedModel
from multitenant.provisioning import (
    ensure_database_exists,
    ensure_database_tenant_ready,
)
from multitenant.routers.tenant import TenantRouter
from multitenant.strategies.database.strategy import DatabaseStrategy
from multitenant.strategies.schema.strategy import SchemaStrategy


User = get_user_model()


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
            created_by=self.user,
            updated_by=self.user,
        )

        self.assertTrue(tenant.schema_name)
        self.assertIsNone(tenant.connection_alias)
        self.assertIsNone(tenant.connection_string)

    def test_database_tenant_auto_generates_alias_and_connection_string(self):
        tenant = Tenant.objects.create(
            slug="acme-db",
            name="Acme DB",
            isolation_mode=Tenant.IsolationMode.DATABASE,
            created_by=self.user,
            updated_by=self.user,
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

        with self.assertRaises(Exception):
            tenant.save()

    def test_schema_tenant_rejects_explicit_connection_alias(self):
        tenant = Tenant(
            slug="acme",
            name="Acme",
            isolation_mode=Tenant.IsolationMode.SCHEMA,
            provisioning_mode=Tenant.ProvisioningMode.MANUAL,
            connection_alias="tenant_acme",
        )

        with self.assertRaises(Exception):
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

        with self.assertRaises(Exception):
            tenant.save()

    def test_soft_delete_and_restore(self):
        tenant = Tenant.objects.create(
            slug="acme",
            name="Acme",
            isolation_mode=Tenant.IsolationMode.SCHEMA,
            created_by=self.user,
            updated_by=self.user,
        )

        self.assertFalse(tenant.deleted)
        self.assertTrue(tenant.is_active)

        tenant.soft_delete(user=self.user)
        tenant.refresh_from_db()

        self.assertTrue(tenant.deleted)
        self.assertFalse(tenant.is_active)
        self.assertEqual(tenant.deleted_by, self.user)

        tenant.restore(user=self.user)
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


class TenantMembershipTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="owner", password="secret")
        self.member = User.objects.create_user(username="member", password="secret")
        self.tenant = Tenant.objects.create(
            slug="acme",
            name="Acme",
            isolation_mode=Tenant.IsolationMode.SCHEMA,
            created_by=self.user,
            updated_by=self.user,
        )

    def test_unique_tenant_membership(self):
        TenantMembership.objects.create(
            tenant=self.tenant,
            user=self.member,
            role=TenantMembership.Role.ADMIN,
            created_by=self.user,
            updated_by=self.user,
        )

        with self.assertRaises(IntegrityError):
            TenantMembership.objects.create(
                tenant=self.tenant,
                user=self.member,
                role=TenantMembership.Role.MEMBER,
            )


class TenantAdminFormTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="owner", password="secret")
        self.tenant = Tenant.objects.create(
            slug="schema-tenant",
            name="Schema Tenant",
            isolation_mode=Tenant.IsolationMode.SCHEMA,
            provisioning_mode=Tenant.ProvisioningMode.MANUAL,
            schema_name="schema_tenant",
            created_by=self.user,
            updated_by=self.user,
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
            created_by=self.user,
            updated_by=self.user,
        )
        self.tenant_two = Tenant.objects.create(
            slug="tenant-two",
            name="Tenant Two",
            isolation_mode=Tenant.IsolationMode.SCHEMA,
            created_by=self.user,
            updated_by=self.user,
        )

    def test_allowed_tenants_empty_means_shared_for_all(self):
        class TenantSharedThingA(TenantSharedModel):
            name = models.CharField(max_length=50)

            class Meta:  # type: ignore[valid-type]
                app_label = "multitenant"
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
            created_by=self.user,
            updated_by=self.user,
        )
        self.tenant_two = Tenant.objects.create(
            slug="tenant-two",
            name="Tenant Two",
            isolation_mode=Tenant.IsolationMode.SCHEMA,
            created_by=self.user,
            updated_by=self.user,
        )

    def test_tenant_shared_admin_filters_by_allowed_tenants(self):
        class TenantSharedThingB(TenantSharedModel):
            name = models.CharField(max_length=50)

            class Meta:  # type: ignore[valid-type]
                app_label = "multitenant"
                db_table = "multitenant_tenantsharedthing_b"

        class TenantSharedThingAdmin(TenantSharedModelAdmin):
            pass

        with connection.schema_editor() as editor:
            editor.create_model(TenantSharedThingB)

        admin = TenantSharedThingAdmin(TenantSharedThingB, multitenant_admin_site)

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

    def test_router_returns_none_without_tenant(self):
        router = TenantRouter()
        self.assertIsNone(router.db_for_read(Tenant))
        self.assertIsNone(router.db_for_write(Tenant))

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
        self.assertEqual(router.db_for_read(Tenant), "tenant_db")
        self.assertEqual(router.db_for_write(Tenant), "tenant_db")
        self.assertTrue(router.allow_migrate("tenant_db", "multitenant", "tenant"))

        self.assertEqual(len(strategy.read_calls), 1)
        self.assertEqual(len(strategy.write_calls), 1)
        self.assertEqual(len(strategy.migrate_calls), 1)


class SchemaStrategyTests(TestCase):
    @patch("multitenant.strategies.schema.strategy.activate_schema")
    @patch("multitenant.strategies.schema.strategy.deactivate_schema")
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

    @patch("multitenant.strategies.schema.strategy.activate_schema")
    @patch("multitenant.strategies.schema.strategy.deactivate_schema")
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
            created_by=self.user,
            updated_by=self.user,
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

    @patch("multitenant.bootstrap.register_database_tenant_connection")
    @patch("multitenant.models.Tenant.get_provisioning_connection_string")
    @patch("multitenant.models.Tenant.get_connection_string")
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
            created_by=self.user,
            updated_by=self.user,
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
            "multitenant.provisioning.ProvisioningStrategyFactory.get_strategy",
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
            created_by=self.owner,
            updated_by=self.owner,
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
            created_by=self.owner,
            updated_by=self.owner,
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
            created_by=self.user,
            updated_by=self.user,
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

        self.assertEqual(response, "ok")
        self.assertEqual(getattr(request, "tenant").pk, self.tenant.pk)
        self.assertIsInstance(getattr(request, "tenant_strategy"), SchemaStrategy)
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

        self.assertEqual(response, "ok")
        self.assertIsNone(getattr(request, "tenant"))
        self.assertIsNone(getattr(request, "tenant_strategy"))

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
        self.assertEqual(getattr(request, "tenant").pk, self.tenant.pk)
        self.assertIsInstance(getattr(request, "tenant_strategy"), SchemaStrategy)


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
            created_by=self.user,
            updated_by=self.user,
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

        response = multitenant_admin_site.tenant_switch_view(request)

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

        response = multitenant_admin_site.tenant_switch_view(request)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(request.session[SESSION_AUTH_SCOPE], AUTH_SCOPE_GLOBAL)
        self.assertNotIn(SESSION_ACTIVE_TENANT_ID, request.session)

    def test_each_context_exposes_tenant_ui_state(self):
        request = self._request()
        request.session[SESSION_AUTH_SCOPE] = AUTH_SCOPE_TENANT
        request.session[SESSION_ACTIVE_TENANT_ID] = str(self.tenant.pk)

        context = multitenant_admin_site.each_context(request)

        self.assertEqual(context["tenant_scope_label"], "Tenant")
        self.assertEqual(context["current_tenant_label"], self.tenant.name)
        self.assertTrue(context["tenant_switch_url"])
        self.assertTrue(context["available_tenants"])

    def test_admin_app_list_shows_shared_models_in_shared_scope(self):
        request = self._request()
        request.user = self.superuser

        app_list = multitenant_admin_site.get_app_list(request)
        model_names = [
            model["object_name"] for app in app_list for model in app["models"]
        ]

        self.assertIn("Tenant", model_names)

    def test_admin_app_list_hides_shared_models_in_tenant_scope(self):
        request = self._request()
        request.user = self.superuser
        request.session[SESSION_AUTH_SCOPE] = AUTH_SCOPE_TENANT
        request.session[SESSION_ACTIVE_TENANT_ID] = str(self.tenant.pk)

        app_list = multitenant_admin_site.get_app_list(request)
        model_names = [
            model["object_name"] for app in app_list for model in app["models"]
        ]

        self.assertNotIn("Tenant", model_names)

    def test_tenant_admin_exposes_operation_urls(self):
        admin = multitenant_admin_site._registry[Tenant]
        assert isinstance(admin, TenantAdmin)

        provision_url = admin.get_operation_url(self.tenant, "provision_migrate")
        self.assertIn("/ops/provision_migrate/", provision_url)
        self.assertIn(str(self.tenant.pk), provision_url)

    @patch("multitenant.admin.provision_and_migrate_tenant")
    def test_tenant_operation_view_posts_and_redirects(self, op_mock):
        admin = multitenant_admin_site._registry[Tenant]
        assert isinstance(admin, TenantAdmin)
        op_mock.return_value = True

        request = self.factory.post(
            f"/admin/multitenant/tenant/{self.tenant.pk}/ops/provision_migrate/"
        )
        request = cast(Any, request)
        request.user = self.user
        request.session = SessionStore()

        response = admin.tenant_operation_view(
            request, object_id=str(self.tenant.pk), operation="provision_migrate"
        )

        self.assertEqual(response.status_code, 302)
        op_mock.assert_called_once()
