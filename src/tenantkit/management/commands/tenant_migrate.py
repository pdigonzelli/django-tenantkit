"""
Apply migrations to shared database or tenant schemas/databases.

This command extends Django's migrate to support tenantkit scenarios:
- Apply migrations to shared models (default database)
- Apply migrations to tenant models across all tenants or specific tenant
- Support for both schema-based and database-based isolation

Usage:
    # Migrate shared models only
    python manage.py tenant_migrate --type=shared

    # Migrate tenant models for all tenants
    python manage.py tenant_migrate --type=tenant

    # Migrate tenant models for specific tenant
    python manage.py tenant_migrate --type=tenant --tenant=acme-corp

    # Migrate everything
    python manage.py tenant_migrate

    # Show what would be migrated without applying (dry run)
    python manage.py tenant_migrate --dry-run

    # Migrate specific app only
    python manage.py tenant_migrate myapp --type=shared
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import CommandError, CommandParser
from django.core.management.commands.migrate import Command as MigrateCommand
from django.db import DEFAULT_DB_ALIAS, connections

from tenantkit.core.context import get_current_tenant, set_current_tenant
from tenantkit.model_config import ModelRegistry
from tenantkit.models import Tenant


class Command(MigrateCommand):
    help = "Applies migrations to shared database or tenant schemas/databases"

    def add_arguments(self, parser: CommandParser) -> None:
        super().add_arguments(parser)
        parser.add_argument(
            "--type",
            choices=["shared", "tenant", "all"],
            default="all",
            help="Type of migrations to apply (default: all)",
        )
        parser.add_argument(
            "--tenant",
            dest="tenant_slug",
            help="Specific tenant slug to migrate (for tenant migrations only)",
        )
        parser.add_argument(
            "--skip-shared",
            action="store_true",
            help="Skip shared migrations even if type=all",
        )
        parser.add_argument(
            "--skip-tenant",
            action="store_true",
            help="Skip tenant migrations even if type=all",
        )
        parser.add_argument(
            "--fake-tenant",
            action="store_true",
            help="Mark tenant migrations as applied without running them",
        )
        parser.add_argument(
            "--create-schemas",
            action="store_true",
            default=True,
            help="Create schemas if they don't exist (PostgreSQL schema mode)",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        self.migration_type = options.get("type")
        self.tenant_slug = options.get("tenant_slug")
        self.skip_shared = options.get("skip_shared")
        self.skip_tenant = options.get("skip_tenant")
        self.fake_tenant = options.get("fake_tenant")
        self.create_schemas = options.get("create_schemas")

        # Validate options
        if self.tenant_slug and self.migration_type == "shared":
            raise CommandError(
                "Cannot specify --tenant with --type=shared. "
                "Tenant option is only for tenant migrations."
            )

        # Track success/failure
        self.shared_success = False
        self.tenant_success = []
        self.tenant_failed = []

        # Execute migrations
        if self.migration_type in ("shared", "all") and not self.skip_shared:
            self._migrate_shared(args, options)

        if self.migration_type in ("tenant", "all") and not self.skip_tenant:
            self._migrate_tenants(args, options)

        # Summary
        self._print_summary()

    def _migrate_shared(self, args: Any, options: dict[str, Any]) -> None:
        """Migrate shared models in the default database."""
        self.stdout.write(self.style.MIGRATE_HEADING("=" * 70))
        self.stdout.write(self.style.MIGRATE_HEADING("MIGRATING SHARED MODELS"))
        self.stdout.write(self.style.MIGRATE_HEADING("=" * 70))
        self.stdout.write()

        # Filter to only migrate apps with shared models
        shared_models = ModelRegistry.get_shared_models()
        if not shared_models:
            self.stdout.write(self.style.WARNING("No shared models registered."))
            self.stdout.write()
            return

        # Get unique app labels
        shared_apps = set(m["app_label"] for m in shared_models)
        self.stdout.write(f"Apps with shared models: {', '.join(sorted(shared_apps))}")
        self.stdout.write()

        # Run standard migrate on default database
        try:
            # Remove our custom options before calling parent
            migrate_options = options.copy()
            migrate_options.pop("type", None)
            migrate_options.pop("tenant", None)
            migrate_options.pop("skip_shared", None)
            migrate_options.pop("skip_tenant", None)
            migrate_options.pop("fake_tenant", None)
            migrate_options.pop("create_schemas", None)

            # Set database to default
            migrate_options["database"] = DEFAULT_DB_ALIAS

            # If specific apps were requested, filter to shared ones
            if args:
                filtered_args = [a for a in args if a in shared_apps]
                if not filtered_args:
                    self.stdout.write(
                        self.style.WARNING("No requested apps have shared models.")
                    )
                    return
                args = tuple(filtered_args)

            super().handle(*args, **migrate_options)
            self.shared_success = True

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Shared migration failed: {e}"))
            self.shared_success = False
            raise

    def _migrate_tenants(self, args: Any, options: dict[str, Any]) -> None:
        """Migrate tenant models across all or specific tenant(s)."""
        self.stdout.write(self.style.MIGRATE_HEADING("=" * 70))
        self.stdout.write(self.style.MIGRATE_HEADING("MIGRATING TENANT MODELS"))
        self.stdout.write(self.style.MIGRATE_HEADING("=" * 70))
        self.stdout.write()

        # Get tenant models
        tenant_models = ModelRegistry.get_tenant_models()
        if not tenant_models:
            self.stdout.write(self.style.WARNING("No tenant models registered."))
            self.stdout.write()
            return

        # Get unique app labels
        tenant_apps = set(m["app_label"] for m in tenant_models)
        self.stdout.write(f"Apps with tenant models: {', '.join(sorted(tenant_apps))}")
        self.stdout.write()

        # Get tenants to migrate
        tenants = self._get_tenants_to_migrate()
        if not tenants:
            self.stdout.write(self.style.ERROR("No tenants found to migrate."))
            return

        self.stdout.write(f"Tenants to migrate: {len(tenants)}")
        for tenant in tenants:
            self.stdout.write(f"  - {tenant.slug} ({tenant.isolation_mode})")
        self.stdout.write()

        # Migrate each tenant
        for tenant in tenants:
            self._migrate_single_tenant(tenant, args, options, tenant_apps)

    def _get_tenants_to_migrate(self) -> list[Tenant]:
        """Get list of tenants to migrate."""
        queryset = Tenant.objects.filter(is_active=True, deleted_at__isnull=True)

        if self.tenant_slug:
            try:
                tenant = queryset.get(slug=self.tenant_slug)
                return [tenant]
            except Tenant.DoesNotExist:
                raise CommandError(f"Tenant '{self.tenant_slug}' not found.")

        return list(queryset)

    def _migrate_single_tenant(
        self,
        tenant: Tenant,
        args: Any,
        options: dict[str, Any],
        tenant_apps: set[str],
    ) -> None:
        """Migrate a single tenant's database/schema."""
        self.stdout.write(self.style.MIGRATE_HEADING("─" * 70))
        self.stdout.write(f"Migrating tenant: {tenant.slug}")
        self.stdout.write(self.style.MIGRATE_HEADING("─" * 70))

        try:
            if tenant.isolation_mode == Tenant.IsolationMode.SCHEMA:
                self._migrate_schema_tenant(tenant, args, options, tenant_apps)
            elif tenant.isolation_mode == Tenant.IsolationMode.DATABASE:
                self._migrate_database_tenant(tenant, args, options, tenant_apps)
            else:
                raise CommandError(f"Unknown isolation mode: {tenant.isolation_mode}")

            self.tenant_success.append(tenant.slug)
            self.stdout.write(
                self.style.SUCCESS(f"✓ {tenant.slug} migrated successfully")
            )

        except Exception as e:
            self.tenant_failed.append((tenant.slug, str(e)))
            self.stdout.write(self.style.ERROR(f"✗ {tenant.slug} failed: {e}"))
            if not options.get("ignore_errors"):
                raise

    def _migrate_schema_tenant(
        self,
        tenant: Tenant,
        args: Any,
        options: dict[str, Any],
        tenant_apps: set[str],
    ) -> None:
        """Migrate a schema-based tenant."""
        from django.db import connection

        schema_name = tenant.schema_name
        if not schema_name:
            raise CommandError(f"Tenant {tenant.slug} has no schema_name defined.")

        # Ensure schema exists
        if self.create_schemas:
            with connection.cursor() as cursor:
                # Check if schema exists
                cursor.execute(
                    "SELECT schema_name FROM information_schema.schemata WHERE schema_name = %s",
                    [schema_name],
                )
                if not cursor.fetchone():
                    self.stdout.write(f"  Creating schema '{schema_name}'...")
                    cursor.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema_name}"')
                    self.stdout.write(self.style.SUCCESS("  ✓ Schema created"))

        # Set search path for this tenant
        with connection.cursor() as cursor:
            cursor.execute(f'SET search_path TO "{schema_name}"')

        try:
            # Run migrations in this schema context
            self._run_migrations_in_context(
                tenant=tenant,
                args=args,
                options=options,
                tenant_apps=tenant_apps,
                using=DEFAULT_DB_ALIAS,
            )
        finally:
            # Reset search path
            with connection.cursor() as cursor:
                cursor.execute("SET search_path TO public")

    def _migrate_database_tenant(
        self,
        tenant: Tenant,
        args: Any,
        options: dict[str, Any],
        tenant_apps: set[str],
    ) -> None:
        """Migrate a database-based tenant."""
        connection_alias = tenant.connection_alias
        if not connection_alias:
            raise CommandError(f"Tenant {tenant.slug} has no connection_alias defined.")

        # Check if connection is configured
        if connection_alias not in connections:
            raise CommandError(
                f"Connection '{connection_alias}' for tenant {tenant.slug} is not configured. "
                f"Make sure to register the tenant connection in DATABASES setting."
            )

        # Run migrations on tenant's database
        self._run_migrations_in_context(
            tenant=tenant,
            args=args,
            options=options,
            tenant_apps=tenant_apps,
            using=connection_alias,
        )

    def _run_migrations_in_context(
        self,
        tenant: Tenant,
        args: Any,
        options: dict[str, Any],
        tenant_apps: set[str],
        using: str,
    ) -> None:
        """Run migrations in a specific database/schema context."""
        # Prepare options
        migrate_options = options.copy()
        migrate_options.pop("type", None)
        migrate_options.pop("tenant", None)
        migrate_options.pop("skip_shared", None)
        migrate_options.pop("skip_tenant", None)
        migrate_options.pop("fake_tenant", None)
        migrate_options.pop("create_schemas", None)

        # Set database
        migrate_options["database"] = using

        # If fake tenant, add --fake
        if self.fake_tenant:
            migrate_options["fake"] = True

        # Filter apps to only tenant apps
        if args:
            filtered_args = [a for a in args if a in tenant_apps]
            if filtered_args:
                args = tuple(filtered_args)

        # Store current tenant in context for potential use in migrations
        previous_tenant = get_current_tenant()
        set_current_tenant(tenant)

        try:
            # Run the migrations
            super().handle(*args, **migrate_options)
        finally:
            # Restore previous tenant context
            set_current_tenant(previous_tenant)

    def _print_summary(self) -> None:
        """Print migration summary."""
        self.stdout.write()
        self.stdout.write(self.style.MIGRATE_HEADING("=" * 70))
        self.stdout.write(self.style.MIGRATE_HEADING("MIGRATION SUMMARY"))
        self.stdout.write(self.style.MIGRATE_HEADING("=" * 70))
        self.stdout.write()

        if self.migration_type in ("shared", "all") and not self.skip_shared:
            status = "✓ SUCCESS" if self.shared_success else "✗ FAILED"
            self.stdout.write(f"Shared migrations: {status}")

        if self.migration_type in ("tenant", "all") and not self.skip_tenant:
            self.stdout.write("Tenant migrations:")
            self.stdout.write(f"  Successful: {len(self.tenant_success)}")
            if self.tenant_success:
                for slug in self.tenant_success:
                    self.stdout.write(f"    ✓ {slug}")

            if self.tenant_failed:
                self.stdout.write(f"  Failed: {len(self.tenant_failed)}")
                for slug, error in self.tenant_failed:
                    self.stdout.write(f"    ✗ {slug}: {error}")

        self.stdout.write()
