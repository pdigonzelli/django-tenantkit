# Management Commands

This document summarizes the project-specific management commands available through the example project.

## Current Commands

### `list_tenant_models`

Lists registered shared and tenant models from the model registry.

```bash
python manage.py list_tenant_models
python manage.py list_tenant_models --type=shared
python manage.py list_tenant_models --type=tenant
python manage.py list_tenant_models --type=unclassified
python manage.py list_tenant_models --include-unregistered
python manage.py list_tenant_models --json
python manage.py list_tenant_models --app=myapp
```

**Flags:**
- `--type=shared|tenant|both|unclassified|all` — filter by model classification
- `--app=<app_label>` — filter by Django app
- `--json` — output as JSON
- `--include-unregistered` — show models not explicitly classified

### `tenant_makemigrations`

Creates migrations for shared or tenant-scoped models depending on the selected mode.

```bash
python manage.py tenant_makemigrations --type=shared
python manage.py tenant_makemigrations --type=tenant
python manage.py tenant_makemigrations --type=all
```

**Flags:**
- `--type=shared|tenant|all` — which model scope to generate migrations for
- `--tenant-name=<slug>` — target tenant for context
- `--dry-run-shared` / `--dry-run-tenant` — preview without writing

### `tenant_migrate`

Applies migrations to the shared plane or to specific tenant targets.

```bash
python manage.py tenant_migrate --type=shared
python manage.py tenant_migrate --type=tenant
python manage.py tenant_migrate --tenant=acme
python manage.py tenant_migrate --type=all
```

**Flags:**
- `--type=shared|tenant|all` — which scope to migrate
- `--tenant=<slug>` — migrate a specific tenant only
- `--skip-shared` / `--skip-tenant` — skip one scope
- `--fake-tenant` — mark migrations as applied without running them
- `--create-schemas` — create PostgreSQL schemas if they don't exist

**Behavior by isolation mode:**
- **Schema tenants**: creates schema if needed, activates `SchemaStrategy`, runs migrations on `default` database
- **Database tenants**: registers connection, runs migrations on the tenant's connection alias

### `check_tenantkit_config`

Validates the current TenantKit configuration and reports issues.

```bash
python manage.py check_tenantkit_config
python manage.py check_tenantkit_config --verbose
```

**Checks performed:**
1. `TENANTKIT_BOTH_APPS` includes `auth` and `contenttypes`
2. Deprecated `TENANTKIT_DUAL_APPS` is not in use
3. No overlapping apps between `SHARED_APPS`, `TENANT_APPS`, and `BOTH_APPS`
4. No unclassified models in non-framework apps
5. `TenantRouter` is configured in `DATABASE_ROUTERS`
6. `TenantMiddleware` is in `MIDDLEWARE` and positioned correctly (after `AuthenticationMiddleware`)

**Flags:**
- `--verbose` — show detailed info for passing checks too

## Current Usage Pattern

Typical commands from the repository root:

```bash
uv sync --dev
uv run python example/manage.py list_tenant_models
uv run python example/manage.py tenant_makemigrations --type=shared
uv run python example/manage.py tenant_migrate --type=shared
uv run python example/manage.py check_tenantkit_config --verbose
```

## Related Documents

- [Quickstart](./quickstart.md)
- [Provisioning](./provisioning.md)
- [Testing](./testing.md)
