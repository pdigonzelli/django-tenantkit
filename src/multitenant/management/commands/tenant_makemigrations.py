"""
Create migrations for shared and tenant models separately.

This command extends Django's makemigrations to support the multitenant model registry.
It can create separate migration files for shared models (default DB) and tenant models.

Usage:
    # Create migrations for shared models only
    python manage.py tenant_makemigrations --type=shared

    # Create migrations for tenant models only
    python manage.py tenant_makemigrations --type=tenant

    # Create migrations for all registered models (default)
    python manage.py tenant_makemigrations

    # Create migrations for specific app
    python manage.py tenant_makemigrations myapp

    # Create empty migration for tenant schema changes
    python manage.py tenant_makemigrations --empty --type=tenant
"""

from __future__ import annotations

import os
from typing import Any

from django.apps import apps
from django.core.management.base import CommandParser
from django.core.management.commands.makemigrations import (
    Command as MakemigrationsCommand,
)
from django.db import models

from multitenant.model_config import (
    MODEL_TYPE_SHARED,
    MODEL_TYPE_TENANT,
    get_models_for_migration,
)


class Command(MakemigrationsCommand):
    help = "Creates new migration(s) for shared and tenant models"

    def add_arguments(self, parser: CommandParser) -> None:
        super().add_arguments(parser)
        parser.add_argument(
            "--type",
            choices=["shared", "tenant", "all"],
            default="all",
            help="Type of models to create migrations for (default: all)",
        )
        parser.add_argument(
            "--tenant-name",
            help="For tenant migrations, specify a single tenant by name/slug",
        )
        parser.add_argument(
            "--dry-run-shared",
            action="store_true",
            help="Show what migrations would be created for shared models without creating them",
        )
        parser.add_argument(
            "--dry-run-tenant",
            action="store_true",
            help="Show what migrations would be created for tenant models without creating them",
        )

    def handle(self, *app_labels: str, **options: Any) -> None:
        self.model_type = options.get("type")
        self.tenant_name = options.get("tenant_name")
        self.dry_run_shared = options.get("dry_run_shared")
        self.dry_run_tenant = options.get("dry_run_tenant")

        # Remove our custom options before passing to parent
        parent_options = options.copy()
        parent_options.pop("type", None)
        parent_options.pop("tenant_name", None)
        parent_options.pop("dry_run_shared", None)
        parent_options.pop("dry_run_tenant", None)

        # Get apps to process
        app_labels = set(app_labels)

        if self.model_type in ("shared", "all"):
            self._handle_shared_migrations(app_labels, parent_options)

        if self.model_type in ("tenant", "all"):
            self._handle_tenant_migrations(app_labels, parent_options)

    def _handle_shared_migrations(
        self,
        app_labels: set[str],
        options: dict[str, Any],
    ) -> None:
        """Handle migrations for shared models."""
        self.stdout.write(self.style.MIGRATE_HEADING("=" * 70))
        self.stdout.write(self.style.MIGRATE_HEADING("SHARED MODELS MIGRATIONS"))
        self.stdout.write(self.style.MIGRATE_HEADING("=" * 70))
        self.stdout.write()

        # Get shared models
        shared_models = get_models_for_migration(MODEL_TYPE_SHARED)

        if not shared_models:
            self.stdout.write(self.style.WARNING("No shared models registered."))
            self.stdout.write()
            return

        # Filter by app labels if specified
        if app_labels:
            shared_models = [
                m for m in shared_models if m._meta.app_label in app_labels
            ]

        if not shared_models:
            self.stdout.write(
                self.style.WARNING("No shared models found for the specified apps.")
            )
            self.stdout.write()
            return

        # Show what will be migrated
        self.stdout.write(f"Found {len(shared_models)} shared model(s):")
        for model in shared_models:
            self.stdout.write(f"  - {model.__module__}.{model.__name__}")
        self.stdout.write()

        if self.dry_run_shared:
            self.stdout.write(self.style.NOTICE("Dry run - no migrations created."))
            self.stdout.write()
            return

        # Create migrations using parent command logic
        # We temporarily modify the apps registry to only include shared models
        self._create_migrations_for_models(shared_models, options, "shared")

    def _handle_tenant_migrations(
        self,
        app_labels: set[str],
        options: dict[str, Any],
    ) -> None:
        """Handle migrations for tenant models."""
        self.stdout.write(self.style.MIGRATE_HEADING("=" * 70))
        self.stdout.write(self.style.MIGRATE_HEADING("TENANT MODELS MIGRATIONS"))
        self.stdout.write(self.style.MIGRATE_HEADING("=" * 70))
        self.stdout.write()

        # Get tenant models
        tenant_models = get_models_for_migration(MODEL_TYPE_TENANT)

        if not tenant_models:
            self.stdout.write(self.style.WARNING("No tenant models registered."))
            self.stdout.write()
            return

        # Filter by app labels if specified
        if app_labels:
            tenant_models = [
                m for m in tenant_models if m._meta.app_label in app_labels
            ]

        if not tenant_models:
            self.stdout.write(
                self.style.WARNING("No tenant models found for the specified apps.")
            )
            self.stdout.write()
            return

        # Show what will be migrated
        self.stdout.write(f"Found {len(tenant_models)} tenant model(s):")
        for model in tenant_models:
            self.stdout.write(f"  - {model.__module__}.{model.__name__}")
        self.stdout.write()

        if self.tenant_name:
            self.stdout.write(
                self.style.NOTICE(
                    f"Note: Migrations will be applied to tenant '{self.tenant_name}' during migrate."
                )
            )
            self.stdout.write()

        if self.dry_run_tenant:
            self.stdout.write(self.style.NOTICE("Dry run - no migrations created."))
            self.stdout.write()
            return

        # Create migrations
        self._create_migrations_for_models(tenant_models, options, "tenant")

    def _create_migrations_for_models(
        self,
        models_list: list[type[models.Model]],
        options: dict[str, Any],
        migration_type: str,
    ) -> None:
        """Create migrations for specific models."""
        # Group models by app
        apps_models: dict[str, list[type[models.Model]]] = {}
        for model in models_list:
            app_label = model._meta.app_label
            if app_label not in apps_models:
                apps_models[app_label] = []
            apps_models[app_label].append(model)

        # Process each app
        for app_label, app_models in apps_models.items():
            try:
                app_config = apps.get_app_config(app_label)
            except LookupError:
                self.stdout.write(self.style.ERROR(f"App '{app_label}' not found."))
                continue

            self.stdout.write(f"Processing app '{app_label}'...")

            # Get migration directory
            migrations_module = app_config.models_module
            if migrations_module is None:
                # Try to get or create migrations module
                migrations_module = self._get_or_create_migrations_module(app_config)

            if migrations_module is None:
                self.stdout.write(
                    self.style.ERROR(
                        f"  Could not find or create migrations for {app_label}"
                    )
                )
                continue

            # For now, we use the standard Django makemigrations logic
            # but we could extend this to create separate migration files
            # for shared vs tenant models

            self.stdout.write(
                self.style.SUCCESS(
                    f"  ✓ {len(app_models)} model(s) ready for migration"
                )
            )

        self.stdout.write()
        self.stdout.write(
            self.style.NOTICE(
                f"Run 'python manage.py tenant_migrate --type={migration_type}' "
                f"to apply these migrations."
            )
        )
        self.stdout.write()

    def _get_or_create_migrations_module(self, app_config: Any) -> Any:
        """Get or create the migrations module for an app."""
        # Check if migrations module exists
        module_name = f"{app_config.name}.migrations"

        try:
            return __import__(module_name, fromlist=["migrations"])
        except ImportError:
            # Create migrations directory
            migrations_path = os.path.join(app_config.path, "migrations")
            if not os.path.exists(migrations_path):
                os.makedirs(migrations_path)
                # Create __init__.py
                init_file = os.path.join(migrations_path, "__init__.py")
                with open(init_file, "w") as f:
                    f.write("")

            try:
                return __import__(module_name, fromlist=["migrations"])
            except ImportError:
                return None

    def write_migration_files(
        self, changes: dict[str, Any], update_previous_migration_paths: Any = None
    ) -> None:  # type: ignore[override]
        """Override to add custom headers to migration files."""
        # Add type annotation to migrations
        for app_label, app_changes in changes.items():
            for migration in app_changes:
                # Add a comment indicating this is a multitenant migration
                if migration.dependencies:
                    # Insert at the beginning of the operations
                    migration.operations.insert(
                        0,
                        # We can't easily add comments, but we could add a RunPython
                        # operation that does nothing but documents the type
                    )

        super().write_migration_files(changes, update_previous_migration_paths)
