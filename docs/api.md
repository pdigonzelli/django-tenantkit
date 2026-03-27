# Tenant Provisioning API (DRF)

This DRF-backed API manages the tenant registry stored in `default`.
It can also provision the physical database for database tenants when the request includes provisioning credentials.

## OpenAPI Documentation

The API is fully documented using **OpenAPI 3.0** specification via drf-spectacular.

### Interactive Documentation URLs

| URL | Description |
|-----|-------------|
| `/api/schema/` | Raw OpenAPI 3.0 schema (YAML) |
| `/api/schema/swagger-ui/` | Interactive Swagger UI (test endpoints directly) |
| `/api/schema/redoc/` | Elegant ReDoc documentation |

### Example: Accessing Swagger UI

1. Start the server:
   ```bash
   uv run python manage.py runserver
   ```

2. Open your browser:
   ```
   http://localhost:8000/api/schema/swagger-ui/
   ```

3. You'll see all endpoints with:
   - Request/response schemas
   - Example payloads
   - Try-it-now functionality
   - Authentication requirements

### Generating Client SDKs

Download the OpenAPI schema and generate clients:

```bash
# Get schema
curl http://localhost:8000/api/schema/ > openapi.yaml

# Generate Python client
openapi-generator generate -i openapi.yaml -g python -o ./client

# Generate TypeScript client
openapi-generator generate -i openapi.yaml -g typescript-fetch -o ./client-ts
```

## Endpoints

- `GET /api/tenants/` - list tenants
- `POST /api/tenants/` - create tenant
- `GET /api/tenants/{slug}/` - retrieve tenant
- `DELETE /api/tenants/{slug}/` - soft delete tenant
- `POST /api/tenants/{slug}/operations/` - provision/migrate tenant operations

## Fields

### Common

- `slug`
- `name`
- `isolation_mode` = `schema | database`
- `provisioning_mode` = `auto | manual`
- `metadata` (optional)

### Database provisioning

For `isolation_mode = database`, the API accepts an optional:

- `provisioning_connection_string`

The tenant `connection_string` is a normalized database locator: for SQLite it may be a path or SQLite URI; for server-based engines it is backend-specific and translated into Django's `DATABASES` configuration.

This field is an encrypted admin DSN used to create or verify the tenant's physical database on its target Postgres server.
It is required only when you want automatic DB provisioning.

Example:

```json
{
  "provisioning_connection_string": "postgresql://admin:secret@db-host:5432/postgres"
}
```

The DB host may differ per tenant.

### Auto provisioning

The backend generates:

- `schema_name` for schema tenants
- `connection_alias` for database tenants
- encrypted `connection_string` for database tenants

**Important limitation**: Auto provisioning for `database` tenants is **only supported for SQLite**. For PostgreSQL, MySQL, MariaDB, Oracle, and other server-based databases, you **must use manual mode** and provide the complete `connection_string`.

If `provisioning_connection_string` is present for a database tenant, the backend also tries to create the physical DB if it does not already exist.

Example: auto database tenant

```json
{
  "slug": "acme-db",
  "name": "Acme DB",
  "isolation_mode": "database",
  "provisioning_mode": "auto",
  "connection_string": "test.db"
}
```

Accepted `connection_string` formats:

- SQLite: `test.db`, `/absolute/path/test.db`, `sqlite:///absolute/path/test.db`
- PostgreSQL/MySQL/MariaDB/Oracle: backend-specific DSN/URL that Django can translate into `DATABASES`

| Backend | Example `connection_string` | Notes |
|---|---|---|
| SQLite | `test.db` | Interpreted as a SQLite file path |
| SQLite | `sqlite:///tmp/tenant.db` | SQLite URI/path form |
| PostgreSQL | `postgresql://user:pass@host:5432/dbname` | Translated to Django `DATABASES` |
| MySQL/MariaDB | `mysql://user:pass@host:3306/dbname` | Translated to Django `DATABASES` |
| Oracle | backend-specific DSN | Translated to Django `DATABASES` |

### Manual provisioning

