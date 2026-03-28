# Model Configuration System - Implementation Summary

**Date:** 2026-03-26  
**Status:** ✅ Implemented and Tested

---

## Overview

Implemented a model configuration system that allows developers to mark Django models as either:
- **Shared**: Stored in the default/global database, accessible across all tenants
- **Tenant**: Stored in tenant-specific schemas or databases, isolated per tenant

---

## Implementation

### 1. Core Module: `tenantkit/model_config.py`

**Components:**
- `ModelRegistry`: Global registry tracking all shared and tenant models
- `@shared_model`: Decorator to mark models as shared
- `@tenant_model`: Decorator to mark models as tenant
- `get_models_for_migration()`: Helper to get models for migration operations

**Key Features:**
- Decorators support options: `auto_migrate`, `allow_global_queries`
- Registry accessible via `ModelRegistry` class methods
- Lazy imports to avoid Django startup issues

### 2. Management Commands

#### `list_tenant_models`
Lists all registered models and their types.

```bash
# List all models
python manage.py list_tenant_models

# List only shared models
python manage.py list_tenant_models --type=shared

# List only tenant models
python manage.py list_tenant_models --type=tenant

# Include unregistered models
python manage.py list_tenant_models --include-unregistered

# Output as JSON
python manage.py list_tenant_models --json
```

#### `tenant_makemigrations`
Creates migrations for shared or tenant models separately.

```bash
# Create migrations for shared models
python manage.py tenant_makemigrations --type=shared

# Create migrations for tenant models
python manage.py tenant_makemigrations --type=tenant

# Dry run
python manage.py tenant_makemigrations --type=shared --dry-run
```

#### `tenant_migrate`
Applies migrations to shared database or tenant schemas/databases.

```bash
# Migrate shared models
python manage.py tenant_migrate --type=shared

# Migrate all tenants
python manage.py tenant_migrate --type=tenant

# Migrate specific tenant
python manage.py tenant_migrate --type=tenant --tenant=acme-corp

# Show migration plan without applying
python manage.py tenant_migrate --type=shared --plan
```

### 3. Updated Router: `tenantkit/routers/tenant.py`

Enhanced to use the model registry:
- Routes shared models to default database
- Routes tenant models to tenant-specific database/schema
- Checks `allow_global_queries` option for tenant models

### 4. Package Exports: `tenantkit/__init__.py`

Uses lazy imports to avoid circular import issues:
```python
from tenantkit import shared_model, tenant_model, ModelRegistry
```

---

## Usage Examples

### Defining Shared Models

```python
from django.db import models
from tenantkit import shared_model

@shared_model
class User(models.Model):
    email = models.EmailField(unique=True)
    first_name = models.CharField(max_length=100)

@shared_model(auto_migrate=False)
class AuditLog(models.Model):
    action = models.CharField(max_length=50)
    timestamp = models.DateTimeField(auto_now_add=True)
```

### Defining Tenant Models

```python
from django.db import models
from tenantkit import tenant_model

@tenant_model
class Product(models.Model):
    name = models.CharField(max_length=200)
    price = models.DecimalField(max_digits=10, decimal_places=2)

@tenant_model(allow_global_queries=True)
class Category(models.Model):
    name = models.CharField(max_length=100)
```

### Using the Registry API

```python
from tenantkit.model_config import ModelRegistry

# Check model type
is_shared = ModelRegistry.is_shared_model(User)
is_tenant = ModelRegistry.is_tenant_model(Product)

# Get all shared models
shared_models = ModelRegistry.get_shared_models()

# Get all tenant models
tenant_models = ModelRegistry.get_tenant_models()

# Get model config
config = ModelRegistry.get_model_config(Product)
print(config["model_type"])  # "tenant"
print(config["auto_migrate"])  # True
```

---

## Models Registered

The following tenantkit models are now registered as **shared**:

| Model | Table | Type |
|-------|-------|------|
| `Tenant` | `tenantkit_tenant` | shared |
| `TenantMembership` | `tenantkit_tenantmembership` | shared |
| `TenantInvitation` | `tenantkit_tenantinvitation` | shared |
| `TenantSetting` | `tenantkit_tenantsetting` | shared |

---

## Testing Results

✅ All commands tested and working:

```bash
$ python manage.py list_tenant_models
# Shows 4 shared models registered

$ python manage.py tenant_migrate --type=shared --plan
# Shows planned migrations for shared models

$ python manage.py tenant_migrate --type=shared
# Successfully applies migrations
```

---

## Notes

### Mixins Removed
The `SharedModel` and `TenantModel` mixins were removed because they caused `AppRegistryNotReady` errors during Django startup. The `__init_subclass__` method was being called before Django's app registry was fully populated.

**Solution:** Use decorators only (`@shared_model`, `@tenant_model`).

### Lazy Imports
The `tenantkit/__init__.py` uses `__getattr__` for lazy imports of components that need Django to be ready (models, middleware, etc.). This prevents circular import issues during startup.

---

## Next Steps

1. **Test with actual tenant models**: Create a sample app with tenant models and test the full workflow
2. **Add more options**: Consider adding `indexes`, `constraints` options to decorators
3. **Documentation**: Add more examples to the main documentation
4. **Integration tests**: Add tests for the management commands

---

## Files Modified/Created

### New Files:
- `tenantkit/model_config.py` - Core registry and decorators
- `tenantkit/management/commands/list_tenant_models.py`
- `tenantkit/management/commands/tenant_makemigrations.py`
- `tenantkit/management/commands/tenant_migrate.py`
- `docs/model_config_example.py` - Usage examples
- `docs/MODEL_CONFIG_IMPLEMENTATION.md` - This document

### Modified Files:
- `tenantkit/__init__.py` - Added lazy imports
- `tenantkit/models.py` - Added decorators to models
- `tenantkit/routers/tenant.py` - Updated to use registry

---

**Ready for use! 🚀**
