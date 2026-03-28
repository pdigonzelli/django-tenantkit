# Database Provisioning Guide

This guide explains how database provisioning works in `django-tenantkit` and how to use it effectively.

## Overview

The framework supports two isolation modes for tenants:

1. **Schema-based isolation**: All tenants share one database but use separate PostgreSQL schemas
2. **Database-based isolation**: Each tenant has its own dedicated database

## Supported Database Engines

The framework uses the **Strategy Pattern** to support multiple database engines:

| Engine | Strategy | User Management | Permissions |
|--------|----------|-----------------|-------------|
| **SQLite** | `SQLiteProvisioningStrategy` | ❌ No (file-based) | ❌ No |
| **PostgreSQL** | `PostgreSQLProvisioningStrategy` | ✅ Yes | ✅ Yes |
| **MySQL/MariaDB** | `PostgreSQLProvisioningStrategy` (default) | ✅ Yes | ✅ Yes |

The appropriate strategy is automatically selected based on the `connection_string` URL scheme.

## Provisioning Modes

For each tenant, you can choose a provisioning mode:

### Auto Mode (`provisioning_mode='auto'`)

The framework automatically generates all necessary configuration:

- **Schema tenants**: Auto-generates `schema_name` from the tenant slug
- **Database tenants**: 
  - Auto-generates `connection_alias` (e.g., `tenant_{slug}`)
  - Auto-generates `connection_string` (SQLite only)
  - **Note**: Database + Auto only works with SQLite. For PostgreSQL/MySQL/MariaDB/Oracle, you must use Manual mode.

### Manual Mode (`provisioning_mode='manual'`)

You provide the structural values, and the framework validates, encrypts, and registers them:

- **Schema tenants**: You provide `schema_name`
- **Database tenants**: You provide `connection_alias`, `connection_string`, and optionally `provisioning_connection_string`

## Database Provisioning Architecture

### Strategy Pattern

```
┌─────────────────────────────────────────────────────────────┐
│         DatabaseProvisioningStrategy (Abstract)               │
├─────────────────────────────────────────────────────────────┤
│  + ensure_database_exists(connection_string, provisioning_url)│
│  + ensure_user_exists(username, password, provisioning_url)   │
│  + grant_permissions(database_name, username, prov_url)       │
│  + delete_database_and_user(connection_string, prov_url)      │
│  + database_exists(connection_string, provisioning_url)     │
│  + user_exists(username, provisioning_url)                  │
└─────────────────────────────────────────────────────────────┘
                              △
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
┌───────┴───────┐    ┌───────┴───────┐    ┌───────┴───────┐
│   SQLite      │    │  PostgreSQL   │    │   (MySQL)     │
│   Strategy    │    │   Strategy    │    │   Strategy    │
├───────────────┤    ├───────────────┤    ├───────────────┤
│ - Creates dir │    │ - CREATE DB   │    │ - CREATE DB   │
│ - No users    │    │ - CREATE USER │    │ - CREATE USER │
│ - No perms    │    │ - GRANT perms │    │ - GRANT perms │
└───────────────┘    └───────────────┘    └───────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│              ProvisioningStrategyFactory                    │
├─────────────────────────────────────────────────────────────┤
│  get_strategy(connection_string) → Appropriate Strategy     │
│  - Detects scheme from URL (sqlite, postgresql, etc.)       │
│  - Returns strategy instance                                │
└─────────────────────────────────────────────────────────────┘
```

### Full Provisioning Flow

