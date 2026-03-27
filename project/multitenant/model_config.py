"""
Model configuration system for django-multitenant.

Provides decorators and mixins to mark models as:
- Shared: Stored in the default/global database
- Tenant: Stored in tenant-specific schema or database

Usage:
    # Option 1: Using mixins
    from multitenant.model_config import SharedModel, TenantModel

    class MySharedModel(SharedModel):
        name = models.CharField(max_length=100)

    class MyTenantModel(TenantModel):
        name = models.CharField(max_length=100)

    # Option 2: Using decorators
    from multitenant.model_config import shared_model, tenant_model

    @shared_model
    class MySharedModel(models.Model):
        name = models.CharField(max_length=100)

    @tenant_model
    class MyTenantModel(models.Model):
        name = models.CharField(max_length=100)
"""

from __future__ import annotations

import logging
from typing import Any, Callable, ClassVar, TypeVar

from django.db import models

logger = logging.getLogger(__name__)

# Registry of model configurations
_model_registry: dict[str, dict[str, Any]] = {}

# Model type constants
MODEL_TYPE_SHARED = "shared"
MODEL_TYPE_TENANT = "tenant"
MODEL_TYPE_UNCLASSIFIED = "unclassified"


class ModelConfigError(Exception):
    """Raised when there's an error in model configuration."""

    pass


class ModelRegistry:
    """Registry for tracking shared and tenant models."""

    _registry: ClassVar[dict[str, dict[str, Any]]] = {}

    @classmethod
    def register(
        cls,
        model_class: type[models.Model],
        model_type: str,
        **options: Any,
    ) -> type[models.Model]:
        """
        Register a model with its type and options.

        Args:
            model_class: The Django model class to register
            model_type: Either MODEL_TYPE_SHARED or MODEL_TYPE_TENANT
            **options: Additional configuration options
                - auto_migrate: bool = True (whether to auto-migrate this model)
                - allow_global_queries: bool = False (for tenant models, allow queries without tenant context)

        Returns:
            The registered model class (for decorator chaining)
        """
        full_name = f"{model_class.__module__}.{model_class.__name__}"

        if model_type not in (MODEL_TYPE_SHARED, MODEL_TYPE_TENANT, MODEL_TYPE_UNCLASSIFIED):
            raise ModelConfigError(f"Invalid model_type: {model_type}")

        cls._registry[full_name] = {
            "model_class": model_class,
            "model_type": model_type,
            "full_name": full_name,
            "app_label": model_class._meta.app_label,
            "model_name": model_class._meta.model_name,
            "auto_migrate": options.get("auto_migrate", True),
            "allow_global_queries": options.get("allow_global_queries", False),
            **options,
        }

        logger.debug(f"Registered {model_type} model: {full_name}")
        return model_class

    @classmethod
    def get_model_config(cls, model_class: type[models.Model] | str) -> dict[str, Any] | None:
        """
        Get configuration for a model.

        Args:
            model_class: Model class or full name string (e.g., 'myapp.MyModel')

        Returns:
            Model configuration dict or None if not registered
        """
        if isinstance(model_class, str):
            full_name = model_class
        else:
            full_name = f"{model_class.__module__}.{model_class.__name__}"

        return cls._registry.get(full_name)

    @classmethod
    def get_model_type(cls, model_class: type[models.Model] | str) -> str:
        """
        Get the type of a model.

        Args:
            model_class: Model class or full name string

        Returns:
            One of MODEL_TYPE_SHARED, MODEL_TYPE_TENANT, or MODEL_TYPE_UNCLASSIFIED
        """
        config = cls.get_model_config(model_class)
        if config:
            return config["model_type"]
        return MODEL_TYPE_UNCLASSIFIED

    @classmethod
    def is_shared_model(cls, model_class: type[models.Model] | str) -> bool:
        """Check if a model is registered as shared."""
        return cls.get_model_type(model_class) == MODEL_TYPE_SHARED

    @classmethod
    def is_tenant_model(cls, model_class: type[models.Model] | str) -> bool:
        """Check if a model is registered as tenant."""
        return cls.get_model_type(model_class) == MODEL_TYPE_TENANT

    @classmethod
    def get_shared_models(cls) -> list[dict[str, Any]]:
        """Get all registered shared models."""
        return [
            config for config in cls._registry.values()
            if config["model_type"] == MODEL_TYPE_SHARED
        ]

    @classmethod
    def get_tenant_models(cls) -> list[dict[str, Any]]:
        """Get all registered tenant models."""
        return [
            config for config in cls._registry.values()
            if config["model_type"] == MODEL_TYPE_TENANT
        ]

    @classmethod
    def get_all_models(cls) -> list[dict[str, Any]]:
        """Get all registered models."""
        return list(cls._registry.values())

    @classmethod
    def clear_registry(cls) -> None:
        """Clear the registry (useful for testing)."""
        cls._registry.clear()


