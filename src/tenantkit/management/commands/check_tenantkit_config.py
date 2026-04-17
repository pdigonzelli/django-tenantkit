"""
Verify tenantkit configuration and detect potential issues.

Usage:
    python manage.py check_tenantkit_config
    python manage.py check_tenantkit_config --verbose
"""

# pyright: reportAttributeAccessIssue=false

from __future__ import annotations

from typing import Any

from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand

from tenantkit.classification import (
    get_app_scope,
    get_both_app_labels,
    get_model_scope,
    get_shared_app_labels,
    get_tenant_app_labels,
    is_framework_app,
)
from tenantkit.model_config import MODEL_TYPE_UNCLASSIFIED


class Command(BaseCommand):
    help = "Verify tenantkit configuration and detect potential issues"

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Show detailed information about each check",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        verbose = options.get("verbose", False)
        issues_found = 0

        self.stdout.write(self.style.MIGRATE_HEADING("=" * 80))
        self.stdout.write(self.style.MIGRATE_HEADING("TENANTKIT CONFIGURATION CHECK"))
        self.stdout.write(self.style.MIGRATE_HEADING("=" * 80))
        self.stdout.write()

        # Check 1: BOTH_APPS configuration
        issues_found += self._check_both_apps(verbose)

        # Check 2: Deprecated DUAL_APPS
        issues_found += self._check_deprecated_dual_apps(verbose)

        # Check 3: Overlapping app configurations
        issues_found += self._check_overlapping_apps(verbose)

        # Check 4: Unclassified models in non-framework apps
        issues_found += self._check_unclassified_models(verbose)

        # Check 5: Router configuration
        issues_found += self._check_router_config(verbose)

        # Check 6: Middleware configuration
        issues_found += self._check_middleware_config(verbose)

        # Summary
        self.stdout.write()
        self.stdout.write(self.style.MIGRATE_HEADING("─" * 80))
        if issues_found == 0:
            self.stdout.write(
                self.style.SUCCESS("✓ All checks passed! No issues found.")
            )
        else:
            self.stdout.write(
                self.style.WARNING(f"⚠ Found {issues_found} issue(s). Review above.")
            )
        self.stdout.write()

    def _check_both_apps(self, verbose: bool) -> int:
        """Check that BOTH_APPS includes auth and contenttypes."""
        both_apps = get_both_app_labels()
        required = {"auth", "contenttypes"}
        missing = required - both_apps

        if missing:
            self.stdout.write(self.style.WARNING("⚠ BOTH_APPS Configuration Issue"))
            self.stdout.write(
                f"   Missing recommended apps: {', '.join(sorted(missing))}"
            )
            self.stdout.write(
                "   These apps should typically be in TENANTKIT_BOTH_APPS"
            )
            self.stdout.write()
            return 1

        if verbose:
            self.stdout.write(
                self.style.SUCCESS("✓ BOTH_APPS includes required framework apps")
            )
            self.stdout.write(f"   Configured: {', '.join(sorted(both_apps))}")
            self.stdout.write()

        return 0

    def _check_deprecated_dual_apps(self, verbose: bool) -> int:
        """Check for deprecated TENANTKIT_DUAL_APPS usage."""
        dual_apps: list[str] = getattr(settings, "TENANTKIT_DUAL_APPS", [])

        if dual_apps:
            self.stdout.write(self.style.WARNING("⚠ Deprecated Configuration"))
            self.stdout.write(
                "   TENANTKIT_DUAL_APPS is deprecated and will be removed in v2.0"
            )
            self.stdout.write(f"   Current value: {dual_apps}")
            self.stdout.write("   Migration: Rename to TENANTKIT_BOTH_APPS")
            self.stdout.write()
            return 1

        if verbose:
            self.stdout.write(
                self.style.SUCCESS("✓ No deprecated TENANTKIT_DUAL_APPS found")
            )
            self.stdout.write()

        return 0

    def _check_overlapping_apps(self, verbose: bool) -> int:
        """Check for apps configured in multiple scopes."""
        shared = get_shared_app_labels()
        tenant = get_tenant_app_labels()
        both = get_both_app_labels()

        overlaps = set()
        overlaps.update(shared & tenant)
        overlaps.update(shared & both)
        overlaps.update(tenant & both)

        if overlaps:
            self.stdout.write(self.style.ERROR("✗ Overlapping App Configuration"))
            for app in sorted(overlaps):
                scopes = []
                if app in shared:
                    scopes.append("SHARED")
                if app in tenant:
                    scopes.append("TENANT")
                if app in both:
                    scopes.append("BOTH")
                self.stdout.write(f"   {app}: configured as {', '.join(scopes)}")
            self.stdout.write("   Each app should only be in one scope configuration")
            self.stdout.write()
            return len(overlaps)

        if verbose:
            self.stdout.write(self.style.SUCCESS("✓ No overlapping app configurations"))
            self.stdout.write(f"   Shared apps: {len(shared)}")
            self.stdout.write(f"   Tenant apps: {len(tenant)}")
            self.stdout.write(f"   Both apps: {len(both)}")
            self.stdout.write()

        return 0

    def _check_unclassified_models(self, verbose: bool) -> int:
        """Check for unclassified models in non-framework apps."""
        unclassified: list[str] = []

        for model in apps.get_models():
            app_label = model._meta.app_label

            if is_framework_app(app_label):
                continue

            # Check if app is configured
            app_scope = get_app_scope(app_label)
            if app_scope != MODEL_TYPE_UNCLASSIFIED:
                continue

            # Check if model is explicitly classified
            model_scope = get_model_scope(model)
            if model_scope == MODEL_TYPE_UNCLASSIFIED:
                unclassified.append(f"{model.__module__}.{model.__name__}")

        if unclassified:
            self.stdout.write(
                self.style.WARNING(f"⚠ Unclassified Models ({len(unclassified)})")
            )
            for name in unclassified[:5]:  # Show first 5
                self.stdout.write(f"   {name}")
            if len(unclassified) > 5:
                self.stdout.write(f"   ... and {len(unclassified) - 5} more")
            self.stdout.write("   Use @shared_model/@tenant_model or configure the app")
            self.stdout.write()
            return len(unclassified)

        if verbose:
            self.stdout.write(
                self.style.SUCCESS("✓ All models are properly classified")
            )
            self.stdout.write()

        return 0

    def _check_router_config(self, verbose: bool) -> int:
        """Check that TenantRouter is configured."""
        routers: list[str] = getattr(settings, "DATABASE_ROUTERS", [])
        has_tenant_router = any(
            "TenantRouter" in r or "tenantkit" in r for r in routers
        )

        if not has_tenant_router:
            self.stdout.write(self.style.ERROR("✗ Missing TenantRouter"))
            self.stdout.write(
                "   DATABASE_ROUTERS must include 'tenantkit.routers.TenantRouter'"
            )
            self.stdout.write()
            return 1

        if verbose:
            self.stdout.write(self.style.SUCCESS("✓ TenantRouter is configured"))
            self.stdout.write(f"   Routers: {routers}")
            self.stdout.write()

        return 0

    def _check_middleware_config(self, verbose: bool) -> int:
        """Check that TenantMiddleware is configured."""
        middleware: list[str] = getattr(settings, "MIDDLEWARE", [])
        has_tenant_middleware = any(
            "TenantMiddleware" in m or "tenantkit" in m for m in middleware
        )

        if not has_tenant_middleware:
            self.stdout.write(self.style.ERROR("✗ Missing TenantMiddleware"))
            self.stdout.write(
                "   MIDDLEWARE must include 'tenantkit.middleware.TenantMiddleware'"
            )
            self.stdout.write()
            return 1

        # Check position (should be after SecurityMiddleware, before SessionMiddleware)
        security_idx = -1
        tenant_idx = -1
        session_idx = -1

        for i, m in enumerate(middleware):
            if "SecurityMiddleware" in m:
                security_idx = i
            if "TenantMiddleware" in m or "tenantkit" in m:
                tenant_idx = i
            if "SessionMiddleware" in m:
                session_idx = i

        position_ok = True
        if security_idx >= 0 and tenant_idx < security_idx:
            position_ok = False
        if session_idx >= 0 and tenant_idx > session_idx:
            position_ok = False

        if not position_ok:
            self.stdout.write(self.style.WARNING("⚠ TenantMiddleware Position"))
            self.stdout.write(
                "   Should be after SecurityMiddleware, before SessionMiddleware"
            )
            self.stdout.write()
            return 1

        if verbose:
            self.stdout.write(
                self.style.SUCCESS("✓ TenantMiddleware is properly configured")
            )
            self.stdout.write(f"   Position: {tenant_idx + 1} of {len(middleware)}")
            self.stdout.write()

        return 0
