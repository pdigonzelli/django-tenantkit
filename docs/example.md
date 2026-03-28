# Example Project

This repository includes a Django reference project under `example/`.

## Purpose

The example project serves as:

- the current integration environment
- the current test harness
- the reference wiring for settings, middleware, routing, and admin behavior

The reusable package source is intentionally separate and lives under `src/multitenant`.

## Current Location

```text
example/
```

## Typical Usage

```bash
uv sync --dev
uv run python example/manage.py test multitenant
uv run python example/manage.py runserver
```

## Scope

The example project is not the package source tree.
It is the reference Django application used to validate and demonstrate the package that lives in `src/multitenant`.

## Related Documents

- [Installation](./installation.md)
- [Quickstart](./quickstart.md)
- [Testing](./testing.md)