# Type variable for generic model class
T = TypeVar("T", bound=type[models.Model])


def shared_model(
    _cls: T | None = None,
    *,
    auto_migrate: bool = True,
    **options: Any,
) -> T | Callable[[T], T]:
    """
    Decorator to mark a model as shared (global/default database).

    Shared models are stored in the default database and are accessible
    across all tenants. Use this for: users, tenant definitions, global settings.

    Args:
        auto_migrate: Whether to include this model in automatic migrations
        **options: Additional configuration options

    Usage:
        @shared_model
        class MyModel(models.Model):
            pass

        @shared_model(auto_migrate=False)
        class MyModel(models.Model):
            pass
    """
    def decorator(cls: T) -> T:
        return ModelRegistry.register(
            cls,
            MODEL_TYPE_SHARED,
            auto_migrate=auto_migrate,
            **options,
        )

    if _cls is None:
        # Called as @shared_model(...) with parentheses
        return decorator
    else:
        # Called as @shared_model without parentheses
        return decorator(_cls)


def tenant_model(
    _cls: T | None = None,
    *,
    auto_migrate: bool = True,
    allow_global_queries: bool = False,
    **options: Any,
) -> T | Callable[[T], T]:
    """
    Decorator to mark a model as tenant-specific.

    Tenant models are stored in tenant-specific schemas or databases.
    Each tenant has its own isolated copy of these tables.

    Args:
        auto_migrate: Whether to include this model in automatic migrations
        allow_global_queries: If True, allows queries without tenant context (returns all tenants' data)
        **options: Additional configuration options

    Usage:
        @tenant_model
        class MyModel(models.Model):
            pass

        @tenant_model(allow_global_queries=True)
        class MyModel(models.Model):
            pass
    """
    def decorator(cls: T) -> T:
        return ModelRegistry.register(
            cls,
            MODEL_TYPE_TENANT,
            auto_migrate=auto_migrate,
            allow_global_queries=allow_global_queries,
            **options,
        )

    if _cls is None:
        # Called as @tenant_model(...) with parentheses
        return decorator
    else:
        # Called as @tenant_model without parentheses
        return decorator(_cls)


# Note: SharedModel and TenantModel mixins removed because they fail
# during Django startup due to AppRegistryNotReady.
# Use @shared_model and @tenant_model decorators instead.


# Convenience function to get all models that need migration
def get_models_for_migration(model_type: str | None = None) -> list[type[models.Model]]:
    """
    Get models that should be migrated.

    Args:
        model_type: If specified, filter by 'shared' or 'tenant'

    Returns:
        List of model classes
    """
    if model_type == MODEL_TYPE_SHARED:
        configs = ModelRegistry.get_shared_models()
    elif model_type == MODEL_TYPE_TENANT:
        configs = ModelRegistry.get_tenant_models()
    else:
        configs = ModelRegistry.get_all_models()

    return [
        config["model_class"]
        for config in configs
        if config.get("auto_migrate", True)
    ]


# Exports
__all__ = [
    "ModelRegistry",
    "ModelConfigError",
    "shared_model",
    "tenant_model",
    "get_models_for_migration",
    "MODEL_TYPE_SHARED",
    "MODEL_TYPE_TENANT",
    "MODEL_TYPE_UNCLASSIFIED",
]
