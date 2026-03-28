# django-tenantkit

[![CI](https://github.com/pdigonzelli/django-multitenant/actions/workflows/ci.yml/badge.svg)](https://github.com/pdigonzelli/django-multitenant/actions)
[![Python](https://img.shields.io/badge/python-3.12%20|%203.13-blue)](https://pypi.org/project/django-tenantkit/)
[![Django](https://img.shields.io/badge/django-6.0-green)](https://pypi.org/project/django-tenantkit/)
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

See [Concepts](docs/concepts.md) for the model vocabulary and architectural terms.

---

## Installation

This repository now uses a package-first layout.
The reusable package lives under `src/multitenant`, while `example/` contains the reference Django project.
The final public package name and distribution workflow are still under review.

For the current setup and integration path, see:

- [Installation](docs/installation.md)
- [Quickstart](docs/quickstart.md)

---

## Minimal quickstart

At a high level, a Django project using the framework will:

1. add the multitenancy app to `INSTALLED_APPS`
2. add tenant-aware middleware
3. add the tenant database router
4. define shared and tenant-scoped models
5. create one or more tenants
6. run the appropriate migration workflow

The current reference Django project lives in `example/`, while the package source lives in `src/multitenant`.

For the guided flow, see [Quickstart](docs/quickstart.md).

---

## Official test command

The current stable validation path is:

```bash
uv sync --dev
uv run python example/manage.py test multitenant
```

For local development, the repository is managed from the root and the example project acts as a consumer of the package.

See [Testing](docs/testing.md) for the current testing entrypoints.

---

## Example project

The repository includes a Django reference project in `example/`.
It currently serves as:

- the integration environment
- the test harness
- the reference wiring for settings, middleware, routing, and admin behavior

The reusable package itself lives in `src/multitenant`.

See [Example Project](docs/example.md).

---

## Documentation

Public documentation:

- [Installation](docs/installation.md)
- [Quickstart](docs/quickstart.md)
- [Concepts](docs/concepts.md)
- [Commands](docs/commands.md)
- [Provisioning](docs/provisioning.md)
- [Testing](docs/testing.md)
- [Example Project](docs/example.md)
- [API Reference](docs/api.md)

Technical and architectural material:

- [Architecture](docs/architecture.md)
- [Model Configuration Implementation](docs/MODEL_CONFIG_IMPLEMENTATION.md)
- [Auth and Admin](docs/auth-and-admin.md)
- [ADRs](docs/adr/)

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
- reviewing the final public package and repository naming before release

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).
All changes should go through Pull Requests.

---

## License

MIT License. See [LICENSE](LICENSE).
