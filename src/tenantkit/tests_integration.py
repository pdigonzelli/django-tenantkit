"""
Integration tests for database provisioning with real PostgreSQL.

These tests require a running PostgreSQL instance.
They create and drop real databases during execution.
"""

# pyright: reportCallIssue=false, reportArgumentType=false, reportOptionalMemberAccess=false

import os
import uuid
from unittest import skipIf
from urllib.parse import unquote, urlparse

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from tenantkit.bootstrap import unregister_database_tenant_connection
from tenantkit.models import Tenant
from tenantkit.provisioning import (
    database_exists,
    ensure_database_exists,
    ensure_database_tenant_ready,
    ensure_user_exists,
    grant_database_permissions,
    user_exists,
)

User = get_user_model()

# Check if PostgreSQL is available for integration tests
POSTGRES_HOST = os.getenv("TEST_POSTGRES_HOST", "localhost")
POSTGRES_PORT = int(os.getenv("TEST_POSTGRES_PORT", "5432"))
POSTGRES_USER = os.getenv("TEST_POSTGRES_USER", "postgres")
POSTGRES_PASSWORD = os.getenv("TEST_POSTGRES_PASSWORD", "postgres")
POSTGRES_MAINTENANCE_DB = os.getenv("TEST_POSTGRES_MAINTENANCE_DB", "postgres")

PROVISIONING_URL = f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_MAINTENANCE_DB}"


def _can_connect_to_postgres() -> bool:
    """Check if we can connect to PostgreSQL for integration tests."""
    try:
        import psycopg

        conn = psycopg.connect(
            host=POSTGRES_HOST,
            port=POSTGRES_PORT,
            user=POSTGRES_USER,
            password=POSTGRES_PASSWORD,
            dbname=POSTGRES_MAINTENANCE_DB,
            connect_timeout=5,
        )
        conn.close()
        return True
    except Exception:
        return False


# Skip all integration tests if PostgreSQL is not available
POSTGRES_AVAILABLE = _can_connect_to_postgres()