```
┌─────────────────────────────────────────────────────────────────┐
│              Full Provisioning Flow (Save Tenant)               │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  1. Validate & Save Tenant                                        │
│     ├── isolation_mode: DATABASE                                  │
│     ├── provisioning_mode: MANUAL                                 │
│     ├── connection_alias: tenant_acme                             │
│     ├── connection_string: postgresql://app_user:pass@.../db      │
│     └── provisioning_connection_string: postgresql://admin@...    │
│                                                                   │
│  2. Auto-Provisioning (on save)                                   │
│     └── Calls ensure_database_tenant_ready()                        │
│         ├── Get Strategy from Factory                             │
│         │   └── Detects engine from connection_string               │
│         │                                                           │
│         ├── Step 1: Ensure Database Exists                        │
│         │   ├── SQLite: Create directory                          │
│         │   └── PostgreSQL: CREATE DATABASE                       │
│         │                                                           │
│         ├── Step 2: Ensure User Exists (PostgreSQL only)          │
│         │   ├── Check if user exists (pg_roles)                     │
│         │   └── CREATE USER WITH PASSWORD (if not exists)           │
│         │                                                           │
│         ├── Step 3: Grant Permissions (PostgreSQL only)             │
│         │   ├── GRANT CONNECT ON DATABASE                         │
│         │   ├── GRANT USAGE, CREATE ON SCHEMA public              │
│         │   ├── GRANT ALL ON ALL TABLES                           │
│         │   └── ALTER DEFAULT PRIVILEGES                          │
│         │                                                           │
│         └── Step 4: Register Connection                           │
│             └── Register alias in Django's connection registry      │
│                                                                   │
│  3. Migration (via "Provision & Migrate" button)                  │
│     └── Run Django migrations on the tenant database                │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
```

## Using the Admin Interface

### Creating a Database Tenant (Manual Mode)

1. Go to `/admin/multitenant/tenant/add/`
2. Fill in basic information:
   - **Slug**: `acme-corp` (unique identifier)
   - **Name**: `Acme Corporation`
   - **Isolation mode**: `DATABASE`
   - **Provisioning mode**: `MANUAL`
3. For manual mode, provide:
   - **Connection alias**: `tenant_acme_corp`
   - **Connection string**: `postgresql://user:pass@localhost:5432/acme_db`
   - **Provisioning connection string**: `postgresql://admin:adminpass@localhost:5432/postgres`
4. Save the tenant

**What happens when you save:**
1. ✅ Connection strings are encrypted and saved
2. ✅ The provisioning connection is validated (must connect successfully)
3. ✅ Database is created if it doesn't exist
4. ✅ User is created if it doesn't exist  
5. ✅ Permissions are granted to the user on the database
6. ✅ Django connection alias is registered

**Note**: If any step fails, the save operation will fail with an error message. This ensures the tenant is fully functional after saving.

### Connection String Format

The `connection_string` is the primary configuration for database tenants. It must include:
- **Username**: The application user for this tenant (PostgreSQL only)
- **Password**: The user's password (PostgreSQL only)
- **Database name**: The tenant's database name

Examples by engine:

**PostgreSQL:**
```
postgresql://acme_app:secret123@localhost:5432/acme_db
postgres://acme_app:secret123@localhost:5432/acme_db
```

**SQLite:**
```
sqlite:///path/to/acme.db
sqlite://./tenant_dbs/acme.sqlite3
```

**MySQL/MariaDB:**
```
mysql://acme_app:secret123@localhost:3306/acme_db
```

### Provisioning Connection String

The `provisioning_connection_string` is used for administrative operations (creating databases, users, granting permissions). It must use an admin account with appropriate privileges:

**PostgreSQL:**
```
postgresql://postgres:adminpass@localhost:5432/postgres
```

**Note for SQLite:** The provisioning connection string is optional for SQLite since there's no user/permission management. If provided, it will be ignored during provisioning.

### Admin Interface Fields

When editing a tenant in the admin, you'll see:

**Database Runtime Section:**
- **Connection alias**: Unique identifier for this tenant's database connection
- **Connection string (plaintext)**: The connection string in plain text (editable)
- **Connection string (encrypted)**: The encrypted value stored in database (read-only)
- **Has connection string**: Indicator if a connection string is configured

**Database Provisioning Section:**
- **Provisioning connection string (plaintext)**: Admin connection string in plain text (editable)
- **Provisioning connection string (encrypted)**: Encrypted value stored in database (read-only)
- **Has provisioning connection string**: Indicator if provisioning is configured

**Note**: When you edit a tenant, the plaintext fields are automatically populated with the decrypted values from the database. Changes to plaintext fields are encrypted before saving.

### Connection String Encryption

All connection strings are **automatically encrypted** using AES-256-CBC via OpenSSL before storage. The encryption key is read from:

- Environment variable: `TENANT_ENCRYPTION_KEY`
- Or Django setting: `TENANT_ENCRYPTION_KEY`

