# Management Commands

This document summarizes the project-specific management commands available through the example project.

## Current Commands

### `list_tenant_models`

Lists registered shared and tenant models.

### `tenant_makemigrations`

Creates migrations for shared or tenant-scoped models depending on the selected mode.

### `tenant_migrate`

Applies migrations to the shared plane or to tenant targets.

## Current Usage Pattern

Typical commands from the repository root:

```bash
uv sync --dev
uv run python example/manage.py list_tenant_models
uv run python example/manage.py tenant_makemigrations --type=shared
uv run python example/manage.py tenant_migrate --type=shared
```

## Notes

The command set will be documented in more detail as the public package and release workflow are finalized.

## Related Documents

- [Quickstart](./quickstart.md)
- [Provisioning](./provisioning.md)
- [Testing](./testing.md)