@skipIf(not POSTGRES_AVAILABLE, "PostgreSQL not available for integration tests")
@override_settings(TENANT_ENCRYPTION_KEY="integration-test-key")
class DatabaseProvisioningIntegrationTests(TestCase):
    """Integration tests that create real PostgreSQL databases."""

    databases = "__all__"

    def setUp(self):
        self._registered_aliases: set[str] = set()
        self.user = User.objects.create_user(
            username=f"testowner_{uuid.uuid4().hex[:8]}", password="secret"
        )
        # Generate unique database names to avoid conflicts
        self.test_db_name = f"test_tenant_{uuid.uuid4().hex[:12]}"
        self.test_db_url = f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{self.test_db_name}"

    def tearDown(self):
        """Clean up: drop any databases and users created during tests."""
        for alias in self._registered_aliases:
            unregister_database_tenant_connection(alias)
        self._drop_database_if_exists(self.test_db_name)
        # Extract username from test_db_url and drop if exists (skip if it's the postgres admin)
        parsed = urlparse(self.test_db_url)
        username = unquote(parsed.username) if parsed.username else None
        if username and username != POSTGRES_USER:
            self._drop_user_if_exists(username)

    def _drop_database_if_exists(self, db_name: str):
        """Helper to drop a database if it exists."""
        import psycopg

        try:
            conn = psycopg.connect(
                host=POSTGRES_HOST,
                port=POSTGRES_PORT,
                user=POSTGRES_USER,
                password=POSTGRES_PASSWORD,
                dbname=POSTGRES_MAINTENANCE_DB,
            )
            conn.autocommit = True
            with conn.cursor() as cur:
                # Terminate any existing connections to the database
                cur.execute(
                    """
                    SELECT pg_terminate_backend(pg_stat_activity.pid)
                    FROM pg_stat_activity
                    WHERE pg_stat_activity.datname = %s
                    AND pid <> pg_backend_pid()
                    """,
                    (db_name,),
                )
                # Drop the database
                cur.execute(f"DROP DATABASE IF EXISTS {db_name}")
            conn.close()
        except Exception as exc:
            print(f"Warning: Could not drop test database {db_name}: {exc}")

    def _drop_user_if_exists(self, username: str):
        """Helper to drop a user if it exists."""
        import psycopg

        try:
            conn = psycopg.connect(
                host=POSTGRES_HOST,
                port=POSTGRES_PORT,
                user=POSTGRES_USER,
                password=POSTGRES_PASSWORD,
                dbname=POSTGRES_MAINTENANCE_DB,
            )
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute(f"DROP USER IF EXISTS {username}")
            conn.close()
        except Exception as exc:
            print(f"Warning: Could not drop test user {username}: {exc}")

    def test_database_exists_returns_false_for_nonexistent_db(self):
        """Verify database_exists returns False for a database that doesn't exist."""
        nonexistent_db = f"nonexistent_{uuid.uuid4().hex[:12]}"
        db_url = f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{nonexistent_db}"

        exists = database_exists(db_url, PROVISIONING_URL)

        self.assertFalse(exists)

    def test_database_exists_returns_true_for_existing_db(self):
        """Verify database_exists returns True after creating a database."""
        # First, create the database directly
        import psycopg

        conn = psycopg.connect(
            host=POSTGRES_HOST,
            port=POSTGRES_PORT,
            user=POSTGRES_USER,
            password=POSTGRES_PASSWORD,
            dbname=POSTGRES_MAINTENANCE_DB,
        )
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(f"CREATE DATABASE {self.test_db_name}")
        conn.close()

        # Now check that database_exists returns True
        exists = database_exists(self.test_db_url, PROVISIONING_URL)

        self.assertTrue(exists)

    def test_ensure_database_exists_creates_database(self):
        """Verify ensure_database_exists creates a real PostgreSQL database."""
        # Verify the database doesn't exist initially
        self.assertFalse(database_exists(self.test_db_url, PROVISIONING_URL))

        # Create the database
        created = ensure_database_exists(self.test_db_url, PROVISIONING_URL)

        # Verify it was created
        self.assertTrue(created)
        self.assertTrue(database_exists(self.test_db_url, PROVISIONING_URL))

    def test_ensure_database_exists_is_idempotent(self):
        """Verify ensure_database_exists returns False if database already exists."""
        # Create the database first
        created1 = ensure_database_exists(self.test_db_url, PROVISIONING_URL)
        self.assertTrue(created1)

        # Try to create again
        created2 = ensure_database_exists(self.test_db_url, PROVISIONING_URL)
        self.assertFalse(created2)  # Should return False since it already exists

    def test_ensure_database_tenant_ready_full_flow(self):
        """Test the complete flow: create tenant, provision database, verify."""
        from tenantkit.crypto import encrypt_text

        # Create a tenant with manual provisioning
        # For manual database tenants, we need to provide connection_alias and connection_string
        tenant_slug = f"integration-{uuid.uuid4().hex[:8]}"
        connection_alias = f"tenant_{tenant_slug}"

        tenant = Tenant(
            slug=tenant_slug,
            name="Integration Test Tenant",
            isolation_mode=Tenant.IsolationMode.DATABASE,
            provisioning_mode=Tenant.ProvisioningMode.MANUAL,
            connection_alias=connection_alias,
            connection_string=encrypt_text(
                self.test_db_url
            ),  # Required for manual mode
        )
        tenant.set_provisioning_connection_string(PROVISIONING_URL)
        tenant.save()

        # Verify the database doesn't exist yet
        self.assertFalse(database_exists(self.test_db_url, PROVISIONING_URL))

        # Run the full provisioning flow
        ready = ensure_database_tenant_ready(tenant)

        # Verify success
        self.assertTrue(ready)
        self.assertTrue(database_exists(self.test_db_url, PROVISIONING_URL))

        # Verify the connection alias was registered
        from django.db import connections

        self.assertIn(tenant.connection_alias, connections.databases)
        if tenant.connection_alias:
            self._registered_aliases.add(tenant.connection_alias)

    def test_user_exists_and_creation(self):
        """Test user existence check and creation."""
        test_user = f"test_user_{uuid.uuid4().hex[:8]}"
        test_password = "test_password_123"

        # Verify user doesn't exist initially
        self.assertFalse(user_exists(test_user, PROVISIONING_URL))

        # Create the user
        created = ensure_user_exists(test_user, test_password, PROVISIONING_URL)
        self.assertTrue(created)

        # Verify user now exists
        self.assertTrue(user_exists(test_user, PROVISIONING_URL))

        # Try to create again (should be idempotent)
        created2 = ensure_user_exists(test_user, test_password, PROVISIONING_URL)
        self.assertFalse(created2)

    def test_grant_database_permissions(self):
        """Test granting permissions to user on database."""
        # Create database and user first
        db_name = f"test_perm_db_{uuid.uuid4().hex[:8]}"
        db_url = f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{db_name}"
        test_user = f"perm_user_{uuid.uuid4().hex[:8]}"
        test_password = "perm_password_123"

        # Create database
        ensure_database_exists(db_url, PROVISIONING_URL)
        self.assertTrue(database_exists(db_url, PROVISIONING_URL))

        # Create user
        ensure_user_exists(test_user, test_password, PROVISIONING_URL)
        self.assertTrue(user_exists(test_user, PROVISIONING_URL))

        # Grant permissions
        granted = grant_database_permissions(db_name, test_user, PROVISIONING_URL)
        self.assertTrue(granted)

    def test_full_provisioning_creates_db_user_and_permissions(self):
        """Test that full provisioning creates DB, user, and grants permissions."""
        from tenantkit.crypto import encrypt_text

        tenant_slug = f"full-int-{uuid.uuid4().hex[:8]}"
        db_name = f"full_db_{uuid.uuid4().hex[:8]}"
        db_user = f"full_user_{uuid.uuid4().hex[:8]}"
        db_password = "full_pass_123"

        db_url = f"postgresql://{db_user}:{db_password}@{POSTGRES_HOST}:{POSTGRES_PORT}/{db_name}"

        tenant = Tenant(
            slug=tenant_slug,
            name="Full Integration Test",
            isolation_mode=Tenant.IsolationMode.DATABASE,
            provisioning_mode=Tenant.ProvisioningMode.MANUAL,
            connection_alias=f"tenant_{tenant_slug}",
            connection_string=encrypt_text(db_url),
        )
        tenant.set_provisioning_connection_string(PROVISIONING_URL)
        tenant.save()

        # Verify nothing exists yet
        self.assertFalse(database_exists(db_url, PROVISIONING_URL))
        self.assertFalse(user_exists(db_user, PROVISIONING_URL))

        # Run full provisioning
        ready = ensure_database_tenant_ready(tenant)
        self.assertTrue(ready)

        # Verify everything was created
        self.assertTrue(database_exists(db_url, PROVISIONING_URL))
        self.assertTrue(user_exists(db_user, PROVISIONING_URL))
        if tenant.connection_alias:
            self._registered_aliases.add(tenant.connection_alias)

    def test_provisioning_with_invalid_credentials_fails(self):
        """Verify provisioning fails gracefully with invalid credentials."""
        invalid_url = "postgresql://invalid:user@localhost:5432/testdb"
        invalid_provisioning = "postgresql://invalid:user@localhost:5432/postgres"

        with self.assertRaises(RuntimeError) as context:
            database_exists(invalid_url, invalid_provisioning)

        self.assertIn("Failed to inspect database", str(context.exception))

    def test_provisioning_connection_string_parsing(self):
        """Verify that provisioning connection strings are parsed correctly."""
        from tenantkit.provisioning import _parse_postgres_url

        # Test standard postgresql URL
        url = "postgresql://admin:secret@localhost:5432/postgres"
        target = _parse_postgres_url(url)

        self.assertIsNotNone(target)
        self.assertEqual(target.host, "localhost")
        self.assertEqual(target.port, 5432)
        self.assertEqual(target.user, "admin")
        self.assertEqual(target.password, "secret")
        self.assertEqual(target.maintenance_db, "postgres")

    def test_provisioning_connection_string_with_special_chars(self):
        """Verify URLs with special characters (encoded) are handled correctly."""
        from tenantkit.provisioning import _parse_postgres_url

        # URL with encoded special characters in password
        url = "postgresql://admin:p%40ss%23word@localhost:5432/postgres"
        target = _parse_postgres_url(url)

        self.assertIsNotNone(target)
        self.assertEqual(target.password, "p@ss#word")  # Decoded