**Important**: Keep this key secure! Losing it means losing access to all encrypted connection strings.

## Using the API

### Create a Database Tenant (Full Provisioning)

When you create a tenant via API with `provisioning_connection_string`, the full provisioning happens automatically:

```bash
curl -X POST http://localhost:8000/api/tenants/ \
  -H "Content-Type: application/json" \
  -d '{
    "slug": "acme-corp",
    "name": "Acme Corporation",
    "isolation_mode": "database",
    "provisioning_mode": "manual",
    "connection_alias": "tenant_acme_corp",
    "connection_string": "postgresql://app_user:app_pass@localhost:5432/acme_db",
    "provisioning_connection_string": "postgresql://admin:adminpass@localhost:5432/postgres"
  }'
```

**What happens:**
1. ✅ Tenant record created
2. ✅ Database `acme_db` created (if not exists)
3. ✅ User `app_user` created with password `app_pass` (if not exists)
4. ✅ Permissions granted to `app_user` on `acme_db`
5. ✅ Django connection alias registered

**Error Response** (if provisioning fails):
```json
{
  "error": {
    "code": "provisioning_failed",
    "message": "Failed to create database: connection failed: FATAL: password authentication failed for user 'admin'",
    "details": {
      "step": "database_creation"
    }
  }
}
```

### Provision and Migrate

After the tenant is created and provisioned, run migrations:

```bash
curl -X POST http://localhost:8000/api/tenants/acme-corp/operations/ \
  -H "Content-Type: application/json" \
  -d '{
    "operation": "provision_and_migrate"
  }'
```

Response:
```json
{
  "success": true,
  "message": "Provision and migrate completed successfully"
}
```

## Provisioning Connection String

The `provisioning_connection_string` is used to connect to a PostgreSQL maintenance database (typically `postgres`) to execute `CREATE DATABASE` commands.

### Why is this needed?

PostgreSQL requires connecting to an existing database to create a new one. The provisioning connection string should:

- Connect to a database that always exists (e.g., `postgres`, `template1`)
- Use credentials with `CREATEDB` privilege
- Be separate from the tenant's own database (which doesn't exist yet)

### Example

```
Tenant database URL:      postgresql://app_user:app_pass@localhost:5432/acme_db
Provisioning URL:         postgresql://admin:admin_pass@localhost:5432/postgres
```

### If Not Provided

If `provisioning_connection_string` is not set, the framework will use the tenant's `connection_string` but replace the database name with `postgres`. This works if the admin user is the same.

## PostgreSQL Permissions

### Provisioning User (Admin)

The user in the `provisioning_connection_string` needs these permissions:

```sql
-- Create a provisioning user (as postgres superuser)
CREATE USER tenant_admin WITH PASSWORD 'secure_password' CREATEDB;

-- Or grant CREATEDB to existing user
ALTER USER existing_user WITH CREATEDB;
```

Required permissions:
- `CREATEDB`: To create new databases
- `CREATEROLE`: To create new users (optional, can use superuser instead)

### Application User (Auto-Created)

The user in the `connection_string` is automatically created with minimal permissions:

- **CONNECT** on the tenant's database only
- **USAGE, CREATE** on schema public
- **ALL** on all tables in schema public
- **Default privileges** for future tables

This user **cannot**:
- Access other databases
- Create new databases
- Create other users
- Access system tables

### Security Model

```
┌─────────────────────────────────────────────────────────────┐
│                    PostgreSQL Security                        │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  Provisioning User (Admin)                                    │
│  ├── Can create databases                                     │
│  ├── Can create users                                         │
│  ├── Can grant permissions                                    │
│  └── Connects to 'postgres' DB                                │
│                                                               │
│  Application User (Tenant)                                    │
│  ├── Can only connect to own database                         │
│  ├── Can create tables in own database                      │
│  ├── Can read/write own data                                  │
│  └── Cannot access other tenants                              │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

## Connection String Format

### PostgreSQL

```
postgresql://user:password@host:port/database
postgres://user:password@host:port/database
```

Examples:
- `postgresql://localhost/mydb`
- `postgresql://user:pass@localhost:5432/mydb`
- `postgresql://user:p%40ss@localhost/mydb` (with URL-encoded special chars)

