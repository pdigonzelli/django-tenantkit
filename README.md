# django-tenantkit

[![CI](https://github.com/pdigonzelli/django-tenantkit/actions/workflows/ci.yml/badge.svg)](https://github.com/pdigonzelli/django-tenantkit/actions)
[![Python](https://img.shields.io/badge/python-3.12%20|%203.13-blue)](https://pypi.org/project/django-tenantkit-core/)
[![Django](https://img.shields.io/badge/django-6.0-green)](https://pypi.org/project/django-tenantkit-core/)
[![License](https://img.shields.io/badge/license-MIT-lightgrey)](LICENSE)

A Django-native multitenancy framework focused on explicit isolation strategies, clear shared-versus-tenant boundaries, and integration with Django middleware, routing, admin, and provisioning workflows.

---

## Why this package?

Multi-tenant Django systems often need different trade-offs depending on scale, operational model, and isolation requirements.
Some solutions focus primarily on PostgreSQL schema isolation, while others assume a narrower routing or provisioning model.

This project aims to provide a more flexible foundation for Django applications that need:

- explicit tenant isolation strategies
- clear separation between shared/public and tenant-scoped data
- Django-native integration points instead of a parallel platform model
- a path toward a reusable package plus a reference example project

---

## Supported isolation strategies

The framework currently supports two primary isolation modes:

| Strategy | Description | Best fit |
|---|---|---|
| `schema` | Multiple PostgreSQL schemas inside one shared database | Shared infrastructure with strong logical isolation |
| `database` | A dedicated database per tenant | Stronger operational isolation and backend flexibility |

The shared/public control plane remains separate from tenant-scoped runtime behavior.

See [Concepts](https://github.com/pdigonzelli/django-tenantkit/blob/main/docs/concepts.md) for the model vocabulary and architectural terms.

---

## Audit and soft-delete

All framework models include **mandatory** audit tracking via [django-auditkit](https://github.com/pdigonzelli/django-auditkit):

- `created_at`, `updated_at`, `deleted_at` — timestamps
- `created_by`, `updated_by`, `deleted_by` — user tracking (foreign keys to `AUTH_USER_MODEL`)

This provides:
- **Soft delete** — records are marked deleted but retained for audit/history
- **User attribution** — every change is traceable to a user
- **Recovery** — soft-deleted records can be restored

The framework models (`Tenant`, `TenantInvitation`, `TenantSetting`) all inherit from `AuditModel` and include these fields automatically. The admin interface shows audit information in a collapsed section at the bottom of each form.

---

## Installation

This repository uses a package-first layout.
The reusable package lives under `src/tenantkit`, while `example/` contains the reference Django project.

For the current setup and integration path, see:

- [Installation](https://github.com/pdigonzelli/django-tenantkit/blob/main/docs/installation.md)
- [Quickstart](https://github.com/pdigonzelli/django-tenantkit/blob/main/docs/quickstart.md)

---

## Minimal quickstart

At a high level, a Django project using the framework will:

1. add the multitenancy app to `INSTALLED_APPS`
2. add tenant-aware middleware
3. add the tenant database router
4. define shared and tenant-scoped models
5. create one or more tenants
6. run the appropriate migration workflow

The current reference Django project lives in `example/`, while the package source lives in `src/tenantkit`.

For the guided flow, see [Quickstart](https://github.com/pdigonzelli/django-tenantkit/blob/main/docs/quickstart.md).

### Quick Configuration

**Critical:** The order of `INSTALLED_APPS` and `MIDDLEWARE` matters. See [Setup Standard Guide](https://github.com/pdigonzelli/django-tenantkit/blob/main/docs/setup-standard.md) for full details.

```python
# settings.py - Minimal working configuration

INSTALLED_APPS = [
    # Django core FIRST (auth before tenantkit)
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    
    # TenantKit AFTER auth
    "tenantkit",
    
    # Your apps
    "myapp",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",  # BEFORE
    "tenantkit.middleware.TenantMiddleware",                  # AFTER
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

DATABASE_ROUTERS = ["tenantkit.routers.TenantRouter"]

TENANTKIT_BOTH_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
]
```

**Why this order matters:**
- `django.contrib.auth` must come **before** `tenantkit` so User/Group/Permission models register first in the `public` schema
- `AuthenticationMiddleware` must come **before** `TenantMiddleware` so authentication happens in `public` before switching to the tenant schema

---

## Official test command

The current stable validation path is:

```bash
uv sync --dev
uv run python example/manage.py test tenantkit
```

For local development, the repository is managed from the root and the example project acts as a consumer of the package.

See [Testing](https://github.com/pdigonzelli/django-tenantkit/blob/main/docs/testing.md) for the current testing entrypoints.

---

## Example project

The repository includes a Django reference project in `example/`.
It currently serves as:

- the integration environment
- the test harness
- the reference wiring for settings, middleware, routing, and admin behavior

The reusable package itself lives in `src/tenantkit`.

See [Example Project](https://github.com/pdigonzelli/django-tenantkit/blob/main/docs/example.md).

---

## Documentation

Public documentation:

- [Installation](https://github.com/pdigonzelli/django-tenantkit/blob/main/docs/installation.md)
- [Setup Standard Guide](https://github.com/pdigonzelli/django-tenantkit/blob/main/docs/setup-standard.md) - **Start here for configuration order**
- [Configuration Guide](https://github.com/pdigonzelli/django-tenantkit/blob/main/docs/configuration-guide.md)
- [Quickstart](https://github.com/pdigonzelli/django-tenantkit/blob/main/docs/quickstart.md)
- [Concepts](https://github.com/pdigonzelli/django-tenantkit/blob/main/docs/concepts.md)
- [Commands](https://github.com/pdigonzelli/django-tenantkit/blob/main/docs/commands.md)
- [Provisioning](https://github.com/pdigonzelli/django-tenantkit/blob/main/docs/provisioning.md)
- [Testing](https://github.com/pdigonzelli/django-tenantkit/blob/main/docs/testing.md)
- [Example Project](https://github.com/pdigonzelli/django-tenantkit/blob/main/docs/example.md)
- [API Reference](https://github.com/pdigonzelli/django-tenantkit/blob/main/docs/api.md)

Technical and architectural material:

- [Architecture](https://github.com/pdigonzelli/django-tenantkit/blob/main/docs/architecture.md)
- [Model Configuration Implementation](https://github.com/pdigonzelli/django-tenantkit/blob/main/docs/MODEL_CONFIG_IMPLEMENTATION.md)
- [Auth and Admin](https://github.com/pdigonzelli/django-tenantkit/blob/main/docs/auth-and-admin.md)
- [ADRs](https://github.com/pdigonzelli/django-tenantkit/tree/main/docs/adr)

---

## Compatibility

| Project status | Python | Django |
|---|---|---|
| Current main branch | 3.12, 3.13 | 6.0 |

- Schema isolation requires PostgreSQL
- Database isolation depends on backend-specific provisioning and runtime support

---

## Status

This project is under active development.

Current transition goals include:

- refining the public documentation structure
- stabilizing the new package-first repository layout
- keeping the `example/` project as the reference integration environment

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).
All changes should go through Pull Requests.

---

## License

MIT License. See [LICENSE](LICENSE).
