# Quickstart

This guide describes the shortest path to understanding how the package is wired in the current repository layout.

## Current Reference Flow

The current reference environment uses:

- `src/tenantkit` as the reusable package source
- `example/` as the Django integration project

```bash
uv sync --dev
uv run python example/manage.py test tenantkit
```

## Minimal Integration Shape

A Django project using the package will typically:

1. add the multitenancy app to `INSTALLED_APPS`
2. add tenant-aware middleware
3. add the tenant database router
4. define shared and tenant-scoped models
5. create one or more tenants
6. run the appropriate migration workflow

In this repository, those integration points are currently exercised through `example/config` and `example/manage.py`.

## Current Example Concepts

The framework currently exposes concepts such as:

- shared models
- tenant models
- schema isolation
- database isolation
- tenant provisioning
- tenant-aware admin behavior

The source code for those capabilities lives in `src/tenantkit`.

## Next Reading

- [Installation](./installation.md)
- [Concepts](./concepts.md)
- [Commands](./commands.md)
- [Provisioning](./provisioning.md)
