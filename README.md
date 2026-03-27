# django-multitenant

[![CI](https://github.com/pdigonzelli/django-multitenant/actions/workflows/ci.yml/badge.svg)](https://github.com/pdigonzelli/django-multitenant/actions)
[![Python](https://img.shields.io/badge/python-3.12%20|%203.13-blue)](https://pypi.org/project/django-multitenant/)
[![Django](https://img.shields.io/badge/django-6.0-green)](https://pypi.org/project/django-multitenant/)
[![License](https://img.shields.io/badge/license-MIT-lightgrey)](LICENSE)

A Django-native multitenancy framework with first-class support for **schema** and **database** isolation strategies.

---

## Why django-multitenant?

Existing solutions in the Django ecosystem solve parts of the problem:

- Some support schema isolation but are PostgreSQL-only by design
- Some support database isolation but lack Django Admin integration
- None offer a clean separation between shared/public data and tenant-local data with a composable resolver pipeline

`django-multitenant` is a smaller, more flexible alternative — built on Django idioms, not on top of a parallel platform.

---

## Vision

`django-multitenant` seeks to provide a native Django foundation supporting two forms of tenant isolation:

- **schema-tenant** (PostgreSQL schemas)
- **database-tenant** (separate databases, any backend)

The framework aligns with Django's philosophy:

- Clean integration with ORM, middleware, and admin
- Clear separation between **shared/public** data and **tenant-local** data
- Minimal implicit magic
- Extensibility through explicit contracts and strategies

---

## Features

- **Dual isolation strategies** — `schema` (PostgreSQL) and `database` (any backend)
- **Zero-config tenant provisioning** — auto-generates `schema_name`, `connection_alias`, and `connection_string` from the tenant slug
- **Model registry with decorators** — `@shared_model` and `@tenant_model` to declare data ownership explicitly
- **Tenant-aware Django Admin** — single `/admin/` with global mode and per-tenant mode, switchable from the UI
- **Encrypted connection strings** — `connection_string` and `provisioning_connection_string` stored encrypted at rest (AES-256-CBC)
- **Soft delete** — all tenant catalog models support soft delete with restore
- **Strategy Pattern for provisioning** — `SQLiteProvisioningStrategy` and `PostgreSQLProvisioningStrategy` with full user/permission management
- **DRF adapter** — REST API at `/api/tenants/` out of the box
- **OpenAPI 3.0 docs** — Swagger UI and ReDoc included via drf-spectacular
- **Comprehensive test suite** — 54 tests (42 unit + 12 integration) against real PostgreSQL

---

## Installation

```bash
pip install django-multitenant
```

Add to `INSTALLED_APPS`:

```python
INSTALLED_APPS = [
    ...
    "multitenant",
]
```

Add the middleware:

```python
MIDDLEWARE = [
    ...
    "multitenant.middleware.TenantMiddleware",
]
```

Add the database router:

```python
DATABASE_ROUTERS = ["multitenant.routers.tenant.TenantRouter"]
```

Run migrations:

```bash
python manage.py migrate
```

---

## Quick Start

### 1. Define your models

Use decorators to mark models as shared (global) or tenant (isolated):

```python
from django.db import models
from multitenant import shared_model, tenant_model

@shared_model
class User(models.Model):
    """Shared across all tenants - stored in default database"""
    email = models.EmailField(unique=True)
    first_name = models.CharField(max_length=100)

@tenant_model
class Product(models.Model):
    """Isolated per tenant - stored in tenant schema/database"""
    name = models.CharField(max_length=200)
    price = models.DecimalField(max_digits=10, decimal_places=2)
```

### 2. Create a tenant

```python
from multitenant.models import Tenant

# Schema tenant (PostgreSQL) - auto provisioning
tenant = Tenant.objects.create(
    slug="acme-corp",
    name="Acme Corporation",
    isolation_mode="schema",
    provisioning_mode="auto",
)
# → automatically generates schema_name="tenant_acme_corp"

# Database tenant (any backend) - manual provisioning
tenant = Tenant.objects.create(
    slug="globex",
    name="Globex Corporation",
    isolation_mode="database",
    provisioning_mode="manual",
    connection_alias="globex_db",
    connection_string="postgresql://app:pass@host/globex",
    provisioning_connection_string="postgresql://admin:pass@host/postgres",
)
# → creates physical database, user, and permissions automatically
```

### 3. Query tenant data

```python
from multitenant.middleware import set_current_tenant

# Set tenant context
tenant = Tenant.objects.get(slug="acme-corp")
set_current_tenant(tenant)

# All queries to tenant models are automatically scoped
products = Product.objects.all()  # Only acme-corp's products
```

---

## Isolation Modes

| Mode | Isolation Unit | Best For | Provisioning |
|------|----------------|----------|--------------|
| `schema` | PostgreSQL schema per tenant | Shared infrastructure, strong isolation | Auto or Manual |
| `database` | Dedicated DB + connection alias | Cross-server, maximum isolation | Auto (SQLite) or Manual |

### Provisioning Modes

| Mode | Required Fields | Generated Fields | Use Case |
|------|-----------------|------------------|----------|
| `auto` | `slug`, `name`, `isolation_mode` | `schema_name` or `connection_alias` + `connection_string` | Quick setup, SQLite |
| `manual` | All structural fields | None | Production, PostgreSQL/MySQL/Oracle |

**Important:** `database + auto` only works for SQLite. For PostgreSQL, MySQL, MariaDB, Oracle, and other server-based databases, use `database + manual`.

---

## Tenant Resolution

Configure how tenants are identified per request:

```python
# settings.py
MULTITENANT_RESOLVERS = [
    "multitenant.resolvers.HeaderTenantResolver",   # X-Tenant-ID header
    "multitenant.resolvers.TokenTenantResolver",    # JWT claim
    "multitenant.resolvers.SessionTenantResolver",  # Session (for admin)
]
```

---

## Tenant-Aware Admin

A single `/admin/` operates in two modes:

- **Global mode** — shows shared/public models (Tenant catalog, users, etc.)
- **Tenant mode** — shows tenant-local models, switchable from `/admin/tenant-switch/`

```python
# Admin automatically filters based on current tenant context
# Superusers can switch between global and tenant modes
```

---

## Management Commands

```bash
# List registered models by type
python manage.py list_tenant_models
python manage.py list_tenant_models --type=shared
python manage.py list_tenant_models --type=tenant --json

# Create migrations per data plane
python manage.py tenant_makemigrations --type=shared
python manage.py tenant_makemigrations --type=tenant

# Apply migrations
python manage.py tenant_migrate --type=shared          # Migrate shared models
python manage.py tenant_migrate --type=tenant          # Migrate all tenants
python manage.py tenant_migrate --type=tenant --tenant=acme-corp  # Specific tenant
```

---

## REST API

Full CRUD API for tenant management:

```http
GET    /api/tenants/              # List all tenants
POST   /api/tenants/              # Create tenant
GET    /api/tenants/{slug}/       # Get tenant details
DELETE /api/tenants/{slug}/       # Soft delete tenant
POST   /api/tenants/{slug}/operations/  # Provisioning operations
```

### OpenAPI Documentation

Interactive API documentation available at:

- **Swagger UI**: `http://localhost:8000/api/schema/swagger-ui/`
- **ReDoc**: `http://localhost:8000/api/schema/redoc/`
- **Raw Schema**: `http://localhost:8000/api/schema/`

Features:
- Auto-generated from DRF serializers
- Interactive "Try it out" functionality
- Request/response examples
- Download as YAML for client generation

---

## Security Model

- **Encrypted connection strings** — All `connection_string` and `provisioning_connection_string` fields are encrypted at rest using AES-256-CBC
- **Provisioning user** — Admin credentials used only to create DB and user; stored encrypted
- **Application user** — Auto-created with minimal permissions (CONNECT, USAGE, CREATE, ALL on tenant schema)
- **Tenant isolation** — Each database tenant has dedicated DB + user; cannot access other tenants
- **Context cleanup** — Tenant context always cleaned up at request end, even on errors

Report vulnerabilities privately — see [SECURITY.md](SECURITY.md).

---

## Development Setup

### Prerequisites

- Python 3.12+
- PostgreSQL 12+ (for schema isolation and integration tests)
- [UV](https://github.com/astral-sh/uv) (recommended)

### Quick Start with UV (Recommended)

```bash
# Install UV
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone repository
git clone git@github.com:pdigonzelli/django-multitenant.git
cd django-multitenant/example

# Install dependencies (creates .venv automatically)
uv sync --dev

# Run tests
uv run pytest

# Run linter
uv run ruff check .

# Run type checker
uv run pyright

# Run development server
uv run python manage.py runserver
```

### Without UV (Fallback)

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run server
python manage.py runserver
```

### Running Integration Tests

Integration tests require PostgreSQL:

```bash
# Start PostgreSQL (Docker)
docker run -d --name postgres-test \
  -e POSTGRES_PASSWORD=postgres \
  -p 5432:5432 \
  postgres:16

# Run all tests
uv run pytest

# Run only integration tests
uv run pytest multitenant/tests_integration.py

# Run with coverage
uv run pytest --cov --cov-report=html
```

---

## Compatibility

| django-multitenant | Python | Django |
|-------------------|--------|--------|
| 0.1.x | 3.12, 3.13 | 6.0 |

Schema isolation requires PostgreSQL. Database isolation works with any Django-supported backend.

---

## Documentation

- [Provisioning Guide](docs/provisioning.md) - Comprehensive guide to tenant provisioning
- [API Documentation](docs/api.md) - REST API reference
- [Architecture](docs/architecture.md) - Framework architecture and design
- [Model Configuration](docs/MODEL_CONFIG_IMPLEMENTATION.md) - Using `@shared_model` and `@tenant_model`
- [Auth and Admin](docs/auth-and-admin.md) - Authentication and admin integration
- [ADRs](docs/adr/) - Architecture Decision Records

---

## Design Principles

- **No domain resolution** as primary strategy
- Tenant resolution via **header**, **JWT claim**, or **session**
- Single `/admin/` tenant-aware, with global and tenant modes
- **Superuser global** + **local users per tenant**
- Tenant isolation mode (`schema` or `database`) is **fixed at creation**
- Core decoupled from REST adapter

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). All changes go through Pull Requests.

**Quick guidelines:**
- Fork the repository
- Create a branch: `feat/your-feature` or `fix/your-bugfix`
- Make focused changes with tests
- Open a Pull Request against `main`

---

## License

MIT License - see [LICENSE](LICENSE) for details.

---

## Tooling

- Project management: **UV**
- Testing: **pytest**
- Linting/formatting: **ruff**
- Type checking: **pyright**

---

**Built with ❤️ for the Django community**
