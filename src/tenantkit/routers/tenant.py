"""
Tenant-aware database router with model registry support.

This router uses the model registry (model_config.py) to determine whether
models should be stored in the shared database or in tenant-specific
schemas/databases.

Usage:
    Add to settings.DATABASE_ROUTERS:
    DATABASE_ROUTERS = ["tenantkit.routers.tenant.TenantRouter"]
"""

from __future__ import annotations

import logging
from typing import Any

from tenantkit.core.context import get_current_strategy, get_current_tenant
from tenantkit.model_config import ModelRegistry

logger = logging.getLogger(__name__)


class TenantRouter:
    """
    Database router that supports shared and tenant models.

    Routes queries based on:
    1. Model registry classification (shared vs tenant)
    2. Current tenant context (from middleware or hints)
    3. Active tenant strategy (schema vs database isolation)

    Shared models always go to the default database.
    Tenant models go to the tenant's schema or database.
    """

    def _get_tenant(self, hints: dict[str, Any]) -> Any | None:
        """Get tenant from hints or current context."""
        if "tenant" in hints:
            return hints["tenant"]
        return get_current_tenant()

    def _get_strategy(self) -> Any | None:
        """Get current tenant strategy."""
        return get_current_strategy()

    def _is_shared_model(self, model: Any) -> bool:
        """Check if a model is registered as shared."""
        return ModelRegistry.is_shared_model(model)

    def _is_tenant_model(self, model: Any) -> bool:
        """Check if a model is registered as tenant."""
        return ModelRegistry.is_tenant_model(model)

    def db_for_read(self, model: Any, **hints: Any) -> str | None:
        """
        Determine which database to use for read operations.

        Args:
            model: The model class being queried
            **hints: Additional hints, may include 'tenant'

        Returns:
            Database alias or None to use default routing
        """
        # Shared models always use default database
        if self._is_shared_model(model):
            logger.debug(f"Routing read for shared model {model.__name__} to default")
            return "default"

        # For tenant models, we need a tenant context
        tenant = self._get_tenant(hints)
        clean_hints = dict(hints)
        clean_hints.pop("tenant", None)

        if tenant is None:
            # No tenant context - check if model allows global queries
            config = ModelRegistry.get_model_config(model)
            if config and config.get("allow_global_queries"):
                logger.debug(
                    f"Routing read for tenant model {model.__name__} to default (global query)"
                )
                return "default"
            # Otherwise, let default routing handle it (will likely fail)
            logger.warning(f"No tenant context for tenant model {model.__name__}")
            return None

        # Check tenant is active
        if getattr(tenant, "deleted", False) or not getattr(tenant, "is_active", True):
            raise RuntimeError(f"Tenant {tenant} is inactive or deleted.")

        # Use strategy to determine database
        strategy = self._get_strategy()
        if strategy is None:
            return None

        db = strategy.db_for_read(model, tenant=tenant, **clean_hints)
        logger.debug(f"Routing read for {model.__name__} to {db} via strategy")
        return db

    def db_for_write(self, model: Any, **hints: Any) -> str | None:
        """
        Determine which database to use for write operations.

        Args:
            model: The model class being written
            **hints: Additional hints, may include 'tenant'

        Returns:
            Database alias or None to use default routing
        """
        # Shared models always use default database
        if self._is_shared_model(model):
            logger.debug(f"Routing write for shared model {model.__name__} to default")
            return "default"

        # For tenant models, we need a tenant context
        tenant = self._get_tenant(hints)
        clean_hints = dict(hints)
        clean_hints.pop("tenant", None)

        if tenant is None:
            logger.warning(f"No tenant context for tenant model {model.__name__}")
            return None

        # Check tenant is active
        if getattr(tenant, "deleted", False) or not getattr(tenant, "is_active", True):
            raise RuntimeError(f"Tenant {tenant} is inactive or deleted.")

        # Use strategy to determine database
        strategy = self._get_strategy()
        if strategy is None:
            return None

        db = strategy.db_for_write(model, tenant=tenant, **clean_hints)
        logger.debug(f"Routing write for {model.__name__} to {db} via strategy")
        return db

    def allow_relation(self, obj1: Any, obj2: Any, **hints: Any) -> bool | None:
        """
        Determine if a relation is allowed between two objects.

        Returns:
            True if relation is allowed, False if not, None to defer to default
        """
        # Get model classes
        model1 = type(obj1)
        model2 = type(obj2)

        is_shared_1 = self._is_shared_model(model1)
        is_shared_2 = self._is_shared_model(model2)
        is_tenant_1 = self._is_tenant_model(model1)
        is_tenant_2 = self._is_tenant_model(model2)

        # Both shared - allow relation
        if is_shared_1 and is_shared_2:
            return True

        # Both tenant - check if same tenant
        if is_tenant_1 and is_tenant_2:
            # Get tenant from instances if available
            tenant1 = getattr(obj1, "tenant", None) or hints.get("tenant")
            tenant2 = getattr(obj2, "tenant", None) or hints.get("tenant")

            if tenant1 and tenant2:
                return tenant1 == tenant2
            # If we can't determine, defer to default
            return None

        # One shared, one tenant - generally not allowed unless explicitly configured
        if (is_shared_1 and is_tenant_2) or (is_tenant_1 and is_shared_2):
            # Could add configuration option to allow cross-tenant relations
            logger.warning(
                f"Cross-tenant relation attempted: {model1.__name__} <-> {model2.__name__}"
            )
            return False

        # Unknown classification - defer to default
        return None

    def allow_migrate(
        self,
        db: str,
        app_label: str,
        model_name: str | None = None,
        **hints: Any,
    ) -> bool | None:
        """
        Determine if migrations are allowed on a database.

        Args:
            db: Database alias
            app_label: Application label
            model_name: Model name (optional)
            **hints: Additional hints

        Returns:
            True if migration is allowed, False if not, None to defer
        """
        # Get the model if possible
        model = None
        if model_name:
            try:
                from django.apps import apps

                model = apps.get_model(app_label, model_name)
            except LookupError:
                pass

        if model:
            # Check model registry
            is_shared = self._is_shared_model(model)
            is_tenant = self._is_tenant_model(model)

            if is_shared:
                # Shared models only migrate on default database
                return db == "default"

            if is_tenant:
                # Tenant models don't migrate on default (they migrate on tenant DBs)
                # Exception: if we're creating the initial schema
                if db == "default":
                    return False
                # Allow on tenant databases - strategy will validate
                return None

        # Unclassified model - defer to strategy or default
        strategy = self._get_strategy()
        if strategy:
            return strategy.allow_migrate(db, app_label, model_name=model_name, **hints)

        return None
