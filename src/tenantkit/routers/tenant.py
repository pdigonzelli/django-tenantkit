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

from tenantkit.classification import (
    MODEL_TYPE_BOTH,
    get_app_scope,
    get_both_app_labels,
    get_model_scope,
)
from tenantkit.core.context import get_current_strategy, get_current_tenant
from tenantkit.model_config import (
    MODEL_TYPE_SHARED,
    MODEL_TYPE_TENANT,
    ModelRegistry,
)

logger = logging.getLogger(__name__)


def _resolve_model_for_migration(
    app_label: str, model_name: str | None, hinted_model: Any | None
) -> Any | None:
    """Resolve the best model object for migration routing.

    Django migrations may pass historical models in ``hints['model']``. Those
    historical model classes do not carry decorator-based registry metadata, so
    we prefer them only when they already classify explicitly; otherwise we
    fall back to the live app model resolved from the app registry.
    """
    if hinted_model is not None:
        hinted_config = ModelRegistry.get_model_config(hinted_model)
        if hinted_config is not None:
            return hinted_model

    if model_name:
        normalized_model_name = model_name.lower()

        for config in ModelRegistry.get_all_models():
            if (
                config.get("app_label") == app_label
                and config.get("model_name") == normalized_model_name
            ):
                return config["model_class"]

        try:
            from django.apps import apps

            return apps.get_model(app_label, model_name)
        except LookupError:
            pass

    return hinted_model


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
        return get_model_scope(model) == MODEL_TYPE_SHARED

    def _is_tenant_model(self, model: Any) -> bool:
        """Check if a model is registered as tenant."""
        return get_model_scope(model) == MODEL_TYPE_TENANT

    def _is_dual_app_model(self, model: Any) -> bool:
        """Check if model belongs to an app configured as both-scoped."""
        return get_model_scope(model) == MODEL_TYPE_BOTH

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

        # Dual-app models (e.g. auth/contenttypes) use default without tenant,
        # or the active tenant strategy when tenant context is present.
        if self._is_dual_app_model(model):
            tenant = self._get_tenant(hints)
            clean_hints = dict(hints)
            clean_hints.pop("tenant", None)

            if tenant is None:
                return "default"

            strategy = self._get_strategy()
            if strategy is None:
                return "default"

            return strategy.db_for_read(model, tenant=tenant, **clean_hints)

        if not self._is_tenant_model(model):
            return None

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

        if self._is_dual_app_model(model):
            tenant = self._get_tenant(hints)
            clean_hints = dict(hints)
            clean_hints.pop("tenant", None)

            if tenant is None:
                return "default"

            strategy = self._get_strategy()
            if strategy is None:
                return "default"

            return strategy.db_for_write(model, tenant=tenant, **clean_hints)

        if not self._is_tenant_model(model):
            return None

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

        Routing logic:
        1. Dual apps (TENANTKIT_DUAL_APPS) → migrate on ALL databases (shared + tenant)
        2. Shared models (@shared_model) → migrate only on 'default'
        3. Tenant models (@tenant_model) → migrate only on tenant databases (not 'default')
        4. Unclassified models → migrate only on 'default'

        Args:
            db: Database alias
            app_label: Application label
            model_name: Model name (optional)
            **hints: Additional hints

        Returns:
            True if migration is allowed, False if not, None to defer
        """
        # 1. Resolve model-specific scope first so decorators override app scope.
        model = _resolve_model_for_migration(app_label, model_name, hints.get("model"))

        if model:
            scope = get_model_scope(model)

            if scope == MODEL_TYPE_SHARED:
                # Shared models only migrate on default database.
                # When a tenant context is active (during tenant migrations),
                # shared models should NOT be created on default because the
                # search_path may point to the tenant schema, which would
                # incorrectly place shared tables in the tenant's schema.
                if db == "default":
                    tenant = self._get_tenant(hints)
                    strategy = self._get_strategy()
                    if tenant is not None and strategy is not None:
                        logger.debug(
                            f"Blocking shared model {model.__name__} migration "
                            f"on default during tenant context ({tenant.slug})"
                        )
                        return False
                    return True
                return False

            if scope == MODEL_TYPE_TENANT:
                # Tenant models don't migrate on default database in general.
                # However, for schema-based tenants, the default database is used
                # with a different search_path. When a schema strategy is active,
                # tenant models should be allowed on "default" because the
                # search_path is already set to the tenant's schema.
                if db == "default":
                    tenant = self._get_tenant(hints)
                    strategy = self._get_strategy()
                    if tenant is not None and strategy is not None:
                        target_db = strategy.db_for_write(model, tenant=tenant)
                        if target_db == "default":
                            logger.debug(
                                f"Allowing tenant model {model.__name__} migration "
                                f"on default for schema-based tenant {tenant.slug}"
                            )
                            return True
                    logger.debug(
                        f"Blocking tenant model {model.__name__} migration on default database"
                    )
                    return False
                # Allow on tenant databases
                return None

            if scope == MODEL_TYPE_BOTH:
                return True

        # 2. Fall back to app scope when the model is not explicitly classified.
        if app_label in get_both_app_labels():
            return True

        app_scope = get_app_scope(app_label)
        if app_scope == MODEL_TYPE_SHARED:
            return db == "default"
        if app_scope == MODEL_TYPE_TENANT:
            return db != "default"

        # 3. Unclassified models → default only
        return db == "default"
