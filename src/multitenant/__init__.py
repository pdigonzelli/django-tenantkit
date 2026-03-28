"""
django-tenantkit: A hybrid multitenant Django framework.

This package provides tools for building multitenant Django applications
with support for both schema-based and database-based isolation.

Quick Start:
    1. Mark your models as shared or tenant:

       from multitenant import shared_model, tenant_model

       @shared_model
       class User(models.Model):
           email = models.EmailField()

       @tenant_model
       class Product(models.Model):
           name = models.CharField(max_length=100)

    2. Use management commands:

       python manage.py list_tenant_models
       python manage.py tenant_makemigrations
       python manage.py tenant_migrate

    3. Add middleware and router to settings:

       MIDDLEWARE = [
           "multitenant.middleware.TenantMiddleware",
           # ...
       ]

       DATABASE_ROUTERS = ["multitenant.routers.tenant.TenantRouter"]
"""

__version__ = "0.1.0"

# Model configuration exports (safe to import early)
from .model_config import (
    MODEL_TYPE_SHARED,
    MODEL_TYPE_TENANT,
    MODEL_TYPE_UNCLASSIFIED,
    ModelConfigError,
    ModelRegistry,
    get_models_for_migration,
    shared_model,
    tenant_model,
)

# Lazy imports for components that need Django to be ready
# These are imported on demand to avoid AppRegistryNotReady


def _lazy_import(name: str):
    """Lazy import to avoid circular imports during Django startup."""
    import importlib

    module_map = {
        # Core context
        "get_current_tenant": (".core.context", "get_current_tenant"),
        "set_current_tenant": (".core.context", "set_current_tenant"),
        "get_current_strategy": (".core.context", "get_current_strategy"),
        # Middleware
        "TenantMiddleware": (".middleware", "TenantMiddleware"),
        "tenant_state": (".middleware", "tenant_state"),
        # Models
        "AuditModel": (".models", "AuditModel"),
        "Tenant": (".models", "Tenant"),
        "TenantMembership": (".models", "TenantMembership"),
        "TenantInvitation": (".models", "TenantInvitation"),
        "TenantSetting": (".models", "TenantSetting"),
        "TenantSharedModel": (".models", "TenantSharedModel"),
    }

    if name not in module_map:
        raise AttributeError(f"module 'multitenant' has no attribute '{name}'")

    module_path, attr_name = module_map[name]
    module = importlib.import_module(module_path, package=__name__)
    return getattr(module, attr_name)


# Use __getattr__ for lazy imports
def __getattr__(name: str):
    return _lazy_import(name)


__all__ = [
    # Version
    "__version__",
    # Model configuration (decorators only - mixins removed)
    "shared_model",
    "tenant_model",
    "ModelRegistry",
    "ModelConfigError",
    "get_models_for_migration",
    "MODEL_TYPE_SHARED",
    "MODEL_TYPE_TENANT",
    "MODEL_TYPE_UNCLASSIFIED",
    # Lazy imports (available after Django setup)
    "get_current_tenant",
    "set_current_tenant",
    "get_current_strategy",
    "TenantMiddleware",
    "tenant_state",
    "AuditModel",
    "Tenant",
    "TenantMembership",
    "TenantInvitation",
    "TenantSetting",
    "TenantSharedModel",
]
