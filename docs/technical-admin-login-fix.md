# Fix: Admin Login with SCHEMA Tenant

## Problem

El login de admin con tenant SCHEMA seleccionado fallaba con error 200 en lugar de redirect.

Cuando un usuario intentaba iniciar sesión en el admin de Django con un tenant de tipo SCHEMA seleccionado, la autenticación fallaba silenciosamente. En lugar de redirigir al usuario al panel de administración, la página de login se recargaba con un código HTTP 200, sin mostrar mensajes de error claros.

## Root Cause

En `TenantAdminAuthenticationForm.clean()`, la restauración del `search_path` usaba f-strings para construir la sentencia SQL:

```python
cursor.execute(f'SET search_path TO {old_search_path}')
```

Si `old_search_path` era `"$user", public` (el valor por defecto en PostgreSQL), la sentencia SQL resultante era inválida porque:

1. Los identificadores con caracteres especiales (como `$`) no estaban correctamente escapados
2. La sintaxis resultante podía generar errores de parsing en PostgreSQL
3. La restauración del search_path fallaba, dejando el cursor en un estado inconsistente

Esto causaba que la autenticación fallara sin mostrar errores al usuario, ya que el formulario de Django esperaba un usuario válido pero el search_path incorrecto impedía encontrar los registros en la tabla `auth_user`.

## Solution

Reemplazar el uso inseguro de f-strings por funciones seguras de PostgreSQL:

### Captura del search_path actual
```python
cursor.execute("SELECT pg_catalog.current_setting('search_path')")
old_search_path = cursor.fetchone()[0]
```

### Seteo del search_path al schema del tenant (con quote_ident para seguridad)
```python
cursor.execute(
    "SELECT pg_catalog.set_config('search_path', pg_catalog.quote_ident(%s) || ', public', false)",
    [schema_name]
)
```

### Restauración del search_path original
```python
cursor.execute(
    "SELECT pg_catalog.set_config('search_path', %s, false)",
    [old_search_path]
)
```

### Beneficios de esta solución

1. **Seguridad**: `pg_catalog.quote_ident()` escapa correctamente los identificadores
2. **Consistencia**: Usa funciones del catálogo de PostgreSQL que son estándar y portables
3. **Robustez**: Maneja correctamente valores complejos del search_path como `"$user", public`
4. **Mantenibilidad**: Código más claro y explícito sobre las operaciones de base de datos

## Files Changed

| File | Change Type | Description |
|------|-------------|-------------|
| `src/tenantkit/admin_site.py` | Bugfix | Fixed search_path restoration in `TenantAdminAuthenticationForm.clean()` |
| `src/tenantkit/tests.py` | Test | Added comprehensive tests for SCHEMA tenant admin login |
| `docs/setup-standard.md` | Documentation | Created standard setup guide with correct configuration order |
| `docs/configuration-guide.md` | Documentation | Updated with correct INSTALLED_APPS and MIDDLEWARE order |
| `README.md` | Documentation | Added quick configuration section |

## Testing

Tests agregados en `src/tenantkit/tests.py`:

### `test_schema_tenant_search_path_restoration_with_complex_values`
Verifica que el search_path se restaure correctamente incluso cuando el valor original contiene caracteres especiales.

### `test_schema_tenant_login_success`
Verifica que el login funciona correctamente cuando las credenciales son válidas para un tenant SCHEMA.

### `test_schema_tenant_login_user_not_found`
Verifica que se muestra el error apropiado cuando el usuario no existe en el schema del tenant.

### `test_schema_tenant_login_wrong_password`
Verifica que se muestra el error apropiado cuando la contraseña es incorrecta.

### `test_schema_tenant_uses_quote_ident`
Verifica que se usa `pg_catalog.quote_ident()` para escapar correctamente los nombres de schema.

### `test_database_tenant_login_still_works`
Verifica que el login con tenants DATABASE sigue funcionando correctamente (regresión).

## Configuration Requirements

Para que el fix funcione correctamente, es crucial tener la configuración en el orden adecuado:

### INSTALLED_APPS
```python
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',  # ← ANTES que tenantkit
    'django.contrib.contenttypes',
    # ... otras apps
    'tenantkit',  # ← DESPUÉS de auth
]
```

### MIDDLEWARE
```python
MIDDLEWARE = [
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',  # ← ANTES
    'tenantkit.middleware.TenantMiddleware',  # ← DESPUÉS
    'django.contrib.messages.middleware.MessageMiddleware',
]
```

Ver `docs/setup-standard.md` para la guía completa de configuración.

## Validation

### Proyecto sensorData
- ✅ Login con tenant SCHEMA seleccionado: Redirige correctamente al admin index
- ✅ Configuración validada: Todas las comprobaciones pasaron
- ✅ No hay regresiones en tenants DATABASE

## References

- [PostgreSQL Documentation: quote_ident()](https://www.postgresql.org/docs/current/functions-string.html)
- [PostgreSQL Documentation: set_config()](https://www.postgresql.org/docs/current/functions-admin.html)
- `docs/setup-standard.md` - Guía de configuración estándar
- `docs/configuration-guide.md` - Guía de configuración detallada

## Date

2026-04-20