### SQLite

```
sqlite:///path/to/db.sqlite3
sqlite://./tenant_dbs/acme.db
```

### MySQL / MariaDB

```
mysql://user:password@host:port/database
mysqlgis://user:password@host:port/database
```

### Oracle

```
oracle://user:password@host:port/SID
```

## Deleting Tenants

### Safe Deletion with Double Confirmation

When you delete a database tenant through the admin interface, the framework implements **double confirmation** to prevent accidental data loss:

#### Single Tenant Deletion Flow

```
User clicks "Delete" on tenant:
│
├── 1. First Confirmation Page
│   └── Shows warning: "Database Will Be Permanently Deleted"
│   └── Lists: tenant name, database name
│   └── Explains: "All data will be permanently lost"
│
├── 2. Double Confirmation Input
│   └── User must type: "DELETE {tenant-slug}"
│   └── Example: "DELETE acme-corp"
│
└── 3. If confirmed correctly:
    ├── Soft delete tenant (mark as deleted)
    ├── DROP DATABASE (physical deletion)
    ├── DROP USER (remove PostgreSQL user)
    └── Unregister Django connection alias
```

#### Bulk Deletion (Multiple Tenants)

When using the "Delete selected tenants with their databases" action:

```
User selects multiple tenants → Action → Delete selected:
│
├── 1. Shows list of all selected tenants and their databases
├── 2. Shows total count of tenants to be deleted
├── 3. Double confirmation: Type "DELETE {N} TENANTS"
│   └── Example: "DELETE 5 TENANTS"
└── 4. If confirmed: Deletes all tenants and their databases
```

**Note**: The default Django "Delete selected" action has been replaced with "Delete selected tenants with their databases" which properly handles database cleanup.

#### What Gets Deleted

1. **Tenant record**: Soft deleted (marked as inactive, not physically removed from DB)
2. **Physical database**: `DROP DATABASE IF EXISTS {database_name}`
3. **PostgreSQL user**: `DROP USER IF EXISTS {username}`
4. **Django connection**: Unregistered from `connections.databases`

**⚠️ Warning**: This action is **irreversible**. The database and all its data are permanently removed.

#### For Non-Database Tenants

Schema tenants or tenants without connection strings use the standard soft delete flow (marked as inactive, no physical database deletion).

## Soft Delete Management in Admin

All models with soft delete support (`AuditModel`) have enhanced admin interfaces for managing deleted records.

### Features

1. **Status Filter**: Filter records by status
   - **Active**: Shows only non-deleted records (default)
   - **Deleted (Soft)**: Shows only soft-deleted records
   - **All**: Shows both active and deleted records

2. **Visual Indicator**: Status column shows:
   - ✅ **Active** for non-deleted records
   - 🗑️ **Deleted** for soft-deleted records

3. **Actions**:
   - **Restore selected records**: Undeletes soft-deleted records
   - **Permanently delete selected records**: Hard delete (requires confirmation)

### Viewing Deleted Records

1. Go to any admin list view (Tenants, Tenant Memberships, etc.)
2. Click on **"Deleted (Soft)"** in the "By status" filter
3. You'll see all soft-deleted records with their deletion date

### Restoring Deleted Records

1. Select the deleted records using checkboxes
2. Choose **"Restore selected records"** from the Action dropdown
3. Click **"Run"**
4. Records will be restored to active status

### Permanent Deletion

⚠️ **Warning**: This action cannot be undone!

1. Select records (active or deleted)
2. Choose **"Permanently delete selected records"** from the Action dropdown
3. Click **"Run"**
4. Type **"HARD DELETE"** to confirm
5. Records will be permanently removed from the database

### Models with Soft Delete Support

- **Tenant**: Full soft delete with database cleanup
- **TenantMembership**: Soft delete with restore capability
- **TenantInvitation**: Soft delete with restore capability
- **TenantSetting**: Soft delete with restore capability

## Troubleshooting

### "Failed to inspect database" Error

**Cause**: Cannot connect to PostgreSQL with the provisioning connection string.

**Solutions**:
1. Verify PostgreSQL is running: `docker ps | grep postgres`
2. Check credentials in `provisioning_connection_string`
3. Verify network connectivity: `psql -h localhost -U admin -d postgres`
4. Check PostgreSQL logs for authentication failures

