"""Create a superuser in a tenant schema or database.

Usage:
    python manage.py tenant_createsuperuser --tenant <slug>
"""

from __future__ import annotations

import getpass
from typing import Any

from django.contrib.auth.management.commands.createsuperuser import Command as BaseCreateSuperuserCommand
from django.core.management.base import CommandError, CommandParser
from django.db import connections

from tenantkit.core.context import (
    clear_current_strategy,
    clear_current_tenant,
    set_current_strategy,
    set_current_tenant,
)
from tenantkit.models import Tenant
from tenantkit.strategies.database.strategy import DatabaseStrategy
from tenantkit.strategies.schema.strategy import SchemaStrategy


class Command(BaseCreateSuperuserCommand):
    help = "Create a superuser inside a tenant schema or database"

    def add_arguments(self, parser: CommandParser) -> None:
        super().add_arguments(parser)
        parser.add_argument(
            "--tenant",
            required=True,
            help="Tenant slug in which to create the superuser",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        tenant_slug: str = options["tenant"]

        try:
            tenant = Tenant.objects.get(slug=tenant_slug)
        except Tenant.DoesNotExist:
            raise CommandError(f"Tenant '{tenant_slug}' does not exist.") from None

        # Activate tenant context so the User model queries the right schema
        if tenant.isolation_mode == Tenant.IsolationMode.SCHEMA:
            strategy = SchemaStrategy()
            set_current_tenant(tenant)
            set_current_strategy(strategy)
            strategy.activate(tenant)
        elif tenant.isolation_mode == Tenant.IsolationMode.DATABASE:
            from tenantkit.bootstrap import register_database_tenant_connection

            register_database_tenant_connection(tenant)
            strategy = DatabaseStrategy()
            set_current_tenant(tenant)
            set_current_strategy(strategy)
        else:
            raise CommandError(f"Unknown isolation mode: {tenant.isolation_mode}")

        try:
            # Let Django's createsuperuser do the rest (it respects the
            # active database connection / search_path set by the strategy).
            super().handle(*args, **options)
        finally:
            if tenant.isolation_mode == Tenant.IsolationMode.SCHEMA:
                strategy.deactivate()  # type: ignore[union-attr]
            clear_current_strategy()
            clear_current_tenant()
