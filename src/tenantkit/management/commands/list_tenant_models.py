"""
List all registered tenant and shared models.

Usage:
    python manage.py list_tenant_models
    python manage.py list_tenant_models --type=shared
    python manage.py list_tenant_models --type=tenant
    python manage.py list_tenant_models --app=myapp
    python manage.py list_tenant_models --json
"""

# pyright: reportAttributeAccessIssue=false

import json
from typing import Any

from django.apps import apps
from django.core.management.base import BaseCommand, CommandParser

from tenantkit.classification import get_model_scope, is_framework_app
from tenantkit.model_config import (
    MODEL_TYPE_UNCLASSIFIED,
    ModelRegistry,
)


class Command(BaseCommand):
    help = "List all registered shared and tenant models"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--type",
            choices=["shared", "tenant", "both", "unclassified", "all"],
            default="all",
            help="Filter models by type (default: all)",
        )
        parser.add_argument(
            "--app",
            help="Filter by app label (e.g., 'myapp')",
        )
        parser.add_argument(
            "--json",
            action="store_true",
            help="Output as JSON",
        )
        parser.add_argument(
            "--include-unregistered",
            action="store_true",
            help="Include models not explicitly registered (marked as unclassified)",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        model_type = options.get("type")
        app_label = options.get("app")
        output_json = bool(options.get("json"))
        include_unregistered = bool(options.get("include_unregistered"))

        # Build the data structure
        models_data = self._collect_models(
            model_type=model_type,
            app_label=app_label,
            include_unregistered=include_unregistered,
        )

        if output_json:
            self._output_json(models_data)
        else:
            self._output_table(models_data)

    def _collect_models(
        self,
        model_type: str | None,
        app_label: str | None,
        include_unregistered: bool,
    ) -> dict[str, list[dict[str, Any]]]:
        """Collect and categorize all models."""
        data: dict[str, list[dict[str, Any]]] = {
            "shared": [],
            "tenant": [],
            "both": [],
            "unclassified": [],
        }

        for model in apps.get_models():
            if app_label and model._meta.app_label != app_label:
                continue

            scope = get_model_scope(model)
            if scope == MODEL_TYPE_UNCLASSIFIED and is_framework_app(
                model._meta.app_label
            ):
                continue
            if scope == MODEL_TYPE_UNCLASSIFIED and not include_unregistered:
                continue

            if model_type not in (scope, "all"):
                continue

            data[scope].append(self._model_to_dict(model, scope))

        return data

    def _model_config_to_dict(self, config: dict[str, Any]) -> dict[str, Any]:
        """Convert model config to dictionary for output."""
        return {
            "full_name": config["full_name"],
            "app_label": config["app_label"],
            "model_name": config["model_name"],
            "table_name": config["model_class"]._meta.db_table,
            "auto_migrate": config.get("auto_migrate", True),
            "allow_global_queries": config.get("allow_global_queries", False),
        }

    def _model_to_dict(self, model: type, scope: str) -> dict[str, Any]:
        config = ModelRegistry.get_model_config(model)
        if config:
            data = self._model_config_to_dict(config)
        else:
            data = {
                "full_name": f"{model.__module__}.{model.__name__}",
                "app_label": model._meta.app_label,
                "model_name": model._meta.model_name,
                "table_name": model._meta.db_table,
                "auto_migrate": None,
                "allow_global_queries": None,
            }

        data["scope"] = scope
        return data

    def _output_json(self, data: dict[str, list[dict[str, Any]]]) -> None:
        """Output as JSON."""
        self.stdout.write(json.dumps(data, indent=2))

    def _output_table(self, data: dict[str, list[dict[str, Any]]]) -> None:
        """Output as formatted table."""
        total_shared = len(data["shared"])
        total_tenant = len(data["tenant"])
        total_both = len(data["both"])
        total_unclassified = len(data["unclassified"])

        # Header
        self.stdout.write(self.style.MIGRATE_HEADING("=" * 80))
        self.stdout.write(self.style.MIGRATE_HEADING("TENANT MODELS REGISTRY"))
        self.stdout.write(self.style.MIGRATE_HEADING("=" * 80))
        self.stdout.write()

        # Summary
        self.stdout.write(self.style.MIGRATE_LABEL("Summary:"))
        self.stdout.write(f"  Shared models:      {total_shared}")
        self.stdout.write(f"  Tenant models:      {total_tenant}")
        self.stdout.write(f"  Both-scope models:  {total_both}")
        if total_unclassified > 0:
            self.stdout.write(f"  Unclassified:       {total_unclassified}")
        self.stdout.write(
            f"  Total:              {total_shared + total_tenant + total_both + total_unclassified}"
        )
        self.stdout.write()

        # Shared models
        if data["shared"]:
            self.stdout.write(self.style.SUCCESS("─" * 80))
            self.stdout.write(self.style.SUCCESS(f"📁 SHARED MODELS ({total_shared})"))
            self.stdout.write(self.style.SUCCESS("─" * 80))
            for model in data["shared"]:
                self._print_model_line(model, "shared")
            self.stdout.write()

        # Tenant models
        if data["tenant"]:
            self.stdout.write(self.style.WARNING("─" * 80))
            self.stdout.write(self.style.WARNING(f"🏢 TENANT MODELS ({total_tenant})"))
            self.stdout.write(self.style.WARNING("─" * 80))
            for model in data["tenant"]:
                self._print_model_line(model, "tenant")
            self.stdout.write()

        if data["both"]:
            self.stdout.write(self.style.MIGRATE_HEADING("─" * 80))
            self.stdout.write(
                self.style.MIGRATE_HEADING(f"🔁 BOTH-SCOPE MODELS ({total_both})")
            )
            self.stdout.write(self.style.MIGRATE_HEADING("─" * 80))
            for model in data["both"]:
                self._print_model_line(model, "both")
            self.stdout.write()

        # Unclassified models
        if data["unclassified"]:
            self.stdout.write(self.style.NOTICE("─" * 80))
            self.stdout.write(
                self.style.NOTICE(f"❓ UNCLASSIFIED MODELS ({total_unclassified})")
            )
            self.stdout.write(self.style.NOTICE("─" * 80))
            self.stdout.write(
                self.style.NOTICE(
                    "These models are not registered as shared or tenant."
                )
            )
            self.stdout.write(
                self.style.NOTICE(
                    "Use @shared_model or @tenant_model decorator, or inherit from SharedModel/TenantModel."
                )
            )
            self.stdout.write()
            for model in data["unclassified"]:
                self._print_model_line(model, "unclassified")
            self.stdout.write()

        # Legend
        self.stdout.write(self.style.MIGRATE_HEADING("─" * 80))
        self.stdout.write("Legend:")
        self.stdout.write("  [✓ auto_migrate]    Model will be automatically migrated")
        self.stdout.write("  [✗ auto_migrate]    Model migration is disabled")
        self.stdout.write("  [global]            Tenant model allows global queries")
        self.stdout.write()

    def _print_model_line(self, model: dict[str, Any], model_type: str) -> None:
        """Print a single model line."""
        full_name = model["full_name"]
        table_name = model["table_name"]

        # Build flags string
        flags = []
        if model_type != "unclassified":
            if model.get("auto_migrate"):
                flags.append("✓ auto_migrate")
            else:
                flags.append("✗ auto_migrate")

            if model_type == "tenant" and model.get("allow_global_queries"):
                flags.append("global")
            if model_type == "both":
                flags.append("both")

        flags_str = f" [{', '.join(flags)}]" if flags else ""

        # Color based on type
        if model_type == "shared":
            prefix = "  📄"
        elif model_type == "tenant":
            prefix = "  🏢"
        elif model_type == "both":
            prefix = "  🔁"
        else:
            prefix = "  ❓"

        self.stdout.write(f"{prefix} {full_name}")
        self.stdout.write(f"     Table: {table_name}{flags_str}")