The request must provide the structural fields required by the selected mode.
For manual database tenants, `provisioning_connection_string` is optional but recommended when the system should be able to create the DB automatically.

Example: manual database tenant

```json
{
  "slug": "acme-db",
  "name": "Acme DB",
  "isolation_mode": "database",
  "provisioning_mode": "manual",
  "connection_alias": "tenant_acme_db",
  "connection_string": "postgresql://tenant_user:tenant_pass@db-host:5432/tenant_acme_db",
  "provisioning_connection_string": "postgresql://admin:secret@db-host:5432/postgres"
}
```

## Response

The API always returns the tenant record, but never exposes `connection_string` in clear text.

Instead, it returns:

- `has_connection_string`
- `connection_string: null`
- `has_provisioning_connection_string`
- `provisioning_connection_string: null`

Example response:

```json
{
  "slug": "acme-db",
  "name": "Acme DB",
  "isolation_mode": "database",
  "provisioning_mode": "manual",
  "schema_name": null,
  "connection_alias": "tenant_acme_db",
  "connection_string": null,
  "has_connection_string": true,
  "provisioning_connection_string": null,
  "has_provisioning_connection_string": true,
  "metadata": {},
  "is_active": true,
  "deleted": false
}
```

## Notes

- `auto` is the default and recommended mode
- `manual` is for operators that need to fully control the connection details
- the tenant registry lives in the `default` database; only the physical tenant DB is provisioned elsewhere

## Validation rules

### Summary table

| isolation_mode | provisioning_mode | Required fields | Generated fields | Invalid fields | DB provisioning |
|---|---|---|---|---|---|
| `schema` | `auto` | `slug`, `name`, `isolation_mode` | `schema_name` | `connection_alias`, `connection_string`, `provisioning_connection_string` | No |
| `schema` | `manual` | `slug`, `name`, `isolation_mode`, `schema_name` | — | `connection_alias`, `connection_string`, `provisioning_connection_string` | No |
| `database` | `auto` | `slug`, `name`, `isolation_mode` | `connection_alias`, `connection_string` | `schema_name` | Optional via `provisioning_connection_string` |
| `database` | `manual` | `slug`, `name`, `isolation_mode`, `connection_alias`, `connection_string` | — | `schema_name` | Optional via `provisioning_connection_string` |

### `schema` tenants

- `auto`: backend generates `schema_name`
- `manual`: request must provide `schema_name`
- `connection_alias`, `connection_string`, and `provisioning_connection_string` are invalid

### `database` tenants

- `auto`: backend generates `connection_alias` and encrypted `connection_string`
- `manual`: request must provide `connection_alias` and `connection_string`
- `provisioning_connection_string` is allowed and enables automatic DB creation

### Provisioning workflow

1. save tenant metadata in `default`
2. decrypt `connection_string` to find the target database name
3. if `provisioning_connection_string` exists, connect to that server as admin
4. create the DB if it does not exist
5. register the alias in Django's connection registry

## Notes

- The registry is authoritative for the tenant catalog.
- The physical DB is external and may vary by tenant.
- `metadata` never replaces structural fields.

## Do / Don’t

### Do

- Use `test.db` or `/abs/path/test.db` for SQLite tenants.
- Use `sqlite:///abs/path/test.db` if you prefer SQLite URI style.
- Use a backend-specific DSN for server-based databases.
- Let Django translate the normalized locator into `DATABASES`.

### Don’t

- Don’t pass only `connection_alias` without a matching `connection_string` for manual database tenants.
- Don’t use `test.db` as a PostgreSQL/MySQL DSN.
- Don’t use `connection_string` as a raw secret store; it is a normalized database locator, not a generic secret field.

## Operation errors

When an operation cannot run because of the runtime/backend, the API returns a structured error:

```json
{
  "error": {
    "code": "SCHEMA_PROVISIONING_UNSUPPORTED",
    "message": "Schema provisioning is not available on this database backend. Use PostgreSQL for shared/default to provision schema tenants."
  }
}
```

Recommended codes:

- `SCHEMA_PROVISIONING_UNSUPPORTED`
- `UNKNOWN_OPERATION`
- `TENANT_NOT_FOUND`
