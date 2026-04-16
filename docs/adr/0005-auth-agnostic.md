# ADR-0005: Backend-Agnostic Authentication Architecture

## Status

Accepted (2026-04-15)

## Context

django-tenantkit needs to support authentication in multi-tenant environments, but different projects use different authentication backends (djangorestframework-simplejwt, Djoser, django-oauth-toolkit, Keycloak, Auth0, etc.).

### Previous Approach

The initial implementation included a user synchronization system:
- **sync.py**: Functions to synchronize users from shared database to tenant databases
- **signals.py**: Django signals for automatic user synchronization
- **AbstractTenantUser**: Abstract base model for tenant-specific users
- **TenantMembership**: Model mapping users to tenants
- **sync_tenant_users**: Management command for manual synchronization

This operated under a "shared users with memberships" principle where:
- "Real" users lived in the shared/default database
- Synchronized copies were created in each tenant database
- TenantMembership tracked which users belonged to which tenants

### Problems Identified

1. **Unnecessary complexity**: Maintaining two copies of each user requires constant synchronization
2. **Potential inconsistencies**: Data can become out of sync if signals fail or are disabled
3. **Strategy limitations**: System assumed a shared DB always exists, which is not true for "database" strategy
4. **Cross-database Foreign Keys**: Django doesn't support FKs between different databases, causing issues with TenantInvitation.accepted_by
5. **Migration overhead**: Requires migrating user models in multiple places with complex logic
6. **Backend lock-in**: Forcing a specific JWT library limits adoption

## Decision

We adopt a **backend-agnostic authentication architecture** with the following principles:

### 1. Independent Users Per Tenant

Each tenant has its own `auth_user` table, completely isolated:
- No synchronization between tenants
- The same email can exist in multiple tenants (different users)
- "Membership" is implicit: if a user exists in the tenant's DB, they are a member
- The shared/default database only contains superadmins for Django admin

### 2. DUAL_APPS for Auth Migration

Introduce `TENANTKIT_DUAL_APPS` setting for apps that must migrate in BOTH default and tenant databases:

```python
TENANTKIT_DUAL_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
]
```

This ensures `auth_user` tables exist in all databases.

### 3. Optional JWT Helpers (Backend-Agnostic)

Provide optional authentication helpers that work with any JWT backend:

- **TenantClaimsMixin**: Adds `tenant_slug` to JWT token claims
- **TenantTokenValidator**: Validates tenant claim matches current request tenant
- **TenantJWTAuthentication**: DRF authentication class combining both

These are foundation classes. Concrete JWT backend integration (e.g., simplejwt) is intentionally deferred to a future phase.

### 4. String-Based User References

Change `TenantInvitation.accepted_by` from `ForeignKey(User)` to `CharField(max_length=255)`:
- Stores username/email of the user who accepted
- Avoids cross-database FK issues
- Sufficient for audit trail purposes

## Implementation

### Phase 1: Remove Synchronization System (DEV-001) ✅

- Deleted: `sync.py`, `signals.py`, `conf.py`, `sync_tenant_users` command
- Removed: `AbstractTenantUser`, `TenantMembership` models
- Changed: `TenantInvitation.accepted_by` to CharField
- Migration: `0003_remove_tenantmembership_change_accepted_by.py`

### Phase 2: Implement DUAL_APPS (DEV-002) ✅

- Modified `TenantRouter.allow_migrate()` to check DUAL_APPS first
- Added `TENANTKIT_DUAL_APPS` setting to example configuration
- Documented migration routing logic

### Phase 3: Create Auth Helpers (DEV-003) ✅

- Created `tenantkit/auth.py` with foundation classes
- Backend-agnostic design accepting optional backend injection
- Concrete JWT technology integration deferred to future phase
- Exported helpers in `tenantkit/__init__.py`

## Consequences

### Positive

- **Simplicity**: No synchronization to maintain or debug
- **Flexibility**: Works with any JWT backend (simplejwt, Djoser, Keycloak, Auth0, etc.)
- **Scalability**: Each tenant is completely independent; can have millions of users
- **Security**: Tenant validation prevents cross-tenant token usage
- **Strategy-agnostic**: Works identically for "schema" and "database" strategies
- **No lock-in**: Projects can choose their preferred authentication technology

### Negative

- **No global user concept**: A user in Tenant A and Tenant B are separate entities
- **Email duplication**: Same email can exist in multiple tenants (this is a feature, not a bug)
- **Future integration work**: Concrete JWT backend integration requires additional implementation

### Neutral

- **Migration required**: Projects using the old sync system must migrate
- **Backend configuration**: Projects must configure their chosen JWT backend

## Alternatives Considered

### 1. Keep Synchronization System
**Rejected**: Too complex, doesn't work well with "database" strategy, prone to inconsistencies.

### 2. Force djangorestframework-simplejwt
**Rejected**: Limits adoption, many projects use other backends (Djoser, Keycloak, Auth0).

### 3. No JWT Helpers
**Rejected**: Leaves security gap; developers would need to implement tenant validation themselves.

### 4. Concrete JWT Integration Now
**Deferred**: Foundation classes provide value immediately; concrete integration can be added incrementally based on user demand.

## Security Considerations

### Cross-Tenant Token Prevention

Without validation, a JWT token generated for Tenant A could be used to access Tenant B.

**Solution**: `TenantTokenValidator` automatically verifies the `tenant_slug` claim matches the current tenant:

1. User authenticates at `tenant-a.example.com`
2. Token generated includes `{"tenant_slug": "tenant-a"}`
3. User attempts to use token at `tenant-b.example.com`
4. `TenantTokenValidator` detects mismatch and rejects token
5. User receives 401 Unauthorized

## Migration Guide

For projects using the previous sync system:

1. **Backup data**: Full database backup before migration
2. **Review AbstractTenantUser usage**: Change to extend `django.contrib.auth.models.AbstractUser` directly
3. **Review TenantMembership queries**: Check if user exists in tenant DB instead
4. **Remove sync function calls**: Delete calls to `sync_user_to_tenant()`, etc.
5. **Update settings**: Add `TENANTKIT_DUAL_APPS = ["django.contrib.auth", "django.contrib.contenttypes"]`
6. **Run migrations**: `python manage.py migrate`

## Future Work

- Document integration examples for popular JWT backends (simplejwt, Djoser, Auth0)
- Add integration tests for auth helpers
- Consider SSO integration patterns for users across multiple tenants
- Evaluate OAuth2/OIDC provider integration

## References

- PLAN_v2_auth_redesign.md
- docs/auth-and-admin.md
- [Django Multi-database Support](https://docs.djangoproject.com/en/stable/topics/db/multi-db/)
- [djangorestframework-simplejwt](https://django-rest-framework-simplejwt.readthedocs.io/)
- [Djoser](https://djoser.readthedocs.io/)