@skipIf(not POSTGRES_AVAILABLE, "PostgreSQL not available for integration tests")
@override_settings(TENANT_ENCRYPTION_KEY="integration-test-key")
class DatabaseProvisioningCleanupTests(TestCase):
    """Tests specifically for cleanup and edge cases."""

    databases = "__all__"

    def setUp(self):
        self.user = User.objects.create_user(
            username=f"cleanupowner_{uuid.uuid4().hex[:8]}", password="secret"
        )

    def test_multiple_database_creation_and_cleanup(self):
        """Test creating multiple databases and cleaning them up."""
        import psycopg

        db_names = []

        try:
            # Create multiple databases
            for _i in range(3):
                db_name = f"test_multi_{uuid.uuid4().hex[:8]}"
                db_url = f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{db_name}"
                db_names.append(db_name)

                created = ensure_database_exists(db_url, PROVISIONING_URL)
                self.assertTrue(created, f"Database {db_name} should be created")

            # Verify all exist
            for db_name in db_names:
                db_url = f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{db_name}"
                self.assertTrue(
                    database_exists(db_url, PROVISIONING_URL),
                    f"Database {db_name} should exist",
                )

        finally:
            # Clean up all databases
            conn = psycopg.connect(
                host=POSTGRES_HOST,
                port=POSTGRES_PORT,
                user=POSTGRES_USER,
                password=POSTGRES_PASSWORD,
                dbname=POSTGRES_MAINTENANCE_DB,
            )
            conn.autocommit = True
            with conn.cursor() as cur:
                for db_name in db_names:
                    try:
                        cur.execute(f"DROP DATABASE IF EXISTS {db_name}")
                    except Exception as exc:
                        print(f"Warning: Could not drop {db_name}: {exc}")
            conn.close()

    def test_delete_database_and_user(self):
        """Test that delete_database_and_user drops database and user."""
        from tenantkit.provisioning import delete_database_and_user

        # Create a database and user first
        db_name = f"test_delete_{uuid.uuid4().hex[:8]}"
        db_user = f"delete_user_{uuid.uuid4().hex[:8]}"
        db_password = "delete_pass_123"

        db_url = f"postgresql://{db_user}:{db_password}@{POSTGRES_HOST}:{POSTGRES_PORT}/{db_name}"

        # Create database and user using provisioning
        from tenantkit.provisioning import ensure_database_exists, ensure_user_exists

        ensure_database_exists(db_url, PROVISIONING_URL)
        ensure_user_exists(db_user, db_password, PROVISIONING_URL)

        # Verify they exist
        self.assertTrue(database_exists(db_url, PROVISIONING_URL))
        self.assertTrue(user_exists(db_user, PROVISIONING_URL))

        # Now delete them
        deleted = delete_database_and_user(db_url, PROVISIONING_URL)
        self.assertTrue(deleted)

        # Verify they no longer exist
        self.assertFalse(database_exists(db_url, PROVISIONING_URL))
        self.assertFalse(user_exists(db_user, PROVISIONING_URL))
