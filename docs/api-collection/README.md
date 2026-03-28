# Bruno API Collection for django-tenantkit

This directory contains a [Bruno](https://www.usebruno.com/) collection for testing the django-tenantkit API.

## Installation

Bruno should already be installed. If not:

```bash
# Arch Linux with AUR
yay -S bruno-bin

# Or AppImage
cd ~/Downloads
wget https://github.com/usebruno/bruno/releases/latest/download/bruno_1.12.0_x86_64.AppImage
chmod +x bruno_1.12.0_x86_64.AppImage
mv bruno_1.12.0_x86_64.AppImage ~/.local/bin/bruno
```

## Opening the Collection

```bash
# Open Bruno with this collection
bruno ./docs/api-collection/
```

Or open Bruno and select "Open Collection" → Navigate to this directory.

## Structure

```
api-collection/
├── bruno.json              # Collection configuration
├── environments/
│   └── local.bru           # Local environment variables
├── tenants/                # Tenant CRUD operations
│   ├── list-tenants.bru
│   ├── create-tenant.bru
│   ├── get-tenant.bru
│   ├── update-tenant.bru
│   └── delete-tenant.bru
└── operations/             # Provisioning operations
    ├── provision-and-migrate.bru
    ├── provision-only.bru
    └── migrate-only.bru
```

## Environment Variables

The collection uses these variables (defined in `environments/local.bru`):

| Variable | Default Value | Description |
|----------|---------------|-------------|
| `baseUrl` | `http://localhost:8000` | Base URL of the Django server |
| `apiPrefix` | `/api` | API prefix |
| `adminUrl` | `http://localhost:8000/admin` | Admin interface URL |
| `adminUsername` | *(secret)* | Admin username for authentication |
| `adminPassword` | *(secret)* | Admin password for authentication |

### Setting Secret Variables

1. Open Bruno
2. Click on the environment dropdown (top right)
3. Select "local"
4. Click "Configure"
5. Add your admin credentials as secrets

## Usage Workflow

### 1. Create a Tenant

Run: `tenants/create-tenant`

This creates a tenant with:
- `isolation_mode`: database
- `provisioning_mode`: manual
- Connection strings for PostgreSQL

The response automatically saves `tenantSlug` for subsequent requests.

### 2. Provision and Migrate

Run: `operations/provision-and-migrate`

This:
1. Creates the physical database (if not exists)
2. Creates the database user (if not exists)
3. Grants permissions
4. Runs Django migrations

### 3. Get Tenant Details

Run: `tenants/get-tenant`

### 4. Update Tenant

Run: `tenants/update-tenant`

### 5. Delete Tenant

Run: `tenants/delete-tenant`

## Testing Different Scenarios

### SQLite Tenant (Auto Mode)

Modify `create-tenant.bru` body:

```json
{
  "slug": "sqlite-tenant",
  "name": "SQLite Tenant",
  "isolation_mode": "database",
  "provisioning_mode": "auto",
  "connection_alias": "tenant_sqlite_tenant"
}
```

### Schema Tenant

Modify `create-tenant.bru` body:

```json
{
  "slug": "schema-tenant",
  "name": "Schema Tenant",
  "isolation_mode": "schema",
  "provisioning_mode": "manual",
  "schema_name": "tenant_schema_tenant"
}
```

## Assertions

Each request includes assertions to verify:
- HTTP status codes (200, 201, 204)
- Response content type

## Scripts

Some requests include post-response scripts:
- `create-tenant`: Automatically saves `tenantSlug` from response

## Troubleshooting

### Connection Refused

Ensure Django server is running:

```bash
uv run python example/manage.py runserver 0.0.0.0:8000
```

### 403 Forbidden

You may need to add authentication. Modify requests to include:

```json
{
  "auth": {
    "type": "basic",
    "basic": {
      "username": "{{adminUsername}}",
      "password": "{{adminPassword}}"
    }
  }
}
```

### Variable Not Found

Make sure you've selected the "local" environment in Bruno (dropdown at top right).

## Adding New Requests

1. Right-click on folder → "New Request"
2. Name it (e.g., `bulk-delete`)
3. Set HTTP method, URL, headers, body
4. Add assertions
5. Save

## Git Integration

Bruno collections are git-friendly! All requests are stored as plain text `.bru` files.

```bash
git add docs/api-collection/
git commit -m "Add Bruno API collection"
```

## Resources

- [Bruno Documentation](https://docs.usebruno.com/)
- [Bruno GitHub](https://github.com/usebruno/bruno)
- [django-tenantkit API Docs](../api.md)
