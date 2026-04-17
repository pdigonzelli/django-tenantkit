# ADR 0006: App and Model Classification System

## Status

**Accepted** – Implemented in v0.2.0

## Context

The original tenantkit architecture relied primarily on model-level decorators (`@shared_model`, `@tenant_model`) to classify models for multi-tenant routing. While this provided fine-grained control, it had several limitations:

1. **Framework apps** (like `django.contrib.auth`, `django.contrib.contenttypes`) needed special handling via `TENANTKIT_DUAL_APPS`, which was conceptually unclear.

2. **No explicit app-level classification** – developers couldn't easily declare "all models in this app are tenant-scoped" without decorating each model individually.

3. **Ambiguous precedence** – when both app-level and model-level classification existed, the resolution rules were implicit and confusing.

4. **Poor developer experience** – discovering which models were classified how required inspecting code or running commands.

## Decision

We will implement a **hierarchical classification system** with explicit precedence rules:

### Classification Levels (highest to lowest precedence)

1. **Model Decorator** (`@shared_model`, `@tenant_model`)
   - Explicit per-model classification
   - Always wins over app-level settings
   - Allows mixed apps (some shared, some tenant models)

2. **Mixed App Configuration** (`TENANTKIT_MIXED_APPS`)
   - Per-model classification within an app
   - Dictionary mapping app labels to lists of model names
   - Example: `{"myapp": {"shared_models": ["Config"], "tenant_models": ["Data"]}}`

3. **Both-Scope Apps** (`TENANTKIT_BOTH_APPS`)
   - Apps that migrate to both shared and tenant contexts
   - Replaces deprecated `TENANTKIT_DUAL_APPS`
   - Models in these apps exist in both scopes

4. **App-Level Classification**
   - `TENANTKIT_SHARED_APPS` – all models in these apps are shared
   - `TENANTKIT_TENANT_APPS` – all models in these apps are tenant-scoped

5. **Default**
   - Unclassified models defer to Django's default routing
   - System check warns about unclassified models in non-framework apps

### Settings Schema

```python
# apps that exist only in shared/default database
TENANTKIT_SHARED_APPS = [
    "tenantkit",  # framework models
]

# apps that exist only in tenant contexts
TENANTKIT_TENANT_APPS = [
    # your tenant-scoped business apps
]

# apps that exist in BOTH shared and tenant contexts
TENANTKIT_BOTH_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
]

# deprecated but supported for backward compatibility
TENANTKIT_DUAL_APPS = []  # emits DeprecationWarning

# fine-grained control for mixed apps (optional)
TENANTKIT_MIXED_APPS = {
    # "myapp": {
    #     "shared_models": ["GlobalConfig"],
    #     "tenant_models": ["TenantData"],
    # }
}
```

### Router Behavior

The `TenantRouter` uses `get_model_scope()` and `get_app_scope()` helpers to determine routing:

**For reads/writes:**
- Shared → `default` database
- Tenant → requires tenant context, uses active strategy
- Both → `default` without tenant, strategy with tenant
- Unclassified → defer to Django default

**For migrations (`allow_migrate`):**
- Shared → only `default`
- Tenant → only non-default (tenant DBs)
- Both → all databases
- Unclassified → only `default` (safe default)

## Consequences

### Positive

1. **Clearer mental model** – developers think in terms of app scope first, model scope second
2. **Better framework integration** – `auth`, `contenttypes` fit naturally into `BOTH_APPS`
3. **Explicit over implicit** – precedence rules are documented and enforced
4. **Backward compatible** – existing `@shared_model`/`@tenant_model` decorators continue working
5. **Discoverability** – `list_tenant_models` command shows classification clearly

### Negative

1. **More configuration options** – potential for confusion with many settings
2. **Migration complexity** – existing projects using `TENANTKIT_DUAL_APPS` need migration
3. **Performance** – classification lookups are cached but add minimal overhead

## Migration Path

### Phase 1: Foundation (v0.2.0)
- New settings available
- Classification helpers implemented
- `TENANTKIT_DUAL_APPS` deprecated with warning

### Phase 2: Tooling (v0.3.0)
- `check_tenantkit_config` command
- Enhanced `list_tenant_models`
- System checks for unclassified models

### Phase 3: Deprecation (v1.0.0)
- `TENANTKIT_DUAL_APPS` marked deprecated
- Migration guide published
- Automated migration detection

### Phase 4: Removal (v2.0.0)
- `TENANTKIT_DUAL_APPS` removed
- Only new settings supported

## References

- Original dual apps concept: `docs/adr/0005-auth-agnostic.md`
- Implementation: `src/tenantkit/classification.py`
- Router updates: `src/tenantkit/routers/tenant.py`
- System checks: `src/tenantkit/checks.py`

## Notes

The term "BOTH" was chosen over "DUAL" to:
- Avoid confusion with the deprecated setting
- Better convey "exists in both scopes" concept
- Align with common multi-tenancy terminology