### "Failed to create database" Error

**Cause**: The provisioning user lacks `CREATEDB` privilege.

**Solution**:
```sql
ALTER USER your_admin_user WITH CREATEDB;
```

### "Failed to create user" Error

**Cause**: The provisioning user lacks `CREATEROLE` privilege or user already exists with different password.

**Solutions**:
```sql
-- Grant CREATEROLE to provisioning user
ALTER USER your_admin_user WITH CREATEROLE;

-- Or drop existing user if password changed
DROP USER IF EXISTS existing_app_user;
```

### "Failed to grant permissions" Error

**Cause**: Cannot connect to the tenant database to grant permissions.

**Solutions**:
1. Verify the database was created successfully
2. Check if provisioning user can connect to the tenant database
3. Grant explicit database access to provisioning user:
```sql
GRANT CONNECT ON DATABASE tenant_db TO provisioning_user;
```

### Database Already Exists

This is not an error. The framework detects existing databases and skips creation. You'll see in logs:
```
tenant.db.exists: {"database": "acme_db"}
```

### User Already Exists

This is not an error. The framework detects existing users and skips creation. You'll see in logs:
```
tenant.user.exists: {"user": "app_user"}
```

### Connection Alias Already Registered

**Cause**: A tenant with the same `connection_alias` already exists.

**Solution**: Use a unique alias per tenant, e.g., `tenant_{slug}_{timestamp}`.

## Testing

### Run Unit Tests

Using `uv` (recommended):
```bash
uv run python manage.py test multitenant.tests
```

Or with standard Python:
```bash
python manage.py test multitenant.tests
```

### Run Integration Tests

Integration tests require a running PostgreSQL instance:

```bash
# Using the demo-tenants container
docker run -d --name demo-tenants \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=postgres \
  -p 5432:5432 \
  postgres:latest

# Run integration tests with uv
uv run python manage.py test multitenant.tests_integration
```

### Environment Variables for Tests

```bash
export TEST_POSTGRES_HOST=localhost
export TEST_POSTGRES_PORT=5432
export TEST_POSTGRES_USER=postgres
export TEST_POSTGRES_PASSWORD=postgres
export TEST_POSTGRES_MAINTENANCE_DB=postgres
```

## Security Best Practices

1. **Use separate provisioning credentials**: Don't use the application database user for provisioning
2. **Limit CREATEDB privilege**: Only the provisioning user needs this privilege
3. **Encrypt connection strings**: Always set `TENANT_ENCRYPTION_KEY` in production
4. **Rotate credentials**: Periodically rotate provisioning and tenant database passwords
5. **Network isolation**: Run tenant databases on isolated networks when possible
6. **Audit logging**: Enable PostgreSQL audit logging for database creation/deletion

## Migration from CLI to Strategy Pattern

Previous versions used CLI tools (`psql`, `createdb`) for database provisioning. The current version uses:

1. **Strategy Pattern Architecture**: Clean separation of concerns per database engine
2. **psycopg (Python driver)**: Direct database connection for PostgreSQL
3. **Native SQLite support**: No external dependencies for SQLite

### Benefits of Strategy Pattern

- **Extensibility**: Easy to add support for MySQL, MariaDB, Oracle
- **Testability**: Each strategy can be tested independently
- **Maintainability**: No scattered `if/else` conditions
- **Type safety**: Full type hints support
- **Better error handling**: Native Python exceptions
- **Cross-platform**: Works on Windows without PostgreSQL client tools

## Performance Considerations

- **Database creation**: ~100-500ms depending on PostgreSQL configuration
- **Migrations**: Time depends on number of migrations and database size
- **Connection pooling**: Tenant databases use Django's standard connection pooling
- **Lazy connections**: Database connections are established only when needed

## Future Enhancements

Potential improvements being considered:

1. **Async provisioning**: Use `psycopg.AsyncConnection` for non-blocking operations
2. **Progress tracking**: WebSocket/SSE updates during long provisioning operations
3. **Rollback support**: Automatic cleanup if provisioning fails mid-way
4. **Database templates**: Use PostgreSQL template databases for faster tenant creation
